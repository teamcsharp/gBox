"""Find the cell near the warp platform where A actually warps, and use it.

Writing `(360, 0, 26)` does not land on the platform - the raised disc is not a walkable cell, so the game corrects the position to a legal spot 25 units away, and A there does
nothing. The warp *did* take once, from `(383.5, 18.8)`, so the interaction is position-sensitive.

So: take the corridor's own **safe** cells within 45 units of the platform, order them by distance, and for each one write the position, press A, and check the entity count - a
field jumps from the city's 31 to 80+. That is a bounded search over verified-walkable ground, and it stops at the first cell where the warp takes.
"""
import math
import struct
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\system")

DISC = r"D:\gBox\cache\436e0bb84d5337d1\Phantasy Star Online Episode I & II Plus (USA).gcz"
PLATFORM = (360.003, 25.998)


def build():
    from gbox.gcdisc import GCDisc
    from gbox.psomap import collision
    from gbox import pso_coop_town as town
    disc = GCDisc(DISC)
    try:
        data = disc.read(town.REL)
    finally:
        disc.f.close()
    return town.Corridor(collision(data))


def snapshot(pad):
    from pso_pad import call
    return call("/api/sessions/%s/rpc" % pad.sid, {"op": "state", "args": {}}, "POST") or {}


def write_position(pad, point) -> str:
    from pso_pad import call
    player = snapshot(pad).get("player") or {}
    pointer = player.get("ptr")
    if not pointer:
        return "no pointer"
    job = call("/api/jobs", {"tool": "write_memory", "require_worker": pad.worker,
                             "input": {"session_id": pad.sid, "address": int(pointer, 16) + 0x38,
                                       "hex_bytes": struct.pack(">fff", *point).hex()}}, "POST")
    job_id = job.get("id") if isinstance(job, dict) else None
    for _ in range(12):
        time.sleep(0.8)
        row = call("/api/jobs/" + job_id) if job_id else {}
        if row.get("state") in ("succeeded", "failed", "cancelled"):
            return str(row.get("state"))
    return "timeout"


if __name__ == "__main__":
    from pso_pad import Pad
    corridor = build()
    pad = Pad()
    print("session:", pad.sid)

    before = snapshot(pad)
    print("entities now:", len(before.get("entities") or []))

    candidates = []
    for cell in corridor.safe:
        point = corridor.center(cell)
        distance = math.dist(point, PLATFORM)
        if distance <= 45:
            candidates.append((distance, point))
    candidates.sort()
    print(f"safe cells within 45 of the platform: {len(candidates)}")

    for index, (distance, point) in enumerate(candidates[:14], 1):
        write_position(pad, (point[0], 0.0, point[1]))
        time.sleep(0.8)
        player = snapshot(pad).get("player") or {}
        here = (float(player.get("x") or 0), float(player.get("z") or 0))
        pad.send([{"key": "a", "down": True}, {"key": "a", "down": False}])
        time.sleep(2.5)
        after = snapshot(pad)
        count = len(after.get("entities") or [])
        print(f"  {index:2d}: wrote ({point[0]:7.1f},{point[1]:7.1f}) d={distance:5.1f} "
              f"-> at ({here[0]:7.1f},{here[1]:7.1f}) room {after.get('player', {}).get('room')} | entities {count}")
        if count > 50:
            print("\nTHE WARP TOOK - in a field")
            print("shot:", pad.shot("warp_found"))
            break
    else:
        print("\nnone of the safe cells near the platform triggered it")
        print("shot:", pad.shot("no_warp_cell"))
