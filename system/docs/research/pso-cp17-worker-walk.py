"""CP17 worker-input walk with a four-key calibration: measure each direction's world vector through the worker, then stride with
the key whose measured vector points at the door, recalibrating every few strides as the camera turns.
"""
import json
import math
import struct
import sys
import time
import urllib.request

sys.path.insert(0, r"C:\_tools\gBox\system")
sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import capture_gbox_app as cap                                     # noqa: E402

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
API = "http://127.0.0.1:8765"
SID = "e731ee594dde4a89-cae9dad929a34d17"
TABLE, MAX_ENTRIES = 0x8050D460, 256
FLOOR = 0x805D5FC0
LOG = r"D:\gBox\pso-ds\cp17-worker2.log"


def log(line):
    text = f"{time.strftime('%H:%M:%S')} {line}"
    print(text, flush=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(text + "\n")


def call(path, method="GET", body=None, timeout=60):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method,
                                 headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent",
                                          "content-type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read() or b"null")


def job(tool, payload, timeout=60):
    started = time.time()
    body = call("/api/jobs", "POST", {"tool": tool, "input": payload})
    while time.time() - started < timeout:
        time.sleep(0.22)
        state = call("/api/jobs/" + body["id"])
        if state.get("state") not in ("queued", "running"):
            return (state.get("output") or {}).get("result")
    return None


def send(events):
    return job("session_op", {"session_id": SID, "op": "send_input", "args": {"events": events}})


def hold(key, seconds):
    send([{"key": key, "down": True}])
    time.sleep(seconds)
    send([{"key": key, "down": False}])
    time.sleep(0.05)


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


def floor():
    return int.from_bytes(read(FLOOR, 4), "big")


def cstring(address, limit=40):
    raw = read(address, limit)
    return raw.split(b"\x00")[0].decode("ascii", "replace") if raw else ""


def key_doors():
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
        if not name.startswith("TObjDoorKey"):
            continue
        x, _y, z = struct.unpack(">fff", read(pointer + 0x38, 12))
        out.append((x, z))
    return out


def pos():
    actor = int.from_bytes(read(0x8050EA10, 4), "big")
    if not actor:
        return None
    x, _y, z = struct.unpack(">fff", read(actor + 0x38, 12))
    return x, z


def calibrate(seconds=0.55):
    vectors = {}
    for key in ("up", "down", "left", "right"):
        before = pos()
        hold(key, seconds)
        time.sleep(0.1)
        after = pos()
        vectors[key] = (after[0] - before[0], after[1] - before[1])
    return vectors


def key_for(direction, vectors):
    best, best_dot = None, -1e9
    length_d = math.hypot(*direction) or 1.0
    for key, (vx, vz) in vectors.items():
        length = math.hypot(vx, vz)
        if length < 1.0:
            continue
        dot = (vx / length) * (direction[0] / length_d) + (vz / length) * (direction[1] / length_d)
        if dot > best_dot:
            best, best_dot = key, dot
    return best, best_dot


def main(budget=600.0):
    log("=== CP17 worker-input calibrated walk")
    me = pos()
    targets = key_doors()
    if not targets:
        log("no key doors")
        return 2
    goal = min(targets, key=lambda g: math.dist(me, g))
    log(f"start {tuple(round(v,1) for v in me)} goal {tuple(round(v,1) for v in goal)} "
        f"dist={math.dist(me, goal):.0f} floor={floor()}")
    vectors = calibrate()
    log(f"calibration: { {k: (round(v[0],1), round(v[1],1)) for k, v in vectors.items()} }")
    started = time.time()
    strides = 0
    while time.time() - started < budget:
        if floor() != 1:
            log(f"FLOOR CHANGED BY WALKING: {floor()}")
            cap.main()
            return 0
        me = pos()
        distance = math.dist(me, goal)
        if distance <= 9:
            log("at the door; interact once")
            send([{"key": "a", "down": True}, {"key": "a", "down": False}])
            time.sleep(0.8)
            for step in range(5):
                hold("up", 0.9)
                now = floor()
                log(f"  push {step}: floor={now} pos={tuple(round(v,1) for v in pos())}")
                if now != 1:
                    log(f"FLOOR CHANGED BY WALKING: {now}")
                    cap.main()
                    return 0
            cap.main()
            return 2
        key, dot = key_for((goal[0] - me[0], goal[1] - me[1]), vectors)
        if key is None:
            log("  calibration useless; re-measuring")
            vectors = calibrate()
            continue
        hold(key, 0.9)
        strides += 1
        if strides % 5 == 0:
            vectors = calibrate()
        if strides % 10 == 0:
            log(f"  stride {strides}: {math.dist(pos(), goal):.0f} units, key={key} align={dot:.2f}, "
                f"pos={tuple(round(v,1) for v in pos())}")
            cap.main()
    log("budget spent")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
