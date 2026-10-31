# Bay Area Event Radar

High-recall discovery of live music, theater and performance across the Bay Area, run entirely by
GitHub Actions. The goal is to learn about the next Peter Stampfel show in a 100-person room weeks
before it happens, not the morning after. See [POSTMORTEM.md](POSTMORTEM.md) for why v1 missed it.

**Outputs**

- Inventory + search: https://esdouglas.github.io/bay-area-event-radar/ (every plausible event, filter by tier/category/date)
- Coverage dashboard: https://esdouglas.github.io/bay-area-event-radar/dashboard.html (every source, its health, what it contributed, run history)
- Calendar feed: https://esdouglas.github.io/bay-area-event-radar/radar.ics (strong + exceptional events; v1 UIDs preserved)
- Immediate alerts: GitHub issues labelled `radar-alert` (assigned to the owner, so GitHub e-mails them)
- Weekly digest: GitHub issues labelled `radar-digest`, Mondays ~8 AM Pacific
- Operational alarms: issues labelled `radar-ops` from the daily watchdog

## How it works

```
sources.yaml ──collect──▶ data/events.json ──score──▶ tiers ──research.json──▶ notify ──▶ issues
   (registry)   75 sources    inventory, dedup,      rules,      daily research    immediate / digest
                              first/last seen        explainable  task findings     
                                       └──────────────── site ───────────────▶ _site/ (Pages)
                                       └──────────────── watchdog ───────────▶ radar-ops issue
```

Stages are independent CLI commands (`python -m radar <stage>`). Nothing uses a paid API: every
collector is deterministic, and the model code paths (`enrich`, `html_llm` extraction) are permanently
off (see [CLAUDE.md](CLAUDE.md)).

| Stage | What it does | Needs |
|---|---|---|
| `collect` | Fetches every due source in `sources.yaml` with the right collector (iCal/Google Calendar, JSON-LD pages with link-following, The Events Calendar REST, Squarespace JSON, Localist, Dice, Songkick, allevents, platform-specific venue parsers, theater season pages), normalises, deduplicates across sources, records first/last seen and per-source history, logs every attempt to `data/runs/`. | nothing |
| `score` | Additive, explainable taste score (seed artists, keyword neighbourhoods, venue priors, source priors, multi-source confirmation); tiers exceptional / strong / inventory / noise. "Exceptional" requires a named seed artist or a psych-folk signal. | `taste.yaml` |
| `research apply` | Folds findings from the daily research task (`data/research.json`) into scores. | nothing |
| `notify` | Opens an issue per new exceptional event (comments on changes, never repeats), weekly digest with new-since-last, next-14-days, and still-upcoming sections. Live posting only from `main` (or `RADAR_NOTIFY_LIVE=1`). | `GITHUB_TOKEN` (automatic) |
| `site` | Static inventory, dashboard, `radar.ics`, `events.json`. | nothing |
| `watchdog` | Fails (and opens/updates a `radar-ops` issue) if the last collection is >14 h old, key sources return zero, sources fail 3+ runs, or nothing new was found in a week. | `GITHUB_TOKEN` |
| `benchmark` | Historical discoverability benchmark (`benchmark/events.yaml`, report in `benchmark/REPORT.md`); `--live` adds Wayback Machine checks. | network |

## Schedules (`.github/workflows/`)

GitHub fires cron schedules only on the default branch (`main`); on `radar-v2` the pipeline runs on pushes.

- `collect.yml`: every 6 h and on code pushes: collect → score → enrich → notify → benchmark → site → commit `data/` → deploy Pages (deploy only from `main`).
- `digest.yml`: Mondays 15:37 UTC.
- `watchdog.yml`: daily 16:11 UTC.
- `benchmark.yml`: manual, with Wayback checks.
- `probe.yml`: manual reachability probe of candidate sources from a GitHub runner.

## Adding a source

Add an entry to `sources.yaml`. For a page with schema.org JSON-LD use `method: jsonld` (add `follow:` to
read detail pages); for The Events Calendar sites `tribe`; for Google Calendar / any `.ics` use `ics`; for
theater season pages `theater_run`; for venue sites on a known ticketing/calendar platform the matching
`venue_*` parser in `radar/collectors/venues.py`; for plain date-list pages `html` with
`heuristic_ok: true` (date-line heuristic, no model). Run `python -m radar collect --only <id> --dry-run` to see what it yields. Blocked or broken
sources stay in the file with `enabled: false` and a note, so the gap remains visible on the dashboard.

## Secrets (repository → Settings → Secrets and variables → Actions)

- `GOOGLE_SERVICE_ACCOUNT_JSON` (optional, free): key of a Google Cloud service account that the FYIs
  calendar is shared with; enables the calendar sync on `main`.
- `EVENTBRITE_TOKEN` (optional, free personal token): enables `eventbrite-east-bay` (official API; Eventbrite's web pages block GitHub runners).

No paid API key is used or wanted.

No secret is ever written to the repository.

## Local use

```
pip install -r requirements.txt
python -m radar status                 # inventory + source health
python -m radar collect --only little-hill-lounge --dry-run
python -m radar score && python -m radar site && open _site/index.html
python -m unittest discover -s tests
```

## Legacy

`events.json` and `pending-leads.json` are the v1 hand-curated records; `legacy/` holds the v1 builder.
The v1 calendar UIDs are emitted unchanged in `radar.ics` so existing subscriptions keep working.
