"""map_bot: follows the map viewer's click commands, fights what is in the way, and never fights the operator.

Loop:
  * `pso_operator.guard()` - if the operator is moving the character, do nothing at all;
  * read D:\\gBox\\pso-ds\\goto.json; a new timestamp is a new order (waypoint, or a clicked enemy);
  * walk to the ordered point over the FLAT collision graph, re-planning every few waypoints so drift cannot accumulate;
  * if an enemy is within 35 units and HP is healthy, approach it and attack-while-stepping (the pattern that lands hits);
  * if HP is low (<= 10), break off and back away instead of fighting;
  * finish when within 10 units of the order, then idle until the next click.
"""
import json
import math
import struct
import sys
import time
import urllib.request
from collections import deque
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\system")
sys.path.insert(0, r"C:\_tools\gBox\.tmp")

from gbox import pso_kbwalk, psomap, pso_walk                      # noqa: E402
from gbox.adapters import win_send_keys                            # noqa: E402

import pso_operator                                                # noqa: E402

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
API = "http://127.0.0.1:8765"
SID = "e731ee594dde4a89-cae9dad929a34d17"
PID = 37032
TABLE, MAX_ENTRIES, HP = 0x8050D460, 256, 0x32C
FLOOR = 0x805D5FC0
REL = Path(r"D:\gBox\pso-ds\rel\map_forest01c.rel")
GOTO = Path(r"D:\gBox\pso-ds\goto.json")
LOG = r"D:\gBox\pso-ds\map_bot.log"
SIZE, STEP_LIMIT = 10.0, 2.5


def log(line):
    text = f"{time.strftime('%H:%M:%S')} {line}"
    print(text, flush=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(text + "\n")


def read(address, length):
    body = json.dumps({"op": "read_memory", "args": {"address": address, "length": length}}).encode()
    for _ in range(3):
        try:
            req = urllib.request.Request(f"{API}/api/sessions/{SID}/rpc", data=body, method="POST",
                                         headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent",
                                                  "content-type": "application/json"})
            return bytes.fromhex(json.loads(urllib.request.urlopen(req, timeout=10).read() or b'""'))
        except Exception:                                        # noqa: BLE001
            time.sleep(0.12)
    return b""


def floor():
    return int.from_bytes(read(FLOOR, 4), "big")


def player():
    actor = int.from_bytes(read(0x8050EA10, 4), "big")
    if not actor:
        return None
    blob = read(actor + 0x38, 12)
    if len(blob) < 12:
        return None
    x, y, z = struct.unpack(">fff", blob)
    return x, y, z


def player_hp():
    actor = int.from_bytes(read(0x8050EA10, 4), "big")
    return int.from_bytes(read(actor + HP, 2), "big") if actor else 0


def cstring(address, limit=40):
    raw = read(address, limit)
    return raw.split(b"\x00")[0].decode("ascii", "replace") if raw else ""


def enemies():
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
        if not name.startswith("TObjEne"):
            continue
        blob = read(pointer + 0x38, 12)
        if len(blob) < 12:
            continue
        x, y, z = struct.unpack(">fff", blob)
        out.append({"class": name, "x": x, "z": z, "hp": int.from_bytes(read(pointer + HP, 2), "big")})
    return [e for e in out if e["hp"] > 0]


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
    if not pso_operator.guard():
        return {}
    import ctypes
    user32 = ctypes.windll.user32
    hwnd = gbox_hwnd()
    if hwnd:
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.04)
    pso_operator.note_bot_input()
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
    time.sleep(0.03)


def tap(key, times=1, gap=0.3):
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


FLAT = None


def load_flat():
    global FLAT
    if FLAT is not None:
        return FLAT
    collision = REL.read_bytes()
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
    FLAT = flat
    return FLAT


