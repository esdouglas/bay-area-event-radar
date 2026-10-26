import datetime as dt
import unittest

from radar import normalize, store
from radar.collectors.common import jsonld_blocks, raw_from_schema, walk_events, links
from radar.collectors.structured import collect_ics
from radar.rank import _compile, load_taste, score_event, tier_for


class NormalizeTests(unittest.TestCase):
    def test_venue_aliases(self):
        self.assertEqual(normalize.norm_venue("The Freight & Salvage"), "Freight & Salvage")
        self.assertEqual(normalize.norm_venue("freight and salvage"), "Freight & Salvage")
        self.assertEqual(normalize.venue_key("Little Hill Lounge"), normalize.venue_key("little hill lounge"))

    def test_dedup_key_collapses_support_acts(self):
        a = normalize.dedup_key("Little Hill Lounge", "2026-10-24", "Peter Stampfel and Will Sprott")
        b = normalize.dedup_key("Little Hill Lounge", "2026-10-24", "Peter Stampfel & the Atomic Meta-Pagans w/ Will Sprott")
        self.assertEqual(a.split("|")[:2], b.split("|")[:2])
        self.assertGreater(normalize.similar_titles("Peter Stampfel and Will Sprott", "Peter Stampfel & the Atomic Meta-Pagans"), 0.3)

    def test_parse_dt_shapes(self):
        self.assertEqual(normalize.parse_dt("2026-10-29T19:00:00-0700").isoformat(), "2026-10-29T19:00:00-07:00")
        self.assertEqual(normalize.parse_dt("2026-10-25T03:00:00Z").hour, 20)  # 8 PM PDT
        self.assertEqual(normalize.parse_dt(1793149200546).year, 2026)
        self.assertIsNone(normalize.parse_dt("not a date at all"))

    def test_region(self):
        self.assertEqual(normalize.region_of("El Cerrito"), "bay")
        self.assertEqual(normalize.region_of("Santa Cruz"), "bay")
        self.assertEqual(normalize.region_of("Sacramento"), "norcal")
        self.assertEqual(normalize.region_of("Portland", "OR"), "outside")
        self.assertEqual(normalize.region_of(""), "unknown")


class StoreTests(unittest.TestCase):
    def test_upsert_merges_across_sources(self):
        events, stats = {}, {}
        src_a = {"id": "venue-feed", "venue": {"name": "Little Hill Lounge", "city": "El Cerrito"}}
        src_b = {"id": "aggregator", "venue": {}}
        r1 = store.normalize_raw({"title": "Peter Stampfel and Will Sprott", "start": "2026-10-24T20:00:00-07:00", "url": "https://a/1"}, src_a)
        r2 = store.normalize_raw({"title": "Peter Stampfel & the Atomic Meta-Pagans", "start": "2026-10-24T20:00:00-07:00", "venue": "Little Hill Lounge", "city": "El Cerrito", "url": "https://b/2", "performers": ["Peter Stampfel"]}, src_b)
        eid1, new1 = store.upsert(events, r1, "venue-feed", "2026-09-21T00:00:00+00:00", stats)
        eid2, new2 = store.upsert(events, r2, "aggregator", "2026-10-01T00:00:00+00:00", stats)
        self.assertTrue(new1)
        self.assertFalse(new2)
        self.assertEqual(eid1, eid2)
        e = events[eid1]
        self.assertEqual(e["first_seen"], "2026-09-21T00:00:00+00:00")
        self.assertEqual(len(e["sources"]), 2)
        self.assertEqual(e["performers"], ["Peter Stampfel"])

    def test_different_nights_do_not_merge(self):
        events, stats = {}, {}
        src = {"id": "s", "venue": {"name": "X", "city": "Oakland"}}
        store.upsert(events, store.normalize_raw({"title": "Karaoke", "start": "2026-11-04T20:00:00-08:00"}, src), "s", "t", stats)
        store.upsert(events, store.normalize_raw({"title": "Karaoke", "start": "2026-11-11T20:00:00-08:00"}, src), "s", "t", stats)
        self.assertEqual(len(events), 2)


