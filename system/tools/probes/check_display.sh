#!/bin/bash
# How does gBox set up the display Citron draws on, and did that setup fail after the reboot?
grep -n -i "display" /home/ehm_eckx/gBox/system/gbox.toml | head -6
echo "== service log, display lines =="
sudo -n journalctl -u gbox.service --since "-45 min" --no-pager 2>/dev/null | grep -i -E "xvfb|DISPLAY|X11|screen" | tail -10 | cut -c1-160
echo "== does :100 answer? =="
DISPLAY=:100 timeout 5 xdpyinfo > /dev/null 2>&1 && echo "yes" || echo "no"
