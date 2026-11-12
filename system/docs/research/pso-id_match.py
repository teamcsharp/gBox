"""Pair live entities to their placements by id, which gives the room transform exactly.

Every earlier attempt to find the room offset was positional, and positional matching is hopeless here: a stationary player gives one sample, the shared room 50 appears
in five layouts, and matching all entities dilutes the vote. But the placements carry ids - `set_id` values like 198488, 198489, 198490, increasing one per record -
and if the game stores that id on the live object, then one entity/placement pair gives the offset exactly, with no statistics at all.

So: take room 50's 21 placements, then scan each live entity's struct for any of those ids. A match is an identity, and `entity_position - placement_position` is the
room's world offset. Several matches must agree, which also validates the result.
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
TABLE, COUNT, POS, STRUCT = 0x8050D460, 256, 0x38, 0x340
ROOM = 50
SCAN = 0x120                      # how far into the entity to look for the id


def rpc(sid, op, args, timeout=30):
    request = urllib.request.Request(
        "http://127.0.0.1:18765/api/sessions/%s/rpc" % sid,
        data=json.dumps({"op": op, "args": args}).encode(), method="POST",
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent", "content-type": "application/json"})
    return json.loads(urllib.request.urlopen(request, timeout=timeout).read() or b"null")


def read(sid, address, length):
    try:
        return bytes.fromhex(rpc(sid, "read_memory", {"address": address, "length": length}))
    except Exception:                                             # noqa: BLE001
        return b""


if __name__ == "__main__":
    sessions = json.loads(urllib.request.urlopen(urllib.request.Request(
        "http://127.0.0.1:18765/api/sessions",
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent"}), timeout=20).read())
    sessions = sessions if isinstance(sessions, list) else (sessions.get("items") or [])
    sid = next(row["session_id"] for row in sessions if row.get("state") in ("running", "starting"))

    disc = gcdisc.GCDisc(DISC)
    recs = [r for r in pso_setdata.records(disc.read("map_cave01_00d.dat")) if r.get("amount") == ROOM]
    print(f"room {ROOM}: {len(recs)} placements")
    by_set = {}
    by_group = {}
    for rec in recs:
        if isinstance(rec.get("set_id"), int):
            by_set[rec["set_id"]] = rec
        if isinstance(rec.get("group_id"), int):
            by_group[rec["group_id"]] = rec
    print("  set_ids:", sorted(by_set)[:6], "...")
    print("  group_ids:", sorted(by_group)[:6], "...")

    blob = read(sid, TABLE, COUNT * 4)
    pointers = [p for p in struct.unpack(">%dI" % COUNT, blob) if 0x80000000 <= p < 0x81800000]
    print(f"\nlive entities: {len(pointers)}")

    matches = []
    for pointer in pointers:
        head = read(sid, pointer, SCAN)
        if len(head) != SCAN:
            continue
        body = read(sid, pointer + POS, 12)
        if len(body) != 12:
            continue
        ex, ey, ez = struct.unpack(">fff", body)
        for offset in range(0, SCAN - 3, 4):
            value = struct.unpack_from(">I", head, offset)[0]
            rec = by_set.get(value) or by_group.get(value)
            if rec is None:
                continue
            dx, dz = ex - rec["x"], ez - rec["z"]
            matches.append((pointer, offset, value, "set" if value in by_set else "group",
                            round(dx, 1), round(dz, 1), ex, ez, rec["x"], rec["z"]))
            break

    print(f"entities whose struct contains a room-{ROOM} id: {len(matches)}")
    for row in matches[:12]:
        pointer, offset, value, kind, dx, dz, ex, ez, px, pz = row
        print(f"  0x{pointer:08X} +0x{offset:03X} {kind} {value}  offset=({dx:.0f}, {dz:.0f})  "
              f"entity ({ex:.0f}, {ez:.0f}) placement ({px:.0f}, {pz:.0f})")

    if not matches:
        raise SystemExit("\nno entity carried a room-50 id - the link is not stored on the object")

    offsets = collections.Counter((row[4], row[5]) for row in matches)
    print("\nagreement on the offset:")
    for (dx, dz), count in offsets.most_common(6):
        print(f"  ({dx:.0f}, {dz:.0f})  {count} entities")

    (bx, bz), count = offsets.most_common(1)[0]
    print(f"\nVERDICT: offset ({bx:.0f}, {bz:.0f}) from {count} id-matched entities")
    player = (rpc(sid, "state", {"player_only": True}) or {}).get("player") or {}
    print(f"  player ({player['x']:.0f}, {player['z']:.0f}) -> room-local "
          f"({player['x'] - bx:.0f}, {player['z'] - bz:.0f})")
