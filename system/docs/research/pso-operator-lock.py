"""Operator arbitration: whenever the operator moves the character, the bot stays off the controller.

Rules (operator's words): stop fighting when the operator takes control; only take back control after the operator has put the
controller down and has not moved the character for three seconds.

How it works: `watch` samples the character position at ~8 Hz. A position change while the bot has not sent input for 0.4 s is operator
motion, and it refreshes `operator-lock.json`. Every driver calls `guard()` before sending anything; while the lock is hot the driver
sleeps. `wait_for_idle()` blocks until 3 s have passed with no operator motion.

Files: D:\\gBox\\pso-ds\\operator-lock.json and D:\\gBox\\pso-ds\\bot-input.json (both tiny, rewritten in place).
"""
import json
import math
import os
import struct
import sys
import time
import urllib.request
from pathlib import Path

SYSTEM = r"C:\_tools\gBox\system"
TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
API = "http://127.0.0.1:8765"
SID = "e731ee594dde4a89-cae9dad929a34d17"
LOCK = Path(r"D:\gBox\pso-ds\operator-lock.json")
BOT_INPUT = Path(r"D:\gBox\pso-ds\bot-input.json")
IDLE_SECONDS = 3.0


def _read(address, length):
    body = json.dumps({"op": "read_memory", "args": {"address": address, "length": length}}).encode()
    try:
        req = urllib.request.Request(f"{API}/api/sessions/{SID}/rpc", data=body, method="POST",
                                     headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent",
                                              "content-type": "application/json"})
        return bytes.fromhex(json.loads(urllib.request.urlopen(req, timeout=8).read() or b'""'))
    except Exception:                                            # noqa: BLE001
        return b""


def position():
    raw = _read(0x8050EA10, 4)
    actor = int.from_bytes(raw, "big") if raw else 0
    if not actor:
        return None
    blob = _read(actor + 0x38, 12)
    if len(blob) < 12:
        return None
    x, _y, z = struct.unpack(">fff", blob)
    return x, z


def note_bot_input():
    """Call right after the bot sends input, so motion that follows is not mistaken for the operator."""
    BOT_INPUT.write_text(json.dumps({"t": time.time()}), encoding="utf-8")


def _bot_input_age():
    try:
        return time.time() - json.loads(BOT_INPUT.read_text(encoding="utf-8"))["t"]
    except Exception:                                            # noqa: BLE001
        return 1e9


def lock_state():
    try:
        return json.loads(LOCK.read_text(encoding="utf-8"))
    except Exception:                                            # noqa: BLE001
        return {"last_motion": 0.0}


def operator_active():
    return time.time() - lock_state().get("last_motion", 0.0) < IDLE_SECONDS


def wait_for_idle(timeout=120.0, poll=0.2):
    """Block until the operator has been idle for IDLE_SECONDS. Returns False on timeout."""
    started = time.time()
    while time.time() - started < timeout:
        if not operator_active():
            return True
        time.sleep(poll)
    return False


def guard(sleep=0.2):
    """Call before any bot input. Returns True when the bot may act."""
    if operator_active():
        time.sleep(sleep)
        return False
    return True


def watch(duration=86400.0, hz=8.0, motion_threshold=1.5):
    """Sampling loop: records operator motion into the lock file. Run as its own process."""
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    last = position()
    last_motion = 0.0
    samples = 0
    while time.time() - started < duration:
        now = position()
        if now and last:
            moved = math.dist(now, last)
            if moved > motion_threshold:
                if _bot_input_age() > 0.4:                       # motion the bot did not cause
                    last_motion = time.time()
                    with open(LOCK, "w", encoding="utf-8") as handle:
                        json.dump({"last_motion": last_motion, "moved": round(moved, 1),
                                   "operator_active": True}, handle)
        if now:
            last = now
        samples += 1
        time.sleep(1.0 / hz)
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "state":
        print(json.dumps({"operator_active": operator_active(), **lock_state()}, indent=1))
    else:
        print("watching operator motion", flush=True)
        raise SystemExit(watch())
