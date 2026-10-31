"""Development probe, run on a GitHub runner by .github/workflows/dev-snapshot.yml.

Reads .github/dev-snapshot-request (YAML):
  urls:    [URL, ...]                       fetched and recorded
  sources: {<id>: {<overrides>} | null}     collected (dry run) with the overrides merged over sources.yaml
With RADAR_FETCH_RECORD set, every response is saved and the workflow pushes the pages to a throwaway
tag, so parsers can be developed against real pages where the hosts are not reachable. Not production."""
import pathlib
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from radar import collect, fetch  # noqa: E402

req = yaml.safe_load(pathlib.Path(sys.argv[1]).read_text()) or {}
for u in req.get("urls") or []:
    try:
        r = fetch.get(u, retries=0)
        print(f"[url] {r.status_code} {len(r.content):8} {u}")
    except fetch.FetchError as e:
        print(f"[url] ERR {e.kind}: {e} {u}")
registry = {s["id"]: s for s in collect.load_sources()}
for sid, over in (req.get("sources") or {}).items():
    s = dict(registry.get(sid, {"id": sid}), **(over or {}))
    st = collect.run_source(s)
    raws = st.pop("_raws", [])
    print(f"[source] {sid:28} {s['method']:12} {st['status']:8} raw={len(raws):4} {st.get('error') or ''} warnings={st.get('warnings', [])[:3]}")
    for r in raws[:3]:
        print(f"           {r.get('start')}  {str(r.get('title'))[:70]}")
