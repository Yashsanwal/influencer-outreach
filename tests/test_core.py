"""Offline unit tests: python -m unittest discover tests"""
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
from outreach import discovery, enrich, filtering, personalize, sender, storage


def rec(**kw):
    base = {"channel_id": "UC1", "name": "Maya Lin", "platform": "YouTube", "followers": 20000,
            "profile_url": "https://youtube.com/channel/UC1", "enriched": True, "videos_sampled": 10,
            "engagement_rate": 0.03, "view_rate": 0.12, "days_since_last_post": 5,
            "description": "Skincare routines and makeup tutorials for beginners",
            "recent_videos": [{"title": f"My night skincare routine {i} the best makeup tips",
                               "views": 1000 * i, "likes": 50, "published": ""} for i in range(1, 6)],
            "email": "maya@example.org", "instagram": "@maya"}
    base.update(kw)
    return base


class Discovery(unittest.TestCase):
    def test_parse_count(self):
        self.assertEqual(discovery.parse_count("12.3K subscribers"), 12300)
        self.assertEqual(discovery.parse_count("1.14M subscribers"), 1_140_000)
        self.assertIsNone(discovery.parse_count("no subscribers listed"))


class Enrichment(unittest.TestCase):
    def test_contacts_never_guess(self):
        self.assertEqual(enrich.extract_contacts("hello, no contact here")["emails"], [])
        c = enrich.extract_contacts("Biz: hi@maya.co  IG https://instagram.com/maya.glow shop https://maya.co")
        self.assertEqual(c["emails"], ["hi@maya.co"])
        self.assertEqual(c["instagram"], "@maya.glow")
        self.assertEqual(c["website"], "https://maya.co")

    def test_metrics(self):
        vids = [{"views": 1000, "likes": 50, "published": "2026-01-01T00:00:00+00:00"}] * 4
        m = enrich.compute_metrics(vids, 10000)
        self.assertEqual(m["engagement_rate"], 0.005)
        self.assertEqual(m["view_rate"], 0.1)


class Filtering(unittest.TestCase):
    def test_pass(self):
        self.assertTrue(filtering.evaluate(rec())["passed"])

    def test_reasons(self):
        r = filtering.evaluate(rec(followers=500_000, engagement_rate=0.001, days_since_last_post=200))
        self.assertFalse(r["passed"])
        self.assertEqual(len(r["fail_reasons"]), 3)

    def test_irrelevant(self):
        r = filtering.evaluate(rec(description="gaming let's plays", recent_videos=[
            {"title": "minecraft the best build", "views": 1, "likes": 1, "published": ""}] * 5))
        self.assertTrue(any("relevance" in x for x in r["fail_reasons"]))


class Personalization(unittest.TestCase):
    def test_limits_and_variation(self):
        config.ANTHROPIC_API_KEY = None
        seen = set()
        for i in range(30):
            r = filtering.evaluate(rec(channel_id=f"UC{i}", followers=8000 + i * 3000))
            m = personalize.generate_messages(r)
            self.assertTrue(60 <= personalize.wc(m["email"]) <= 90, m["email"])
            self.assertTrue(15 <= personalize.wc(m["dm"]) <= 30, m["dm"])
            seen.add(m["dm"])
        self.assertGreater(len(seen), 1)

    def test_title_cleaning(self):
        self.assertIsNone(personalize.clean_title("#shorts 😍"))
        self.assertEqual(personalize.clean_title("My Night Skincare Routine | 2026"), "My Night Skincare Routine")


class Sending(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        config.DB_PATH = Path(self.tmp.name) / "t.db"
        config.DATA_DIR = Path(self.tmp.name)
        self.con = storage.connect()

    def add(self, r, approved=1):
        r = filtering.evaluate(r)
        storage.save_influencer(self.con, r)
        self.con.execute("INSERT INTO messages VALUES (?,?,?,?,?,?,?,?)",
                         (r["channel_id"], "s", "b", "dm", "a", "rules", approved, ""))
        self.con.commit()

    def test_no_duplicates_and_missing_email(self):
        self.add(rec(channel_id="A", email="x@y.com"))
        self.add(rec(channel_id="B", email="Not Found"))
        self.add(rec(channel_id="C", email="x@y.com"))  # same address as A
        s1 = sender.send_emails(self.con, log=lambda *_: None)
        self.assertEqual((s1["SIMULATED"], s1["SKIPPED_NO_EMAIL"], s1["SKIPPED_DUPLICATE"]), (1, 1, 1))
        s2 = sender.send_emails(self.con, log=lambda *_: None)  # second run sends nothing new
        self.assertEqual(s2["SIMULATED"], 0)

    def test_unapproved_not_sent(self):
        self.add(rec(channel_id="A"), approved=0)
        self.assertEqual(sender.send_emails(self.con, log=lambda *_: None)["SIMULATED"], 0)


if __name__ == "__main__":
    unittest.main()
