# Postmortem: why the radar missed Peter Stampfel at Little Hill Lounge (2026-10-24)

Written 2026-10-25 from the repository, its Actions history, and live probes of the sources. Each finding
is labelled **confirmed** (observed directly) or **hypothesis** (not verifiable from here).

## What the v1 system actually was

- **Confirmed.** The repository was created on 2026-10-20/21. `events.json` held 36 hand-entered records,
  all added in one commit on 2026-10-21 ("Populate 36 verified performances") from earlier ChatGPT
  recommendations. No commit in the history ever added an event after that.
- **Confirmed.** The six-hourly GitHub job (`build.py --refresh`) re-read JSON-LD for the 6 records whose
  source page exposed it (Humanitix, Ticket Tailor, Cafe du Nord, Fillmore) and only confirmed they
  still existed. The other 30 were marked `editorial-review` and never fetched. All 27 scheduled runs
  reported success while discovering nothing. It also incremented every refreshed record's `SEQUENCE`
  on each run even when nothing changed (sequence 24 after four days), which makes subscribed
  calendars reprocess the entries four times a day.
- **Confirmed.** Discovery was delegated to a daily "heartbeat" in a ChatGPT desktop chat that
  required the Mac and app to be running; the README itself says its write path was never proven.
- **Confirmed.** The v1 source list (WATCHLIST.md) did not include Little Hill Lounge, Eventbrite, KALX,
  the California Bluegrass Association, SFFMC, Starry Plough, Eli's, Stork Club, Down Home Music, or any
  house-concert source. It was a list of the venues the recommendations had already come from.
- **Classification:** v1 was a curated calendar publisher with a model-driven recommendation step in
  front of it. It was not a discovery engine: it had no collection stage, no inventory beyond the
  shortlist, no source registry, no per-source logging, and no way to find a show at a venue nobody
  had named.

## Why Stampfel specifically was missed

- **Confirmed: the show was discoverable 33 days early from the venue's own feed.** Little Hill Lounge's
  website is a thin client over a public Google Calendar. That feed carries the show as
  `SUMMARY: Peter Stampfel and Will Sprott`, `DESCRIPTION: folk music; music on at 8pm; tickets $15`,
  `CREATED: 2026-09-21T22:46:04Z`. A reader of that feed needed no artist name to see it.
- **Confirmed: nothing in v1 read that feed, or any Little Hill or Eventbrite source.**
- **Hypothesis:** the ChatGPT heartbeat's web search favours large, well-indexed venue pages and
  ticketing giants; a bar calendar titled "Peter Stampfel and Will Sprott" with no "Atomic Meta-Pagans"
  and no Freight-style SEO page is exactly what such a search misses. I cannot inspect ChatGPT's run
  history, so the timing of its automation being disabled or re-enabled is not evidence either way.
- **Confirmed pattern, not a one-off:** Mountain Grass Unit at Cafe du Nord (2026-10-05) was in the
  venue's own `shows.ics`, which v1 only read for one already-known record. Tony Furtado at Fifth
  Street Farms (2025-12-12) was announced on the house's own WordPress site (`fifthstfarms.com`), which
  v1 did not read; v1's "Fifth Street Farms" URL was the Ticket Tailor page only.

## Systematic biases found in v1

1. Source list = places past recommendations came from; no grassroots calendars, no aggregators.
2. Verification-first design: a record only entered the feed after a human-grade check, so recall was
   capped by the editorial step rather than by what the web exposed.
3. "Success" was measured as the process finishing, not as events found per source.
4. Nothing recorded first-seen dates, so lead time could not even be measured.

## What was kept from v1

- The calendar feed URL and the 36 stable UIDs (`events.json`, now a legacy input), so an existing
  subscription keeps working; `radar.ics` now also carries every event rated strong or better.
- The Pages deployment and the rule that a fetch failure is never evidence of cancellation.
- `pending-leads.json` as historical notes.

Everything else is replaced by the pipeline described in README.md.
