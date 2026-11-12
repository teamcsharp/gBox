"""Get the bot into a field and hand it to autoplay - the flow that worked, made repeatable.

The route that reached the Forest last time, in order:

1. a memory write into the corridor's region, because walking there from a city corner is not reliable and the game's
   collision corrects the write to a legal cell;
2. verify the landing is a **safe** cell of the disc's own mesh (`pso_coop_town.Corridor`);
3. write onto the warp platform `(360, 0, 26)` and press **A** - that warp put the bot in a Forest field with 85 entities
   including gates;
4. confirm the room actually changed (a field has far more entities than the city's 31);
5. start the app's autoplay, which in a field has doors to walk to and enemies to fight.

Every step is checked against the semantic profile, so a failure is visible at the step it happens rather than at the end.
"""
import json
import struct
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\system")

DISC = r"D:\gBox\cache\436e0bb84d5337d1\Phantasy Star Online Episode I & II Plus (USA).gcz"
PLATFORM_WRITE = (360.0, 0.0, 26.0)
CORRIDOR_WRITE = (240.0, 0.0, 60.0)


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


def state(pad):
    from pso_pad import call
    return call("/api/sessions/%s/rpc" % pad.sid, {"op": "state", "args": {}}, "POST") or {}


def write_position(pad, point) -> str:
    from pso_pad import call
    player = state(pad).get("player") or {}
    pointer = player.get("ptr")
    if not pointer:
        return "no player pointer"
    job = call("/api/jobs", {"tool": "write_memory", "require_worker": pad.worker,
                             "input": {"session_id": pad.sid, "address": int(pointer, 16) + 0x38,
                                       "hex_bytes": struct.pack(">fff", *point).hex()}}, "POST")
    job_id = job.get("id") if isinstance(job, dict) else None
    for _ in range(15):
        time.sleep(1)
        row = call("/api/jobs/" + job_id) if job_id else {}
        if row.get("state") in ("succeeded", "failed", "cancelled"):
            return str(row.get("state")) + ("" if row.get("state") == "succeeded"
                                            else ": " + str(row.get("error"))[:80])
    return "timeout"


def tap(pad, key):
    pad.send([{"key": key, "down": True}, {"key": key, "down": False}])


if __name__ == "__main__":
    from pso_pad import Pad, call
    corridor = build()
    pad = Pad()
    print("session:", pad.sid)

    player = state(pad).get("player") or {}
    print("start:", (player.get("x"), player.get("z")), "room", player.get("room"),
          "| entities", len(state(pad).get("entities") or []))

    print("\n1) write into the corridor region")
    print("   ", write_position(pad, CORRIDOR_WRITE))
    time.sleep(1.5)
    player = state(pad).get("player") or {}
    here = (float(player.get("x") or 0), float(player.get("z") or 0))
    cell = corridor.cell(here)
    print(f"    landed ({here[0]:.1f},{here[1]:.1f}) cell {cell} safe={cell in corridor.safe}")

    if cell not in corridor.safe:
        print("    not on the corridor; trying the platform write directly")
        write_position(pad, PLATFORM_WRITE)
        time.sleep(1.5)

    print("\n2) write onto the warp platform and press A")
    print("   ", write_position(pad, PLATFORM_WRITE))
    time.sleep(2)
    for attempt in range(3):
        tap(pad, "a")
        time.sleep(4)
        player = state(pad).get("player") or {}
        room = player.get("room")
        count = len(state(pad).get("entities") or [])
        print(f"    A {attempt + 1}: room {room} | entities {count}")
        if count and count > 50:
            print("\n    IN A FIELD (entity count jumped)")
            break

    entities = state(pad).get("entities") or []
    kinds = sorted({str(e.get("kind")) for e in entities})
    print(f"\nfinal: {len(entities)} entities | kinds {kinds}")
    print("shot:", pad.shot("field_again"))

    if len(entities) > 50:
        print("\n3) starting autoplay")
        job = call("/api/jobs", {"tool": "autoplay", "require_worker": pad.worker,
                                 "input": {"session_id": pad.sid, "op": "start"}}, "POST")
        job_id = job.get("id") if isinstance(job, dict) else None
        for _ in range(15):
            time.sleep(2)
            row = call("/api/jobs/" + job_id) if job_id else {}
            if row.get("state") in ("succeeded", "failed", "cancelled"):
                print("   autoplay:", row.get("state"),
                      json.dumps((row.get("output") or {}).get("result"))[:180])
                break
    else:
        print("\nstill in the city - the warp did not take")
