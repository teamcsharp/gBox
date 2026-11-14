"""portal-state - freeze the live session state before the town-portal experiment.

Writes one JSON receipt (and prints a summary) with the facts the handoff's step A asks for:

    ROM build and game mode, difficulty, floor/episode, phase, stage flags, session id, player, and the
    entity census around Pioneer 2's warp pad at (360,26).

Read-only: it issues no input and writes no memory. The only writes are its receipt file.

    python pso-portal-state.py --out D:\\gBox\\pso-ds\\mandate
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import pathlib
import sys
import time
import urllib.request

sys.path.insert(0, r"C:\_tools\gBox\system")

BASE = os.environ.get("GBOX_API") or "http://127.0.0.1:8765"
TOKEN_PATH = pathlib.Path(r"C:\_tools\gBox\system\gbox-data\api_token")

GAME_ID = "GPOE8P"
DOL_SHA256 = "1f80fb82b41c05b26b6d0545b1ba9c0aa60b52e6589cf32fbb2ffe644692a61a"
CATALOG_ID = "436e0bb84d5337d1"
CATALOG_TITLE = "Phantasy Star Online Episode I & II Plus (USA)"

PHASE = 0x804FE120
FLOOR = 0x805D5FC0
EPISODE = 0x805D6060
DIFFICULTY = 0x805D5550
STAGE_FLAGS = 0x80515CC8
STAGE_FLAGS_LEN = 576
PAD = (360.0, 26.0)


def token() -> str:
    return TOKEN_PATH.read_text(encoding="utf-8").strip()


def call(path, payload=None, method="GET", timeout=40):
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={"authorization": "Bearer " + token(), "x-gbox-actor": "agent",
                 "content-type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(request, timeout=timeout).read() or b"null")
    except Exception as exc:                                      # noqa: BLE001
        return {"err": type(exc).__name__, "detail": str(exc)}


def live() -> list:
    rows = call("/api/sessions")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    return [row for row in rows if row.get("state") in ("running", "starting")]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="freeze the live PSO session state and the pad census")
    ap.add_argument("--state", action="store_true", help="unused; state is always printed")
    ap.add_argument("--out", default=r"D:\gBox\pso-ds\mandate")
    args = ap.parse_args(argv)

    rows = live()
    if not rows:
        print("no live session")
        return 2
    row = rows[0]
    sid = row["session_id"]
    worker = sid.split("-")[0]

    def rpc(op, **kwargs):
        return call(f"/api/sessions/{sid}/rpc", {"op": op, "args": kwargs}, "POST", 40)

    def read(address, length):
        raw = rpc("read_memory", address=address, length=length)
        return bytes.fromhex(raw) if isinstance(raw, str) else b""

    def u32(address):
        raw = read(address, 4)
        return int.from_bytes(raw, "big") if len(raw) == 4 else None

    state = rpc("state") or {}
    player = state.get("player") or {}
    entities = state.get("entities") or []
    flags = read(STAGE_FLAGS, STAGE_FLAGS_LEN)
    difficulty = u32(DIFFICULTY)
    receipt = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "session": sid,
        "worker": worker,
        "rom": {"catalog_id": CATALOG_ID, "title": CATALOG_TITLE, "serial": GAME_ID,
                "executable": "PsoV3.dol", "dol_sha256": DOL_SHA256,
                "disc_path": row.get("detail", {}).get("rom", "") if isinstance(row.get("detail"), dict) else ""},
        "mode": {"adapter": row.get("adapter"), "mod": row.get("mod")},
        "game": {"phase": read(PHASE, 1)[0] if len(read(PHASE, 1)) == 1 else None,
                 "floor": u32(FLOOR), "episode": (u32(EPISODE) + 1) if u32(EPISODE) is not None else None,
                 "difficulty": difficulty,
                 "difficulty_name": {0: "Normal", 1: "Hard", 2: "VeryHard", 3: "Ultimate"}.get(difficulty)},
        "stage_flags": {"sha256": hashlib.sha256(flags).hexdigest() if flags else None,
                        "set_bits": [sum(bin(byte).count("1") for byte in flags[g * 32:(g + 1) * 32])
                                     for g in range(18)] if flags else []},
        "player": player,
        "entity_count": len(entities),
        "pad": None,
        "matches": {"TObject": [], "warp": []},
    }
    for entity in entities:
        cls = str(entity.get("class") or "")
        x, z = entity.get("x"), entity.get("z")
        if x is None or z is None:
            continue
        distance = math.hypot(float(x) - PAD[0], float(z) - PAD[1])
        slim = {"class": cls, "ptr": entity.get("ptr"), "room": entity.get("room"),
                "x": x, "y": entity.get("y"), "z": z, "distance_to_pad": round(distance, 2)}
        if distance <= 3.0:
            receipt["pad"] = receipt["pad"] or slim
        if "Warp" in cls:
            receipt["matches"]["warp"].append(slim)
        elif cls == "TObject" and distance < 120.0:
            receipt["matches"]["TObject"].append(slim)

    play = call(f"/api/sessions/{sid}/rpc", {"op": "state", "args": {"player_only": True}}, "POST") or {}
    receipt["player_only"] = play

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"freeze-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(receipt, indent=1), encoding="utf-8")

    print(json.dumps({k: receipt[k] for k in ("session", "game", "stage_flags", "entity_count", "pad")},
                     indent=1))
    print("player:", receipt["player"])
    print("TObjects near the pad:", json.dumps(receipt["matches"]["TObject"], indent=1))
    print("warp-family entities:", json.dumps(receipt["matches"]["warp"], indent=1))
    print("wrote", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
