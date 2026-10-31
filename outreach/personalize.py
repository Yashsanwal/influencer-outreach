"""Stage 4 - Personalisation: one email pitch (60-90 words) + one Instagram DM (15-30 words).

Two generators share the same input "signals":
  * LLM generator  - Claude via the Messages API (used when ANTHROPIC_API_KEY is set)
  * Rule generator - offline fallback that assembles sentences from the signals
Both outputs are validated against the word-count limits; the LLM path retries and
then falls back to the rule generator.
"""
import hashlib
import json
import re
import urllib.request

import config
from .filtering import SUBNICHES, ENGLISH_STOP, _words

PROMPT = """You write short, genuine creator-collaboration outreach for the brand below.
Use ONLY the facts in the JSON signals; never invent stats, products seen, or personal details.
Brand: {brand} ({product}). Sender: {sender}.

Return strict JSON: {{"subject": str, "email": str, "dm": str}}
- email: {ew0}-{ew1} words including greeting and sign-off, plain text, references the creator's
  niche, their tone, ONE specific recent video title (quote it), their audience, the proposed
  collaboration ({angle}) and a concrete value proposition. One soft call to action.
- dm: {dw0}-{dw1} words, casual and natural, mentions their content and niche, no links, no emojis spam.
- Do not sound templated; vary sentence structure. No fake urgency, no claims of having watched
  more than the listed titles.

Signals:
{signals}"""


