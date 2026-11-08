#!/bin/bash
# The reboot left no X display at all, and Citron has nowhere to draw. Start one on the display gBox uses and launch.
set -u
if DISPLAY=:100 timeout 5 xdpyinfo > /dev/null 2>&1; then
  echo ":100 already answers"
else
  nohup Xvfb :100 -screen 0 1600x900x24 -nolisten tcp > /tmp/xvfb100.log 2>&1 &
  sleep 4
  if DISPLAY=:100 timeout 5 xdpyinfo > /dev/null 2>&1; then
    echo ":100 started"
  else
    echo ":100 FAILED to start:"; tail -3 /tmp/xvfb100.log
    exit 1
  fi
fi
T=$(cat /home/ehm_eckx/gBox/system/gbox-data/api_token)
API=http://127.0.0.1:8765
echo "== launch with the tint build =="
curl -s -m 240 -X POST -H 'content-type: application/json' -H 'x-gbox-actor: agent' \
  "$API/api/games/270a15eb98dab4d7/launch?node=lilspark&mod=re4sw-tint2&token=$T" -d '{}' -o /tmp/launch.json -w "http %{http_code}\n"
