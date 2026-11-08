#!/bin/bash
# Does the mine/grenade object swap build? The panel's "Swap the object" calls /api/decrypt-lab/model-swap with two archive paths.
T=$(cat /home/ehm_eckx/gBox/system/gbox-data/api_token)
API=http://127.0.0.1:8765
cat > /tmp/obj.json <<'JSON'
{"title":"re5_switch","arc_path":"nativeNXx64/ImgNX/Archive/uWp06.arc",
 "donor_arc":"nativeNXx64/ImgNX/Archive/uWp0a.arc","build":"mercmode-objtest"}
JSON
curl -s -m 300 -H 'content-type: application/json' -H 'x-gbox-actor: agent' \
  -d @/tmp/obj.json "$API/api/decrypt-lab/model-swap?token=$T" -o /tmp/objresp.json -w "http %{http_code}\n"
head -c 700 /tmp/objresp.json
echo