# ------------------------------------------------------------------ signals
def clean_title(t: str, max_words: int = 7):
    """Strip hashtags/emoji/pipes; return None unless it reads like a real English title."""
    t = re.sub(r"#\w+", " ", t)
    t = re.split(r"\s[|\-–—]\s|\|", t)[0]
    t = re.sub(r"[^\x00-\x7F]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip(" .,:;!-")
    words = t.split()
    words = words[:max_words]
    while words and words[-1].lower().strip("'.,") in {"let's", "lets", "so", "and", "the", "a", "to", "of", "in", "for", "with", "my", "i", "your", "this", "how", "&"}:
        words.pop()  # don't end on a dangling word after truncation
    if len(words) < 2 or not (set(_words(t)) & ENGLISH_STOP):
        return None
    return " ".join(words)


def first_name(name: str):
    """Greeting name only when the channel name looks like a person's first name."""
    toks = re.findall(r"[A-Za-z]+", name or "")
    if not 1 <= len(toks) <= 2 or any(len(t) < 2 for t in toks):
        return None
    flat = {w for kws in SUBNICHES.values() for k in kws for w in k.split()}
    if any(t.lower() in flat or t.lower() in ENGLISH_STOP for t in toks):
        return None
    if not all(t[0].isupper() for t in toks):
        return None
    return toks[0]


def tone(rec: dict) -> str:
    text = rec.get("description", "") + " " + " ".join(v["title"] for v in rec.get("recent_videos", []))
    emoji = len(re.findall(r"[^\x00-\x7F]", text))
    edu = len(re.findall(r"\b(tutorial|how to|tips|guide|review|routine|step)\b", text, re.I))
    if edu >= 3:
        return "clear, practical and educational"
    if emoji >= 6 or text.count("!") >= 3:
        return "warm, upbeat and personal"
    return "relaxed and authentic"


def pick_angle(rec: dict) -> str:
    f, er = rec["followers"], rec.get("engagement_rate") or 0
    if f >= 50_000:
        return "paid sponsorship"
    if er >= 0.04:
        return "UGC content creation"
    if f < 15_000:
        return "barter collaboration"
    if rec.get("sub_niche") in ("fashion", "makeup"):
        return "affiliate campaign"
    return "brand ambassador program"


def build_signals(rec: dict) -> dict:
    vids = [v for v in rec.get("recent_videos", []) if clean_title(v["title"])]
    # reference the best-performing recent video (by views) among usable titles
    best = max(vids, key=lambda v: v.get("views") or 0) if vids else None
    return {
        "creator_name": rec["name"], "greeting_name": first_name(rec["name"]),
        "platform": rec["platform"], "followers": rec["followers"],
        "niche": rec["sub_niche"], "themes": rec["content_themes"],
        "tone": tone(rec),
        "recent_video_title": clean_title(best["title"]) if best else None,
        "avg_likes_pct_of_subscribers": round((rec.get("engagement_rate") or 0) * 100, 1),
        "collab_angle": pick_angle(rec),
    }


# ------------------------------------------------------------ rule generator
def _pick(options, key: str, salt: str):
    h = int(hashlib.sha1((key + salt).encode()).hexdigest(), 16)
    return options[h % len(options)]


ANGLE_PITCH = {
    "paid sponsorship": "We'd like to sponsor a dedicated video featuring our {product}, with a fee that reflects your reach.",
    "UGC content creation": "We'd love to commission UGC content: you create a short video with our {product} and we license it for our channels, paid per piece.",
    "barter collaboration": "We'd like to send you our {product} to try, with no strings attached, and you share honest thoughts only if you love it.",
    "affiliate campaign": "We're launching an affiliate campaign for our {product}, with a custom code for your viewers and a commission on every sale.",
    "brand ambassador program": "We're opening a small ambassador program for our {product}: early access, free products and a recurring commission.",
}
VALUE = {
    "paid sponsorship": "You keep full creative control, and we handle products and logistics.",
    "UGC content creation": "You keep your voice and style, and we handle briefs and shipping.",
    "barter collaboration": "It's a low-pressure way to test whether we're a fit.",
    "affiliate campaign": "You earn on performance, with free products to film from.",
    "brand ambassador program": "It's a long-term partnership, not a one-off post.",
}


def rule_generate(rec: dict, s: dict) -> dict:
    key, b = rec["channel_id"], config.BRAND
    name = s["greeting_name"]
    hi = f"Hi {name}," if name else "Hi there,"
    theme = s["niche"] if s["niche"] != "unclassified" else "fashion and beauty"
    vid = s["recent_video_title"]

    opener = (_pick([
        f'I just watched "{vid}" and really liked how {s["tone"]} your content feels.',
        f'Your recent video "{vid}" stood out to me, especially how {s["tone"]} it is.',
        f'Watching "{vid}", I could tell your {theme} content is {s["tone"]}.',
    ], key, "o") if vid else _pick([
        f"I've been following your {theme} content, and it feels {s['tone']}.",
        f"Your {theme} channel stands out to me for being {s['tone']}.",
    ], key, "o"))
    fit = _pick([
        f"About {s['avg_likes_pct_of_subscribers']}% of your subscribers like each upload, which tells me your {theme} audience genuinely trusts you.",
        f"Your {theme}-focused audience looks highly engaged, with roughly {s['avg_likes_pct_of_subscribers']}% of subscribers liking each video.",
    ], key, "f")
    pitch = ANGLE_PITCH[s["collab_angle"]].format(product=b["product"])
    value = VALUE[s["collab_angle"]]
    cta = _pick(["Would you be open to a quick chat?", "Open to hearing more?",
                 "Shall I share the details?"], key, "c")
    sign = f"Best,\n{b['sender_name']}"

    # Candidate sentence sets, most complete first; keep the first inside the word budget.
    wrap = lambda ps: f"{hi}\n\n" + " ".join(ps) + f"\n\n{sign}"
    candidates = [[opener, fit, pitch, value, cta], [opener, fit, pitch, cta],
                  [opener, pitch, value, cta], [opener, pitch, cta]]
    lo, hi_w = config.EMAIL_WORDS
    body = next((wrap(c) for c in candidates if lo <= wc(wrap(c)) <= hi_w), wrap(candidates[-1]))
    subject = _pick([f"{s['collab_angle'].capitalize()} idea for your {theme} channel",
                     f"{b['name']} x {rec['name']}: a collab idea",
                     f"Loved your {theme} content"], key, "s")

    ref = f'"{vid}" video' if vid and len(vid.split()) <= 5 else f"{theme} content"
    dm = _pick([
        f"{hi[:-1] if name else 'Hey'}, loved your {ref}! Your {theme} audience looks like a perfect fit for our {s['collab_angle']} at {b['name']}. Open to details?",
        f"{('Hey ' + name) if name else 'Hey'}! Really enjoyed {ref}. {b['name']} would love to explore a {s['collab_angle']} with you. Interested?",
    ], key, "d")
    return {"subject": subject, "email": body, "dm": dm}


# ------------------------------------------------------------- LLM generator
def llm_generate(s: dict) -> dict:
    b = config.BRAND
    prompt = PROMPT.format(brand=b["name"], product=b["product"], sender=b["sender_name"],
                           ew0=config.EMAIL_WORDS[0], ew1=config.EMAIL_WORDS[1],
                           dw0=config.DM_WORDS[0], dw1=config.DM_WORDS[1],
                           angle=s["collab_angle"], signals=json.dumps(s, indent=2))
    req = urllib.request.Request(
        config.ANTHROPIC_BASE_URL.rstrip("/") + "/v1/messages",
        data=json.dumps({"model": config.LLM_MODEL, "max_tokens": 700,
                         "messages": [{"role": "user", "content": prompt}]}).encode(),
        headers={"x-api-key": config.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"})
    out = json.loads(urllib.request.urlopen(req, timeout=60).read())
    text = "".join(c.get("text", "") for c in out["content"])
    return json.loads(text[text.index("{"): text.rindex("}") + 1])


# ----------------------------------------------------------------- validation
def wc(text: str) -> int:
    return len(text.split())


def valid(msg: dict) -> bool:
    return (all(msg.get(k) for k in ("subject", "email", "dm"))
            and config.EMAIL_WORDS[0] <= wc(msg["email"]) <= config.EMAIL_WORDS[1]
            and config.DM_WORDS[0] <= wc(msg["dm"]) <= config.DM_WORDS[1])


def generate_messages(rec: dict, retries: int = 2) -> dict:
    s = build_signals(rec)
    if config.ANTHROPIC_API_KEY:
        for _ in range(retries + 1):
            try:
                msg = llm_generate(s)
                if valid(msg):
                    return {**msg, "generator": f"llm:{config.LLM_MODEL}", "angle": s["collab_angle"], "signals": s}
            except Exception:
                continue
    msg = rule_generate(rec, s)
    if not valid(msg):
        raise ValueError(f"generated message out of limits for {rec['name']}: "
                         f"email={wc(msg['email'])}w dm={wc(msg['dm'])}w")
    return {**msg, "generator": "rules", "angle": s["collab_angle"], "signals": s}
