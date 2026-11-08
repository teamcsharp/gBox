#!/bin/bash
# Exercise the replace route end to end: a real preview of "replace the zombies with Sonic" (write=false, so no build is touched).
T=$(cat /home/ehm_eckx/gBox/system/gbox-data/api_token)
cat > /tmp/replace_body.json <<'JSON'
{"title":"re4_switch","pack":"em16.udas",
 "donor_glb":"/home/ehm_eckx/agent-work/re4chars/sonic_src.glb","write":false}
JSON
echo "body: $(wc -c < /tmp/replace_body.json) bytes"
curl -s -m 180 -H 'content-type: application/json' -d @/tmp/replace_body.json \
  "http://127.0.0.1:8765/api/decrypt-lab/replace?token=$T" | head -c 900
echo
