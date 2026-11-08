#!/bin/bash
# What materials does the player's body slot have? The census the "remove clothes" picker shows.
T=$(cat /home/ehm_eckx/gBox/system/gbox-data/api_token)
echo "== pl00 slot 0 materials =="
curl -s -m 120 "http://127.0.0.1:8765/api/decrypt-lab/pack-materials?title=re4_switch&pack=pl00.udas&slot=0&token=$T" | head -c 1200
echo
echo "== the pack's slot list =="
curl -s -m 120 "http://127.0.0.1:8765/api/decrypt-lab/pack-slots?title=re4_switch&pack=pl00.udas&token=$T" | head -c 600
echo
