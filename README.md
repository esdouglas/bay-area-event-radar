# Bay Area Event Radar

Subscribe once: https://esdouglas.github.io/bay-area-event-radar/radar.ics

Google Calendar: Other calendars → + → From URL. Apple Calendar: File → New Calendar Subscription. Do not repeatedly import. Existing personal calendars are untouched; hide overlapping legacy calendars if necessary.

The registry contains verified public performance choices. Default FYI does not mean attendance. Interested/Going, stable UIDs, sequence revisions, cancellation tombstones, free time and no alarms are preserved. Only primary-source end times are emitted. Listings and ticket checkout availability are different: inventory is explicitly unverified.

## Maintenance
- `events.json`: durable event registry and verification metadata.
- `build.py`: standard-library calendar/site builder and structured-source refresher.
- `refresh-and-save.sh`: retries publication preparation from current main after concurrent writes, without force pushes.
- `.github/workflows/publish.yml`: on push/manual dispatch and every six hours, test, refresh known structured sources, persist current state and deploy Pages. Individual unavailable sources retain last verified records and report in `health.json`.
- `WATCHLIST.md`: daily discovery/editorial verification instructions and taste criteria recovered from historical radar results.
- `pending-leads.json`: unverified historical leads, not calendar facts.

A daily 8 AM Pacific discovery heartbeat has been saved in the current desktop chat. It can search primary sources and attempt verified registry updates via the connected GitHub plugin. It requires the computer and app running. Its first scheduled connector-write and live-publication test is pending; do not claim unattended discovery publishing has been proven. The GitHub-hosted build/refresh/save/deploy path has already succeeded. Six-hour schedules can be delayed or disabled by GitHub after public-repository inactivity; inspect Actions rather than assuming a timer fired.

No private calendar tickets, seats, guests, travel plans or uncertain placeholders are copied here. Full original requirements were not recoverable from content-reference-only conversation messages. Historical recommendation details were rechecked rather than treated as current evidence.
