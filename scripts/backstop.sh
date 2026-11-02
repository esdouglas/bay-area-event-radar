#!/usr/bin/env bash
# Backstop for GitHub's unreliable cron: GitHub may delay or silently drop scheduled runs
# (on 2026-11-02 the Monday digest and the daily watchdog never fired). The six-hourly collect
# run calls this to start them by hand when they are overdue. Needs GH_TOKEN with actions: write.
set -euo pipefail
ref="${1:-main}"
now=$(date -u +%s)

last_run() {  # epoch seconds of the newest run of workflow $1 (any event), or 0
  local t
  t=$(gh run list --workflow "$1" --branch "$ref" --limit 1 --json createdAt --jq '.[0].createdAt // empty')
  if [ -n "$t" ]; then date -u -d "$t" +%s; else echo 0; fi
}

# Digest: due from Monday 16:00 UTC (just after its 15:37 slot) through Sunday.
dow=$(date -u +%u)                                   # 1 = Monday
monday=$(date -u -d "$(date -u +%F) -$((dow - 1)) days" +%s)
due=$((monday + 16 * 3600))
if [ "$now" -ge "$due" ] && [ "$(last_run digest.yml)" -lt "$monday" ]; then
  echo "backstop: no digest run this week; dispatching digest.yml"
  gh workflow run digest.yml --ref "$ref"
fi

# Watchdog: daily at 16:11 UTC; dispatch if nothing in 26 hours.
if [ $((now - $(last_run watchdog.yml))) -gt $((26 * 3600)) ]; then
  echo "backstop: no watchdog run in 26 h; dispatching watchdog.yml"
  gh workflow run watchdog.yml --ref "$ref"
fi
echo "backstop: done"
