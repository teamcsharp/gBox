"""Measure whether fast-forward actually speeds the game up, using a counter in memory.

`session_op` already routes `{op: 'fast_forward', args: {on: ...}}` to `rewind.set_fast_forward`, which on Dolphin holds the "Disable Emulation Speed Limit" lane key
with `hidden_ok=True` - no focus needed.

Measuring it needs something that advances on its own. The player is idle, so this scans the globals window for 32-bit values that increase between two reads one
second apart, picks the one with the steadiest rate, and measures it again after fast-forward is on. A rate increase on the same address is evidence the game is
running faster, not an inference from a flag.
"""
import json
import sys
import time
import urllib.request

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S                                                # noqa: E402

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
SCAN_BASE = 0x805D5F00
SCAN_WORDS = 320


def rpc(sid, op, args, timeout=30):
    request = urllib.request.Request(
        "http://127.0.0.1:18765/api/sessions/%s/rpc" % sid,
        data=json.dumps({"op": op, "args": args}).encode(), method="POST",
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent", "content-type": "application/json"})
    return json.loads(urllib.request.urlopen(request, timeout=timeout).read() or b"null")


def read(sid, address, length):
    return bytes.fromhex(rpc(sid, "read_memory", {"address": address, "length": length}) or "")


def counters(sid, seconds=1.5):
    a = read(sid, SCAN_BASE, SCAN_WORDS * 4)
    time.sleep(seconds)
    b = read(sid, SCAN_BASE, SCAN_WORDS * 4)
    if len(a) != len(b) or not a:
        return {}
    out = {}
    for index in range(SCAN_WORDS):
        before = int.from_bytes(a[index * 4:index * 4 + 4], "big")
        after = int.from_bytes(b[index * 4:index * 4 + 4], "big")
        delta = (after - before) & 0xFFFFFFFF
        if 0 < delta < 100000:
            out[SCAN_BASE + index * 4] = delta / seconds
    return out


def service(sid, op, args):
    body = {"tool": "session_op", "input": {"session_id": sid, "op": op, "args": args}, "require_worker": sid.split("-")[0]}
    request = urllib.request.Request(
        "http://127.0.0.1:18765/api/jobs", data=json.dumps(body).encode(), method="POST",
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent", "content-type": "application/json"})
    try:
        job = json.loads(urllib.request.urlopen(request, timeout=30).read() or b"null")
    except Exception as exc:                                       # noqa: BLE001
        return {"_error": str(exc)[:160]}
    job_id = job.get("id")
    for _ in range(30):
        time.sleep(1)
        row = json.loads(urllib.request.urlopen(urllib.request.Request(
            f"http://127.0.0.1:18765/api/jobs/{job_id}",
            headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent"}), timeout=20).read())
        if row.get("state") in ("succeeded", "failed", "cancelled"):
            return {"state": row.get("state"), "error": str(row.get("error") or "")[:150],
                    "result": row.get("result")}
    return {"state": "timeout"}


if __name__ == "__main__":
    sessions = json.loads(urllib.request.urlopen(urllib.request.Request(
        "http://127.0.0.1:18765/api/sessions",
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent"}), timeout=20).read())
    sessions = sessions if isinstance(sessions, list) else (sessions.get("items") or [])
    sid = next(row["session_id"] for row in sessions if row.get("state") in ("running", "starting"))
    print("session:", sid)

    print("\n=== baseline counters (1x) ===")
    base = counters(sid)
    for address, rate in sorted(base.items(), key=lambda kv: -kv[1])[:6]:
        print(f"  0x{address:08X}  {rate:10.1f} /s")
    if not base:
        print("  none found in the scan window")

    print("\n=== enabling fast-forward ===")
    print(json.dumps(service(sid, "fast_forward", {"on": True}), default=str)[:300])
    time.sleep(1.5)

    print("\n=== counters with fast-forward on ===")
    fast = counters(sid)
    for address in sorted(set(base) & set(fast), key=lambda a: -base[a])[:6]:
        ratio = fast[address] / base[address] if base[address] else 0
        print(f"  0x{address:08X}  {base[address]:8.1f} -> {fast[address]:8.1f} /s   x{ratio:.2f}")

    shared = sorted(set(base) & set(fast), key=lambda a: -base[a])
    if shared:
        address = shared[0]
        print(f"\nVERDICT: counter 0x{address:08X} went from {base[address]:.0f}/s to {fast[address]:.0f}/s "
              f"(x{fast[address] / base[address]:.2f})")

    print("\n=== restoring normal speed ===")
    print(json.dumps(service(sid, "fast_forward", {"on": False}), default=str)[:300])
