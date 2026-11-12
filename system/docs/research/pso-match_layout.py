"""Identify the loaded cave layout and its offset by matching live entities to placement records.

Floor 3 is `map_cave01` with six layouts, and the player's position falls outside all of them because a room is translated when it loads. The placements are the
way to resolve it: the live entity table holds objects at world positions, and a layout's set data lists where its objects belong. If the layout is the loaded one,
many entities share one consistent offset - the mode of (entity - placement) - and a wrong layout has no such consensus.

This extracts each cave layout's set data from the owned disc, reads the live entity positions, and scores every layout by how many entities land on a placement
under one shared offset. The winner is the loaded layout, and its offset is what path-guiding needs.
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
LAYOUTS = [f"map_cave01_0{i}" for i in range(6)]
BIN = 24.0                    # offset vote granularity, in world units


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

    blob = read(sid, TABLE, COUNT * 4)
    pointers = [p for p in struct.unpack(">%dI" % COUNT, blob) if 0x80000000 <= p < 0x81800000]
    live = []
    for pointer in pointers:
        body = read(sid, pointer + POS, 12)
        if len(body) == 12:
            x, y, z = struct.unpack(">fff", body)
            if all(abs(v) < 100000 for v in (x, y, z)):
                live.append((x, z))
    print(f"live entities with positions: {len(live)}")

    disc = gcdisc.GCDisc(DISC)
    names = set(disc.files)
    print("disc files:", len(names))

    best = None
    for layout in LAYOUTS:
        candidates = [n for n in names if n.endswith(f"{layout}d.dat") or n.endswith(f"{layout}ad.dat")]
        if not candidates:
            print(f"  {layout}: no set file on the disc")
            continue
        name = sorted(candidates)[0]
        try:
            data = disc.read(name)
        except Exception as exc:                                   # noqa: BLE001
            print(f"  {layout}: read failed {type(exc).__name__}")
            continue
        recs = pso_setdata.records(data)
        places = [(r["x"], r["z"]) for r in recs if all(isinstance(r.get(k), (int, float)) for k in ("x", "z"))]
        if not places:
            print(f"  {layout}: no placements")
            continue

        votes = collections.Counter()
        for (ex, ez) in live:
            for (px, pz) in places:
                votes[(round((ex - px) / BIN), round((ez - pz) / BIN))] += 1
        (bx, bz), count = votes.most_common(1)[0]
        print(f"  {layout:16s} {name:22s} placements={len(places):4d} best offset=({bx * BIN:.0f}, {bz * BIN:.0f}) votes={count}")
        if best is None or count > best[0]:
            best = (count, layout, name, bx * BIN, bz * BIN, len(places))

    if best:
        count, layout, name, ox, oz, total = best
        print(f"\nVERDICT: loaded layout is {layout} (from {name})")
        print(f"  offset ({ox:.0f}, {oz:.0f}) explains {count} entity-placement coincidences out of {len(live)} entities")
        print(f"  player world (-188, -729) -> room-local ({-188 - ox:.0f}, {-729 - oz:.0f})")
