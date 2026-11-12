"""Why the bot stands there taking hits: the semantic state contains one entity - the player.

`state` returned `entities: 1`, the player alone, so nothing in the bot can know an enemy exists, let alone where it is. The game keeps a live entity table at
`0x8050D460` (256 pointers, struct 0x340). This walks it and reports every slot that holds a plausible object: pointer, vtable, position, HP, and the class name
if the registry knows the vtable.

The comparison matters: if the table holds enemies the state reader is dropping, the fix is in the reader; if it is empty, the table address is wrong for this
build.
"""
import json
import struct
import sys
import urllib.request

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S                                                # noqa: E402

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
TABLE = 0x8050D460
COUNT = 256
STRUCT = 0x340
POS = 0x38
HP = 0x330            # profile "hp" for PSO GC players (autoplay._hold_hp uses 0x330)
ANGLE = 0x44          # candidate facing float - reported, not trusted


def rpc(sid, op, args):
    request = urllib.request.Request(
        "http://127.0.0.1:18765/api/sessions/%s/rpc" % sid,
        data=json.dumps({"op": op, "args": args}).encode(), method="POST",
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent", "content-type": "application/json"})
    return json.loads(urllib.request.urlopen(request, timeout=30).read() or b"null")


def read(sid, address, length):
    raw = rpc(sid, "read_memory", {"address": address, "length": length})
    try:
        return bytes.fromhex(raw)
    except Exception:                                             # noqa: BLE001
        return b""


if __name__ == "__main__":
    rows = json.loads(urllib.request.urlopen(urllib.request.Request(
        "http://127.0.0.1:18765/api/sessions",
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent"}), timeout=20).read())
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    sid = next(row["session_id"] for row in rows if row.get("state") in ("running", "starting"))
    print("session:", sid)

    blob = read(sid, TABLE, COUNT * 4)
    print("table bytes:", len(blob))
    if len(blob) != COUNT * 4:
        raise SystemExit("could not read the entity table")

    pointers = struct.unpack(">%dI" % COUNT, blob)
    live = [(index, pointer) for index, pointer in enumerate(pointers)
            if 0x80000000 <= pointer < 0x81800000]
    print(f"non-null pointers: {len(live)} of {COUNT}")

    print("\nslot  pointer     vtable      x        y        z        hp")
    rows_out = []
    for index, pointer in live[:40]:
        head = read(sid, pointer, 0x20 + 16)
        if len(head) < 0x24:
            continue
        vtable = struct.unpack_from(">I", head, 0x18)[0] if len(head) >= 0x1C else 0
        body = read(sid, pointer + POS, 12)
        if len(body) != 12:
            continue
        x, y, z = struct.unpack(">fff", body)
        hp_raw = read(sid, pointer + HP, 2)
        hp = struct.unpack(">H", hp_raw)[0] if len(hp_raw) == 2 else -1
        sane = all(abs(v) < 100000 for v in (x, y, z))
        print(f"{index:4d}  0x{pointer:08X}  0x{vtable:08X}  {x:8.1f} {y:8.1f} {z:8.1f}  {hp:6d}"
              + ("" if sane else "   (implausible)"))
        rows_out.append({"slot": index, "ptr": pointer, "vtable": vtable, "x": x, "y": y, "z": z, "hp": hp})

    print("\ndistinct vtables:", sorted({hex(row["vtable"]) for row in rows_out}))
    print("plausible positions:", sum(1 for row in rows_out if all(abs(row[k]) < 100000 for k in ("x", "y", "z"))))
