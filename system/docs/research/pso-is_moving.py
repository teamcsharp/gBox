"""Is the character moving right now? If it is, a live-coordinate navigation grid can be recorded.

Live positions need no room transform, which is what blocks the disc maps. `operator-walk-summary` already proved the method: 2316 samples gave 1163 cells and 1221
edges, fully connected. So the question is only whether there is motion to record now.

Samples the player for a few seconds and reports the travelled distance, the extent, and how many distinct 8-unit cells the trail covers - the same resolution the
existing recorded walk used.
"""
import json
import math
import sys
import time
import urllib.request

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
SIZE = 8.0


def rpc(sid, op, args, timeout=30):
    request = urllib.request.Request(
        "http://127.0.0.1:18765/api/sessions/%s/rpc" % sid,
        data=json.dumps({"op": op, "args": args}).encode(), method="POST",
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent", "content-type": "application/json"})
    return json.loads(urllib.request.urlopen(request, timeout=timeout).read() or b"null")


if __name__ == "__main__":
    sessions = json.loads(urllib.request.urlopen(urllib.request.Request(
        "http://127.0.0.1:18765/api/sessions",
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent"}), timeout=20).read())
    sessions = sessions if isinstance(sessions, list) else (sessions.get("items") or [])
    live = [row for row in sessions if row.get("state") in ("running", "starting")]
    print("live sessions:", len(live))
    if not live:
        raise SystemExit("no live session")
    sid = live[0]["session_id"]

    trail = []
    for _ in range(24):
        player = (rpc(sid, "state", {"player_only": True}) or {}).get("player") or {}
        if "x" in player and "z" in player:
            trail.append((player["x"], player["z"]))
        time.sleep(0.25)

    if len(trail) < 2:
        raise SystemExit("could not sample")
    length = sum(math.dist(a, b) for a, b in zip(trail, trail[1:]))
    cells = {(math.floor(x / SIZE), math.floor(z / SIZE)) for x, z in trail}
    print(f"\nsamples: {len(trail)}")
    print(f"travelled: {length:.1f} units")
    print(f"extent: x {min(p[0] for p in trail):.0f}..{max(p[0] for p in trail):.0f}  "
          f"z {min(p[1] for p in trail):.0f}..{max(p[1] for p in trail):.0f}")
    print(f"distinct {SIZE:.0f}-unit cells: {len(cells)}")
    print("\nVERDICT:", "moving - a grid can be recorded" if length > 20 else "stationary - nothing to record")
