# Automated Micro-Influencer Outreach System (Fashion & Beauty, YouTube)

Pipeline: **Discovery → Enrichment → Filtering → AI Personalization → Review → Sending → Tracking**

## Quick start
```bash
python3 pipeline.py demo          # run -> approve all -> simulated send -> export (stdlib only, Python 3.9+)
python3 -m unittest discover tests
```
Step by step: `run`, `approve --all` (human review gate), `send [--smtp]`, `export`.
First run takes ~15-25 min (polite rate limit + YouTube throttling); responses are cached in `cache/`, so reruns are fast.

## Stack, tools, data sources
Python 3 standard library only (urllib, sqlite3, csv, smtplib). No paid APIs, no API keys required.
Data sources (all public, no login): YouTube channel-search results, each channel's public page metadata,
the public per-channel RSS feed (last ~15 uploads with titles, dates, views, likes), and a creator's own
website (homepage `/contact`) if linked in their channel description. No Instagram/TikTok scraping.

## Discovery
30 fashion/beauty search queries (`config.SEARCH_QUERIES`) against YouTube's channel search; results are
de-duplicated by channel ID. Sub-5k / >100k channels are still recorded (with the reason they failed).
Adding queries scales discovery to 500+ (cache + SQLite storage; enrichment is the only slow stage).

## Filtering logic (`outreach/filtering.py`, thresholds in `config.py`)
A channel passes only if ALL hold; every failed rule is listed in the `Reasons` column:
followers 5k-100k; engagement rate >= 1% (avg likes per recent video / subscribers); view rate >= 5%
(avg views / subscribers); posted within 45 days; >= 3 recent posts; fashion/beauty keyword relevance >= 3
(channel name + description + recent titles; also yields sub-niche and content themes); mostly English
titles; brand-safety blocklist. Cheap gate first: out-of-range follower counts skip enrichment.

## Enrichment
Metrics from the RSS feed; email/Instagram/TikTok/website extracted by regex from the channel description
(then the creator's own site). Role mailboxes (shipping@, support@...) are ignored. **Emails are never
guessed**: if none is found the value is `Not Found`.
Audience age/gender/geography are not publicly exposed by YouTube, so they are `Not Available`.

## AI personalization (`outreach/personalize.py`)
Signals per creator: first name (only if the channel name looks like a person), sub-niche, tone
(derived from description/titles), a real recent video title (best-performing usable one), real like-rate,
and a collab angle chosen by rules (sponsorship >=50k; UGC if engagement >=4%; barter <15k; affiliate for
fashion/makeup; else ambassador). Two generators:
- **LLM** (when `ANTHROPIC_API_KEY` is set; model `claude-haiku-5-5`): the prompt in `PROMPT` supplies only the
  signals JSON, forbids invented facts, requests 60-90 word email + 15-30 word DM. Output is validated and
  retried, then falls back to rules. *This path is implemented but was not exercised in the submitted run (no key).*
- **Rule-based** (used for the submitted dataset): sentence blocks chosen per creator from the signals, with
  variants selected per channel, and fitted to the word limits. This is signal-driven but more templated than LLM output.

## Sending layer (`outreach/sender.py`)
Selects shortlisted influencers with a valid found email and an **approved** message; sends via SMTP
(`--smtp`, env `SMTP_HOST/PORT/USER/PASSWORD/FROM`) or **simulates** (default, nothing leaves the machine).
Duplicate outreach is blocked by SQLite UNIQUE indexes on (email, channel) and (channel_id, channel).
Every attempt is stored in `outreach_log`. Instagram DMs are never automated: they go to
`data/instagram_dm_queue.csv` for manual sending.

## Outputs (`data/`)
`influencers_all.csv|json` (all discovered, PASSED/FAILED + reasons), `shortlist_enriched.csv`,
`messages.md` (email + DM per shortlisted creator), `outreach_tracker.csv`, `instagram_dm_queue.csv`, `outreach.db`.

## Limitations
- YouTube only; subscriber counts are rounded by YouTube (e.g. "16K").
- Engagement = likes only (comments are not in the RSS feed); it is a proxy, not the standard (likes+comments)/followers.
- Many creators publish no email; those are `Not Found` and not emailed. Page structure may change and break parsing.
- Audience demographics unavailable. Language filter is a heuristic. Brand "Aurelle" is a placeholder (`config.BRAND`).
- Submitted run was a dry-run: **no emails were actually sent**.
