#!/bin/bash
# Point the library's RE4 link at the cached ROM, which is a real local file, and prove the result is readable.
# The reboot left the SMB share unmounted and the share's _switch folder no longer holds the game, so the catalog's source path is dead;
# the 12.97 GB cache copy under gbox-cache is not.
set -u
CACHE="/home/ehm_eckx/gBox_alt/gbox-cache/270a15eb98dab4d7"
NSP="$CACHE/Resident Evil 4 [UPDATE 1.0.2] [010099a00bc1e000].nsp"
LINK="/home/ehm_eckx/gBox_alt/switch/titles/Resident Evil 4 [010099A00BC1E000].nsp"

echo "cache file:"
ls -la "$NSP" 2>/dev/null | head -1
echo "link before:"
readlink -f "$LINK" 2>/dev/null

ln -sfn "$NSP" "$LINK"
echo "link after:"
readlink -f "$LINK" 2>/dev/null
echo "first bytes of the target:"
head -c 8 "$LINK" 2>/dev/null | od -c | head -1
