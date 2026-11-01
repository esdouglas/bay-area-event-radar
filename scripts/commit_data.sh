#!/usr/bin/env bash
# Commit data/ and benchmark/REPORT.md back to the branch the workflow ran on, retrying on concurrent
# updates without ever force-pushing. The checkout is disposable; the repository is the database.
set -euo pipefail
BRANCH="${1:-${GITHUB_REF_NAME:-main}}"
MSG="${2:-Radar: scheduled collection}"
git config user.name 'github-actions[bot]'
git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
git add -A data
git add -A benchmark/REPORT.md 2>/dev/null || true
if git diff --cached --quiet; then echo "nothing to commit"; exit 0; fi
git commit -q -m "$MSG"
for attempt in 1 2 3 4 5; do
  if git push origin "HEAD:$BRANCH"; then echo "pushed on attempt $attempt"; exit 0; fi
  echo "push rejected (concurrent update); rebasing and retrying ($attempt/5)"
  git fetch origin "$BRANCH"
  # During a rebase, -X theirs prefers the commit being replayed, i.e. this run's fresh data.
  if ! git rebase -X theirs "origin/$BRANCH"; then
    git rebase --abort || true
    git reset --soft "origin/$BRANCH"
    git commit -q -m "$MSG" || true
  fi
  sleep $((attempt * 5))
done
echo '::error::could not push data after 5 attempts'
exit 1