class ParserTests(unittest.TestCase):
    def test_jsonld_event_extraction(self):
        html = '<html><script type="application/ld+json">{"@context":"https://schema.org","@type":"MusicEvent","name":"Nora Brown","startDate":"2027-01-11T19:00:00-08:00","location":{"@type":"Place","name":"Kuumbwa Jazz Center","address":{"@type":"PostalAddress","addressLocality":"Santa Cruz","addressRegion":"CA"}},"performer":[{"@type":"MusicGroup","name":"Nora Brown"}],"offers":{"url":"https://t/1","price":"30","priceCurrency":"USD"}}</script></html>'
        evs = list(walk_events(jsonld_blocks(html)))
        self.assertEqual(len(evs), 1)
        raw = raw_from_schema(evs[0], "https://x/")
        self.assertEqual(raw["venue"], "Kuumbwa Jazz Center")
        self.assertEqual(raw["city"], "Santa Cruz")
        self.assertEqual(raw["performers"], ["Nora Brown"])
        self.assertEqual(raw["price"], "30 USD")

    def test_links_unescape_entities(self):
        html = '<a href="&#x2F;events&#x2F;fifthstreetfarms&#x2F;2431227">x</a><a href="/other">y</a>'
        self.assertEqual(links(html, "https://buytickets.at/fifthstreetfarms", r"fifthstreetfarms/\d+"), ["https://buytickets.at/events/fifthstreetfarms/2431227"])

    def test_ics_created_becomes_announced(self):
        from unittest.mock import patch
        ics = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nDTSTART:20991025T030000Z\r\nDTEND:20991025T053000Z\r\nUID:x@google.com\r\n"
               "CREATED:20260921T224604Z\r\nDESCRIPTION:folk music\r\nSUMMARY:Peter Stampfel and Will Sprott\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
        class R:
            content = ics.encode()
        with patch("radar.fetch.get", return_value=R()), patch("radar.config.HORIZON_DAYS", 40000):
            out = collect_ics({"id": "t", "url": "https://x/basic.ics", "venue": {"name": "Little Hill Lounge"}}, {})
        self.assertEqual(out[0]["title"], "Peter Stampfel and Will Sprott")
        self.assertTrue(out[0]["announced"].startswith("2026-09-21"))


class RankTests(unittest.TestCase):
    def setUp(self):
        self.C = _compile(load_taste())

    def _ev(self, title, venue, desc="", srcs=("x",)):
        return {"title": title, "performers": [], "description": desc, "tags": [], "venue": normalize.norm_venue(venue), "venue_raw": venue,
                "sources": [{"source": s} for s in srcs], "category": "music", "date": "2026-12-01", "region": "bay", "status": "scheduled"}

    def test_seed_artist_in_small_room_is_exceptional(self):
        sc, reasons, sig = score_event(self._ev("Peter Stampfel and Will Sprott", "Little Hill Lounge"), self.C, dt.date(2026, 10, 1))
        self.assertGreaterEqual(sc, 78)
        self.assertEqual(tier_for(sc, self.C["tiers"], None, sig), "exceptional")

    def test_karaoke_is_noise(self):
        sc, _, sig = score_event(self._ev("Karaoke Wednesday 8-11pm", "Little Hill Lounge"), self.C, dt.date(2026, 10, 1))
        self.assertEqual(tier_for(sc, self.C["tiers"], None, sig), "noise")

    def test_unknown_trio_cannot_be_exceptional_without_model(self):
        sc, _, sig = score_event(self._ev("Generic Name Trio", "Kuumbwa Jazz", "jazz trio improvisation"), self.C, dt.date(2026, 10, 1))
        self.assertNotEqual(tier_for(sc, self.C["tiers"], None, sig), "exceptional")

    def test_model_fit_lifts_unknown_name(self):
        sc, _, sig = score_event(self._ev("Rakish", "Red Poppy Art House"), self.C, dt.date(2026, 10, 1))
        self.assertEqual(tier_for(sc, self.C["tiers"], 90, sig), "exceptional")


if __name__ == "__main__":
    unittest.main()