def route(start, goal):
    flat = load_flat()
    start_cell = min(flat, key=lambda c: math.dist(pso_walk.cell_centre(c), start))
    goal_cell = min(flat, key=lambda c: math.dist(pso_walk.cell_centre(c), goal))
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
    path = []
    cell = goal_cell
    while cell is not None:
        path.append(pso_walk.cell_centre(cell))
        cell = previous[cell]
    path.reverse()
    return path


def unit(dx, dz):
    length = math.hypot(dx, dz)
    return (dx / length, dz / length) if length > 1e-6 else (0.0, 0.0)


def closing_key(goal):
    me = player()
    if not me:
        return None
    bearing = unit(goal[0] - me[0], goal[1] - me[2])
    best = None
    for key in ("up", "down", "left", "right"):
        before = player()
        hold(key, 0.22)
        after = player()
        if not after or not before:
            continue
        vector = (after[0] - before[0], after[2] - before[2])
        length = math.hypot(*vector)
        if length < 0.5:
            continue
        align = (vector[0] / length) * bearing[0] + (vector[1] / length) * bearing[1]
        if best is None or align > best[1]:
            best = (key, align)
    return best


def attack_while_stepping(goal, swings=3):
    facing = closing_key(goal)
    if not facing:
        return False
    key = facing[0]
    send([{"key": key, "down": True}])
    time.sleep(0.18)
    for _ in range(swings):
        send([{"key": "a", "down": True}])
        time.sleep(0.06)
        send([{"key": "a", "down": False}])
        time.sleep(0.34)
    send([{"key": key, "down": False}])
    return True


def main(duration=43200.0):
    log("=== map bot ready; waiting for a click on the map")
    seen = 0.0
    order = None
    started = time.time()
    while time.time() - started < duration:
        if pso_operator.operator_active():
            time.sleep(0.3)
            continue
        try:
            payload = json.loads(GOTO.read_text(encoding="utf-8"))
            if payload.get("t", 0) > seen:
                seen = payload["t"]
                order = payload
                log(f"order: {order}")
        except Exception:                                        # noqa: BLE001
            pass
        if order is None:
            time.sleep(0.4)
            continue
        if floor() != 1:
            log("not in Forest 1; order paused")
            time.sleep(1.0)
            continue
        me = player()
        if not me:
            time.sleep(0.3)
            continue
        target = (order["x"], order["z"])
        distance = math.dist((me[0], me[2]), target)
        if distance <= 10:
            log(f"arrived at {target}; order complete")
            order = None
            continue
        # fight what is in the way, but not when badly hurt
        mobs = enemies()
        if mobs and player_hp() > 12:
            near = min(mobs, key=lambda e: math.dist((me[0], me[2]), (e["x"], e["z"])))
            gap = math.dist((me[0], me[2]), (near["x"], near["z"]))
            if gap <= 35:
                if gap > 11:
                    path = route((me[0], me[2]), (near["x"], near["z"]))
                    if path:
                        try:
                            pso_kbwalk.walk_path(lambda: (player()[0], player()[2]), hold, path[:4], tolerance=7.0)
                        except Exception:                        # noqa: BLE001
                            hold(closing_key((near["x"], near["z"]))[0], 0.4) if closing_key((near["x"], near["z"])) else None
                else:
                    attack_while_stepping((near["x"], near["z"]))
                    log(f"attacked {near['class']} at {gap:.0f}; remaining {[(e['class'], e['hp']) for e in enemies()]}")
                continue
        path = route((me[0], me[2]), target)
        if not path:
            log("no flat route to the order; waiting")
            time.sleep(1.0)
            continue
        try:
            pso_kbwalk.walk_path(lambda: (player()[0], player()[2]), hold, [tuple(w) for w in path[:4]], tolerance=8.0)
        except RuntimeError as exc:
            log(f"walk_path: {exc}")
        if int(time.time() - started) % 30 < 2:
            me = player()
            log(f"  heading to {target}: {math.dist((me[0], me[2]), target):.0f} units, hp={player_hp()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
