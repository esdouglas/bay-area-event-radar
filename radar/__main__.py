"""CLI: python -m radar <stage> [options]"""
import argparse
import sys


def main(argv=None):
    p = argparse.ArgumentParser(prog="radar", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("collect", help="pull events from every due source into data/events.json")
    c.add_argument("--only", nargs="*", help="source ids to run (forces them even if not due)")
    c.add_argument("--force", action="store_true", help="ignore per-source frequency")
    c.add_argument("--workers", type=int, default=6)
    c.add_argument("--dry-run", action="store_true", help="collect but do not write data files")

    sub.add_parser("score", help="rules-based taste scoring for every upcoming event")

    e = sub.add_parser("enrich", help="model-based research on plausible candidates (needs an API key)")
    e.add_argument("--limit", type=int, default=60)
    e.add_argument("--min-score", type=float, default=None)

    n = sub.add_parser("notify", help="open GitHub issues for exceptional finds / weekly digest")
    n.add_argument("--digest", action="store_true", help="also post the weekly digest")
    n.add_argument("--dry-run", action="store_true")

    sub.add_parser("site", help="build _site/ (inventory, dashboard, radar.ics)")
    w = sub.add_parser("watchdog", help="fail if collection is stale or broken; opens an issue")
    w.add_argument("--dry-run", action="store_true")
    b = sub.add_parser("benchmark", help="historical discoverability benchmark report")
    b.add_argument("--live", action="store_true", help="also probe live sources for present-day evidence")
    sub.add_parser("status", help="print inventory and source health summary")
    sub.add_parser("sources", help="list registry sources")

    a = p.parse_args(argv)
    if a.cmd == "collect":
        from . import collect
        collect.run(only=a.only, force=a.force, workers=a.workers, dry_run=a.dry_run)
    elif a.cmd == "score":
        from . import rank
        rank.run()
    elif a.cmd == "enrich":
        from . import enrich
        enrich.run(limit=a.limit, min_score=a.min_score)
    elif a.cmd == "notify":
        from . import notify
        notify.run(digest_flag=a.digest, dry_run=a.dry_run)
    elif a.cmd == "site":
        from . import site
        site.run()
    elif a.cmd == "watchdog":
        from . import watchdog
        sys.exit(watchdog.run(dry_run=a.dry_run))
    elif a.cmd == "benchmark":
        from . import benchmark
        benchmark.run(live=a.live)
    elif a.cmd == "status":
        from . import status
        status.run()
    elif a.cmd == "sources":
        from .collect import load_sources
        for s in load_sources():
            print(f"{s['id']:36} {s['method']:14} {s.get('frequency', 'every'):7} {'' if s.get('enabled', True) else 'DISABLED ':9}{s.get('url') or ''}")


if __name__ == "__main__":
    main()
