"""Learn from the operator's own session: wait for their launch, record inputs and route, then write both missions.

gBox's gameplay journal is deliberately off for agent launches (`gameplay_actions.start` returns 'off' when `ctx.agent_use`), so the
product only learns from a session the operator started. This watcher is what turns such a session into reusable material:

  1. waits for a running session whose `agent_owned` is false (the operator's own Play);
  2. records the operator's pad at 30 Hz (XInput, no plane involvement) and their world position at 4 Hz through the 18765 byte RPC;
  3. when the session ends, writes `operator-timeline-<ts>.json`, learns the burst style with `imitate.learn`, and writes the route
     as a `navigate` mission via `pso_chords.route_mission`.
"""
import json
import struct
import sys
import threading
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp\main-repo\system")

from gbox import pad_bind, pso_chords, pso_learn_play as LP, pso_ram, xinput   # noqa: E402

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
API = "http://127.0.0.1:8765"
LOCAL = "http://127.0.0.1:18765"
OUT = Path(r"D:\gBox\pso-ds")
BUTTONS = {0x1000: "a", 0x2000: "b", 0x4000: "x", 0x8000: "y", 0x0010: "start", 0x0020: "back",
           0x0200: "z", 0x0001: "dup", 0x0002: "ddown", 0x0004: "dleft", 0x0008: "dright"}


def get(path):
    req = urllib.request.Request(API + path, headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent"})
    return json.loads(urllib.request.urlopen(req, timeout=20).read() or b"null")


class LocalReader:
    def __init__(self, session):
        self.session = session

    def read(self, address, length):
        body = json.dumps({"op": "read_memory", "args": {"address": address, "length": length}}).encode()
        req = urllib.request.Request(f"{LOCAL}/api/sessions/{self.session}/rpc", data=body, method="POST",
                                     headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent",
                                              "content-type": "application/json"})
        reply = json.loads(urllib.request.urlopen(req, timeout=10).read() or b'""')
        return bytes.fromhex(reply) if isinstance(reply, str) else b""


def pressed(gamepad) -> frozenset:
    keys = {name for bit, name in BUTTONS.items() if gamepad.buttons & bit}
    if abs(gamepad.lx) > 7849:
        keys.add("right" if gamepad.lx > 0 else "left")
    if abs(gamepad.ly) > 7849:
        keys.add("down" if gamepad.ly > 0 else "up")
    if abs(gamepad.rx) > 7849:
        keys.add("cright" if gamepad.rx > 0 else "cleft")
    if abs(gamepad.ry) > 7849:
        keys.add("cdown" if gamepad.ry > 0 else "cup")
    return frozenset(keys)


def main() -> int:
    print("waiting for the operator's own session (agent-launched sessions are not journaled)", flush=True)
    session, started = None, time.time()
    while time.time() - started < 12 * 3600:
        try:
            for s in get("/api/sessions?include_ended=false"):
                if s.get("state") == "running" and not s.get("agent_owned"):
                    session = s["session_id"]
                    break
        except Exception as exc:                                  # noqa: BLE001
            print("api:", exc, flush=True)
        if session:
            break
        time.sleep(5)
    if not session:
        print("no operator session in the watch window")
        return 1
    print("recording operator session", session, flush=True)
    stop = threading.Event()
    pad_rows, route_rows = [], []
    reader = LocalReader(session)

    def pad_loop():
        fn = xinput.load()
        slot, keys = None, None
        began = time.time()
        while not stop.is_set():
            states = {}
            for s in range(4):
                st = xinput.read(fn, s)
                if st is not None:
                    g = st.gamepad
                    states[s] = (g.buttons, g.lx, g.ly)
            alive = pad_bind.live_slots(states)
            slot = alive[0] if alive else slot
            if slot is not None:
                st = xinput.read(fn, slot)
                if st is not None:
                    now = pressed(st.gamepad)
                    if now != keys:
                        pad_rows.append((round(time.time() - began, 3), sorted(now)))
                        keys = now
            time.sleep(1 / 30)

    def route_loop():
        actor, misses, began = 0, 0, time.time()
        while not stop.is_set():
            try:
                if not actor or misses > 10:
                    slots = struct.unpack(">4I", reader.read(pso_ram.PLAYER_SLOTS, 16))
                    actor = next((x for x in slots if x), 0)
                    misses = 0
                if actor:
                    x, y, z = struct.unpack(">3f", reader.read(actor + 0x38, 12))
                    floor = struct.unpack(">I", reader.read(pso_ram.FLOOR, 4))[0]
                    route_rows.append({"t": round(time.time() - began, 2), "x": round(x, 1), "y": round(y, 1),
                                       "z": round(z, 1), "floor": floor})
                    misses = 0
                else:
                    misses += 1
            except Exception:                                     # noqa: BLE001
                misses += 1
            time.sleep(0.25)

    threads = [threading.Thread(target=pad_loop, daemon=True), threading.Thread(target=route_loop, daemon=True)]
    for thread in threads:
        thread.start()
    while True:
        time.sleep(5)
        try:
            running = [s for s in get("/api/sessions?include_ended=false") if s.get("session_id") == session]
        except Exception:                                         # noqa: BLE001
            running = []
        if not running or running[0].get("state") != "running":
            break
    stop.set()
    for thread in threads:
        thread.join(timeout=3)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    OUT.mkdir(parents=True, exist_ok=True)
    timeline = OUT / f"operator-timeline-{stamp}.json"
    timeline.write_text(json.dumps({"session": session, "rows": pad_rows}, indent=1), encoding="utf-8")
    print(f"inputs: {len(pad_rows)} changes -> {timeline}")
    if len(pad_rows) >= 8:
        learned = LP.learn([(t, frozenset(k)) for t, k in pad_rows])
        mission = LP.mission(learned, game_id="436e0bb84d5337d1", name=f"pso-learned-{stamp}", run=session)
        path = LP.save(mission, OUT / "learned-missions")
        print(f"bursts: {len(learned.get('bursts') or [])} (keys {learned.get('menu')}) -> {path}")
    if len(route_rows) >= 4:
        route = OUT / "routes" / f"route-{stamp}.json"
        route.parent.mkdir(parents=True, exist_ok=True)
        route.write_text(json.dumps(route_rows, indent=0), encoding="utf-8")
        mission = pso_chords.route_mission(route_rows, game_id="436e0bb84d5337d1",
                                           name=f"route-{stamp}", source=str(route))
        path = LP.save(mission, OUT / "learned-missions")
        print(f"route: {len(route_rows)} samples, {mission['provenance']['waypoints']} waypoints -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
