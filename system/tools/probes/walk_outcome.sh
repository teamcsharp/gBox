#!/bin/bash
# Where did each pack-swap run end? Print the walk outcome lines only.
for f in /tmp/fam1.log /tmp/fam2.log; do
  echo "== $f"
  grep -E 'MARK (walk|waited)' "$f" | tail -2
  echo "   frames: $(ls /home/ehm_eckx/gBox_alt/re4-lab/$(basename "$f" .log)*_*.jpg 2>/dev/null | wc -l)"
done
