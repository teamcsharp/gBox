#!/bin/bash
# What is actually open in the inbox? One summary: counts by state, and the oldest open tickets with their titles.
T=$(cat /home/ehm_eckx/gBox/system/gbox-data/api_token)
curl -s -m 60 "http://127.0.0.1:8765/api/requests?limit=200&token=$T" > /tmp/reqs.json
/home/ehm_eckx/gBox/system/.venv-linux-aarch64/bin/python - <<'PY'
import json
rows = json.load(open("/tmp/reqs.json"))
rows = rows if isinstance(rows, list) else rows.get("requests") or []
print("total fetched:", len(rows))
counts = {}
for r in rows:
    counts[r.get("status")] = counts.get(r.get("status"), 0) + 1
print("by status:", counts)
open_rows = [r for r in rows if r.get("status") == "open"]
print("open:", len(open_rows))
for r in open_rows[:12]:
    print("  ", str(r.get("created"))[:10], str(r.get("title"))[:70], "|", str(r.get("category") or "")[:24])
PY
