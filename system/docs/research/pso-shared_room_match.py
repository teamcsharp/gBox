"""Room 50 is a shared room: 21 placements, present in five of the six cave layouts.

That explains the degenerate vote exactly. Matching all ~200 placements of a layout lets the shared room 50 dominate, so every layout answers with the same
offset. Room 50's own 21 placements are the specific evidence - if they are byte-identical across layouts, they describe the room the player is standing in
regardless of which layout surrounds it, and matching **only those** gives a clean offset.

Then, with the offset known, the player's position can be tested against each layout's collision bounds: the layout whose bounds contain it is the loaded one.
"""
import collections
import json
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
BIN = 16.0


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
    disc = gcdisc.GCDisc(DISC)
    names = set(disc.files)

    # 1. are room 50's placements the same in every layout that has it?
    signatures = {}
    for index in range(6):
        for suffix in ("d.dat", "ad.dat"):
            name = f"map_cave01_0{index}{suffix}"
            if name not in names:
                continue
            recs = pso_setdata.records(disc.read(name))
            mine = [(round(r["x"], 1), round(r["z"], 1), r.get("kind")) for r in recs if r.get("amount") == ROOM]
            signatures[name] = sorted(mine)

    print("room 50 placement sets:")
    first = None
    for name, mine in signatures.items():
        tag = ""
        if first is None:
            first = mine
        elif mine == first:
            tag = "  (identical to the first)"
        else:
            tag = "  (DIFFERS)"
        print(f"  {name:24s} {len(mine):3d} placements{tag}")

    places = signatures.get("map_cave01_00d.dat") or next(iter(signatures.values()))
    print(f"\nusing {len(places)} room-50 placements")

    # 2. live entities
    sessions = json.loads(urllib.request.urlopen(urllib.request.Request(
        "http://127.0.0.1:18765/api/sessions",
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent"}), timeout=20).read())
    sessions = sessions if isinstance(sessions, list) else (sessions.get("items") or [])
    sid = next(row["session_id"] for row in sessions if row.get("state") in ("running", "starting"))
    blob = read(sid, TABLE, COUNT * 4)
    pointers = [p for p in struct.unpack(">%dI" % COUNT, blob) if 0x80000000 <= p < 0x81800000]
    live = []
    for pointer in pointers:
        body = read(sid, pointer + POS, 12)
        if len(body) == 12:
            x, y, z = struct.unpack(">fff", body)
            if all(abs(v) < 100000 for v in (x, y, z)):
                live.append((x, z))
    print(f"live entities: {len(live)}")

    votes = collections.Counter()
    for (ex, ez) in live:
        for (px, pz, _kind) in places:
            votes[(round((ex - px) / BIN), round((ez - pz) / BIN))] += 1
    (bx, bz), count = votes.most_common(1)[0]
    ox, oz = bx * BIN, bz * BIN
    print(f"\nbest offset ({ox:.0f}, {oz:.0f}) with {count} coincidences")

    player = (rpc(sid, "state", {"player_only": True}) or {}).get("player") or {}
    px, pz = player["x"] - ox, player["z"] - oz
    print(f"player world ({player['x']:.0f}, {player['z']:.0f}) -> room-local ({px:.0f}, {pz:.0f})")

    print("\nwhich layout's collision bounds contain that point?")
    from pathlib import Path
    routes = Path(r"D:\gBox\pso-ds\routes")
    for index in range(6):
        path = routes / f"map_cave01_0{index}c-mesh.json"
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        (x0, z0), (x1, z1) = data["bounds"]
        inside = x0 <= px <= x1 and z0 <= pz <= z1
        print(f"  map_cave01_0{index}  ({x0}, {z0})..({x1}, {z1})  contains: {inside}")
