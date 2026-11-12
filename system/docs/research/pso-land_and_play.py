"""Wait for the warp to land, confirm a field, and hand it to autoplay.

The warp from `(361.2, 28.8)` - three units from the platform centre, the fifth safe cell of the disc's own mesh near it - produced room 1 with 130 entities, which is a
field rather than the city's 31. This waits for the landing, reports what kind of place it is, starts the app's autoplay, and measures whether it plays.
"""
import json
import time

from pso_pad import Pad, call


def snapshot(pad):
    return call("/api/sessions/%s/rpc" % pad.sid, {"op": "state", "args": {}}, "POST") or {}


if __name__ == "__main__":
    pad = Pad()
    print("session:", pad.sid)

    landed = None
    for index in range(12):
        time.sleep(3)
        state = snapshot(pad)
        player = state.get("player") or {}
        entities = state.get("entities") or []
        kinds = sorted({str(e.get("kind")) for e in entities})
        print(f"  {index + 1}: room {player.get('room')} | ({player.get('x')},{player.get('z')}) "
              f"| {len(entities)} entities | {kinds}")
        if player and len(entities) > 50:
            landed = state
            break

    if not landed:
        print("\nnever landed in a field")
        print("shot:", pad.shot("landing_failed"))
        raise SystemExit(1)

    entities = landed.get("entities") or []
    gates = [e for e in entities if str(e.get("kind")) == "gate"]
    print(f"\nIN A FIELD: {len(entities)} entities, {len(gates)} gates")
    print("shot:", pad.shot("field_landing"))

    print("\nstarting autoplay")
    job = call("/api/jobs", {"tool": "autoplay", "require_worker": pad.worker,
                             "input": {"session_id": pad.sid, "op": "start"}}, "POST")
    job_id = job.get("id") if isinstance(job, dict) else None
    for _ in range(15):
        time.sleep(2)
        row = call("/api/jobs/" + job_id) if job_id else {}
        if row.get("state") in ("succeeded", "failed", "cancelled"):
            print("  autoplay:", row.get("state"), json.dumps((row.get("output") or {}).get("result"))[:200])
            break

    time.sleep(4)
    spots = []
    for index in range(8):
        time.sleep(3)
        player = snapshot(pad).get("player") or {}
        spot = (round(float(player.get("x") or 0), 1), round(float(player.get("z") or 0), 1))
        spots.append(spot)
        print(f"  {index + 1}: {spot} hp {player.get('hp')}")
    moved = sum(abs(a[0] - b[0]) + abs(a[1] - b[1]) for a, b in zip(spots, spots[1:]))
    print(f"\nMOVEMENT: {moved:.1f} units over 24 s")

    status = call("/api/jobs", {"tool": "autoplay", "require_worker": pad.worker,
                                "input": {"session_id": pad.sid, "op": "status"}}, "POST")
    status_id = status.get("id") if isinstance(status, dict) else None
    for _ in range(10):
        time.sleep(1.5)
        row = call("/api/jobs/" + status_id) if status_id else {}
        if row.get("state") in ("succeeded", "failed", "cancelled"):
            print("autoplay status:", json.dumps((row.get("output") or {}).get("result"))[:300])
            break
    print("shot:", pad.shot("autoplay_field"))
