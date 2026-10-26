# Bay Area Event Radar

High-recall discovery of live music, theater and performance across the Bay Area, run entirely by
GitHub Actions. The goal is to learn about the next Peter Stampfel show in a 100-person room weeks
before it happens, not the morning after. See [POSTMORTEM.md](POSTMORTEM.md) for why v1 missed it.

**Outputs**

- Inventory + search: https://esdouglas.github.io/bay-area-event-radar/ (every plausible event, filter by tier/category/date)
- Coverage dashboard: https://esdouglas.github.io/bay-area-event-radar/dashboard.html (every source, its health, what it contributed, run history, model spend)
- Calendar feed: https://esdouglas.github.io/bay-area-event-radar/radar.ics (strong + exceptional events; v1 UIDs preserved)
- Immediate alerts: GitHub issues labelled `radar-alert` (assigned to the owner, so GitHub e-mails them)
- Weekly digest: GitHub issues labelled `radar-digest`, Mondays ~8 AM Pacific
- Operational alarms: issues labelled `radar-ops` from the daily watchdog

## How it works

```
sources.yaml ──collect──▶ data/events.json ──score──▶ tiers ──enrich (model)──▶ notify ──▶ issues
   (registry)   75 sources    inventory, dedup,      rules,      fit, background,   immediate / digest
                              first/last seen        explainable  scarcity           
                                       └──────────────── site ───────────────▶ _site/ (Pages)
                                       └──────────────── watchdog ───────────▶ radar-ops issue
```

Stages are independent CLI commands (`python -m radar <stage>`), all model-independent except
`enrich`, which talks to whichever provider the environment names.

| Stage | What it does | Needs |
|---|---|---|
| `collect` | Fetches every due source in `sources.yaml` with the right collector (iCal/Google Calendar, JSON-LD pages with link-following, The Events Calendar REST, Squarespace JSON, Localist, Dice, Songkick, Eventbrite API, allevents, HTML→text→model extraction), normalises, deduplicates across sources, records first/last seen and per-source history, logs every attempt to `data/runs/`. | nothing |
| `score` | Additive, explainable taste score (seed artists, keyword neighbourhoods, venue priors, source priors, multi-source confirmation); tiers exceptional / strong / inventory / noise. Without a model, "exceptional" requires a named seed artist or a psych-folk signal. | `taste.yaml` |
| `enrich` | Two-pass model research on candidates (taste venues, taste calendars, score ≥ 35): fast pass on all, deeper pass with Wikipedia grounding on the promising ones. Cached per event fingerprint and per artist; every call's cost is logged. | `ANTHROPIC_API_KEY` (or `OPENAI_API_KEY`) |
| `notify` | Opens an issue per new exceptional event (comments on changes, never repeats), weekly digest with new-since-last, next-14-days, and still-upcoming sections. Live posting only from `main` (or `RADAR_NOTIFY_LIVE=1`). | `GITHUB_TOKEN` (automatic) |
| `site` | Static inventory, dashboard, `radar.ics`, `events.json`. | nothing |
| `watchdog` | Fails (and opens/updates a `radar-ops` issue) if the last collection is >14 h old, key sources return zero, sources fail 3+ runs, or nothing new was found in a week. | `GITHUB_TOKEN` |
| `benchmark` | Historical discoverability benchmark (`benchmark/events.yaml`, report in `benchmark/REPORT.md`); `--live` adds Wayback Machine checks. | network |

## Schedules (`.github/workflows/`)

- `collect.yml`: every 6 h and on code pushes: collect → score → enrich → notify → benchmark → site → commit `data/` → deploy Pages (deploy only from `main`).
- `digest.yml`: Mondays 15:37 UTC.
- `watchdog.yml`: daily 16:11 UTC.
- `benchmark.yml`: manual, with Wayback checks.
- `probe.yml`: manual reachability probe of candidate sources from a GitHub runner.

## Adding a source

Add an entry to `sources.yaml`. For a page with schema.org JSON-LD use `method: jsonld` (add `follow:` to
read detail pages); for The Events Calendar sites `tribe`; for Google Calendar / any `.ics` use `ics`;
for anything else `html` (text extraction by the model, cached by content hash, so unchanged pages cost
nothing; add `heuristic_ok: true` only for plain date-list pages that the no-model fallback can read). Run `python -m radar collect --only <id> --dry-run` to see what it yields. Blocked or broken
sources stay in the file with `enabled: false` and a note, so the gap remains visible on the dashboard.

## Secrets (repository → Settings → Secrets and variables → Actions)

- `ANTHROPIC_API_KEY` (recommended): enrichment and HTML extraction. Model defaults: `claude-haiku-5-5` fast, `claude-sonnet-5-5` deep; override with `RADAR_LLM_FAST` / `RADAR_LLM_SMART`. `OPENAI_API_KEY` works the same way.
- `EVENTBRITE_TOKEN` (optional): enables `eventbrite-east-bay` (official API; Eventbrite's web pages block GitHub runners).

No secret is ever written to the repository; `data/costs.jsonl` records token counts and dollars only.

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
