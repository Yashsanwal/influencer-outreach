#!/usr/bin/env python3
"""Influencer outreach pipeline CLI.

  python pipeline.py run                 discover -> enrich -> filter -> generate messages
  python pipeline.py approve --all       human review gate (approve generated messages)
  python pipeline.py send [--smtp]       send (default: simulate) approved emails + DM queue
  python pipeline.py export              write CSV/JSON/Markdown deliverables to data/
  python pipeline.py demo                run + approve --all + send (dry-run) + export
"""
import argparse
import csv
import json
import sys
from concurrent.futures import ThreadPoolExecutor

import config
from outreach import discovery, enrich, filtering, personalize, sender, storage


def cmd_run(args):
    con = storage.connect()
    print("1/4 Discovery")
    found = discovery.discover(log=print)
    print(f"   -> {len(found)} unique channels discovered")
    in_range = [r for r in found.values() if r["followers"] is not None
                and config.MIN_FOLLOWERS <= r["followers"] <= config.MAX_FOLLOWERS]
    print(f"2/4 Enrichment ({len(in_range)} channels in follower range)")

    def work(r):
        try:
            enrich.enrich(r)
            r["enriched"] = True
        except Exception as e:
            r["enriched"], r["notes"] = False, [f"enrichment error: {e}"]
        return r
    # network is the bottleneck, but http.fetch rate-limits globally, so keep it sequential
    for i, r in enumerate(in_range, 1):
        work(r)
        if i % 10 == 0:
            print(f"   enriched {i}/{len(in_range)}")
    print("3/4 Filtering & classification")
    for r in found.values():
        filtering.evaluate(r)
        storage.save_influencer(con, r)
    passed = [r for r in found.values() if r["passed"]]
    print(f"   -> {len(passed)} passed, {len(found) - len(passed)} failed")
    print("4/4 Message generation")
    for r in passed:
        try:
            m = personalize.generate_messages(r)
        except Exception as e:
            print(f"   ! {r['name']}: {e}")
            continue
        con.execute("INSERT OR REPLACE INTO messages(channel_id,email_subject,email_body,instagram_dm,"
                    "collab_angle,generator,approved,created_at) VALUES (?,?,?,?,?,?,0,?)",
                    (r["channel_id"], m["subject"], m["email"], m["dm"], m["angle"],
                     m["generator"], storage.now()))
    con.commit()
    print("done. Review messages, then: python pipeline.py approve --all")


def cmd_approve(args):
    con = storage.connect()
    if args.all:
        n = con.execute("UPDATE messages SET approved=1").rowcount
    else:
        n = con.execute("UPDATE messages SET approved=1 WHERE channel_id IN (%s)" %
                        ",".join("?" * len(args.ids)), args.ids).rowcount
    con.commit()
    print(f"approved {n} message sets")


def cmd_send(args):
    con = storage.connect()
    stats = sender.send_emails(con, "smtp" if args.smtp else "dry-run")
    n = sender.queue_dms(con, config.DATA_DIR / "instagram_dm_queue.csv")
    print("email:", stats)
    print(f"instagram DM manual queue: {n} rows -> data/instagram_dm_queue.csv")


def _fmt(x):
    return "" if x is None else x


def cmd_export(args):
    con = storage.connect()
    recs = sorted(storage.load_influencers(con), key=lambda r: (not r["passed"], -(r.get("followers") or 0)))
    d = config.DATA_DIR
    with open(d / "influencers_all.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Name", "Platform", "Followers", "Engagement Rate (avg likes/subs)", "View Rate",
                    "Niche", "Email", "Profile URL", "Content Themes", "Status", "Reasons"])
        for r in recs:
            w.writerow([r["name"], r["platform"], _fmt(r["followers"]), _fmt(r.get("engagement_rate")),
                        _fmt(r.get("view_rate")), r.get("sub_niche", ""), r.get("email", "Not evaluated"),
                        r["profile_url"], ", ".join(r.get("content_themes", [])),
                        "PASSED" if r["passed"] else "FAILED",
                        "meets all criteria" if r["passed"] else "; ".join(r["fail_reasons"])])
    short = [r for r in recs if r["passed"]]
    cols = ["name", "platform", "profile_url", "followers", "engagement_rate", "view_rate", "category",
            "sub_niche", "content_themes", "email", "email_source", "instagram", "tiktok", "website",
            "audience_age", "audience_gender", "audience_geography", "avg_views", "days_since_last_post"]
    with open(d / "shortlist_enriched.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in short:
            w.writerow([", ".join(r[c]) if isinstance(r.get(c), list) else _fmt(r.get(c)) for c in cols])
    with open(d / "influencers_all.json", "w", encoding="utf-8") as f:
        json.dump(recs, f, indent=1, ensure_ascii=False)
    msgs = {r["channel_id"]: r for r in con.execute("SELECT * FROM messages")}
    with open(d / "messages.md", "w", encoding="utf-8") as f:
        f.write("# Personalized outreach messages\n\n")
        for r in short:
            m = msgs.get(r["channel_id"])
            if not m:
                continue
            f.write(f"## {r['name']} ({r['followers']:,} subs, {r.get('sub_niche')})\n"
                    f"*Angle: {m['collab_angle']} | generator: {m['generator']} | email: {r['email']}*\n\n"
                    f"**Subject:** {m['email_subject']}\n\n{m['email_body']}\n\n"
                    f"**Instagram DM:** {m['instagram_dm']}\n\n---\n\n")
    with open(d / "outreach_tracker.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Influencer", "Email", "Message Generated", "Approved", "Sent", "Date", "Status", "Detail"])
        for r in short:
            m = msgs.get(r["channel_id"])
            log = con.execute("SELECT * FROM outreach_log WHERE channel_id=? AND channel='email' "
                              "ORDER BY id DESC LIMIT 1", (r["channel_id"],)).fetchone()
            real = bool(log and log["status"] == "SENT")
            w.writerow([r["name"], r["email"], "Yes" if m else "No", "Yes" if m and m["approved"] else "No",
                        "Yes" if real else "No", log["sent_at"] if log else "",
                        log["status"] if log else "PENDING", log["detail"] if log else ""])
    print(f"exported {len(recs)} records ({len(short)} shortlisted) to data/")


def cmd_demo(args):
    cmd_run(args)
    args.all = True
    cmd_approve(args)
    args.smtp = False
    cmd_send(args)
    cmd_export(args)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="cmd", required=True)
    sp.add_parser("run").set_defaults(fn=cmd_run)
    a = sp.add_parser("approve")
    a.add_argument("--all", action="store_true")
    a.add_argument("ids", nargs="*")
    a.set_defaults(fn=cmd_approve)
    s = sp.add_parser("send")
    s.add_argument("--smtp", action="store_true", help="really send via SMTP (default: simulate)")
    s.set_defaults(fn=cmd_send)
    sp.add_parser("export").set_defaults(fn=cmd_export)
    sp.add_parser("demo").set_defaults(fn=cmd_demo)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
