"""Operator arbitration v2: the bot declares how long its own input is on the wire, and anything outside that is the operator.

The v1 detector compared motion against "time since the bot last called send", but a stride HOLD is 0.7 s of continuous input after that
call, so the operator's motion during a stride was attributed to the bot and the lock never engaged. That is why the bot kept taking the
controller back.

v2 fixes it with an explicit action window:
  * `note_bot_input(seconds)` records `bot_active_until = now + seconds` - the period the bot's own input will be affecting the game;
  * the watcher marks OPERATOR motion only when the character moves while `now > bot_active_until + GRACE`;
  * `guard()` refuses to send while operator motion is inside the last 3 s.

The decision logic is a pure function (`classify_motion`) so it can be tested without touching the game.
"""
import json
import math
import struct
import sys
import time
import urllib.request
from pathlib import Path

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
API = "http://127.0.0.1:18765"
LOCK = Path(r"D:\gBox\pso-ds\operator-lock.json")
BOT_INPUT = Path(r"D:\gBox\pso-ds\bot-input.json")
IDLE_SECONDS = 3.0
GRACE = 0.20


def _read(address, length):
    body = json.dumps({"op": "read_memory", "args": {"address": address, "length": length}}).encode()
    try:
        request = urllib.request.Request(f"{API}/api/sessions/{_session_id()}/rpc", data=body, method="POST",
                                         headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent",
                                                  "content-type": "application/json"})
        return bytes.fromhex(json.loads(urllib.request.urlopen(request, timeout=8).read() or b'""'))
    except Exception:                                            # noqa: BLE001
        return b""


def _session_id():
    try:
        cached = json.loads(Path(r"D:\gBox\pso-ds\.pso-sid").read_text())
        if time.time() - cached.get("t", 0) < 30:
            return cached["sid"]
    except Exception:                                            # noqa: BLE001
        pass
    try:
        request = urllib.request.Request(API + "/api/sessions",
                                         headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent"})
        sessions = json.loads(urllib.request.urlopen(request, timeout=15).read() or b"null") or []
        for session in sessions:
            if session.get("state") == "running" and "phantasy" in str(session.get("title", "")).lower():
                sid = session["session_id"]
                Path(r"D:\gBox\pso-ds\.pso-sid").write_text(json.dumps({"sid": sid, "t": time.time()}))
                return sid
    except Exception:                                            # noqa: BLE001
        pass
    return ""


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


def note_bot_input(seconds=0.0):
    """Record that the bot's own input will affect the game for the next `seconds`."""
    payload = {"t": time.time(), "until": time.time() + max(0.0, seconds)}
    try:
        BOT_INPUT.write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        pass


def bot_active_until():
    try:
        return json.loads(BOT_INPUT.read_text(encoding="utf-8")).get("until", 0.0)
    except Exception:                                            # noqa: BLE001
        return 0.0


def classify_motion(moved, now, active_until, grace=GRACE):
    """Pure decision: is this motion the operator's?"""
    if moved <= 1.5:
        return False
    return now > active_until + grace


def lock_state():
    try:
        return json.loads(LOCK.read_text(encoding="utf-8"))
    except Exception:                                            # noqa: BLE001
        return {"last_motion": 0.0}


def operator_active():
    return time.time() - lock_state().get("last_motion", 0.0) < IDLE_SECONDS


def wait_for_idle(timeout=120.0, poll=0.2):
    started = time.time()
    while time.time() - started < timeout:
        if not operator_active():
            return True
        time.sleep(poll)
    return False


def guard(sleep=0.2):
    if operator_active():
        time.sleep(sleep)
        return False
    return True


def watch(duration=86400.0, hz=8.0):
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    last = position()
    last_motion = 0.0
    while time.time() - started < duration:
        now_position = position()
        if now_position and last:
            moved = math.dist(now_position, last)
            if classify_motion(moved, time.time(), bot_active_until()):
                last_motion = time.time()
                try:
                    LOCK.write_text(json.dumps({"last_motion": last_motion, "moved": round(moved, 1),
                                                "operator_active": True}), encoding="utf-8")
                except OSError:
                    pass
        if now_position:
            last = now_position
        time.sleep(1.0 / hz)
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "state":
        print(json.dumps({"operator_active": operator_active(), **lock_state(),
                          "bot_active_until_in": round(bot_active_until() - time.time(), 2)}, indent=1))
    elif len(sys.argv) > 1 and sys.argv[1] == "selftest":
        now = 1000.0
        cases = [
            ("operator moves while the bot is idle", 5.0, now, now - 5.0, True),
            ("bot's own stride", 5.0, now, now + 0.5, False),
            ("bot's stride just ended (grace)", 5.0, now, now - 0.1, False),
            ("tiny jitter", 0.5, now, now - 5.0, False),
            ("operator moves 1 s after the bot stopped", 5.0, now, now - 1.2, True),
        ]
        failures = 0
        for label, moved, at, active_until, expected in cases:
            got = classify_motion(moved, at, active_until)
            status = "ok" if got == expected else "FAIL"
            if got != expected:
                failures += 1
            print(f"  {status:<4} {label:<42} moved={moved} bot_active_until={active_until - at:+.1f}s "
                  f"-> operator={got} (expected {expected})")
        print("failures:", failures)
        raise SystemExit(0 if failures == 0 else 2)
    else:
        print("watching operator motion (v2 action window)", flush=True)
        raise SystemExit(watch())
