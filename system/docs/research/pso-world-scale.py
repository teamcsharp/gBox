"""How big is the live world compared with one room's collision? That settles the transform question.

The entity fit failed for a clear reason visible in the numbers: the 125 entities have a centroid of (1421, -791), while `cave01_00`'s collision bounds are
(-44,-214)..(315,43). No offset can put a world that wide inside one room's geometry.

This measures the spread of the live entities and compares it with the collision bounds of the layouts, which decides the model: if the world is many times one room's
size, then a layout is a set of room instances placed far apart, each with its own offset - and a single room's collision file cannot cover it.
"""
import json
import struct
import sys
import urllib.request

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
TABLE, COUNT, POS = 0x8050D460, 256, 0x38
ROUTES = r"D:\gBox\pso-ds\routes"
LAYOUTS = [f"map_cave01_0{i}" for i in range(6)]


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

    blob = read(sid, TABLE, COUNT * 4)
    pointers = [p for p in struct.unpack(">%dI" % COUNT, blob) if 0x80000000 <= p < 0x81800000]
    entities = []
    for pointer in pointers:
        body = read(sid, pointer + POS, 12)
        if len(body) == 12:
            x, y, z = struct.unpack(">fff", body)
            if all(abs(v) < 100000 for v in (x, y, z)):
                entities.append((x, z))

    xs = [e[0] for e in entities]
    zs = [e[1] for e in entities]
    span_x, span_z = max(xs) - min(xs), max(zs) - min(zs)
    print(f"live entities: {len(entities)}")
    print(f"  x {min(xs):8.0f} .. {max(xs):8.0f}   span {span_x:7.0f}")
    print(f"  z {min(zs):8.0f} .. {max(zs):8.0f}   span {span_z:7.0f}")

    print("\ncollision bounds per layout:")
    areas = []
    for layout in LAYOUTS:
        try:
            data = json.load(open(f"{ROUTES}\\{layout}c-mesh.json", encoding="utf-8"))
        except Exception:                                          # noqa: BLE001
            continue
        (x0, z0), (x1, z1) = data["bounds"]
        areas.append((layout, x1 - x0, z1 - z0))
        print(f"  {layout:16s} {x1 - x0:6.0f} x {z1 - z0:6.0f}")

    room_area = sum(w * h for _, w, h in areas) / max(len(areas), 1)
    world_area = span_x * span_z
    print(f"\nmean room footprint: {room_area:,.0f} sq units")
    print(f"live world extent:   {world_area:,.0f} sq units")
    print(f"ratio:               {world_area / room_area:.1f}x one room")

    print("\n=== does any layout bounds contain the entity spread? ===")
    for layout, _, _ in areas:
        data = json.load(open(f"{ROUTES}\\{layout}c-mesh.json", encoding="utf-8"))
        (x0, z0), (x1, z1) = data["bounds"]
        inside = sum(1 for (x, z) in entities if x0 <= x <= x1 and z0 <= z <= z1)
        print(f"  {layout:16s} contains {inside:3d} of {len(entities)} entities")

    print("\nVERDICT:", "the world is many rooms wide, so a layout is a set of placed room instances "
          "and one room's collision cannot cover it" if world_area > room_area * 3
          else "the world fits within a room's scale - the model needs revisiting")
