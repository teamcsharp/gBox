"""Start autoplay in the Forest and measure what it does.

The city could never satisfy `explore` - it needs doors to walk to and enemies to fight. The Forest has both: 85 entities including `gate` kind (`TLazerFenceSw`,
`TOBarrierEnergy01`) and enemies on the minimap. So this is the first place the app's own autoplay has a chance to play the game the way it was written to.
"""
import json
import time

from pso_pad import Pad, call

if __name__ == "__main__":
    pad = Pad()
    print("session:", pad.sid)

    job = call("/api/jobs", {"tool": "autoplay", "require_worker": pad.worker,
                             "input": {"session_id": pad.sid, "op": "start"}}, "POST")
    job_id = job.get("id") if isinstance(job, dict) else None
    for _ in range(12):
        time.sleep(2)
        row = call("/api/jobs/" + job_id) if job_id else {}
        if row.get("state") in ("succeeded", "failed", "cancelled"):
            print("autoplay:", row.get("state"), json.dumps((row.get("output") or {}).get("result"))[:220])
            break

    time.sleep(4)
    spots = []
    for index in range(10):
        time.sleep(3)
        state = call("/api/sessions/%s/rpc" % pad.sid, {"op": "state", "args": {"player_only": True}}, "POST") or {}
        player = state.get("player") or {}
        spot = (round(float(player.get("x") or 0), 1), round(float(player.get("z") or 0), 1))
        spots.append(spot)
        print("  %d: %s hp %s" % (index + 1, spot, player.get("hp")))

    moved = sum(abs(a[0] - b[0]) + abs(a[1] - b[1]) for a, b in zip(spots, spots[1:]))
    print()
    print("MOVEMENT:", round(moved, 1), "units over 30s")

    status = call("/api/jobs", {"tool": "autoplay", "require_worker": pad.worker,
                                "input": {"session_id": pad.sid, "op": "status"}}, "POST")
    status_id = status.get("id") if isinstance(status, dict) else None
    for _ in range(10):
        time.sleep(1.5)
        row = call("/api/jobs/" + status_id) if status_id else {}
        if row.get("state") in ("succeeded", "failed", "cancelled"):
            print("autoplay status:", json.dumps((row.get("output") or {}).get("result"))[:400])
            break
    print("shot:", pad.shot("autoplay_forest"))
