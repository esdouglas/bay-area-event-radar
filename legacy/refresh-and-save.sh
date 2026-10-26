#!/usr/bin/env bash
# The runner checkout is disposable. A fresh registry is read on every retry.
set -euo pipefail
git config user.name 'github-actions[bot]'
git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
for attempt in 1 2 3; do
  git fetch origin main
  git reset --hard origin/main
  python -m unittest discover -p 'test_*.py'
  python build.py --refresh
  git add events.json radar.ics index.html health.json
  if git diff --cached --quiet; then exit 0; fi
  git commit -m 'Refresh verified radar sources'
  if git push origin HEAD:main; then exit 0; fi
  echo "Registry changed during refresh; retrying from latest main ($attempt/3)."
done
echo '::error::Concurrent registry updates prevented publication after three safe retries.'
exit 1
