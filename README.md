# Bay Area Event Radar

Existing subscription: https://esdouglas.github.io/bay-area-event-radar/radar.ics

**Replacement status: SHADOW / NOT VALIDATED.** The existing ChatGPT daily radar remains enabled. A workflow success is not evidence of discovery recall or early alerting.

## Two outputs

* Curated calendar: events.json → build.py → radar.ics / index.html. Existing immutable IDs, Going/Interested choices, cancellation tombstones, free time and no alarms are preserved. A listing does not verify ticket inventory.
* Broad discovery: sources.json → radar.py → data/inventory.json / inventory.html. Every extracted dated candidate is retained regardless of name recognition. Unknown names enter a separate research queue. Nothing is automatically copied into the curated calendar.

[Live broad inventory and coverage](https://esdouglas.github.io/bay-area-event-radar/inventory.html)

## Small durable pipeline

The existing six-hour GitHub Actions job collects and refreshes, runs tests, commits state and deploys Pages. Research-only pushes render current state without scanning venues again; their research_updated_at never replaces the actual collection timestamp. The collector uses standard-library Python with six concurrent source workers, request limits/timeouts, bounded rotating link enumeration, dedicated KALX/Bluegrass Signal/Hicks/Cafe du Nord/Ticket Tailor parsers and recursive JSON-LD. Other formats/dynamic pages go to an explicit extraction queue rather than being treated as successful coverage.

A separate scheduled ChatGPT research worker uses the connected GitHub app and primary public sources to research unfamiliar acts, rank taste fit, recover unparsed sources and report exceptional discoveries. See [its exact contract](docs/AI_WORKER.md). Its first unattended execution must still be verified. No paid API key is required for this path. An optional compatible API backend is explicitly configured, never silently assumed.

## Auditable state

| File | Meaning |
|---|---|
| data/inventory.json | Broad inventory, actual first/last seen and per-source observations |
| data/runs.jsonl | Append-only collection history, including failures |
| data/coverage.json | Latest attempted/fetched/extracted counts, per-source dates, truncation and errors |
| data/frontiers.json | Last-attempted URLs; rotate bounded detail-page coverage |
| data/research-queue.json | Future events awaiting evidence-backed research |
| data/extraction-queue.json | Fetched/unparsed, dynamic, failed and unresolved pages |
| data/research.json | AI findings, evidence, tiers and uncertainty |
| data/outbox.json | Pending/reported alerts; a prepared alert is not delivered |
| data/benchmark.json | Reproducible retrospective recovery and explicit validation limits |
| health.json | Legacy known-event refresh status, **not source coverage** |

Exact compressed page captures are content-addressed under .capture/ and uploaded as Actions artifacts for 90 days. Hashes and observation records persist in Git. Raw captures are not permanent: archive artifacts before expiry if needed for longer historical replay. No date of first public announcement or pre-sellout availability is inferred from a mutable page timestamp.

## Review and validation

Read [postmortem and architecture review](docs/REBUILD_REVIEW.md), [historical evaluation](docs/VALIDATION.md) and WATCHLIST.md before changing collection or ranking. The benchmark contains the three user-confirmed misses, 20 additional provisional relevant historical events and eight low-alert-fit controls. It measures **retrospective extraction**, not autonomous historical discovery or proven alert precision.

```
python -m unittest discover
python benchmark.py
python radar.py --enrich
python build.py
```

An HTTP 200 with no parsed events is not verified calendar coverage. Pending link counts, missing months, stale sources, research backlog and alert failures must remain visible. Source coverage is never exhaustive Bay Area event recall. Schedules can be delayed or disabled by GitHub; inspect Actions and latest completed_at. Keep the old radar until prospective validation passes.
