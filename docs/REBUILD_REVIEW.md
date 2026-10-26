# Discovery rebuild: postmortem and design review

Reviewed 2026-10-25 before implementation. Baseline main 19cebd0.

## What failed

The repository has 36 editorially selected events, a calendar renderer and an exact-name JSON-LD refresher. No source registry, calendar enumeration, unfamiliar-act research worker, collection ledger, alert delivery ledger or historical recall benchmark exists. Eight passing tests verify calendar mechanics, not discovery. Scheduled Actions have succeeded, but only refresh known records. health.json mixes editorial-review with actual fetch results and does not measure source coverage. Most sources require a human/chat to discover each new show.

The enabled ChatGPT daily radar contains an extensive, repeatedly expanded prompt. Its own records explicitly disclaim a durable change log. Prompt instructions to search broadly cannot establish which sources were enumerated, whether all events were collected or whether unknown names were researched. The task is enabled and is left unchanged.

Stampfel: KALX's Oct 19–25 calendar explicitly lists Peter Stampfel of the Holy Modal Rounders at Little Hill Lounge on Oct 24. The page currently says posted Oct 14 (10 days before); this is a retrospective publisher timestamp, NOT a dated archived copy proving that exact listing was present Oct 14. Eventbrite also has a dedicated listing. Little Hill's current calendar is client-rendered: merely fetching its HTML produces a loading shell. An HTTP 200 must not mean coverage. The collector must use redundant KALX/ticket paths and flag the shell.

Mountain Grass Unit: the Cafe du Nord show on Oct 5 has venue/ticket/artist/aggregator paths. Missing an unfamiliar bluegrass act is an enrichment failure as well as a collection failure. Name recognition must never gate inventory storage.

Tony Furtado: Fifth Street Farms' mutable WordPress posts and Ticket Tailor organizer pages require enumeration, not refreshing already-selected ticket URLs. A page's old publication date is not announcement evidence: the current homepage labels December 2026 content with a 2024 date. Discovery before sellout remains unproven without a dated observation of both listing and ticket availability.

## Smallest credible architecture

Keep the existing calendar renderer and curated events.json. Add one standard-library Python collector with a JSON source registry. Store broad inventory, append-only observations and page-fetch ledger in Git; preserve compressed content-addressed page snapshots as Actions artifacts (90 days). Enumerate KALX weekly pages, parse Bluegrass Signal's multi-date blocks, JSON-LD, ICS and feed sources, follow bounded event/ticket links. Unknown/unparseable pages remain visible research/extraction work, never successful zero-event coverage.

Use a separate cached research/ranking pass. Research primary artist/label/presenter biographies and credible music history sources for unfamiliar performers and retain evidence URLs and findings. Use a separate scheduled ChatGPT worker through the existing connected GitHub app, or an explicitly configured compatible model API. Current GitHub documentation states GitHub Models retired July 30, 2026, so it is not a viable dependency (https://docs.github.com/en/github-models). No keyword filter removes inventory. All pending research and model errors are counted. No invented reputation or inferred ticket availability. A broad inventory page is separate from selected calendar entries.

Persist exceptional-event alert outbox independently of inventory; scheduled chat delivery reads it and reports coverage gaps. An alert generated is not an alert delivered. Acknowledgment requires a separate explicit operation. Existing radar remains on during shadow validation. No private calendar writes are introduced.

One existing six-hour Actions schedule owns refresh, collect, enrich, persist and Pages publishing, with concurrency serialization. Source requests have timeouts, bounded fanout and per-source errors. JSON is adequate at this scale and reviewable without a database/server. Do not add a frontend framework, hosted database or vector search.

## Review risks and acceptance gates

* HTTP success is not extraction success. Report configured/attempted/fetched/extracted sources, per-source dates, pending links, truncation and errors.
* Calendar date-only leads remain outside the subscription feed until primary dates/times are verified.
* No absence-based cancellation. No retrospective first_seen fabrication. Preserve raw evidence hashes, original source dates and actual observation time separately.
* Historical retrospective recovery is not prospective recall. Benchmark the three named misses plus at least 20 additional events, include negatives and unknowns, and report source-family concentration and selection bias.
* For lead-time validation, require dated source capture before event (target >=14 days; rare-show floor >=7 days). Publisher timestamps are weaker evidence; undated current pages do not pass.
* Replacement gate: all three misses recoverable by actual parsers; >=90% held-out relevant-event recovery across multiple source families; measured false-positive rate on a labeled mixed sample; >=14 consecutive monitored days; no unreported failed/stale sources; real successful alert delivery. Until then status is NOT VALIDATED.
* Six-hour schedules are best effort; report staleness and GitHub inactivity disabling. No promise of exhaustive internet coverage.
