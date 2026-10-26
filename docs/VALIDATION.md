# Validation, not a success claim

## Historical test run, October 25, 2026

Run `python benchmark.py`. Full cases and provenance: tests/historical_cases.json, tests/fixtures/manifest.json and data/benchmark.json.

| Measure | Result | Interpretation |
|---|---:|---|
| Named misses parsed | 3 / 3 | Stampfel via KALX; Mountain Grass Unit via Songkick; Furtado via Bandsintown |
| Additional relevant historical cases parsed | 20 / 20 | Provisional taste labels, mostly one KALX week |
| Retrospective extraction recall | 23 / 23 (100%) | Seeded convenience sample; **not validated discovery recall** |
| Low-alert-fit controls retained | 8 / 8 | Correct broad collection; these are not automatically recommendations |
| Proven historical early discoveries | 0 / 23 | All fixture observations occurred after the shows |
| End-to-end alert recall | Unknown | No historical collection + research + delivery replay exists |
| Alert false-positive rate / precision | Unknown | No independent labeled alert sample yet; no fabricated zero-FP claim |

All 31 tests are historical event cases, separate from code unit tests. The 20 additional positive cases include Geese/Bill Orcutt, Julian Lage, Laura Veirs/Karl Blau, Devil Makes Three/Two Runner, Allah-Las, Bedouine, Todd Rundgren, Liberty Ellman, Hannah Mayree, Maria BC, Country Risqué, Los Vega, Julia Jacklin, John Gorka, the Black Banjo Reclamation Project bill, Christian Sands, Steve Reich at 90, Tyondai Braxton, Lavay Smith and Soji Sai. Ground-truth dates/venues were transcribed manually from KALX. These are candidate-fit labels, not claims that Erik would definitely attend all 20.

The fixture transformation preserves factual source text and date headings or JSON-LD fields, without unrelated site material/biographies. Original response hashes are recorded. These are October 25 captures, not historical snapshots. Targeting a known expired event URL does not prove autonomous discovery.

## What lead time can actually be supported?

* **Stampfel, Oct 24:** KALX currently says its Oct 19–25 page was posted Oct 14: potential **10-day** window. Exact listing presence on that date is unproven without an earlier capture/revision. Eventbrite's structured description identifies Holy Modal Rounders/Fugs and claims a first Bay Area show in 26 years; treat rarity as organizer claim. Sources: https://kalx.berkeley.edu/event/events-october-19-25-2026/ and https://www.eventbrite.com/e/peter-stampfel-the-atomic-meta-pagans-will-sprott-tickets-2002646892766 .
* **Mountain Grass Unit, Oct 5:** a dated June 15 tour announcement lists Cafe du Nord and June 18 general on-sale: **112 days** from publication and **109 days** from on-sale. This establishes a public discovery opportunity, not that the new collector would have harvested it. Source: https://www.gratefulweb.com/articles/mountain-grass-unit-announces-expansive-appalachian-smoke-tour/ . Artist/label qualification: https://www.dualtone.com/mountain-grass-unit and https://www.mountaingrassunit.com/about .
* **Tony Furtado, Oct 16:** historic listing is recoverable but announcement and sellout times are unresolved. Reused WordPress timestamps and search-engine crawl summaries are insufficient. No pre-sellout lead-time claim.
* **Live forward test:** collection on Oct 25 retained Showman & Coole (Lonesome Ace duo), Otter Opry Feb 12, 2027, **110 days** ahead. Primary presenter biography specifically describes fiddle/clawhammer, old-time/bluegrass, Dock Boggs and John Hartford repertoire. Primary date checked against the explicitly year-labeled Bluegrass Signal calendar. Presenter time wording conflicts with dinner wording; ticket checkout unverified. This demonstrates useful candidate lead time today, not historical recall or guaranteed delivery. https://otteropry.org/ .
* Other current collected examples: Jim Lauderdale Nov 15 (**21 days**), Crooked Jades Dec 6 (**42 days**), Kendl Winter Dec 12 (**48 days**). The last two were already known to the prior radar and must not be presented as novel discoveries.

## Unresolved coverage gaps

Read **current data/coverage.json**, not a frozen source count in this document. Each source reports actual page outcomes, extracted dates and pending links; none is certified exhaustive for six months. Failures and zero-parser-result pages remain extraction tasks. Known problem classes:

* Little Hill's dynamic calendar and blocked DoTheBay route; KALX and geographic Eventbrite provide independent paths, but KALX is principally short horizon.
* Small-club social-only/poster announcements and private mailing-list house concerts. No unauthorized account joins/subscriptions are introduced.
* Humanitix/Ticket Tailor/Eventbrite organizer/calendar coverage is partial; ticket recommendation carousels can include unrelated/out-of-area events. Store them, qualify geography and identity during research, and do not auto-alert by schema alone.
* Dynamic theater/jazz calendars and page-specific formats at Freight, SFJAZZ, Cal Performances, ACT, Berkeley Rep and others need extraction-worker recovery. A fetched homepage is not season coverage.
* Artist pages using embedded Bandsintown/Songkick widgets, pagination, long-future shows beyond index pages, and rotating bounded link backlog.
* Duplicate aliases remain possible across changed bills, titles and room names. Conservative canonicalization handles city suffixes and ticket-title decorations; ambiguous identities remain separate rather than silently merged.
* Scheduled ChatGPT worker write/notification behavior must be checked in an actual unattended run. The collector cannot measure whether a push notification was read.

## Prospective promotion gates

Retain shadow status for at least 14 monitored days. For a held-out mixed sample across at least five source families, manually label relevance and match source events to inventory. Report relevant-event collection recall, researched-event fraction, exceptional-event alert recall, alert precision and negative-control FPR separately. Use explicit denominators and unknown labels; don't treat unresearched events as true negatives. Track actual first_seen-to-event and first_alert-to-event distributions and sellout lead time only where checkout was observed.

Require >=90% relevant-event recall on the independent sample, all three miss mechanisms addressed by observed enumeration (not just detail parsing), rare-show discovery >=7 days where source publication permits, desirable normal lead >=14 days, no silent stale/failed sources and a recorded real alert output. Threshold failure means fix and continue shadow operation; it does not justify disabling the old radar.
