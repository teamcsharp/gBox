#!/bin/bash
# The control that has been missing since the reboot: does a STOCK run reach a round at all?
# If it does not, the tint is not the problem - the walk is. If it does, the tint build really does hang the load.
PY=/home/ehm_eckx/gBox/system/.venv-linux-aarch64/bin/python
cd /home/ehm_eckx/gBox/system || exit 1
timeout 550 "$PY" -u /tmp/walk_cap.py "" ctrl 6 > /tmp/ctrl.log 2>&1
grep -E "reached|walk steps" /tmp/ctrl.log | tail -2
echo "frames: $(ls /home/ehm_eckx/gBox_alt/re4-lab/ctrl*_*.jpg 2>/dev/null | wc -l)"
