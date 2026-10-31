# CLAUDE.md

## Branches
- `main` is production: GPT's v1 publisher plus GitHub Pages. Do not commit to it directly; it changes
  only by merging a reviewed pull request from `radar-v2`, with Erik's explicit OK.
- `radar-v2` is the replacement and the only development branch. GitHub is the source of truth.
- GitHub cron fires only on the default branch (`main`). Until cutover, `radar-v2` runs only on pushes,
  and the digest and watchdog schedules do not run.

## Ownership
- Claude owns development on `radar-v2`.
- ChatGPT is review-only. It does not commit.
- The daily Claude research task may commit **only** `data/research.json`.
- Actions bots commit `data/` (and `benchmark/REPORT.md`) via `scripts/commit_data.sh`.

## No paid APIs
Erik will not pay for API keys. Do not add, require or recommend `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`
or any other paid API or service. The model code paths (`html_llm` extraction, `enrich`) are permanently
off. Every collector must be deterministic: JSON-LD, ICS feeds, ticketing-platform pages/APIs, or plain
page structure (see `radar/collectors/theater.py` and `radar/collectors/venues.py`). Free services are
fine: GitHub Actions, GitHub Pages, Google Calendar via a free service account.

## Checks
- `python -m unittest discover -s tests -p 'test_*.py'`
- `python -m radar collect --only <id> --dry-run` for any collector change; report events per source.

## Cutover checklist
Before merge (PR `radar-v2` → `main`):
1. Tests pass; `main` merged into `radar-v2` (keep the intent of f89f5ac).
2. Alert test (`.github/notify-test-request`) and calendar test (`.github/gcal-test-request`) run, and
   Erik confirms the issue e-mail and the calendar event actually arrived. A green run is not proof.
3. PR explains for Erik: the site, `radar.ics` continuity (v1 UIDs preserved), expected alert volume
   including the one-time roundup issue on the first live run, digest and watchdog schedules starting.
4. Merge only with Erik's explicit OK.

After merge, confirm:
1. A scheduled collect run happened on `main`.
2. Pages deployed.
3. `radar.ics` still carries the v1 UIDs.
4. Monday's digest issue arrived.
5. The daily watchdog ran.
