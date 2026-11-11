"""CP17, final integrated attempt:
  1. warp to Forest 1 if needed, press B twice (the arrival pad blocks movement),
  2. flat route from the current position to the key door (level cells only),
  3. walk it chunk by chunk; on a stall, kill an adjacent Booma (boosted ATP) or press B if none,
  4. at the door press A once, push, and watch pso_ram.floor.
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
TABLE, MAX_ENTRIES, HP, HP_MAX = 0x8050D460, 256, 0x32C, 0x2B8
FLOOR = 0x805D5FC0
REL = Path(r"D:\gBox\pso-ds\rel\map_forest01c.rel")
LOG = r"D:\gBox\pso-ds\cp17-last.log"
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
        row = {"class": name, "x": x, "z": z}
        if prefix == "TObjEne":
            row["hp"] = int.from_bytes(read(pointer + HP, 2), "big")
        out.append(row)
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


def floor_heights(tris):
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
    return heights


def flat_route(collision, start, goal):
    tris = psomap.collision(collision)
    floors, walls = pso_walk.cells(collision)
    walkable = floors - walls
    heights = floor_heights(tris)
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
    if not flat:
        return []
    start_cell = min(flat, key=lambda c: math.dist(pso_walk.cell_centre(c), start))
    goal_cell = min(flat, key=lambda c: math.dist(pso_walk.cell_centre(c), goal))
    queue = deque([start_cell])
    previous = {start_cell: None}
    while queue:
        cell = queue.popleft()
        if cell == goal_cell:
            break
        x, z = cell
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            neighbour = (x + dx, z + dz)
            if neighbour in flat and neighbour not in previous:
                previous[neighbour] = cell
                queue.append(neighbour)
    if goal_cell not in previous:
        return []
    route = []
    cell = goal_cell
    while cell is not None:
        route.append(pso_walk.cell_centre(cell))
        cell = previous[cell]
    route.reverse()
    return route


def fight_if_adjacent():
    me = read_pos()
    mobs = entities("TObjEne")
    near = [m for m in mobs if math.dist(me, (m["x"], m["z"])) <= 16]
    if not near:
        return False
    for _ in range(4):
        hold("left", 0.16)
        tap("a", 2, 0.22)
    return True


def main(budget=900.0):
    log("=== CP17 final integrated run")
    if floor() != 1:
        controls("floor_warp", {"target": "1"})
        time.sleep(10)
    controls("stat", {"name": "atp", "value": 999})
    tap("b", 2, 0.5)                                             # step off the arrival pad
    me = read_pos()
    keys = [d for d in entities("TObjDoor") if d["class"].startswith("TObjDoorKey")]
    if not keys:
        log("no key doors")
        return 2
    goal = min(((d["x"], d["z"]) for d in keys), key=lambda g: math.dist(me, g))
    collision = REL.read_bytes()
    route = flat_route(collision, me, goal)
    log(f"start {tuple(round(v,1) for v in me)} goal {tuple(round(v,0) for v in goal)} route {len(route)} waypoints")
    if not route:
        log("no flat route")
        return 2
    started = time.time()
    index, still = 0, 0
    last = me
    while index < len(route) and time.time() - started < budget:
        if floor() != 1:
            log(f"FLOOR CHANGED BY WALKING: {floor()}")
            cap.main()
            return 0
        chunk = [tuple(w) for w in route[index:index + 4]]
        try:
            pso_kbwalk.walk_path(read_pos, hold, chunk, tolerance=9.0)
        except RuntimeError as exc:
            log(f"  walk_path: {exc}")
        now = read_pos()
        moved = math.dist(now, last)
        last = now
        index += len(chunk)
        still = still + 1 if moved < 3 else 0
        if still >= 2:
            if fight_if_adjacent():
                log(f"  fought an adjacent enemy at {tuple(round(v,1) for v in now)}")
            else:
                tap("b", 1, 0.35)
            still = 0
        if index % 12 == 0:
            log(f"  waypoint {index}/{len(route)} pos={tuple(round(v,1) for v in now)} moved={moved:.0f}")
            cap.main()
    log(f"route done at {tuple(round(v,1) for v in read_pos())} dist_to_door={math.dist(read_pos(), goal):.0f}")
    if math.dist(read_pos(), goal) > 20:
        log("did not arrive; rebuilding a short route")
        route = flat_route(collision, read_pos(), goal)
        for waypoint in route[:20]:
            pso_kbwalk.walk_path(read_pos, hold, [tuple(waypoint)], tolerance=7.0)
    if math.dist(read_pos(), goal) <= 20:
        log("at the door; interacting")
        tap("a", 1, 0.8)
        for step in range(5):
            hold("up", 0.9)
            now = floor()
            log(f"  push {step}: floor={now} pos={tuple(round(v,1) for v in read_pos())}")
            if now != 1:
                log(f"FLOOR CHANGED BY WALKING: {now}")
                cap.main()
                return 0
    cap.main()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
