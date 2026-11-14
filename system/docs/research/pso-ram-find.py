"""ram-find - dump PSO GameCube main RAM and locate item-record runs without assuming the slot layout.

The repo's inventory reader assumes the Dreamcast 28-byte slot; on this GameCube build the app tool answers
"inventory not found", so the slot layout/stride is unconfirmed. This tool avoids the assumption: it reads all 24 MiB
through the session channel, then searches for runs of FOUR consecutive records whose first three bytes are a real item
code from the disc's own item table (1,257 codes). A random 24 MiB cannot produce four in a row (chance ~1e-17 per
position), so a run is a real item record and the distance between records is the stride.

    python pso-ram-find.py dump
    python pso-ram-find.py find --file D:\\gBox\\pso-ds\\mandate\\status\\ram-....bin
    python pso-ram-find.py find --file ... --stride 28 --code-offset 8
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
import urllib.request

sys.path.insert(0, r"C:\_tools\gBox\system")

BASE = os.environ.get("GBOX_API") or "http://127.0.0.1:18765"
TOKEN_PATH = pathlib.Path(r"C:\_tools\gBox\system\gbox-data\api_token")
OUT = pathlib.Path(r"D:\gBox\pso-ds\mandate\status")
RAM_START, RAM_SIZE = 0x80000000, 0x1800000
CHUNK = 0x100000


def token() -> str:
    return TOKEN_PATH.read_text(encoding="utf-8").strip()


def call(path, payload=None, method="GET", timeout=180):
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


def dump() -> int:
    sid = live()
    if not sid:
        print("no live session")
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"ram-{time.strftime('%Y%m%d-%H%M%S')}.bin"
    started = time.monotonic()
    with path.open("wb") as handle:
        base = RAM_START
        while base < RAM_START + RAM_SIZE:
            length = min(CHUNK, RAM_START + RAM_SIZE - base)
            raw = call(f"/api/sessions/{sid}/rpc",
                       {"op": "read_memory", "args": {"address": base, "length": length}}, "POST", 180)
            if not isinstance(raw, str):
                print(f"read failed at {base:#x}: {raw}")
                return 1
            data = bytes.fromhex(raw)
            handle.write(data)
            base += len(data)
            if len(data) != length:
                print(f"short read at {base - len(data):#x}: {len(data)} of {length}")
                return 1
            print(f"  {base - RAM_START:#x} / {RAM_SIZE:#x} ({time.monotonic() - started:.0f}s)")
    print(f"wrote {path} ({path.stat().st_size} bytes, {time.monotonic() - started:.1f}s)")
    return 0


def item_codes(version: str = "gc") -> set:
    payload = call(f"/api/pso/items?version={version}", None, "GET", 120)
    if not isinstance(payload, list):
        return set()
    return {int(item["code"], 16) for item in payload if isinstance(item.get("code"), str)}


def find(path: pathlib.Path, strides, code_offsets, required: int) -> int:
    import numpy as np
    data = path.read_bytes()
    print(f"{path.name}: {len(data)} bytes")
    codes = item_codes()
    print(f"item codes from the disc table: {len(codes)}")
    valid = np.zeros(1 << 24, dtype=bool)
    valid[np.fromiter(codes, dtype=np.int64)] = True
    arrays = np.frombuffer(data, dtype=np.uint8).astype(np.uint32)
    index = (arrays[:-2] << 16) | (arrays[1:-1] << 8) | arrays[2:]
    codes_at = valid[index]
    report = []
    for code_offset in code_offsets:
        for stride in strides:
            span = required * stride
            if code_offset + span >= len(codes_at):
                continue
            run = (codes_at[code_offset:code_offset + span:stride]
                   & codes_at[code_offset + stride:code_offset + stride + span:stride]
                   & codes_at[code_offset + 2 * stride:code_offset + 2 * stride + span:stride]
                   & codes_at[code_offset + 3 * stride:code_offset + 3 * stride + span:stride])
            hits = np.flatnonzero(run)
            if hits.size:
                report.append({"stride": stride, "code_offset": code_offset, "count": int(hits.size),
                               "first": int(hits[0]), "addresses": [hex(RAM_START + int(h))
                                                                    for h in hits[:10]]})
                print(f"stride {stride:2d} code offset {code_offset}: {hits.size} run(s), "
                      f"first at {RAM_START + int(hits[0]):#010x}")
    out = OUT / (path.stem + "-item-runs.json")
    out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print("wrote", out)
    return 0 if report else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="dump/locate PSO item records in GameCube main RAM")
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("dump")
    find_parser = sub.add_parser("find")
    find_parser.add_argument("--file", required=True)
    find_parser.add_argument("--strides", default="12,16,20,24,28,32,36")
    find_parser.add_argument("--code-offsets", default="0,4,8,12,16")
    find_parser.add_argument("--required", type=int, default=4)
    args = parser.parse_args(argv)
    if args.mode == "dump":
        return dump()
    strides = [int(v) for v in args.strides.split(",") if v.strip()]
    offsets = [int(v) for v in args.code_offsets.split(",") if v.strip()]
    return find(pathlib.Path(args.file), strides, offsets, args.required)


if __name__ == "__main__":
    raise SystemExit(main())
