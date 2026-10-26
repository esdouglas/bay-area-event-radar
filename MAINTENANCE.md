# Maintenance plan and operating costs

## Expected costs

| Item | Cost | Notes |
|---|---|---|
| GitHub Actions | $0 | Public repository: unlimited minutes. A collection run takes ~5–15 min (Songkick pacing dominates). |
| GitHub Pages | $0 | |
| Model enrichment | ~$3–12 / month | Fast pass (`claude-haiku-5-5`, $0.10/M in, $0.50/M out): ~300–600 candidate judgements/week at ~1.2k tokens ≈ $0.10/week. Deep pass (`claude-sonnet-5-5`, $2/$10 per M): ~50–120/week at ~3k tokens ≈ $1–3/week. HTML extraction: ~45 pages, only when their text changes, ~8k tokens each on Haiku ≈ $0.05/day. Actuals are in `data/costs.jsonl` and on the dashboard. |
| Eventbrite API | $0 | Personal token. |
| Everything else | $0 | |

Prices verified against platform.claude.com/docs/en/models/overview on 2026-10-25; update `PRICES` in
`radar/llm.py` when they change.

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
   sources check the URL still lists events; for `html` sources the model extraction usually survives
   redesigns, but check `data/cache/` output with `python -m radar collect --only <id> --dry-run`.
4. "no collection run in 14 h" = GitHub skipped or disabled the schedule. Open Actions; a manual
   `workflow_dispatch` of "Collect, rank, alert, publish" restarts it.

## Monthly (15 minutes)

- Skim the dashboard's "Venues represented" list for venues that only appear via aggregators and
  deserve a direct source (a `venue` entry in `sources.yaml`).
- Look at `noise`-tier events with high model fit, and `exceptional` alerts you dismissed: adjust
  `taste.yaml` (seed artists, keyword weights, venue lists). Scores are additive and explained per
  event, so every change is predictable.
- Check `data/costs.jsonl` totals against the budget above.

## Known limits (honest)

- **Eventbrite**: web pages and the front-end search API answer HTTP 405 to GitHub runners. Only the
  official API with a token works, and it lists by organizer/venue/event id, not by geography, so
  Eventbrite-only shows at venues we have not named still need an aggregator (allevents.in is read).
- **Freight & Salvage, SFJAZZ, Bandsintown, Rickshaw Stop, Mystic Theatre, Theatre Bay Area, SF Station,
  DoTheBay**: Cloudflare or equivalent challenges. Freight and SFJAZZ are covered second-hand by
  Songkick (partial) and Bluegrass Signal; both are the biggest remaining blind spots and an official
  API key or feed from either venue would close them.
- **Songkick**: serves only CDN-cached pages to automated clients; each run sees roughly half of the
  metro pages, and coverage accumulates across runs. Not a complete source on any single run.
- **Without a model key** the `html` sources use a crude date-line heuristic (marked `heuristic` on
  each event, scored down 8 points) and unknown performers cannot be recognised; the benchmark shows
  rules alone would have put 13 of 29 historical events in the alert/digest tiers.
- **Instagram-only announcements** are not collected. Venues that post nowhere else are out of reach.

## Changing the model provider

Set `RADAR_LLM_PROVIDER=openai` and `OPENAI_API_KEY`, or point `RADAR_LLM_FAST`/`RADAR_LLM_SMART` at
other model ids. Collection, scoring, dedup and the site never touch a model.
