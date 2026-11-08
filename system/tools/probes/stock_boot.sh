#!/bin/bash
# Stock boot, no mod at all: if this hangs too, the problem is the environment, not the tinted build.
set -u
T=$(cat /home/ehm_eckx/gBox/system/gbox-data/api_token)
API=http://127.0.0.1:8765
curl -s -m 240 -X POST -H 'content-type: application/json' -H 'x-gbox-actor: agent' \
  "$API/api/games/270a15eb98dab4d7/launch?node=lilspark&token=$T" -d '{}' -o /tmp/stock.json -w "launch http %{http_code}\n"
sleep 75
curl -s -m 40 "$API/api/sessions?token=$T" -o /tmp/s2.json
/home/ehm_eckx/gBox/system/.venv-linux-aarch64/bin/python /tmp/sess_show.py /tmp/s2.json | head -3
echo "== citron processes =="
pgrep -c citron || echo "none"
echo "== last citron log lines =="
L=$(ls -t /home/ehm_eckx/gBox/system/gbox-data/runtime-linux-aarch64/citron-linux/data/citron/log/citron_log.txt 2>/dev/null | head -1)
tail -6 "$L" 2>/dev/null | cut -c1-150
