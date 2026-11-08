#!/bin/bash
# The GPU is held by two ComfyUI instances. gBox's own coordinator suspends ComfyUI when a game runs, so do the same by hand
# (SIGSTOP is reversible with SIGCONT) and then try a stock launch to see whether Vulkan initialises.
set -u
PIDS=$(pgrep -f "ComfyUI.*main.py" | head -4)
echo "comfy pids: ${PIDS:-none}"
for pid in $PIDS; do
  kill -STOP "$pid" 2>/dev/null && echo "  suspended $pid"
done
sleep 2
echo "== gpu holders now =="
sudo -n fuser /dev/nvidia0 2>&1 | head -2
T=$(cat /home/ehm_eckx/gBox/system/gbox-data/api_token)
API=http://127.0.0.1:8765
echo "== stock launch =="
curl -s -m 240 -X POST -H 'content-type: application/json' -H 'x-gbox-actor: agent' \
  "$API/api/games/270a15eb98dab4d7/launch?node=lilspark&token=$T" -d '{}' -o /tmp/stock2.json -w "launch http %{http_code}\n"
sleep 70
L=/home/ehm_eckx/gBox/system/gbox-data/runtime-linux-aarch64/citron-linux/data/citron/log/citron_log.txt
echo "== citron's own verdict =="
grep -i -E "vulkan|CreateGPU|Failed to initialize system" "$L" 2>/dev/null | tail -3 | cut -c1-140
echo "== sessions =="
curl -s -m 40 "$API/api/sessions?token=$T" -o /tmp/s3.json
/home/ehm_eckx/gBox/system/.venv-linux-aarch64/bin/python /tmp/sess_show.py /tmp/s3.json | head -2
