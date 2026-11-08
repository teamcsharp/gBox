#!/bin/bash
# Kernel-side view of the GPU: did the driver come up cleanly in this boot?
echo "== nvidia / gpu lines from this boot =="
sudo -n journalctl -k -b --no-pager 2>/dev/null | grep -iE 'nvidia|nvrm|gpu' | tail -10 | cut -c1-150
echo "== driver version and module params =="
cat /proc/driver/nvidia/version 2>/dev/null | head -2
ls /proc/driver/nvidia/ 2>/dev/null
echo "== vulkan test tools present? =="
for tool in vulkaninfo vkcube vkcube-wayland eglinfo glxinfo; do
  command -v "$tool" > /dev/null 2>&1 && echo "  $tool: yes" || echo "  $tool: no"
done
