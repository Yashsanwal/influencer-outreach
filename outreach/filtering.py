"""Stage 2 - Filtering & classification for the Fashion & Beauty segment.

Every rule returns (passed, reason). A record passes only if all rules pass and
`fail_reasons` lists every rule that failed, so the outcome is fully explainable.
"""
import re

import config

# sub-niche -> keywords (matched on whole words / stems in channel + video text)
SUBNICHES = {
    "skincare": ["skincare", "skin care", "serum", "moisturizer", "cleanser", "sunscreen",
                 "spf", "acne", "retinol", "k-beauty", "kbeauty", "glass skin"],
    "makeup": ["makeup", "make up", "foundation", "lipstick", "eyeshadow", "mascara",
               "grwm", "get ready with me", "concealer", "blush", "drugstore", "palette"],
    "hair": ["hair", "haircare", "curly", "curls", "shampoo", "hairstyle", "wig", "braids"],
    "nails": ["nail", "nails", "manicure", "gel nails"],
    "fragrance": ["perfume", "fragrance", "cologne", "scent"],
    "fashion": ["outfit", "outfits", "fashion", "style", "styling", "wardrobe", "ootd",
                "lookbook", "haul", "thrift", "thrifted", "clothes", "clothing", "dress",
                "sneakers", "capsule", "streetwear", "modest"],
    "grooming": ["grooming", "beard", "skincare for men", "shaving"],
}
# Brand-safety / off-topic markers (channel should not be mainly about these)
BLOCKLIST = ["gambling", "casino", "betting", "crypto signals", "forex", "adult", "18+",
             "mlm", "get rich", "giveaway scam", "kids toys"]
ENGLISH_STOP = {"the", "and", "my", "i", "to", "of", "for", "with", "in", "a", "is", "this",
                "you", "how", "what", "your", "on", "best", "new", "day", "routine", "outfit",
                "makeup", "skin", "haul", "tutorial", "review", "vlog", "hair", "style"}


def _words(text: str) -> list:
    return re.findall(r"[a-z0-9+\-']+", (text or "").lower())


def _hits(text: str, kws: list) -> int:
    t = " " + " ".join(_words(text)) + " "
    return sum(t.count(" " + k + " ") for k in kws)


def corpus(rec: dict) -> str:
    vids = " ".join(v["title"] for v in rec.get("recent_videos", []))
    return f"{rec.get('name','')} {rec.get('description','')} {vids}"


def classify(rec: dict) -> dict:
    """Sub-niche counts and top content themes."""
    text = corpus(rec)
    scores = {k: _hits(text, kws) for k, kws in SUBNICHES.items()}
    ranked = [k for k, v in sorted(scores.items(), key=lambda kv: -kv[1]) if v > 0]
    return {"relevance_score": sum(scores.values()),
            "sub_niche": ranked[0] if ranked else "unclassified",
            "content_themes": ranked[:3] or ["unclassified"],
            "niche_scores": scores}


def english_ratio(rec: dict) -> float:
    titles = [v["title"] for v in rec.get("recent_videos", [])] or [rec.get("description", "")]
    ok = 0
    for t in titles:
        letters = [c for c in t if c.isalpha()]
        if not letters:
            continue
        ascii_share = sum(c.isascii() for c in letters) / len(letters)
        if ascii_share > 0.9 and (set(_words(t)) & ENGLISH_STOP or len(letters) < 12):
            ok += 1
    return ok / len(titles) if titles else 0.0


def evaluate(rec: dict) -> dict:
    """Attach classification + pass/fail with reasons to the record."""
    if not rec.get("enriched"):  # cheap gate: skipped enrichment, only followers were judged
        f = rec.get("followers")
        rec["passed"] = False
        rec["fail_reasons"] = [f"followers {f:,} outside {config.MIN_FOLLOWERS:,}-{config.MAX_FOLLOWERS:,}"
                               if f is not None else "followers unknown"]
        rec["category"] = rec["sub_niche"] = "not evaluated"
        return rec
    rec.update(classify(rec))
    rec["english_ratio"] = round(english_ratio(rec), 2)
    fails = []
    f = rec.get("followers")
    if f is None:
        fails.append("followers unknown")
    elif not config.MIN_FOLLOWERS <= f <= config.MAX_FOLLOWERS:
        fails.append(f"followers {f:,} outside {config.MIN_FOLLOWERS:,}-{config.MAX_FOLLOWERS:,}")
    if rec.get("videos_sampled", 0) < config.MIN_VIDEOS_IN_FEED:
        fails.append("not enough recent posts to compute metrics")
    else:
        er, vr = rec.get("engagement_rate"), rec.get("view_rate")
        if er is None or er < config.MIN_ENGAGEMENT_RATE:
            fails.append(f"engagement rate {er if er is not None else 'n/a'} "
                         f"< {config.MIN_ENGAGEMENT_RATE}")
        if vr is None or vr < config.MIN_VIEW_RATE:
            fails.append(f"view rate {vr if vr is not None else 'n/a'} < {config.MIN_VIEW_RATE}")
        d = rec.get("days_since_last_post")
        if d is None or d > config.MAX_DAYS_SINCE_LAST_POST:
            fails.append(f"inactive (last post {d if d is not None else '?'} days ago)")
    if rec["relevance_score"] < config.MIN_RELEVANCE_SCORE:
        fails.append(f"low fashion/beauty relevance ({rec['relevance_score']} keyword hits "
                     f"< {config.MIN_RELEVANCE_SCORE})")
    if rec["english_ratio"] < config.MIN_ENGLISH_RATIO:
        fails.append(f"content mostly non-English (ratio {rec['english_ratio']})")
    bad = [b for b in BLOCKLIST if _hits(corpus(rec), [b])]
    if bad:
        fails.append("brand-safety: " + ", ".join(bad))
    rec["passed"] = not fails
    rec["fail_reasons"] = fails
    rec["category"] = "Fashion & Beauty" if rec["relevance_score"] >= config.MIN_RELEVANCE_SCORE else "Other"
    return rec
