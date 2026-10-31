"""Stage 3 - Enrichment: recent-post metrics, content themes, contact details.

Everything here is read from public pages. Anything that cannot be found is
recorded as None / "Not Found" - values are never guessed or generated.
"""
import re
import statistics
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from .http import fetch, initial_data

NS = {"a": "http://www.w3.org/2005/Atom", "m": "http://search.yahoo.com/mrss/",
      "y": "http://www.youtube.com/xml/schemas/2015"}
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
URL_RE = re.compile(r"https?://[^\s<>\"')]+")
SOCIAL_HOSTS = ("instagram.com", "tiktok.com", "youtube.com", "youtu.be", "facebook.com",
                "twitter.com", "x.com", "linktr.ee", "pinterest.com", "snapchat.com")
ROLE_PREFIXES = ("shipping", "support", "orders", "noreply", "no-reply", "help", "returns",
                 "customerservice", "billing", "privacy", "abuse", "legal")
JUNK_EMAIL_DOMAINS = ("example.com", "sentry.io", "wixpress.com")


def fetch_feed(channel_id: str) -> list:
    """Last ~15 uploads with views, likes, title, date from the public RSS feed."""
    xml = fetch(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}")
    root = ET.fromstring(xml)
    vids = []
    for e in root.findall("a:entry", NS):
        stats = e.find("m:group/m:community/m:statistics", NS)
        rating = e.find("m:group/m:community/m:starRating", NS)
        vids.append({
            "title": e.findtext("a:title", "", NS),
            "published": e.findtext("a:published", "", NS),
            "description": e.findtext("m:group/m:description", "", NS) or "",
            "views": int(stats.get("views")) if stats is not None else None,
            "likes": int(rating.get("count")) if rating is not None else None,
            "url": (e.find("a:link", NS).get("href") if e.find("a:link", NS) is not None else ""),
        })
    return vids


def channel_description(profile_url: str) -> str:
    """Full channel description from the channel page's metadata block."""
    data = initial_data(fetch(profile_url))
    if not data:
        return ""
    md = data.get("metadata", {}).get("channelMetadataRenderer", {})
    return md.get("description", "") or ""


def compute_metrics(vids: list, followers: int) -> dict:
    views = [v["views"] for v in vids if v["views"] is not None]
    likes = [v["likes"] for v in vids if v["likes"] is not None]
    dates = []
    for v in vids:
        try:
            dates.append(datetime.fromisoformat(v["published"]))
        except ValueError:
            pass
    out = {"videos_sampled": len(vids), "avg_views": None, "avg_likes": None,
           "engagement_rate": None, "view_rate": None, "days_since_last_post": None}
    if views:
        out["avg_views"] = round(statistics.mean(views))
        out["view_rate"] = round(out["avg_views"] / followers, 4) if followers else None
    if likes and followers:
        out["avg_likes"] = round(statistics.mean(likes))
        out["engagement_rate"] = round(out["avg_likes"] / followers, 4)
    if dates:
        out["days_since_last_post"] = (datetime.now(timezone.utc) - max(dates)).days
    return out


def extract_contacts(*texts: str) -> dict:
    blob = "\n".join(t for t in texts if t)
    emails = []
    for e in EMAIL_RE.findall(blob):
        e = e.strip(".").lower()
        if (not e.endswith(JUNK_EMAIL_DOMAINS) and e not in emails
                and not e.split("@")[0].startswith(ROLE_PREFIXES)):  # not collab contacts
            emails.append(e)
    urls = [u.rstrip(".,;)") for u in URL_RE.findall(blob)]
    ig = tt = site = None
    for u in urls:
        host = urllib.parse.urlparse(u).netloc.lower().replace("www.", "")
        path = urllib.parse.urlparse(u).path.strip("/")
        if host.endswith("instagram.com") and path and not ig:
            ig = "@" + path.split("/")[0]
        elif host.endswith("tiktok.com") and path and not tt:
            tt = path.split("/")[0]
        elif not any(host.endswith(s) for s in SOCIAL_HOSTS) and not site:
            site = u
    if not ig:  # "IG: @name" / "Instagram: @name"
        m = re.search(r"(?:instagram|insta|ig)\s*[:\-]?\s*@([A-Za-z0-9._]{2,30})", blob, re.I)
        ig = "@" + m.group(1) if m else None
    return {"emails": emails, "instagram": ig, "tiktok": tt, "website": site}


def email_from_website(site: str):
    """Look for a mailto:/plain email on the creator's own site (homepage + /contact)."""
    base = site.rstrip("/")
    for u in (base, base + "/contact", base + "/pages/contact"):
        try:
            html = fetch(u, retries=1, timeout=10)
        except Exception:
            continue
        for e in EMAIL_RE.findall(html):
            e = e.lower().strip(".")
            if (not e.endswith(JUNK_EMAIL_DOMAINS) and not e.split("@")[0].startswith(ROLE_PREFIXES)
                    and not re.search(r"\.(png|jpg|jpeg|gif|webp|svg)$", e)):
                return e, u
    return None, None


def enrich(rec: dict, follow_websites: bool = True) -> dict:
    """Add metrics + contact + context to a discovery record (mutates and returns it)."""
    rec["notes"] = []
    try:
        vids = fetch_feed(rec["channel_id"])
    except Exception as e:
        vids = []
        rec["notes"].append(f"RSS feed unavailable: {e}")
    rec["recent_videos"] = [{k: v[k] for k in ("title", "published", "views", "likes", "url")}
                            for v in vids[:10]]
    rec.update(compute_metrics(vids, rec["followers"]))
    try:
        desc = channel_description(rec["profile_url"])
    except Exception as e:
        desc = ""
        rec["notes"].append(f"channel page unavailable: {e}")
    rec["description"] = desc or rec.get("snippet", "")

    c = extract_contacts(desc, rec.get("snippet", ""),
                         *[v["description"] for v in vids[:5]])
    rec["email"], rec["email_source"] = "Not Found", None
    if c["emails"]:
        rec["email"], rec["email_source"] = c["emails"][0], "channel description"
    elif follow_websites and c["website"]:
        e, src = email_from_website(c["website"])
        if e:
            rec["email"], rec["email_source"] = e, src
    rec["instagram"] = c["instagram"] or "Not Found"
    rec["tiktok"] = c["tiktok"] or "Not Found"
    rec["website"] = c["website"] or "Not Found"
    # Audience demographics are not exposed publicly by YouTube.
    rec["audience_age"] = rec["audience_gender"] = rec["audience_geography"] = "Not Available"
    return rec
