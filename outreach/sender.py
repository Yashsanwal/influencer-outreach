"""Stage 6 - Sending layer: email via SMTP (or simulated), DM via manual queue.

Rules enforced here:
  * only influencers with a syntactically valid, *found* email are emailed
  * only human-approved messages are sent
  * a UNIQUE index in SQLite (see storage.py) blocks duplicate outreach per email/channel
  * every attempt - sent, simulated, skipped, failed - is written to outreach_log
Instagram DMs are never automated (Meta's API does not permit cold DMs); they are
written to a manual queue instead.
"""
import csv
import re
import smtplib
import sqlite3
from email.message import EmailMessage

import config
from . import storage

VALID_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


def _log(con, rec, email, channel, status, detail=""):
    try:
        con.execute("INSERT INTO outreach_log(channel_id,email,channel,status,detail,sent_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (rec["channel_id"], email, channel, status, detail, storage.now()))
        con.commit()
        return True
    except sqlite3.IntegrityError:
        con.rollback()
        return False


def _smtp_send(to: str, subject: str, body: str):
    c = config.SMTP
    if not (c["host"] and c["user"] and c["password"]):
        raise RuntimeError("SMTP_HOST/SMTP_USER/SMTP_PASSWORD not configured")
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = c["from"] or c["user"], to, subject
    msg.set_content(body)
    with smtplib.SMTP(c["host"], c["port"], timeout=30) as s:
        s.starttls()
        s.login(c["user"], c["password"])
        s.send_message(msg)


def send_emails(con, mode: str = "dry-run", log=print) -> dict:
    """mode: 'dry-run' (simulate, default) or 'smtp' (really send)."""
    stats = {"SENT": 0, "SIMULATED": 0, "SKIPPED_NO_EMAIL": 0, "SKIPPED_DUPLICATE": 0,
             "SKIPPED_NOT_APPROVED": 0, "FAILED": 0}
    rows = {r["channel_id"]: r for r in con.execute("SELECT * FROM messages")}
    for rec in storage.load_influencers(con):
        if not rec.get("passed"):
            continue
        cid, email = rec["channel_id"], rec.get("email", "Not Found")
        m = rows.get(cid)
        if not m or not m["approved"]:
            stats["SKIPPED_NOT_APPROVED"] += 1
            continue
        if not VALID_EMAIL.match(email or ""):
            if not con.execute("SELECT 1 FROM outreach_log WHERE channel_id=? AND channel='email'",
                               (cid,)).fetchone():
                _log(con, rec, email, "email", "SKIPPED_NO_EMAIL", "no valid contact email found")
            stats["SKIPPED_NO_EMAIL"] += 1
            continue
        dup = con.execute("SELECT 1 FROM outreach_log WHERE channel='email' AND status IN "
                          "('SENT','SIMULATED') AND (email=? OR channel_id=?)", (email, cid)).fetchone()
        if dup:
            _log(con, rec, email, "email", "SKIPPED_DUPLICATE", "already contacted")
            stats["SKIPPED_DUPLICATE"] += 1
            continue
        try:
            if mode == "smtp":
                _smtp_send(email, m["email_subject"], m["email_body"])
                status, detail = "SENT", "delivered to SMTP server"
            else:
                status, detail = "SIMULATED", "dry-run: email not actually sent"
        except Exception as e:
            status, detail = "FAILED", str(e)
        if _log(con, rec, email, "email", status, detail):
            stats[status] += 1
            log(f"  [{status}] {rec['name']} <{email}>")
    return stats


def queue_dms(con, path) -> int:
    """Write the manual Instagram DM queue (no automated cold DMs)."""
    msgs = {r["channel_id"]: r for r in con.execute("SELECT * FROM messages WHERE approved=1")}
    n = 0
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["influencer", "instagram_handle", "profile_url", "dm_text", "status", "sent_by_hand_on"])
        for rec in storage.load_influencers(con):
            m = msgs.get(rec["channel_id"])
            if rec.get("passed") and m:
                w.writerow([rec["name"], rec.get("instagram", "Not Found"), rec["profile_url"],
                            m["instagram_dm"],
                            "MANUAL_PENDING" if rec.get("instagram", "Not Found") != "Not Found"
                            else "NO_INSTAGRAM_HANDLE_FOUND", ""])
                n += 1
    return n