class EnrichTests(unittest.TestCase):
    def test_pipeline_with_fake_model(self):
        """End-to-end enrich on a tiny inventory with the model stubbed out: tiers and caches update."""
        import json, os, tempfile
        from unittest.mock import patch
        from radar import config, enrich, llm, rank
        fast = json.dumps({"fit": 92, "known": True, "significance": "foundational", "why": "Holy Modal Rounders founder in a bar", "flags": ["historic"]})
        deep = json.dumps({"fit": 95, "tier": "exceptional", "headline": "Psych-folk founder, 100 seats", "why": "why", "background": "bg",
                           "scarcity": "rare", "uncertainty": "none", "performers": [{"name": "Peter Stampfel", "known_for": "Holy Modal Rounders", "significance": "foundational"}]})
        calls = []

        def fake_complete(system, user, tier="fast", **kw):
            calls.append(tier)
            return fast if tier == "fast" else deep
        with tempfile.TemporaryDirectory() as d:
            ev = {"title": "Peter Stampfel and Will Sprott", "performers": [], "description": "", "tags": [], "venue": "Little Hill Lounge", "venue_raw": "Little Hill Lounge",
                  "city": "El Cerrito", "region": "bay", "category": "music", "date": "2099-10-24", "start": "2099-10-24T20:00:00-07:00", "status": "scheduled",
                  "url": "https://x", "sources": [{"source": "little-hill-lounge", "url": "https://x", "first_seen": "t", "last_seen": "t"}], "first_seen": "2099-09-21T00:00:00+00:00",
                  "last_seen": "t", "id": "ev_test", "score": 42.0, "tier": "inventory", "enrichment": None, "signals": {"seed_hits": [], "keyword_groups": []}}
            with patch.object(config, "EVENTS_FILE", __import__("pathlib").Path(d) / "events.json"), patch.object(config, "ARTISTS_FILE", __import__("pathlib").Path(d) / "artists.json"), \
                 patch.object(config, "COSTS_FILE", __import__("pathlib").Path(d) / "costs.jsonl"), patch.object(config, "DATA", __import__("pathlib").Path(d)), \
                 patch.object(llm, "available", lambda: True), patch.object(llm, "complete", fake_complete), patch.object(llm, "model_for", lambda t: "fake"), \
                 patch.object(enrich, "wiki_lookup", lambda name, artists: None):
                from radar import store
                store.save_events({"ev_test": ev})
                res = enrich.run(limit=5)
                out = store.load_events()["ev_test"]
            self.assertEqual(res["researched"], 1)
            self.assertEqual(calls, ["fast", "smart"])
            self.assertEqual(out["tier"], "exceptional")
            self.assertGreaterEqual(out["final_score"], 78)
            self.assertEqual(out["enrichment"]["deep"]["performers"][0]["significance"], "foundational")


class NotifyTests(unittest.TestCase):
    def test_dry_run_notify_and_digest_do_not_crash(self):
        import io, contextlib, pathlib, tempfile
        from unittest.mock import patch
        from radar import config, notify, store
        with tempfile.TemporaryDirectory() as d:
            dp = pathlib.Path(d)
            ev = {"id": "ev_a", "title": "Peter Stampfel and Will Sprott", "date": "2099-10-24", "start": "2099-10-24T20:00:00-07:00", "venue": "Little Hill Lounge",
                  "city": "El Cerrito", "status": "scheduled", "tier": "exceptional", "score": 90.0, "final_score": 90.0, "url": "https://x", "first_seen": "2099-09-21T00:00:00+00:00",
                  "sources": [{"source": "little-hill-lounge", "url": "https://x", "first_seen": "t", "last_seen": "t"}], "score_reasons": ["seed artist"], "region": "bay", "performers": [], "tags": []}
            with patch.object(config, "EVENTS_FILE", dp / "events.json"), patch.object(config, "ALERTS_FILE", dp / "alerts.json"), \
                 patch.object(config, "SOURCE_HEALTH_FILE", dp / "health.json"), patch.object(config, "COSTS_FILE", dp / "costs.jsonl"), \
                 patch.object(config, "DATA", dp), patch.dict("os.environ", {"GITHUB_TOKEN": ""}):
                store.save_events({"ev_a": ev})
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    notify.run(digest_flag=True, dry_run=True)
                out = buf.getvalue()
            self.assertIn("[dry-run issue] [radar] Peter Stampfel", out)
            self.assertIn("[radar digest]", out)
            self.assertFalse(notify.live_enabled())
