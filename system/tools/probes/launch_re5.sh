#!/bin/bash
# Launch RE5 with the character-swap build, let it come up, and capture frames so we can see who is on screen.
set -u
T=$(cat /home/ehm_eckx/gBox/system/gbox-data/api_token)
API=http://127.0.0.1:8765
PY=/home/ehm_eckx/gBox/system/.venv-linux-aarch64/bin/python

curl -s -m 60 -X POST -H 'content-type: application/json' -H 'x-gbox-actor: agent' \
  "$API/api/mercmode?token=$T" -d '{"op":"configure","host":"lilspark","enabled":false}' > /dev/null
echo "rotation paused"
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

echo "launching RE5 with the swap build"
curl -s -m 240 -X POST -H 'content-type: application/json' -H 'x-gbox-actor: agent' \
  "$API/api/games/52d15709be0fda1a/launch?node=lilspark&mod=re5-charswap&token=$T" -d '{}' -o /tmp/re5launch.json -w "http %{http_code}\n"
sleep 90
SID=$(curl -s -m 40 "$API/api/sessions?token=$T" | $PY -c "
import json,sys
d=json.load(sys.stdin); rows=d if isinstance(d,list) else d.get('sessions',[])
print(next((r.get('session_id','') for r in rows if r.get('state')=='running'),''))")
echo "session: $SID"
for i in 1 2 3 4; do
  curl -s -m 60 "$API/api/sessions/$SID/frame.jpg?token=$T" -o "/tmp/re5_$i.jpg"
  echo "frame $i: $(wc -c < /tmp/re5_$i.jpg) bytes"
  sleep 8
done
