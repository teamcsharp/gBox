#!/bin/bash
# The panel's live path: every MercMode swap writes the build named `mercmode-swap`, and the title applies it at its next boot.
# So put the character swap there, point the rotation at RE5 alone, and let it boot Merc Mode with the swap in place.
set -u
T=$(cat /home/ehm_eckx/gBox/system/gbox-data/api_token)
API=http://127.0.0.1:8765
PY=/home/ehm_eckx/gBox/system/.venv-linux-aarch64/bin/python

echo "== stop the current session =="
for sid in $(curl -s -m 40 "$API/api/sessions?token=$T" | $PY -c "
import json,sys
d=json.load(sys.stdin); rows=d if isinstance(d,list) else d.get('sessions',[])
print(' '.join(r.get('session_id','') for r in rows if r.get('state')=='running'))"); do
  curl -s -m 60 -X POST -H 'content-type: application/json' -H 'x-gbox-actor: agent' "$API/api/jobs?token=$T" \
    -d "{\"tool\":\"session_op\",\"input\":{\"session_id\":\"$sid\",\"op\":\"stop_game\",\"args\":{}}}" > /dev/null
done
sleep 6
pkill -f citron-linux 2>/dev/null
sleep 4

echo "== rebuild the swap into the panel's live build =="
cd /home/ehm_eckx/gBox/system || exit 1
GBOX_CONFIG=/home/ehm_eckx/gBox/system/gbox.toml "$PY" /tmp/swap_re5.py \
  uPl02JillCos1.arc=uPl00ChrisNormal.arc mercmode-swap 52d15709be0fda1a 2>&1 | tail -2

echo "== rotation: RE5 only, so its next boot carries the swap =="
cat > /tmp/mm_re5.json <<'JSON'
{"op":"configure","host":"lilspark","enabled":true,"titles":["re5"],"rounds_per_title":1,"keep_warm":0,
 "preferred_editions":{"re5":{"platform":"switch","mode":"no_mercy","title_id":"010018100CD46000"}}}
JSON
curl -s -m 90 -H 'content-type: application/json' -H 'x-gbox-actor: agent' -d @/tmp/mm_re5.json \
  "$API/api/mercmode?token=$T" -o /tmp/mm_re5.out -w "configure http %{http_code}\n"
sleep 120
curl -s -m 40 "$API/api/mercmode?token=$T" -o /tmp/mm5.json
$PY /tmp/mm_state.py /tmp/mm5.json | head -4
