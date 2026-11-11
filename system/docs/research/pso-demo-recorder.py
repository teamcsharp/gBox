"""Demonstration recorder: capture everything while the operator plays, so the bot can learn from it.

Writes one session directory per run:
    D:\\gBox\\pso-ds\\demos\\demo-<stamp>\\state.jsonl   one line per sample: player pos/facing/floor/hp, door states, enemies,
                                                       room-relative minimap door markers
    D:\\gBox\\pso-ds\\demos\\demo-<stamp>\\frames\\*.png   a screenshot every `frame_every` seconds
    D:\\gBox\\pso-ds\\demos\\demo-<stamp>\\path.json     the demonstrated path as waypoints + per-step timing

The path is the "recreation": the sequence of positions the operator actually walked, ready to replay or to train a policy on.
Run with no arguments; Ctrl-C or job_kill stops it and finalises path.json.
"""
import json
import math
import struct
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\system")
sys.path.insert(0, r"C:\_tools\gBox\.tmp")

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
API = "http://127.0.0.1:8765"
SID = "e731ee594dde4a89-cae9dad929a34d17"
TABLE, MAX_ENTRIES, HP = 0x8050D460, 256, 0x32C
FLOOR = 0x805D5FC0
ROOT = Path(r"D:\gBox\pso-ds\demos")
MINIMAP_BOX = (660, 80, 900, 275)
GREEN = lambda p: p[1] > 105 and p[0] < 110 and p[2] < 110     # noqa: E731


def read(address, length):
    body = json.dumps({"op": "read_memory", "args": {"address": address, "length": length}}).encode()
    for _ in range(3):
        try:
            req = urllib.request.Request(f"{API}/api/sessions/{SID}/rpc", data=body, method="POST",
                                         headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent",
                                                  "content-type": "application/json"})
            return bytes.fromhex(json.loads(urllib.request.urlopen(req, timeout=10).read() or b'""'))
        except Exception:                                        # noqa: BLE001
            time.sleep(0.1)
    return b""


def cstring(address, limit=40):
    raw = read(address, limit)
    return raw.split(b"\x00")[0].decode("ascii", "replace") if raw else ""


def snapshot():
    actor = int.from_bytes(read(0x8050EA10, 4), "big")
    state = {"t": round(time.time(), 3), "floor": int.from_bytes(read(FLOOR, 4), "big")}
    if actor:
        x, y, z = struct.unpack(">fff", read(actor + 0x38, 12))
        facing = struct.unpack(">f", read(actor + 0x20, 4))[0] if actor else 0.0
        state.update({"x": round(x, 2), "y": round(y, 2), "z": round(z, 2), "facing": round(facing, 3),
                      "hp": int.from_bytes(read(actor + HP, 2), "big")})
    doors = []
    entities = []
    raw = read(TABLE, MAX_ENTRIES * 4)
    for index in range(MAX_ENTRIES):
        pointer = int.from_bytes(raw[index * 4:index * 4 + 4], "big")
        if not (0x80000000 <= pointer < 0x81800000):
            continue
        name_pointer = int.from_bytes(read(pointer, 4), "big")
        if not (0x80000000 <= name_pointer < 0x81800000):
            continue
        name = cstring(name_pointer)
        if name.startswith("TObjDoor"):
            blob = read(pointer, 0x190)
            if len(blob) >= 0x190:
                dx, dy, dz = struct.unpack(">fff", blob[0x38:0x44])
                doors.append({"i": index, "c": name, "x": round(dx, 1), "z": round(dz, 1),
                              "state": struct.unpack(">i", blob[0x18C:0x190])[0]})
        elif name.startswith("TObjEne"):
            ex, ey, ez = struct.unpack(">fff", read(pointer + 0x38, 12))
            entities.append({"c": name, "x": round(ex, 1), "z": round(ez, 1),
                             "hp": int.from_bytes(read(pointer + HP, 2), "big")})
    state["doors"] = doors
    state["enemies"] = entities
    return state


def minimap_markers(frame_path):
    """Green squares on the minimap are the doors the operator uses; return their crop coordinates."""
    try:
        from PIL import Image
        image = Image.open(frame_path).convert("RGB")
        crop = image.crop(MINIMAP_BOX)
        px = crop.load()
        w, h = crop.size
        points = [(x, y) for y in range(h) for x in range(w) if GREEN(px[x, y])]
        clusters = []
        for point in points:
            for cluster in clusters:
                if abs(point[0] - cluster[0][0]) <= 4 and abs(point[1] - cluster[0][1]) <= 4:
                    cluster.append(point)
                    break
            else:
                clusters.append([point])
        out = []
        for cluster in clusters:
            if len(cluster) < 6:
                continue
            xs = [p[0] for p in cluster]
            ys = [p[1] for p in cluster]
            out.append({"mx": round(sum(xs) / len(xs), 1), "my": round(sum(ys) / len(ys), 1), "px": len(cluster)})
        return out
    except Exception:                                            # noqa: BLE001
        return []


def main(duration=7200.0, sample=0.5, frame_every=2.0):
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = ROOT / f"demo-{stamp}"
    frames = out / "frames"
    frames.mkdir(parents=True, exist_ok=True)
    state_path = out / "state.jsonl"
    print(f"recording to {out}", flush=True)
    started = time.time()
    last_frame = 0.0
    path = []
    with open(state_path, "a", encoding="utf-8") as handle:
        while time.time() - started < duration:
            state = snapshot()
            if state.get("x") is not None:
                if not path or math.dist((state["x"], state["z"]), (path[-1]["x"], path[-1]["z"])) > 3.0:
                    path.append({"x": state["x"], "z": state["z"], "t": state["t"], "floor": state["floor"]})
            if time.time() - last_frame >= frame_every:
                last_frame = time.time()
                try:
                    import capture_gbox_app as cap
                    cap.main()
                    newest = sorted(Path(r"D:\gBox\pso-ds\demo").glob("*.png"),
                                    key=lambda p: p.stat().st_mtime)[-1]
                    target = frames / f"{time.strftime('%H%M%S')}.png"
                    target.write_bytes(newest.read_bytes())
                    state["minimap"] = minimap_markers(str(target))
                except Exception as exc:                         # noqa: BLE001
                    state["frame_error"] = str(exc)[:80]
            handle.write(json.dumps(state) + "\n")
            handle.flush()
            time.sleep(sample)
    (out / "path.json").write_text(json.dumps({"stamp": stamp, "waypoints": path}, indent=1), encoding="utf-8")
    print(f"stopped; {len(path)} path waypoints in {out / 'path.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
