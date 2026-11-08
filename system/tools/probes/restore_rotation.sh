#!/bin/bash
# Put the rotation back the way the operator wants it: enabled, RE4 + RE5 pinned to their Switch editions.
T=$(cat /home/ehm_eckx/gBox/system/gbox-data/api_token)
API=http://127.0.0.1:8765
cat > /tmp/mm_restore.json <<'JSON'
{"op":"configure","host":"lilspark","enabled":true,"titles":["re4","re5"],"rounds_per_title":1,"keep_warm":0,
 "preferred_editions":{"re4":{"platform":"switch","mode":"mercenaries","title_id":"010099A00BC1E000"},
                       "re5":{"platform":"switch","mode":"no_mercy","title_id":"010018100CD46000"}}}
JSON
curl -s -m 90 -H 'content-type: application/json' -H 'x-gbox-actor: agent' \
  -d @/tmp/mm_restore.json "$API/api/mercmode?token=$T" -o /tmp/mm_restore.out -w "http %{http_code}\n"
head -c 300 /tmp/mm_restore.out
echo
sleep 20
curl -s -m 40 "$API/api/mercmode?token=$T" -o /tmp/mm4.json
/home/ehm_eckx/gBox/system/.venv-linux-aarch64/bin/python /tmp/mm_state.py /tmp/mm4.json | head -4
