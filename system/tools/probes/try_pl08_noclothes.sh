#!/bin/bash
# The payoff: with the player pack now known to be pl08, vanish every material of its body slot except the first.
# If material 0 is the base body, what shows is the character without the clothing materials.
T=$(cat /home/ehm_eckx/gBox/system/gbox-data/api_token)
cat > /tmp/pl08_clothes.json <<'JSON'
{"title":"re4_switch","pack":"pl08.udas",
 "hide":[1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24],
 "hide_mode":"vanish","build":"re4sw-pl08-noclothes","write":true}
JSON
curl -s -m 240 -H 'content-type: application/json' -d @/tmp/pl08_clothes.json \
  "http://127.0.0.1:8765/api/decrypt-lab/replace?token=$T" | head -c 900
echo
