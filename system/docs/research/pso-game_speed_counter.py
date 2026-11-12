"""Find a game-speed counter and prove whether fast-forward speeds the game.

Dolphin's `query_runtime` reports only `{running, emulator, state}` - no rate - so the speed has to be measured on something the game increments itself. At 1x PSO's
logic runs 60 ticks a second, so a counter climbing near 60/s is game time; the 43.7 kHz value found earlier is a real-time timer and cannot show a speed-up.

This scans a 12 KB window of globals for counters, keeps those between 30 and 200 per second at 1x, then measures the same addresses with fast-forward enabled. A
counter that keeps its 1x rate is real time; one that multiplies is game time, and the multiplier is the speed the game is actually running at.
"""
import json
import sys
import time
import urllib.request

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
BASE = 0x805D4000
BYTES = 12 * 1024


def rpc(sid, op, args, timeout=40):
    request = urllib.request.Request(
        "http://127.0.0.1:18765/api/sessions/%s/rpc" % sid,
        data=json.dumps({"op": op, "args": args}).encode(), method="POST",
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent", "content-type": "application/json"})
    return json.loads(urllib.request.urlopen(request, timeout=timeout).read() or b"null")


def service(sid, op, args):
    body = {"tool": "session_op", "input": {"session_id": sid, "op": op, "args": args}, "require_worker": sid.split("-")[0]}
    request = urllib.request.Request(
        "http://127.0.0.1:18765/api/jobs", data=json.dumps(body).encode(), method="POST",
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent", "content-type": "application/json"})
    job = json.loads(urllib.request.urlopen(request, timeout=30).read() or b"null")
    job_id = job.get("id")
    for _ in range(30):
        time.sleep(1)
        row = json.loads(urllib.request.urlopen(urllib.request.Request(
            f"http://127.0.0.1:18765/api/jobs/{job_id}",
            headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent"}), timeout=20).read())
        if row.get("state") in ("succeeded", "failed", "cancelled"):
            return row.get("state")
    return "timeout"


def rates(sid, seconds=2.0):
    a = bytes.fromhex(rpc(sid, "read_memory", {"address": BASE, "length": BYTES}) or "")
    time.sleep(seconds)
    b = bytes.fromhex(rpc(sid, "read_memory", {"address": BASE, "length": BYTES}) or "")
    out = {}
    if len(a) != BYTES or len(b) != BYTES:
        return out
    for offset in range(0, BYTES - 3, 4):
        before = int.from_bytes(a[offset:offset + 4], "big")
        after = int.from_bytes(b[offset:offset + 4], "big")
        delta = (after - before) & 0xFFFFFFFF
        if 0 < delta < 20000:
            out[BASE + offset] = delta / seconds
    return out


if __name__ == "__main__":
    sessions = json.loads(urllib.request.urlopen(urllib.request.Request(
        "http://127.0.0.1:18765/api/sessions",
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent"}), timeout=20).read())
    sessions = sessions if isinstance(sessions, list) else (sessions.get("items") or [])
    sid = next(row["session_id"] for row in sessions if row.get("state") in ("running", "starting"))
    print("session:", sid)

    print("\n=== scanning for counters at 1x ===")
    base = rates(sid)
    game_like = {a: r for a, r in base.items() if 30 <= r <= 200}
    print(f"  {len(base)} counters total, {len(game_like)} between 30 and 200 per second")
    for address, rate in sorted(game_like.items(), key=lambda kv: -kv[1])[:10]:
        print(f"    0x{address:08X}  {rate:7.1f} /s")

    if not game_like:
        raise SystemExit("no game-rate counter found in the window; cannot measure speed this way")

    print("\n=== fast-forward on ===")
    print("  job:", service(sid, "fast_forward", {"on": True}))
    time.sleep(2.0)

    fast = rates(sid)
    print("\n  same addresses with fast-forward:")
    scaled = 0
    for address in sorted(game_like, key=lambda a: -game_like[a])[:10]:
        if address not in fast:
            continue
        ratio = fast[address] / game_like[address]
        if abs(ratio - 1) > 0.2:
            scaled += 1
        print(f"    0x{address:08X}  {game_like[address]:7.1f} -> {fast[address]:7.1f} /s   x{ratio:.2f}")

    print("\n=== restore 1x ===")
    print("  job:", service(sid, "fast_forward", {"on": False}))
    print(f"\nVERDICT: {scaled} of the sampled game-rate counters changed rate under fast-forward")
