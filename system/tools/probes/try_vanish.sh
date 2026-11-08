#!/bin/bash
# "Remove clothes", second attempt: VANISH the garment materials (collapse hid them inside the body and nothing showed).
# Materials 1, 2 and 7 are the large ones on the body atlas; vanishing all three should leave the base body visible.
T=$(cat /home/ehm_eckx/gBox/system/gbox-data/api_token)
cat > /tmp/vanish_body.json <<'JSON'
{"title":"re4_switch","pack":"pl00.udas","hide":[1,2,7],"hide_mode":"vanish","build":"re4sw-vanish","write":true}
JSON
curl -s -m 240 -H 'content-type: application/json' -d @/tmp/vanish_body.json \
  "http://127.0.0.1:8765/api/decrypt-lab/replace?token=$T" | head -c 800
echo
