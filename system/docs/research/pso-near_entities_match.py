"""Match only the entities near the player against room 50's placements.

The previous attempt used all 125 live entities against room 50's 21 placements and got 6 coincidences. That is the wrong comparison: most of those entities are in
**other rooms**, so they cannot agree on room 50's offset and they swamp the vote.

The player is in room 50, so its objects are the ones nearby. Filtering the entities to a radius around the player before voting leaves only candidates that could
belong to this room, which makes the answer sharp instead of diluted.

If a consistent offset appears, it applies to the room the player is in - the offset that disc collision needs.
"""
import collections
import json
import math
import struct
import sys
import urllib.request

sys.path.insert(0, r"C:\_tools\gBox\.tmp")
sys.path.insert(0, r"C:\_tools\gBox\system")

from gbox import gcdisc, pso_setdata                             # noqa: E402

DISC = r"D:\gBox\cache\436e0bb84d5337d1\Phantasy Star Online Episode I & II Plus (USA).gcz"
TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
TABLE, COUNT, POS = 0x8050D460, 256, 0x38
ROOM = 50
RADIUS = 220.0
BINS = (64.0, 32.0, 16.0)


def rpc(sid, op, args):
    request = urllib.request.Request(
        "http://127.0.0.1:18765/api/sessions/%s/rpc" % sid,
        data=json.dumps({"op": op, "args": args}).encode(), method="POST",
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent", "content-type": "application/json"})
    return json.loads(urllib.request.urlopen(request, timeout=30).read() or b"null")


def read(sid, address, length):
    try:
        return bytes.fromhex(rpc(sid, "read_memory", {"address": address, "length": length}))
    except Exception:                                              # noqa: BLE001
        return b""


if __name__ == "__main__":
    sessions = json.loads(urllib.request.urlopen(urllib.request.Request(
        "http://127.0.0.1:18765/api/sessions",
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent"}), timeout=20).read())
    sessions = sessions if isinstance(sessions, list) else (sessions.get("items") or [])
    sid = next(row["session_id"] for row in sessions if row.get("state") in ("running", "starting"))

    player = (rpc(sid, "state", {"player_only": True}) or {}).get("player") or {}
    px, pz = player["x"], player["z"]
    print(f"player ({px:.1f}, {pz:.1f}) room={player.get('room')} y={player.get('y'):.2f}")

    blob = read(sid, TABLE, COUNT * 4)
    pointers = [p for p in struct.unpack(">%dI" % COUNT, blob) if 0x80000000 <= p < 0x81800000]
    all_live = []
    for pointer in pointers:
        body = read(sid, pointer + POS, 12)
        if len(body) == 12:
            x, y, z = struct.unpack(">fff", body)
            if all(abs(v) < 100000 for v in (x, y, z)):
                all_live.append((x, z))
    near = [(x, z) for (x, z) in all_live if math.dist((x, z), (px, pz)) <= RADIUS]
    print(f"entities: {len(all_live)} total, {len(near)} within {RADIUS:.0f} units of the player")
    for spot in sorted(near, key=lambda p: math.dist(p, (px, pz)))[:12]:
        print(f"   ({spot[0]:8.1f}, {spot[1]:8.1f})  d={math.dist(spot, (px, pz)):6.1f}")

    disc = gcdisc.GCDisc(DISC)
    places = [(r["x"], r["z"]) for r in pso_setdata.records(disc.read("map_cave01_00d.dat"))
              if r.get("amount") == ROOM and isinstance(r.get("x"), (int, float))]
    print(f"\nroom {ROOM} placements: {len(places)}")
    print("  x range", round(min(p[0] for p in places), 1), "..", round(max(p[0] for p in places), 1),
          "| z range", round(min(p[1] for p in places), 1), "..", round(max(p[1] for p in places), 1))

    print()
    best = None
    for bin_size in BINS:
        votes = collections.Counter()
        for (ex, ez) in near:
            for (pxp, pzp) in places:
                votes[(round((ex - pxp) / bin_size), round((ez - pzp) / bin_size))] += 1
        if not votes:
            continue
        (bx, bz), count = votes.most_common(1)[0]
        ox, oz = bx * bin_size, bz * bin_size
        print(f"  bin {bin_size:4.0f}: offset ({ox:8.0f}, {oz:8.0f}) votes={count} "
              f"of {len(near) * len(places)} pairs")
        if best is None or count > best[0]:
            best = (count, ox, oz, bin_size)

    if best:
        count, ox, oz, bin_size = best
        local = (px - ox, pz - oz)
        print(f"\nbest: offset ({ox:.0f}, {oz:.0f}) at bin {bin_size:.0f}, {count} votes")
        print(f"player world ({px:.0f}, {pz:.0f}) -> room-local ({local[0]:.0f}, {local[1]:.0f})")
        print("is that inside room 50's placement box?",
              min(p[0] for p in places) - 100 <= local[0] <= max(p[0] for p in places) + 100 and
              min(p[1] for p in places) - 100 <= local[1] <= max(p[1] for p in places) + 100)
