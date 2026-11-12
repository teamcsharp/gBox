"""Measure the game's real frame rate, then try to drive it faster.

The 10x clause needs a measurement, not an opinion. `0x805D53A4` is the game's frame counter (earlier measured at ~32/s at normal speed and ~116/s with the fast-forward
lane key held), so sampling it twice gives the rate directly.

Order of work:

1. baseline now, with the bot playing;
2. `fast_forward` on (the op wired through `tools.py` to `rewind.set_fast_forward`);
3. measure again, and again after a moment to see whether it settles or the emulator throttles.

If the rate does not improve, the ceiling is CPU per frame - the next lever is Dolphin's per-frame work (EFB access, EFB copies, DSP), which needs a relaunch to take.
"""
import json
import time

from pso_pad import Pad, call

COUNTER = 0x805D53A4


def read(pad: Pad, address: int) -> int | None:
    raw = call("/api/sessions/%s/rpc" % pad.sid,
               {"op": "read_memory", "args": {"address": address, "length": 4}}, "POST")
    try:
        return int.from_bytes(bytes.fromhex(raw), "big")
    except Exception:                                              # noqa: BLE001
        return None


def rate(pad: Pad, seconds: float = 4.0) -> float | None:
    first = read(pad, COUNTER)
    time.sleep(seconds)
    second = read(pad, COUNTER)
    if first is None or second is None or second < first:
        return None
    return round((second - first) / seconds, 1)


def session_op(pad: Pad, op: str, args: dict) -> str:
    job = call("/api/jobs", {"tool": "session_op", "require_worker": pad.worker,
                             "input": {"session_id": pad.sid, "op": op, "args": args}}, "POST")
    job_id = job.get("id") if isinstance(job, dict) else None
    if not job_id:
        return "rejected: " + json.dumps(job)[:140]
    for _ in range(40):
        time.sleep(0.5)
        row = call("/api/jobs/" + job_id)
        if row.get("state") in ("succeeded", "failed", "cancelled"):
            return str(row.get("state")) + ("" if row.get("state") == "succeeded"
                                            else ": " + str(row.get("error"))[:100])
    return "timeout"


if __name__ == "__main__":
    pad = Pad()
    print("session:", pad.sid)

    base = rate(pad)
    print("baseline frames/s:", base)

    print("\nfast_forward on:", session_op(pad, "fast_forward", {"on": True}))
    time.sleep(2)
    fast = rate(pad)
    print("fast-forward frames/s:", fast)
    time.sleep(3)
    settled = rate(pad)
    print("fast-forward (settled):", settled)

    if base and fast:
        print(f"\nmultiplier: {fast / base:.1f}x" if base else "")
    print("shot:", pad.shot("fast_forward"))

    print("\nfast_forward off:", session_op(pad, "fast_forward", {"on": False}))
    time.sleep(2)
    print("back to:", rate(pad), "frames/s")
