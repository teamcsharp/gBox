"""Can the bot grind a boss down? It has the pieces: `always_hit`, DARK FLOW, and a permanent Scape Doll.

The Dragon is 1300 HP and the character is level 5 with 68 HP, so it cannot win a straight fight - but it does not need to. `survival` is a **virtual Scape Doll: native revival on death, no
inventory slot**, and `always_hit` removes the accuracy roll, leaving only *"targets must still be in range and hittable"*. So the strat is not to survive the Dragon, it is to **keep hitting it
and keep coming back** until 1300 HP is gone.

Measured against the only thing that matters: the boss's HP over time.

Each swing is preceded by `b` (a pause menu eats the attack), and movement never releases a single direction - releasing `up` alone pins the stick hard left (`lx -32768`), which is what
made the bot look frozen for so long.
"""
import math
import time

from pso_pad import Pad, call

DIRECTIONS = ("up", "down", "left", "right")


def state(pad):
    return call("/api/sessions/%s/rpc" % pad.sid, {"op": "state", "args": {}}, "POST") or {}


def mods(pad, payload, wait=90.0):
    job = call("/api/jobs", {"tool": "pso_mods", "require_worker": pad.worker,
                             "input": {"session_id": pad.sid, **payload}}, "POST")
    job_id = job.get("id") if isinstance(job, dict) else None
    if not job_id:
        return {"state": "rejected", "answer": job}
    deadline = time.time() + wait
    while time.time() < deadline:
        time.sleep(2)
        row = call("/api/jobs/" + job_id)
        if row.get("state") in ("succeeded", "failed", "cancelled"):
            return {"state": row.get("state"), "error": row.get("error"),
                    "output": (row.get("output") or {}).get("result")}
    return {"state": "timeout"}


def tap(pad, key):
    pad.send([{"key": key, "down": True}, {"key": key, "down": False}])


def hold(pad, key, secs):
    pad.send([{"key": key, "down": True}])
    time.sleep(secs)
    pad.send([{"key": key, "down": False} for key in DIRECTIONS])


if __name__ == "__main__":
    pad = Pad()
    print("session:", pad.sid)
    answer = mods(pad, {"op": "boss_warp", "target": "dragon"})
    print("boss_warp:", answer.get("state"), str(answer.get("error"))[:100])

    for _ in range(10):
        time.sleep(3)
        now = state(pad)
        boss = [e for e in (now.get("entities") or [])
                if str(e.get("kind")) == "enemy" and e.get("hp") and "Colli" not in str(e.get("class"))]
        if boss:
            print("boss present:", [(e.get("class"), e.get("hp")) for e in boss][:2])
            break

    start_hp = None
    for step in range(70):
        now = state(pad)
        me = now.get("player") or {}
        if not me:
            time.sleep(1)
            continue
        x, z = float(me.get("x") or 0), float(me.get("z") or 0)
        heading = float(me.get("heading_deg") or 0)
        boss = [e for e in (now.get("entities") or [])
                if str(e.get("kind")) == "enemy" and e.get("hp") and float(e.get("hp")) > 0
                and "Colli" not in str(e.get("class"))]
        if not boss:
            print(f"\nNO BOSS LEFT - defeated at step {step}")
            break
        target = max(boss, key=lambda e: float(e.get("hp") or 0))
        bx, bz = float(target.get("x") or 0), float(target.get("z") or 0)
        hp = float(target.get("hp") or 0)
        if start_hp is None:
            start_hp = hp
        distance = math.hypot(bx - x, bz - z)
        want = (math.degrees(math.atan2(bx - x, bz - z)) + 360.0) % 360.0
        error = ((want - heading + 540.0) % 360.0) - 180.0
        if step % 6 == 0:
            print(f"  {step:2d}: boss hp {hp:5.0f} (from {start_hp:.0f}) d {distance:6.1f} aim {error:+6.1f} | me hp {me.get('hp')}")

        if abs(error) > 25:
            hold(pad, "left" if error > 0 else "right", min(0.3, max(0.1, abs(error) / 400.0)))
        elif distance > 30:
            hold(pad, "up", min(0.8, max(0.25, distance / 300.0)))
        else:
            tap(pad, "b")
            time.sleep(0.15)
            tap(pad, "a")
            time.sleep(0.35)
        time.sleep(0.15)

    final = state(pad)
    boss = [e for e in (final.get("entities") or []) if str(e.get("kind")) == "enemy" and e.get("hp")]
    print("\nfinal:", [(e.get("class"), e.get("hp")) for e in boss][:3])
