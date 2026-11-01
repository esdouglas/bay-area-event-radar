"""Bay Area Event Radar: high-recall event discovery.

Stages (each a CLI subcommand, each independently runnable):
  collect  -> pull raw events from every source in sources.yaml into the inventory
  score    -> rules-based taste scoring on every inventory event (cheap, no API)
  enrich   -> model-based research on plausible candidates only (needs an API key)
  notify   -> open/update GitHub Issues for exceptional finds and the weekly digest
  site     -> build the static inventory, coverage dashboard and radar.ics
  watchdog -> detect stale or failed collection and raise an issue
"""
__version__ = "2.0.0"
