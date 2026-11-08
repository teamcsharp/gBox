#!/bin/bash
# Which texture archives does the game actually open? Trace its file opens for a few seconds during a round.
#
# The question round 117 left: `pl08` names global texture ids 1, 2, 5, 9, and only 9 exists in imagepackhd - so where does the loader get
# the surface it clearly draws? The process's own openat() calls answer it without guessing: every archive it reads is named.
T=$(cat /home/ehm_eckx/gBox/system/gbox-data/api_token)
API=http://127.0.0.1:8765
OUT=/tmp/opens.txt
: > "$OUT"

PID=$(pgrep -f citron-linux | head -1)
if [ -z "$PID" ]; then
  echo "no citron running: launching the title first"
  curl -s -m 90 -X POST -H 'content-type: application/json' -H 'x-gbox-actor: agent' \
    "$API/api/games/270a15eb98dab4d7/launch?node=lilspark&token=$T" > /dev/null
  sleep 50
  PID=$(pgrep -f citron-linux | head -1)
fi
echo "citron pid: $PID"
if [ -z "$PID" ]; then
  echo "still no citron; nothing to trace"
  exit 1
fi

# -f follows threads, -e openat keeps the log small, -qq drops the exit banners.
timeout 25 strace -f -qq -e trace=openat -p "$PID" -o "$OUT" 2>/dev/null &
TRACER=$!
sleep 26
wait $TRACER 2>/dev/null
echo "trace lines: $(wc -l < "$OUT")"

echo "--- imagepackhd archives opened ---"
grep -o 'imagepackhd/[0-9a-f]\{8\}\.pack\.fen' "$OUT" | sort | uniq -c | sort -rn | head -20

echo "--- em packs opened ---"
grep -o 'bio4/em/[a-z0-9_]*\.udas' "$OUT" | sort | uniq -c | sort -rn | head -12

echo "--- any romfs paths at all? ---"
grep -c 'romfs' "$OUT" || echo 0
