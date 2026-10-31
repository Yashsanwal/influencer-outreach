"""Polite, cached, retrying HTTP client (stdlib only)."""
import hashlib
import time
import urllib.request
import urllib.error

import config

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
_last = 0.0


def fetch(url: str, retries: int = 5, use_cache: bool = True, timeout: int = 20) -> str:
    """GET `url` and return text. Raises RuntimeError after retries are exhausted."""
    global _last
    config.CACHE_DIR.mkdir(exist_ok=True)
    path = config.CACHE_DIR / (hashlib.sha1(url.encode()).hexdigest() + ".txt")
    if use_cache and path.exists():
        return path.read_text(encoding="utf-8")
    err = None
    for attempt in range(retries):
        wait = config.REQUEST_DELAY_S - (time.time() - _last)
        if wait > 0:
            time.sleep(wait)
        _last = time.time()
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": _UA, "Accept-Language": "en-US,en;q=0.9",
                "Cookie": "CONSENT=YES+1"})
            body = urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace")
            path.write_text(body, encoding="utf-8")
            return body
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            err = e
            time.sleep(4 * (attempt + 1))  # YouTube throttles with transient 404/429/5xx
    raise RuntimeError(f"fetch failed for {url}: {err}")


def initial_data(html: str):
    """Extract YouTube's embedded ytInitialData JSON (two markup variants exist)."""
    import json
    import re
    for pat in (r'<script[^>]*id="yt-initial-data"[^>]*>(\{.*?\})</script>',
                r"var ytInitialData = (\{.*?\});</script>"):
        m = re.search(pat, html, re.S)
        if m:
            try:
                return json.loads(m.group(1))
            except ValueError:
                continue
    return None
