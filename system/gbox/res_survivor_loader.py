"""Loader evidence for Resident Evil - Survivor (PSX) KERNEL.BIN.

game_id a178bf02b925ec44.  The PS-X EXE program (KERNEL.BIN) is the owned
loader: it names the disc containers it opens.  This module lifts those
CD-relative path strings straight out of the owned bytes and cross-checks the
named container against its byte-derived pBAV header, so loader and container
format are tied together by evidence instead of by a catalog label.

Offsets here are file-byte offsets inside the owned member (offset base = the
first byte of the extracted member), not ISO LBA.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from gbox.res_survivor_formats import (  # noqa: E402
    chd_path, detect_pbav, open_disc, parse_psx_exe, read_range,
)

KERNEL_MEMBER = "KERNEL.BIN"
PRINTABLE_RE = re.compile(rb"[ -~]{6,}")


def loader_cd_paths(exe_bytes):
    """CD-relative container paths named inside the loader.

    A hit is a printable run that carries both the parent-directory step
    ("..") and a "CD\\" directory component, i.e. a disc path, not code.
    """
    hits = []
    for m in PRINTABLE_RE.finditer(exe_bytes):
        raw = m.group()
        if b".." in raw and b"CD\\" in raw:
            parts = raw.replace(b"\\", b"/").split(b"/")
            hits.append({"offset": m.start(),
                         "text": raw.decode("ascii"),
                         "basename": parts[-1].decode("ascii")})
    return hits


def load_kernel_bytes(disc, members, member=KERNEL_MEMBER):
    by = {m["path"]: m for m in members}
    return read_range(disc, by[member])


def build_loader_report(path=None):
    """Loader paths, the load base and the container they name, from owned bytes."""
    disc, iso, members = open_disc(path)
    by = {m["path"]: m for m in members}
    kernel = load_kernel_bytes(disc, members)
    paths = loader_cd_paths(kernel)
    containers = []
    for p in paths:
        name = p["basename"]
        m = by.get(name)
        entry = {"loader_path": p["text"], "member": name,
                 "present_in_iso": bool(m)}
        if m:
            data = read_range(disc, m)
            entry["size"] = m["size"]
            entry["sha256"] = hashlib.sha256(data).hexdigest()
            entry["pbav"] = detect_pbav(data[:4096])
        containers.append(entry)
    return {"game_id": "a178bf02b925ec44",
            "title": "Resident Evil - Survivor (USA) [PSX]",
            "source": chd_path(path),
            "volume_id": iso["volume_id"],
            "byte_order": "little-endian (MIPS LE)",
            "offset_base": "file byte offset inside the extracted member",
            "kernel": {"member": KERNEL_MEMBER,
                       "size": len(kernel),
                       "sha256": hashlib.sha256(kernel).hexdigest(),
                       "exe": parse_psx_exe(kernel)},
            "loader_cd_paths": paths,
            "containers": containers}


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "res_survivor_loader.json"
    rep = build_loader_report()
    Path(out).write_text(json.dumps(rep, indent=2, sort_keys=True))
    print(json.dumps({"kernel": rep["kernel"],
                      "loader_cd_paths": rep["loader_cd_paths"],
                      "containers": rep["containers"]}, indent=2))
