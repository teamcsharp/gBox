#!/bin/bash
# Ship the walk harness to /tmp and prove it parses, without any quoting games: the file goes over scp, and this script only
# checks it.
set -e
ls -la /tmp/wcap.py
if grep -q 'where == "playing"' /tmp/wcap.py; then echo "playing branch: present"; else echo "playing branch: MISSING"; fi
/home/ehm_eckx/gBox/system/.venv-linux-aarch64/bin/python - <<'PY'
import ast
ast.parse(open("/tmp/wcap.py").read())
print("parses")
PY
cp /tmp/wcap.py /tmp/walk_cap.py
echo "installed /tmp/walk_cap.py"
