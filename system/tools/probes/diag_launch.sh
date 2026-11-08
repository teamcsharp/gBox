#!/bin/bash
# Why does a launch produce no running session? Print the job states and errors, the session rows, and whether an emulator exists.
T=$(cat /home/ehm_eckx/gBox/system/gbox-data/api_token)
API=http://127.0.0.1:8765
PY=/home/ehm_eckx/gBox/system/.venv-linux-aarch64/bin/python
curl -s -m 40 "$API/api/jobs?limit=6&token=$T" -o /tmp/j.json
curl -s -m 40 "$API/api/sessions?token=$T" -o /tmp/s.json
echo "== jobs =="
$PY /tmp/jobs_show.py /tmp/j.json
echo "== sessions =="
$PY /tmp/sess_show.py /tmp/s.json
echo "== processes =="
pgrep -fc citron || echo "no citron"
uptime | head -1
