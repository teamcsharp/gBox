#!/bin/bash
# Clear the launch queue my retries built up, so the next single attempt is not stuck behind five hung boots.
T=$(cat /home/ehm_eckx/gBox/system/gbox-data/api_token)
API=http://127.0.0.1:8765
curl -s -m 40 "$API/api/jobs?limit=20&token=$T" -o /tmp/jq.json
IDS=$(/home/ehm_eckx/gBox/system/.venv-linux-aarch64/bin/python -c "
import json
d=json.load(open('/tmp/jq.json'))
rows=d if isinstance(d,list) else d.get('jobs',[])
print(' '.join(r.get('id','') for r in rows if r.get('state') in ('queued','running') and r.get('tool')=='launch_game'))
")
echo "cancelling: ${IDS:-none}"
for jid in $IDS; do
  code=$(curl -s -m 30 -X DELETE -o /dev/null -w "%{http_code}" "$API/api/jobs/$jid?token=$T")
  echo "  $jid -> $code"
done
sleep 3
curl -s -m 40 "$API/api/jobs?limit=8&token=$T" -o /tmp/jq2.json
/home/ehm_eckx/gBox/system/.venv-linux-aarch64/bin/python /tmp/jobs_show.py /tmp/jq2.json
