"""SQLite storage: influencers, messages, outreach log."""
import json
import sqlite3
from datetime import datetime, timezone

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS influencers (
  channel_id TEXT PRIMARY KEY, data TEXT NOT NULL, passed INTEGER, updated_at TEXT);
CREATE TABLE IF NOT EXISTS messages (
  channel_id TEXT PRIMARY KEY, email_subject TEXT, email_body TEXT, instagram_dm TEXT,
  collab_angle TEXT, generator TEXT, approved INTEGER DEFAULT 0, created_at TEXT);
CREATE TABLE IF NOT EXISTS outreach_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id TEXT, email TEXT, channel TEXT,
  status TEXT, detail TEXT, sent_at TEXT);
-- Duplicate protection: one successful/simulated email per address and per channel.
CREATE UNIQUE INDEX IF NOT EXISTS uq_sent_email ON outreach_log(email, channel)
  WHERE status IN ('SENT','SIMULATED');
CREATE UNIQUE INDEX IF NOT EXISTS uq_sent_channel ON outreach_log(channel_id, channel)
  WHERE status IN ('SENT','SIMULATED');
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    config.DATA_DIR.mkdir(exist_ok=True)
    con = sqlite3.connect(config.DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def save_influencer(con, rec: dict):
    con.execute("INSERT OR REPLACE INTO influencers VALUES (?,?,?,?)",
                (rec["channel_id"], json.dumps(rec), int(rec.get("passed", 0)), now()))
    con.commit()


def load_influencers(con) -> list:
    return [json.loads(r["data"]) for r in con.execute("SELECT data FROM influencers")]
