import datetime as dt
import unittest

from radar.collectors import venues


class FindDates(unittest.TestCase):
    today = dt.date(2026, 10, 31)

    def test_month_day_infers_next_occurrence(self):
        self.assertEqual(venues.find_dates("Fri Jan 15", self.today), [dt.date(2027, 1, 15)])
        self.assertEqual(venues.find_dates("Nov 06 Fri", self.today), [dt.date(2026, 11, 6)])

    def test_explicit_year_iso_and_range(self):
        self.assertEqual(venues.find_dates("Friday October 30 2026", self.today), [dt.date(2026, 10, 30)])
        self.assertEqual(venues.find_dates("2026-11-06 20:00", self.today), [dt.date(2026, 11, 6)])
        self.assertEqual(venues.find_dates("Tue, Nov 10, 2026 - Sun, Dec 6, 2026", self.today),
                         [dt.date(2026, 11, 10), dt.date(2026, 12, 6)])

    def test_show_time_preferred_over_doors(self):
        self.assertEqual(venues.find_time("Doors: 7:00 pm | Show: 8:00 pm"), (20, 0))
        self.assertEqual(venues.find_time("8:00PM doors -- music at 8:30PM"), (20, 30))
        self.assertEqual(venues.find_time("2026-11-06 20:00"), (20, 0))


class Cards(unittest.TestCase):
    def test_cards_from_markup(self):
        page = """<div class="ev"><h2>Peter Stampfel</h2><p class="d">Sat Nov 21</p><p class="t">Show 8pm</p>
                  <a href="/e/1">x</a></div><div class="ev"><h2>No Date</h2></div>"""

        class R:
            text, url = page, "https://example.org/cal"
        orig = venues.fetch.get
        venues.fetch.get = lambda *a, **k: R
        try:
            st = {}
            out = venues.collect_cards({"id": "x", "url": R.url, "cards": {"item": "div.ev", "title": "h2", "date": "p.d", "time": "p.t"}}, st)
        finally:
            venues.fetch.get = orig
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["title"], "Peter Stampfel")
        self.assertEqual(out[0]["url"], "https://example.org/e/1")
        self.assertEqual(out[0]["start"].hour, 20)
        self.assertTrue(st["warnings"])


if __name__ == "__main__":
    unittest.main()
