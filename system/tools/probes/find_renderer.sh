#!/bin/bash
# Where is the Citron binary, and does it expose a renderer choice? A working OpenGL backend would unblock every emulator task
# without needing the GPU's Vulkan device to come back.
R=/home/ehm_eckx/gBox/system/gbox-data/runtime-linux-aarch64/citron-linux
echo "== layout =="
ls "$R" | head -10
BIN=$(find "$R" -maxdepth 2 -type f -executable -name "citron*" 2>/dev/null | head -3)
echo "candidates:"; echo "$BIN"
FIRST=$(echo "$BIN" | head -1)
if [ -n "$FIRST" ]; then
  echo "== --help renderer lines =="
  timeout 20 "$FIRST" --help 2>&1 | grep -iE 'render|vulkan|gl' | head -6
  echo "== config keys mentioning renderer =="
  grep -n -iE 'renderer|backend' "$R/config/citron/qt-config.ini" 2>/dev/null | head -6
fi
