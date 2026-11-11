"""CP17, fully integrated: receding-horizon flat route for the distance, and a door handler whenever a door is within reach.

Round 200 showed each phase works alone - the flat receding planner converges to ~140 units, and the door interaction produces a
56-unit jump - but neither finishes the run. This runs both in one loop: plan from the live position, walk three waypoints, and any
time a TObjDoor/TObjDoorKey is within 30 units, approach it, press A, push, and require the jump before continuing.
"""
import json
import math
import struct
import sys
import time
import urllib.request
import uuid
from collections import deque
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\system")
sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import capture_gbox_app as cap                                     # noqa: E402
from gbox import pso_kbwalk, psomap, pso_walk                      # noqa: E402
from gbox.adapters import win_send_keys                            # noqa: E402

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
API = "http://127.0.0.1:8765"
SID = "e731ee594dde4a89-cae9dad929a34d17"
PID = 37032
TABLE, MAX_ENTRIES = 0x8050D460, 256
FLOOR = 0x805D5FC0
REL = Path(r"D:\gBox\pso-ds\rel\map_forest01c.rel")
LOG = r"D:\gBox\pso-ds\cp17-full.log"
SIZE, STEP_LIMIT = 10.0, 2.5


def log(line):
    text = f"{time.strftime('%H:%M:%S')} {line}"
    print(text, flush=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(text + "\n")


def read(address, length):
    body = json.dumps({"op": "read_memory", "args": {"address": address, "length": length}}).encode()
    for attempt in range(4):
        try:
            req = urllib.request.Request(f"{API}/api/sessions/{SID}/rpc", data=body, method="POST",
                                         headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent",
                                                  "content-type": "application/json"})
            return bytes.fromhex(json.loads(urllib.request.urlopen(req, timeout=12).read() or b'""'))
        except Exception:                                        # noqa: BLE001
            time.sleep(0.2)
    return b""


def controls(op, fields, timeout=90):
    body = {"op": "pso_controls", "args": {"command_id": str(uuid.uuid4()), "expires": time.time() + 5,
                                          "input": {"session_id": SID, "op": op, **fields}}}
    data = json.dumps(body).encode()
    req = urllib.request.Request(f"{API}/api/sessions/{SID}/rpc", data=data, method="POST",
                                 headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent",
                                          "content-type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=timeout).read() or b"null")
    except Exception as exc:                                     # noqa: BLE001
        return {"error": str(exc)[:120]}


def floor():
    return int.from_bytes(read(FLOOR, 4), "big")


def cstring(address, limit=40):
    raw = read(address, limit)
    return raw.split(b"\x00")[0].decode("ascii", "replace") if raw else ""


def entities(prefix):
    raw = read(TABLE, MAX_ENTRIES * 4)
    out = []
    for index in range(MAX_ENTRIES):
        pointer = int.from_bytes(raw[index * 4:index * 4 + 4], "big")
        if not (0x80000000 <= pointer < 0x81800000):
            continue
        name_pointer = int.from_bytes(read(pointer, 4), "big")
        if not (0x80000000 <= name_pointer < 0x81800000):
            continue
        name = cstring(name_pointer)
        if not name.startswith(prefix):
            continue
        x, _y, z = struct.unpack(">fff", read(pointer + 0x38, 12))
        out.append({"class": name, "x": x, "z": z})
    return out


def read_pos():
    actor = int.from_bytes(read(0x8050EA10, 4), "big")
    if not actor:
        return None
    x, _y, z = struct.unpack(">fff", read(actor + 0x38, 12))
    return x, z


def gbox_hwnd():
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _l):
        if not user32.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        if buf.value.strip() == "gBox":
            found.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return found[0] if found else None


def send(events):
    import ctypes
    user32 = ctypes.windll.user32
    hwnd = gbox_hwnd()
    if hwnd:
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.05)
    try:
        return win_send_keys(PID, events)
    except Exception:                                            # noqa: BLE001
        return {}


def hold(keys, seconds):
    if isinstance(keys, str):
        keys = [keys]
    keys = list(keys)
    send([{"key": k, "down": True} for k in keys])
    time.sleep(seconds)
    send([{"key": k, "down": False} for k in keys])
    time.sleep(0.04)


def tap(key, times=1, gap=0.4):
    for _ in range(times):
        send([{"key": key, "down": True}, {"key": key, "down": False}])
        time.sleep(gap)


