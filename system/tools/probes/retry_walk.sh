#!/bin/bash
# A failed resume-prompt press is not recoverable by pressing again: the dialog wants input at a moment it does not
# announce. So a failed attempt re-boots the title instead, up to three times, and the first one that reaches a round
# keeps its frames.
BUILD="$1"
TAG="${2:-coh}"
FRAMES="${3:-12}"
PY=/home/ehm_eckx/gBox/system/.venv-linux-aarch64/bin/python
cd /home/ehm_eckx/gBox/system || exit 1
for i in 1 2 3; do
  log="/tmp/${TAG}${i}.log"
  "$PY" -u /tmp/walk_cap.py "$BUILD" "${TAG}${i}" "$FRAMES" > "$log" 2>&1
  if grep -q "reached True" "$log"; then
    echo "ATTEMPT $i reached a round (log $log)"
    exit 0
  fi
  echo "ATTEMPT $i did not reach a round (log $log)"
done
echo "no attempt reached a round"
exit 1
