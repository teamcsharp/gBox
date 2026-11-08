#!/bin/bash
# "Remove clothes" through the panel route: hide material 7 of the player's body slot (566 triangles - the jacket-sized one),
# write it into a build, and report what the operation says it did. No donor is involved.
T=$(cat /home/ehm_eckx/gBox/system/gbox-data/api_token)
cat > /tmp/clothes_body.json <<'JSON'
{"title":"re4_switch","pack":"pl00.udas","hide":[7],"build":"re4sw-noclothes","write":true}
JSON
curl -s -m 240 -H 'content-type: application/json' -d @/tmp/clothes_body.json \
  "http://127.0.0.1:8765/api/decrypt-lab/replace?token=$T" | head -c 700
echo
