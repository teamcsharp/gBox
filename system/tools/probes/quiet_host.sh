#!/bin/bash
# Quiet the host before a single-boot experiment: pause the rotation and stop whatever session the reboot brought back.
T=$(cat /home/ehm_eckx/gBox/system/gbox-data/api_token)
API=http://127.0.0.1:8765
curl -s -m 60 -X POST -H 'content-type: application/json' -H 'x-gbox-actor: agent' \
  "$API/api/mercmode?token=$T" -d '{"op":"configure","host":"lilspark","enabled":false}' > /dev/null
echo "rotation paused"
curl -s -m 40 "$API/api/sessions?token=$T" -o /tmp/sess.json
SIDS=$(/home/ehm_eckx/gBox/system/.venv-linux-aarch64/bin/python -c "
import json
d=json.load(open('/tmp/sess.json'))
rows=d if isinstance(d,list) else d.get('sessions',[])
print(' '.join(r.get('session_id','') for r in rows if r.get('state')=='running'))
")
echo "running: ${SIDS:-none}"
for sid in $SIDS; do
  curl -s -m 60 -X POST -H 'content-type: application/json' -H 'x-gbox-actor: agent' "$API/api/jobs?token=$T" \
    -d "{\"tool\":\"session_op\",\"input\":{\"session_id\":\"$sid\",\"op\":\"stop_game\",\"args\":{}}}" > /dev/null
  echo "stopped $sid"
done
sleep 8
pkill -f citron-linux 2>/dev/null
pkill -f walk_cap 2>/dev/null
sleep 4
echo "strays: $(pgrep -fc 'citron-linux|walk_cap' || echo 0)"
uptime | head -1
