#!/usr/bin/env bash
# Commit data/ and benchmark/ changes back to the branch the workflow ran on, retrying on concurrent
# updates without ever force-pushing. The checkout is disposable; the repository is the database.
set -euo pipefail
BRANCH="${1:-${GITHUB_REF_NAME:-main}}"
MSG="${2:-Radar: scheduled collection}"
git config user.name 'github-actions[bot]'
git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
for attempt in 1 2 3 4; do
  git add -A data benchmark/REPORT.md 2>/dev/null || git add -A data
  if git diff --cached --quiet; then echo "nothing to commit"; exit 0; fi
  git commit -q -m "$MSG" -m "Co-Authored-By: github-actions[bot] <41898282+github-actions[bot]@users.noreply.github.com>"
  if git push origin "HEAD:$BRANCH"; then exit 0; fi
  echo "push rejected (concurrent update); rebasing and retrying ($attempt/4)"
  git fetch origin "$BRANCH"
  git rebase -X theirs "origin/$BRANCH" || { git rebase --abort; git reset --soft "origin/$BRANCH"; }
done
echo '::error::could not push data after 4 attempts'
exit 1
