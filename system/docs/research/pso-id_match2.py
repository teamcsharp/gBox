"""Pair entities to placements by a DISTINCTIVE id, excluding the null id that matched everything.

The previous run reported "125 entities carried a room-50 id" - which is obviously wrong, and the output showed why: every match was `set 0`. Zero is a valid
`set_id` in the record set (and a very common word in any object), so `by_set.get(0)` matched almost every entity and produced garbage offsets that disagreed.

The real set ids are large and distinctive (198488, 198489, 198490...). So this run only considers ids above 0x1000, requires at least two entities to agree on the
same offset before reporting one, and prints the ids that actually matched - so a second null-like trap is visible rather than silent.
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
SCAN = 0x140
MIN_ID = 0x1000                   # below this, ids are nulls or flags that appear everywhere


def rpc(sid, op, args, timeout=30):
    request = urllib.request.Request(
        "http://127.0.0.1:18765/api/sessions/%s/rpc" % sid,
        data=json.dumps({"op": op, "args": args}).encode(), method="POST",
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent", "content-type": "application/json"})
    return json.loads(urllib.request.urlopen(request, timeout=timeout).read() or b"null")


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

    disc = gcdisc.GCDisc(DISC)
    all_recs = pso_setdata.records(disc.read("map_cave01_00d.dat"))
    recs = [r for r in all_recs if r.get("amount") == ROOM]

    by_set, by_group = {}, {}
    for rec in recs:
        for key, table in (("set_id", by_set), ("group_id", by_group)):
            value = rec.get(key)
            if isinstance(value, int) and value >= MIN_ID:
                table[value] = rec
    print(f"room {ROOM}: {len(recs)} placements")
    print(f"  distinctive set ids:   {len(by_set)}  {sorted(by_set)[:6]}")
    print(f"  distinctive group ids: {len(by_group)}  {sorted(by_group)[:6]}")
    if not by_set and not by_group:
        raise SystemExit("no distinctive ids to match on")

    blob = read(sid, TABLE, COUNT * 4)
    pointers = [p for p in struct.unpack(">%dI" % COUNT, blob) if 0x80000000 <= p < 0x81800000]
    print(f"\nlive entities: {len(pointers)}")

    matches = []
    for pointer in pointers:
        head = read(sid, pointer, SCAN)
        body = read(sid, pointer + POS, 12)
        if len(head) != SCAN or len(body) != 12:
            continue
        ex, ey, ez = struct.unpack(">fff", body)
        for offset in range(0, SCAN - 3, 4):
            value = struct.unpack_from(">I", head, offset)[0]
            rec = by_set.get(value) or by_group.get(value)
            if rec is None:
                continue
            matches.append((pointer, offset, value, round(ex - rec["x"], 1), round(ez - rec["z"], 1),
                            round(ex, 1), round(ez, 1), round(rec["x"], 1), round(rec["z"], 1)))
            break

    print(f"entities carrying a distinctive room-{ROOM} id: {len(matches)}")
    for pointer, offset, value, dx, dz, ex, ez, px, pz in matches[:14]:
        print(f"  0x{pointer:08X} +0x{offset:03X} id {value:6d}  offset=({dx:8.1f}, {dz:8.1f})  "
              f"entity ({ex:7.1f},{ez:8.1f}) placement ({px:7.1f},{pz:8.1f})")

    if not matches:
        raise SystemExit("\nno entity carried a distinctive room id - the link is not stored on the object")

    # cluster offsets within 12 units, since float position is exact but the pairing may be one of several
    buckets = collections.Counter((round(row[3] / 12.0), round(row[4] / 12.0)) for row in matches)
    (bx, bz), count = buckets.most_common(1)[0]
    print("\noffset clusters (12-unit):")
    for (ux, uz), n in buckets.most_common(5):
        print(f"  ({ux * 12:8.0f}, {uz * 12:8.0f})  {n} entities")
    print(f"\nbest cluster ({bx * 12:.0f}, {bz * 12:.0f}) from {count} entities")
    if count < 2:
        print("NOTE: only one entity agrees - this is a coincidence, not a transform")
    else:
        exact = [row for row in matches if round(row[3] / 12.0) == bx and round(row[4] / 12.0) == bz]
        mx = sum(row[3] for row in exact) / len(exact)
        mz = sum(row[4] for row in exact) / len(exact)
        player = (rpc(sid, "state", {"player_only": True}) or {}).get("player") or {}
        print(f"mean offset ({mx:.1f}, {mz:.1f}) over {len(exact)} matches")
        print(f"  player ({player['x']:.0f}, {player['z']:.0f}) -> room-local "
              f"({player['x'] - mx:.0f}, {player['z'] - mz:.0f})")
