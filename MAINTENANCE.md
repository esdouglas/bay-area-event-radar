# Maintenance plan and operating costs

## Expected costs

| Item | Cost | Notes |
|---|---|---|
| GitHub Actions | $0 | Public repository: unlimited minutes. A collection run takes ~5–15 min (Songkick pacing dominates). |
| GitHub Pages | $0 | |
| Eventbrite API | $0 | Personal token (optional). |
| Google Calendar sync | $0 | Free Google Cloud service account; no billing account needed. |
| Everything else | $0 | No paid API or model is used; total cost is $0. |

## Routine (nothing to do)

- Every 6 h: collect → score → enrich → alert → site. Data is committed to the repo; the repo stays
  active so GitHub never auto-disables the schedule for inactivity.
- Mondays: digest issue. Daily: watchdog.
- If anything goes stale or breaks, a `radar-ops` issue is opened/updated and the watchdog run turns red.

## When a `radar-ops` issue appears

1. Open the dashboard: which sources are failing, since when, and the error.
2. `blocked` = the site now challenges automated clients. Check whether an alternative route exists
   (feed, API, aggregator); otherwise set `enabled: false` with a note so the gap is visible.
3. `format` / zero events from an `ok` source = the page changed. For `jsonld`/`tribe`/`squarespace`
   sources check the URL still lists events; for `venue_*` and `theater_run` sources
   the platform markup changed: run `python -m radar collect --only <id> --dry-run` and fix the parser
   in `radar/collectors/venues.py` / `theater.py`.
   If the site cannot be reached from where you are working, change `.github/dev-snapshot-request`
   (YAML: `urls`, per-source `sources` overrides, `collect` ids) and push: the Dev snapshot workflow
   runs it on a runner, prints the counts, and pushes the fetched pages to a `dev-snap-<run>` tag that
   `RADAR_FETCH_REPLAY=<dir>` can replay locally (`radar.fetch.index_replay_dir`). The next run deletes
   old tags; a request of just `cleanup_only: true` deletes them without making a new one.
4. "no collection run in 14 h" = GitHub skipped or disabled the schedule. Open Actions; a manual
   `workflow_dispatch` of "Collect, rank, alert, publish" restarts it.

## Monthly (15 minutes)

- Skim the dashboard's "Venues represented" list for venues that only appear via aggregators and
  deserve a direct source (a `venue` entry in `sources.yaml`).
- Look at `exceptional` alerts you dismissed and good shows that landed in `noise`: adjust
  `taste.yaml` (seed artists, keyword weights, venue lists). Scores are additive and explained per
  event, so every change is predictable.

## Known limits (honest)

- **Eventbrite**: web pages and the front-end search API answer HTTP 405 to GitHub runners. Only the
  official API with a token works, and it lists by organizer/venue/event id, not by geography, so
  Eventbrite-only shows at venues we have not named still need an aggregator (allevents.in is read).
- **The Back Room (Humanitix)**: collections.humanitix.com answers 403 to GitHub runners (it worked from
  a non-datacenter IP). Second-hand coverage via the SFFMC and Bluegrass Signal calendars (e.g. the
  Newberry & Verch show appears there). A collector run from a residential IP would close this.
- **Freight & Salvage, SFJAZZ, Bandsintown, Rickshaw Stop, Mystic Theatre, Theatre Bay Area, SF Station,
  DoTheBay**: Cloudflare or equivalent challenges. Freight and SFJAZZ are covered second-hand by
  Songkick (partial) and Bluegrass Signal; both are the biggest remaining blind spots and a public feed from either
  venue would close them.
- **Songkick**: serves only CDN-cached pages to automated clients; each run sees roughly half of the
  metro pages, and coverage accumulates across runs. Not a complete source on any single run.
- **No model, by design.** Every source is read by a deterministic parser. Pages that resist one are
  listed in `sources.yaml` with a note; unknown performers are not recognised by name, so scoring relies
  on venue priors, keywords and the daily research task's findings (`data/research.json`). The benchmark
  shows rules alone put 13 of 29 historical events in the alert/digest tiers.
- **Instagram-only announcements** are not collected. Venues that post nowhere else are out of reach.
- **Calendar feed (`radar.ics`)** carries exceptional events and strong events scoring 65+ (about 90 at
  a time) so it stays readable; the site holds the full inventory.
- **Heuristic extraction leaves the venue blank** on calendar-style pages (Bluegrass Signal, SFFMC), so a
  show seen there and on the venue's own page can appear twice (text lines are deliberately never
  merged into structured records by time alone).
- **Caches** (`data/cache/`, page hashes and detail-page extractions) are committed so Actions runs reuse
  them; entries untouched for 21 days are pruned automatically.