def build_flat(collision):
    tris = psomap.collision(collision)
    floors, walls = pso_walk.cells(collision)
    walkable = floors - walls
    heights = {}
    for (a, b, c, flags, normal) in tris:
        if flags & psomap.TRIGGER_FLAG or normal[1] <= 0.6:
            continue
        xs, zs = (a[0], b[0], c[0]), (a[2], b[2], c[2])
        for i in range(int(math.floor(min(xs) / SIZE)), int(math.floor(max(xs) / SIZE)) + 1):
            for j in range(int(math.floor(min(zs) / SIZE)), int(math.floor(max(zs) / SIZE)) + 1):
                px, pz = (i + 0.5) * SIZE, (j + 0.5) * SIZE
                if psomap._inside(px, pz, a, b, c):
                    y = psomap._height(px, pz, a, b, c)
                    heights[(i, j)] = max(heights.get((i, j), -1e9), y)
    flat = set()
    for cell in walkable:
        height = heights.get(cell)
        if height is None:
            continue
        worst = 0.0
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            neighbour = (cell[0] + dx, cell[1] + dz)
            if neighbour in walkable:
                other = heights.get(neighbour)
                if other is not None:
                    worst = max(worst, abs(other - height))
        if worst <= STEP_LIMIT:
            flat.add(cell)
    return flat


def route_from(flat, start, goal_cell):
    if not flat:
        return []
    start_cell = min(flat, key=lambda c: math.dist(pso_walk.cell_centre(c), start))
    queue = deque([start_cell])
    previous = {start_cell: None}
    found = False
    while queue:
        cell = queue.popleft()
        if cell == goal_cell:
            found = True
            break
        x, z = cell
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            neighbour = (x + dx, z + dz)
            if neighbour in flat and neighbour not in previous:
                previous[neighbour] = cell
                queue.append(neighbour)
    if not found:
        return []
    route = []
    cell = goal_cell
    while cell is not None:
        route.append(pso_walk.cell_centre(cell))
        cell = previous[cell]
    route.reverse()
    return route


def try_door(door):
    me = read_pos()
    log(f"  door {door['class']} at ({door['x']:.0f},{door['z']:.0f}) dist={math.dist(me, (door['x'], door['z'])):.0f}")
    for attempt in range(3):
        tap("a", 1, 0.6)
        before = read_pos()
        hold("up", 1.1)
        after = read_pos()
        moved = math.dist(before, after)
        log(f"    attempt {attempt}: moved {moved:.0f} -> {tuple(round(v,1) for v in after)} floor={floor()}")
        if moved > 8:
            return True
    return False


def main(budget=840.0):
    log("=== CP17 integrated route+doors")
    if floor() != 1:
        controls("floor_warp", {"target": "1"})
        time.sleep(10)
    controls("stat", {"name": "atp", "value": 999})
    tap("b", 2, 0.5)
    collision = REL.read_bytes()
    flat = build_flat(collision)
    key_doors = entities("TObjDoorKey")
    if not key_doors:
        log("no key doors")
        return 2
    key_goal = min(((d["x"], d["z"]) for d in key_doors), key=lambda g: math.dist(read_pos(), g))
    goal_cell = min(flat, key=lambda c: math.dist(pso_walk.cell_centre(c), key_goal))
    log(f"start {tuple(round(v,1) for v in read_pos())} key door {tuple(round(v,0) for v in key_goal)} "
        f"flat {len(flat)}")
    started = time.time()
    rounds = 0
    while time.time() - started < budget:
        if floor() != 1:
            log(f"FLOOR CHANGED: {floor()}")
            cap.main()
            return 0
        me = read_pos()
        distance = math.dist(me, key_goal)
        if distance <= 10:
            log("at the key door")
            try_door({"class": "TObjDoorKey", "x": key_goal[0], "z": key_goal[1]})
            cap.main()
            return 0 if floor() != 1 else 2
        near_doors = sorted((d for d in entities("TObjDoor") if math.dist(me, (d["x"], d["z"])) <= 30),
                            key=lambda d: math.dist(me, (d["x"], d["z"])))
        if near_doors:
            if try_door(near_doors[0]):
                log("  a door opened")
            rounds += 1
            continue
        route = route_from(flat, me, goal_cell)
        if not route:
            log("no flat route")
            return 2
        before = me
        try:
            pso_kbwalk.walk_path(read_pos, hold, [tuple(w) for w in route[:3]], tolerance=8.0)
        except RuntimeError as exc:
            log(f"  walk_path: {exc}")
        if math.dist(read_pos(), before) < 3:
            tap("b", 1, 0.3)
        rounds += 1
        if rounds % 5 == 0:
            log(f"  round {rounds}: {math.dist(read_pos(), key_goal):.0f} units, pos={tuple(round(v,1) for v in read_pos())}")
            cap.main()
    log(f"budget spent; {math.dist(read_pos(), key_goal):.0f} units from the key door")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
