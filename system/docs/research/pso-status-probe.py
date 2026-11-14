"""status-probe - snapshot and diff the player-related RAM windows to locate the status-effect field.

The live problem this serves: the operator's character is paralysed and the attack is gated by it. The status is
"never expires" (PSO: Paralysis is cured by Antiparalysis/Sol Atomizer/Anti 3+), so the RAM field holding it can be
captured while it is on and again after the operator cures it - the diff is the field.

    python pso-status-probe.py snapshot --label paralysed
    # operator cures with Antiparalysis / Sol Atomizer
    python pso-status-probe.py snapshot --label cured
    python pso-status-probe.py diff --a D:\\gBox\\pso-ds\\mandate\\status\\paralysed.json --b ...\\cured.json

Read-only: it never writes memory. The windows are chosen around the TObjPlayer actor and the game's global state
blocks the repo already reads (pso_ram), not the whole 24 MiB, so a diff stays interpretable.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import struct
import sys
import time
import urllib.request

BASE = os.environ.get("GBOX_API") or "http://127.0.0.1:18765"
TOKEN_PATH = pathlib.Path(r"C:\_tools\gBox\system\gbox-data\api_token")
OUT = pathlib.Path(r"D:\gBox\pso-ds\mandate\status")

WINDOWS = (
    ("player_struct", None, 0x0000, 0x1000),          # TObjPlayer's first pages (actor fields)
    ("player_neighbourhood", None, -0x8000, 0x18000),  # the actor pool around TObjPlayer
    ("globals_low", 0x804FE000, 0, 0x14000),          # phase / player manager area below the actor heap
    ("globals_flags", 0x80514000, 0, 0x14000),        # stage flags / party state
    ("globals_floor", 0x805D4000, 0, 0x20000),        # floor, difficulty, collision roots
)


def token() -> str:
    return TOKEN_PATH.read_text(encoding="utf-8").strip()


def call(path, payload=None, method="GET", timeout=120):
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={"authorization": "Bearer " + token(), "x-gbox-actor": "agent",
                 "content-type": "application/json"})
    return json.loads(urllib.request.urlopen(request, timeout=timeout).read() or b"null")


def live() -> str:
    rows = call("/api/sessions")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    alive = [row for row in rows if row.get("state") in ("running", "starting")]
    return alive[0]["session_id"] if alive else ""


def snapshot(label: str) -> int:
    sid = live()
    if not sid:
        print("no live session")
        return 2

    def rpc(op, **args):
        return call(f"/api/sessions/{sid}/rpc", {"op": op, "args": args}, "POST", 120)

    state = rpc("state") or {}
    player = state.get("player") or {}
    pointer = int(player.get("ptr"), 16)
    OUT.mkdir(parents=True, exist_ok=True)
    doc = {"label": label, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "session": sid,
           "player": player, "windows": []}
    for name, fixed, relative, length in WINDOWS:
        base = fixed if fixed is not None else pointer + relative
        raw = rpc("read_memory", address=base, length=length)
        if not isinstance(raw, str):
            print(f"{name}: read failed {raw}")
            continue
        data = bytes.fromhex(raw)
        path = OUT / f"{label}-{name}.bin"
        path.write_bytes(data)
        doc["windows"].append({"name": name, "base": base, "length": len(data), "file": str(path)})
        print(f"{name}: {len(data)} bytes at {base:#010x} -> {path}")
    doc_path = OUT / f"{label}.json"
    doc_path.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    print("wrote", doc_path)
    return 0


def diff(a_path: pathlib.Path, b_path: pathlib.Path) -> int:
    a = json.loads(a_path.read_text(encoding="utf-8"))
    b = json.loads(b_path.read_text(encoding="utf-8"))
    wa = {row["name"]: row for row in a["windows"]}
    wb = {row["name"]: row for row in b["windows"]}
    report = {"a": str(a_path), "b": str(b_path), "changes": []}
    for name in wa:
        if name not in wb:
            continue
        da = pathlib.Path(wa[name]["file"]).read_bytes()
        db = pathlib.Path(wb[name]["file"]).read_bytes()
        base = wa[name]["base"]
        changes = []
        index = 0
        while index < min(len(da), len(db)):
            if da[index] != db[index]:
                start = index
                while index < min(len(da), len(db)) and da[index] != db[index]:
                    index += 1
                la = da[start:index].hex()
                lb = db[start:index].hex()
                changes.append({"address": hex(base + start), "offset": start,
                                "a": la, "b": lb,
                                "a_u32": (da[start:start + 4] + b"\0" * 4)[:4].hex(),
                                "b_u32": (db[start:start + 4] + b"\0" * 4)[:4].hex()})
            else:
                index += 1
        report["changes"].append({"window": name, "base": hex(base), "changed_bytes": sum(
            len(row["a"]) // 2 for row in changes), "runs": changes[:400]})
    path = OUT / f"diff-{a['label']}-{b['label']}.json"
    path.write_text(json.dumps(report, indent=1), encoding="utf-8")
    for window in report["changes"]:
        print(f"{window['window']}: {window['changed_bytes']} changed bytes")
        for run in window["runs"][:40]:
            print(f"  {run['address']} +{run['offset']:#06x}  {run['a']} -> {run['b']}")
    print("wrote", path)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="snapshot/diff PSO player state to locate the status field")
    sub = parser.add_subparsers(dest="mode", required=True)
    snap = sub.add_parser("snapshot")
    snap.add_argument("--label", required=True)
    dif = sub.add_parser("diff")
    dif.add_argument("--a", required=True)
    dif.add_argument("--b", required=True)
    args = parser.parse_args(argv)
    return snapshot(args.label) if args.mode == "snapshot" else diff(pathlib.Path(args.a), pathlib.Path(args.b))


if __name__ == "__main__":
    raise SystemExit(main())
