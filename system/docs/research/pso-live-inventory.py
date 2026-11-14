"""live-inventory - find the PSO inventory through the session channel, list it, and act on it.

The app's own ``pso_inventory`` tool scans main RAM in 1 MiB through the adapter and can come back "inventory not found"
when that path fails; this tool does the same scan over the session RPC in smaller chunks, then decodes the 30 x 28-byte
slots the same way and prints each slot with its catalog name. Read-only.

    python pso-live-inventory.py list
    python pso-live-inventory.py scan --chunk 262144
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

sys.path.insert(0, r"C:\_tools\gBox\system")

from gbox import psoitems  # noqa: E402

BASE = os.environ.get("GBOX_API") or "http://127.0.0.1:18765"
TOKEN_PATH = pathlib.Path(r"C:\_tools\gBox\system\gbox-data\api_token")
RAM_START, RAM_SIZE = 0x80000000, 0x1800000
CHUNK = 0x40000
OVERLAP = 0x4000
E = ">"


def token() -> str:
    return TOKEN_PATH.read_text(encoding="utf-8").strip()


def call(path, payload=None, method="GET", timeout=120):
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={"authorization": "Bearer " + token(), "x-gbox-actor": "agent",
                 "content-type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(request, timeout=timeout).read() or b"null")
    except Exception as exc:                                     # noqa: BLE001
        return {"err": type(exc).__name__, "detail": str(exc)}


def live() -> str:
    rows = call("/api/sessions")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    alive = [row for row in rows if row.get("state") in ("running", "starting")]
    return alive[0]["session_id"] if alive else ""


class Memory:
    def __init__(self, sid: str) -> None:
        self.sid = sid

    def read_memory(self, address: int, length: int) -> bytes:
        raw = call(f"/api/sessions/{self.sid}/rpc",
                   {"op": "read_memory", "args": {"address": address, "length": length}}, "POST", 120)
        if not isinstance(raw, str):
            raise OSError(f"read_memory failed at {address:#x}: {raw}")
        return bytes.fromhex(raw)


def scan(memory: Memory, chunk: int = CHUNK, overlap: int = OVERLAP) -> dict:
    started = time.monotonic()
    found = []
    base = RAM_START
    while base < RAM_START + RAM_SIZE:
        length = min(chunk + overlap, RAM_START + RAM_SIZE - base)
        try:
            data = memory.read_memory(base, length)
        except OSError as exc:
            print(f"  read failed at {base:#x}: {exc}")
            base += chunk
            continue
        hit = psoitems.find_inventory(data, base, E) or psoitems.find_inventory_loose(data, base, E)
        if hit:
            found.append(hit)
            print(f"  inventory candidate at {hit:#x} ({len(found)})")
        base += chunk
        if len(found) >= 4:
            break
    print(f"scan finished in {time.monotonic() - started:.1f}s, {len(found)} candidate(s)")
    return {"candidates": found, "seconds": round(time.monotonic() - started, 1)}


def decode(memory: Memory, base: int, catalog: dict) -> list:
    raw = memory.read_memory(base, psoitems.SLOT * psoitems.SLOTS)
    rows = []
    for index in range(psoitems.SLOTS):
        slot = psoitems.decode_slot(raw[index * psoitems.SLOT:(index + 1) * psoitems.SLOT], E)
        code = slot.get("code") or ""
        row = {"slot": index, **slot, "name": catalog.get(code) or catalog.get(code[:4]) or ""}
        rows.append(row)
    return rows


def catalog(version: str = "gc") -> dict:
    payload = call(f"/api/pso/items?version={version}", None, "GET", 120)
    if isinstance(payload, dict) and payload.get("err"):
        return {}
    return {item["code"]: item.get("name") or "" for item in payload}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="find/list the live PSO inventory")
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("scan")
    show = sub.add_parser("list")
    show.add_argument("--base", default="", help="slot-0 address in hex, if known")
    args = parser.parse_args(argv)
    sid = live()
    if not sid:
        print("no live session")
        return 2
    memory = Memory(sid)
    cats = catalog()
    if args.mode == "scan" or not getattr(args, "base", ""):
        result = scan(memory)
        if not result["candidates"]:
            print("no inventory candidate found")
            return 1
        base = result["candidates"][0]
    else:
        base = int(args.base, 16)
    rows = decode(memory, base, cats)
    present = [row for row in rows if row.get("present")]
    print(f"inventory slot 0 at {base:#x}, {len(present)} present slots")
    for row in present:
        print(f"  [{row['slot']:2d}] {row.get('code')} {row.get('name')} "
              f"equipped={bool(row.get('equipped'))} id={row.get('id')}")
    out = pathlib.Path(r"D:\gBox\pso-ds\mandate") / "live-inventory.json"
    out.write_text(json.dumps({"session": sid, "base": hex(base), "slots": rows}, indent=1), encoding="utf-8")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
