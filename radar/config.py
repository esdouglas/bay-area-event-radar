"""Paths and constants. Everything persisted lives under data/ so it survives between runs via git."""
import datetime as dt
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RUNS = DATA / "runs"
CACHE = DATA / "cache"
SITE = ROOT / "_site"

EVENTS_FILE = DATA / "events.json"
ARTISTS_FILE = DATA / "artists.json"
SOURCE_HEALTH_FILE = DATA / "source_health.json"
RUN_SUMMARY_FILE = DATA / "run_summary.json"
COSTS_FILE = DATA / "costs.jsonl"
ALERTS_FILE = DATA / "alerts.json"
LEGACY_EVENTS_FILE = ROOT / "events.json"  # the v1 hand-curated registry; kept for UID continuity

SOURCES_FILE = ROOT / "sources.yaml"
TASTE_FILE = ROOT / "taste.yaml"
BENCHMARK_FILE = ROOT / "benchmark" / "events.yaml"

LOCAL_TZ = "America/Los_Angeles"
HORIZON_DAYS = int(os.environ.get("RADAR_HORIZON_DAYS", "190"))  # ~6 months forward
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/129.0 Safari/537.36 BayAreaEventRadar/2.0 (+https://github.com/esdouglas/bay-area-event-radar)"
)
FETCH_TIMEOUT = 40

# Approximate centre of the coverage area (Rockridge, Oakland) and the radius we keep events within.
HOME_LAT, HOME_LON = 37.8445, -122.2520
MAX_DISTANCE_MI = float(os.environ.get("RADAR_MAX_DISTANCE_MI", "90"))

STAMPFEL_RULE = "A foundational musician in a 100-person room may matter more than an arena headliner."


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def now_iso() -> str:
    return now_utc().replace(microsecond=0).isoformat()


def ensure_dirs():
    for p in (DATA, RUNS, CACHE):
        p.mkdir(parents=True, exist_ok=True)
