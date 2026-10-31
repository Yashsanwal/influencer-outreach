"""Stage 1 - Discovery: find YouTube channels via public channel-search results."""
import re
import urllib.parse

import config
from .http import fetch, initial_data


def parse_count(text: str):
    """'12.3K subscribers' -> 12300. Returns None if unparseable (never guesses)."""
    m = re.search(r"([\d.,]+)\s*([KMB]?)", text or "", re.I)
    if not m:
        return None
    try:
        n = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return int(n * {"": 1, "K": 1e3, "M": 1e6, "B": 1e9}[m.group(2).upper()])


def _walk(o, out):
    if isinstance(o, dict):
        if "channelRenderer" in o:
            out.append(o["channelRenderer"])
        for v in o.values():
            _walk(v, out)
    elif isinstance(o, list):
        for v in o:
            _walk(v, out)


def _text(node) -> str:
    if not node:
        return ""
    return node.get("simpleText") or "".join(r.get("text", "") for r in node.get("runs", []))


def search_channels(query: str) -> list:
    url = ("https://www.youtube.com/results?search_query="
           + urllib.parse.quote_plus(query) + "&sp=EgIQAg%253D%253D")  # filter: channels
    data = initial_data(fetch(url))
    if not data:
        return []
    found = []
    _walk(data, found)
    rows = []
    for c in found:
        cid = c.get("channelId")
        # YouTube's markup puts the @handle in subscriberCountText and the
        # subscriber count in videoCountText.
        subs = parse_count(_text(c.get("videoCountText")))
        handle = _text(c.get("subscriberCountText"))
        if not cid:
            continue
        rows.append({
            "channel_id": cid, "name": _text(c.get("title")).strip(),
            "handle": handle if handle.startswith("@") else "",
            "followers": subs, "snippet": _text(c.get("descriptionSnippet")),
            "profile_url": f"https://www.youtube.com/channel/{cid}",
            "platform": "YouTube", "discovered_via": query,
        })
    return rows


def discover(queries=None, log=print) -> dict:
    """Run all queries; de-duplicate by channel id. Failed queries are skipped."""
    seen = {}
    for q in queries or config.SEARCH_QUERIES:
        try:
            rows = search_channels(q)
        except Exception as e:  # network / parse problems must not abort the run
            log(f"  ! query '{q}' failed: {e}")
            continue
        new = 0
        for r in rows:
            if r["channel_id"] not in seen:
                seen[r["channel_id"]] = r
                new += 1
        log(f"  query '{q}': {len(rows)} channels, {new} new")
    return seen
