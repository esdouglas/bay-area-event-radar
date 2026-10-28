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
    n.add_argument("--test", action="store_true", help="post one labelled test alert")

    sub.add_parser("site", help="build _site/ (inventory, dashboard, radar.ics)")
    w = sub.add_parser("watchdog", help="fail if collection is stale or broken; opens an issue")
    w.add_argument("--dry-run", action="store_true")
    b = sub.add_parser("benchmark", help="historical discoverability benchmark report")
    b.add_argument("--live", action="store_true", help="also probe live sources for present-day evidence")
    sub.add_parser("status", help="print inventory and source health summary")
    rs = sub.add_parser("research", help="research queue for routine/interactive review; apply findings")
    rs.add_argument("action", choices=["queue", "apply"])
    rs.add_argument("-n", type=int, default=40)
    g = sub.add_parser("gcal", help="Google Calendar sync (dedicated FYIs calendar only)")
    g.add_argument("action", choices=["test", "sync", "preview"])
    g.add_argument("--limit", type=int)
    g.add_argument("--dry-run", action="store_true")
    sub.add_parser("compact", help="merge duplicate records already in the inventory")
    ig = sub.add_parser("import-gpt", help="one-time reconciled import of main's GPT collector history")
    ig.add_argument("path")
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
        if a.test:
            notify.test_alert(dry_run=a.dry_run)
        else:
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
    elif a.cmd == "research":
        from . import research
        research.build_queue(a.n) if a.action == "queue" else research.apply()
    elif a.cmd == "gcal":
        from . import gcal
        if a.action == "test":
            sys.exit(0 if gcal.test() else 1)
        elif a.action == "preview":
            items = gcal.curated_items() + gcal.radar_items()
            print(f"{len(items)} items would sync")
            import json as _j
            print(_j.dumps(gcal.body_for(next(i for i in items if i["id"] == "cal-kentridge-2026-12")), indent=1))
        else:
            gcal.sync(limit=a.limit, dry_run=a.dry_run)
    elif a.cmd == "compact":
        from . import store
        ev = store.load_events(); n = store.compact(ev); store.save_events(ev); print(f"[compact] merged {n} duplicates; {len(ev)} remain")
    elif a.cmd == "import-gpt":
        from . import importer
        importer.run(a.path)
    elif a.cmd == "status":
        from . import status
        status.run()
    elif a.cmd == "sources":
        from .collect import load_sources
        for s in load_sources():
            print(f"{s['id']:36} {s['method']:14} {s.get('frequency', 'every'):7} {'' if s.get('enabled', True) else 'DISABLED ':9}{s.get('url') or ''}")


if __name__ == "__main__":
    main()
