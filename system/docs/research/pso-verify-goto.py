"""Verify the click-to-command plumbing without a game.

The operator asked to drive the bot from the map: click to move it, shift+click an enemy to target it. The viewer writes an order to
`goto.json` and `map_bot.py` consumes it. This posts both kinds of order through the real endpoint and checks the file the bot reads, so the
handoff is proven even when PSO is not running.
"""
import json
import time
import urllib.request
from pathlib import Path

URL = "http://127.0.0.1:8801/api/goto"
GOTO = Path(r"D:\gBox\pso-ds\goto.json")


def post(payload):
    body = json.dumps(payload).encode()
    request = urllib.request.Request(URL, data=body, method="POST",
                                     headers={"content-type": "application/json"})
    with urllib.request.urlopen(request, timeout=8) as reply:
        return reply.status, reply.read().decode()[:200]


print("--- a waypoint order ---")
print(post({"x": -125, "z": 205}))
time.sleep(0.4)
print("goto.json:", GOTO.read_text(encoding="utf-8")[:240] if GOTO.exists() else "missing")

print("\n--- an enemy order (what shift+click sends) ---")
print(post({"enemy": "TObjEneBeast", "x": 502, "z": 3}))
time.sleep(0.4)
data = json.loads(GOTO.read_text(encoding="utf-8")) if GOTO.exists() else {}
print("goto.json:", json.dumps(data)[:260])
print("has enemy field:", "enemy" in data)
print("timestamp fresh:", bool(data.get("t")) and time.time() - float(data.get("t", 0)) < 30)
