# Bay Area Event Radar

Subscription URL (valid only after successful Pages deployment):
https://esdouglas.github.io/bay-area-event-radar/radar.ics

Subscribe once via From URL in Google Calendar or New Calendar Subscription in Apple Calendar. Do not repeatedly import. Hide the previous Erik event FYIs calendar to avoid overlapping legacy entries; it is unchanged.

`events.json` is the persistent verified event registry. `build.py --refresh` reads the exact organizer JSON-LD source, validates dates/status, refreshes known events and builds RFC 5545 output. UTC times avoid DST ambiguity. No external Python dependencies. Workflow runs on push, manual dispatch, and every six hours; publishes with GitHub Pages Actions. Configure repository Settings → Pages → Source: GitHub Actions.

Immutable IDs become UIDs. Keep the same ID on date/title/status/interest changes. Increment sequence and modified_at on editorial changes. Never reuse IDs or delete cancelled events: retain tombstones with status CANCELLED. Source disappearance or fetch failure fails the build and preserves the last deployed feed; it does not imply cancellation. Explicit organizer EventCancelled is supported. All interest levels remain TRANSPARENT, with no VALARM. Ticket checkout availability is never inferred from a listing.

Only one historical discovery has been independently reverified and seeded. Other old recommendations are unverified leads, not calendar facts. Private attendance details and date placeholders have not been copied into this public repository. FYI is the default, not an inference about attendance.

## Automation boundary
The workflow refreshes known structured sources and publishes without an external credential using GITHUB_TOKEN. It does not discover additional events or execute the previous ChatGPT radar task. No claim that scheduled discovery can write through the GitHub connector is warranted until a real unattended write is observed. The previous task's full watch instructions were unavailable in the retrieved conversation. No API key or hidden automation dependency is installed.

GitHub can delay scheduled runs and disable schedules after inactivity on public repositories. Inspect Actions for failures. A successful manually dispatched run demonstrates the worker path, not that the cron trigger has fired. Record a schedule-triggered success separately.
