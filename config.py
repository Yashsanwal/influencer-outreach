"""Central configuration. Override secrets via environment variables."""
import os
from pathlib import Path

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
CACHE_DIR = ROOT / "cache"
DB_PATH = DATA_DIR / "outreach.db"

# --- Brand sending the outreach (placeholder: change to your own brand) -----
BRAND = {
    "name": os.getenv("BRAND_NAME", "Aurelle"),
    "product": os.getenv("BRAND_PRODUCT", "clean skincare and makeup line"),
    "sender_name": os.getenv("SENDER_NAME", "Maya from Aurelle"),
}

# --- Target segment: Fashion & Beauty micro-influencers on YouTube ----------
MIN_FOLLOWERS = 5_000
MAX_FOLLOWERS = 100_000
MIN_ENGAGEMENT_RATE = 0.01     # avg likes per video / subscribers (>=1%)
MIN_VIEW_RATE = 0.05           # avg views per video / subscribers (>=5%)
MAX_DAYS_SINCE_LAST_POST = 45  # still active
MIN_RELEVANCE_SCORE = 3        # fashion/beauty keyword hits (see filtering.py)
MIN_ENGLISH_RATIO = 0.7        # share of recent titles that are English-looking
MIN_VIDEOS_IN_FEED = 3         # need enough posts to compute metrics

# --- Discovery ---------------------------------------------------------------
SEARCH_QUERIES = [
    "skincare routine", "everyday makeup tutorial", "get ready with me",
    "drugstore makeup review", "korean skincare routine", "outfit ideas",
    "thrift haul", "fashion haul", "capsule wardrobe", "hair care routine",
    "clean beauty review", "makeup for beginners", "styling tips",
    "affordable fashion", "night skincare routine", "minimalist makeup",
    "summer outfits lookbook", "beauty product empties", "curly hair routine",
    "sustainable fashion", "plus size fashion", "men's grooming routine",
    "nail art tutorial", "dark skin makeup tutorial", "winter outfit ideas",
    "wardrobe essentials", "makeup collection declutter", "body care routine",
    "fragrance collection", "modest fashion",
]
REQUEST_DELAY_S = 0.6

# --- Personalisation ---------------------------------------------------------
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
LLM_MODEL = os.getenv("LLM_MODEL", "claude-haiku-5-5")
EMAIL_WORDS = (60, 90)
DM_WORDS = (15, 30)

# --- Sending -----------------------------------------------------------------
SMTP = {
    "host": os.getenv("SMTP_HOST"), "port": int(os.getenv("SMTP_PORT", "587")),
    "user": os.getenv("SMTP_USER"), "password": os.getenv("SMTP_PASSWORD"),
    "from": os.getenv("SMTP_FROM"),
}
