#!/bin/bash
# Put the title's save back to a menu state: launch stock, wait for the title screen, stop the session from there.
# Round 98 measured that this is what makes the next boot clean - stopping mid-load recreates the resume prompt.
T=$(cat /home/ehm_eckx/gBox/system/gbox-data/api_token)
API=http://127.0.0.1:8765
PY=/home/ehm_eckx/gBox/system/.venv-linux-aarch64/bin/python
cd /home/ehm_eckx/gBox/system || exit 1

curl -s -m 60 -X POST -H "content-type: application/json" -H "x-gbox-actor: agent" \
  "$API/api/mercmode?token=$T" -d '{"op":"configure","host":"lilspark","enabled":false}' > /dev/null
for sid in $(curl -s -m 40 "$API/api/sessions?token=$T" | python3 -c 'import json,sys;d=json.load(sys.stdin);r=d if isinstance(d,list) else d.get("sessions",[]);print(" ".join(x.get("session_id","") for x in r if x.get("state")=="running"))'); do
  curl -s -m 60 -X POST -H "content-type: application/json" -H "x-gbox-actor: agent" "$API/api/jobs?token=$T" \
    -d "{\"tool\":\"session_op\",\"input\":{\"session_id\":\"$sid\",\"op\":\"stop_game\",\"args\":{}}}" > /dev/null
done
sleep 8
pkill -f citron-linux
sleep 5

curl -s -m 90 -X POST -H "content-type: application/json" -H "x-gbox-actor: agent" \
  "$API/api/games/270a15eb98dab4d7/launch?node=lilspark&token=$T" > /dev/null
sleep 55
SID=$(curl -s -m 40 "$API/api/sessions?token=$T" | python3 -c 'import json,sys;d=json.load(sys.stdin);r=d if isinstance(d,list) else d.get("sessions",[]);print(next((x.get("session_id","") for x in r if x.get("state")=="running"),""))')
echo "session: $SID"
for i in 1 2 3 4 5; do
  sleep 10
  curl -s -m 60 "$API/api/sessions/$SID/frame.jpg?token=$T" -o /tmp/menu_$i.jpg
  $PY -c "from PIL import Image; import statistics; print('menu $i mean %.1f' % statistics.fmean(list(Image.open('/tmp/menu_$i.jpg').convert('L').getdata())))" 2>/dev/null
done
# stop from the menu: this is the step that writes a menu-state save
curl -s -m 60 -X POST -H "content-type: application/json" -H "x-gbox-actor: agent" "$API/api/jobs?token=$T" \
  -d "{\"tool\":\"session_op\",\"input\":{\"session_id\":\"$SID\",\"op\":\"stop_game\",\"args\":{}}}" > /dev/null
echo "stopped from the menu"
