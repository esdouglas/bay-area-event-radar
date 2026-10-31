"""Development probe, run on a GitHub runner by .github/workflows/dev-snapshot.yml.

Reads .github/dev-snapshot-request: lines `source <id> [<id> ...]` run `collect --only ... --dry-run`;
lines `url <URL>` just fetch the URL. With RADAR_FETCH_RECORD set, every response is saved, and the
workflow pushes the saved pages to a throwaway tag so they can be read where the hosts are not
reachable. Nothing here runs in production."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from radar import collect, fetch  # noqa: E402

ids, urls = [], []
for line in pathlib.Path(sys.argv[1]).read_text().splitlines():
    parts = line.split()
    if len(parts) >= 2 and parts[0] == "source":
        ids += parts[1:]
    elif len(parts) == 2 and parts[0] == "url":
        urls.append(parts[1])
for u in urls:
    try:
        r = fetch.get(u, retries=0)
        print(f"[url] {r.status_code} {len(r.content):8} {u}")
    except fetch.FetchError as e:
        print(f"[url] ERR {e.kind}: {e} {u}")
if ids:
    collect.run(only=ids, dry_run=True)
