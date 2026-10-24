"""Owned-build inventory for Super Smash Bros. Melee (GameCube, GALE01): streamed source hash, disc layout, main.dol
hash, and a per-fighter census of costume files (Pl<code><Costume>.dat) checked against the FIGHTERS table.
Read-only: the source image (ISO/GCM/GCZ) is never modified."""
from __future__ import annotations

import hashlib
import json
import re
import struct
import sys
from pathlib import Path

from .gcdisc import GCDisc
from .melee_models import FIGHTERS

COSTUME_RE = re.compile(r"^Pl([A-Z][a-z])([A-Za-z]{2})\.dat$")


def sha256_file(path, chunk=1 << 22) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(chunk):
            h.update(b)
    return h.hexdigest()


def inventory(src, hash_source: bool = True) -> dict:
    src = Path(src)
    d = GCDisc(src)
    try:
        dol = d.dol()
        dol_off = struct.unpack(">I", d._r(0x420, 4))[0]
        fst_off, fst_size = struct.unpack(">II", d._r(0x424, 8))
        codes = {c: n for n, c in FIGHTERS}
        census: dict[str, dict] = {}
        for name, (off, size) in sorted(d.files.items()):
            m = COSTUME_RE.match(name.split("/")[-1])
            if m and m.group(1) in codes:
                e = census.setdefault(codes[m.group(1)], {"code": m.group(1), "costumes": {}, "base": None})
                e["costumes"][m.group(2)] = {"path": name, "disc_offset": off, "size": size}
            m2 = re.match(r"^Pl([A-Z][a-z])\.dat$", name.split("/")[-1])
            if m2 and m2.group(1) in codes:
                e = census.setdefault(codes[m2.group(1)], {"code": m2.group(1), "costumes": {}, "base": None})
                e["base"] = {"path": name, "disc_offset": off, "size": size}
        missing = [n for n, _ in FIGHTERS if n not in census]
        return {
            "source": str(src), "source_size": src.stat().st_size,
            "source_sha256": sha256_file(src) if hash_source else None,
            "container": "GCZ (Dolphin zlib blocks)" if src.suffix.lower() == ".gcz" else "GC ISO/GCM",
            "byte_order": "big-endian (PowerPC)", "offset_base": "disc offset 0 (decompressed image)",
            "game_id": d.game_id, "title": d.title, "revision": d._r(7, 1)[0],
            "fst": {"offset": fst_off, "size": fst_size, "files": len(d.files)},
            "main_dol": {"disc_offset": dol_off, "size": len(dol), "sha256": hashlib.sha256(dol).hexdigest()},
            "fighters_table": len(FIGHTERS), "fighters_found": len(census), "fighters_missing": missing,
            "census": census,
            "target_slot": {"fighter": "Peach", "file": "PlPeNr.dat", "costume_file_present": "Nr" in census.get("Peach", {}).get("costumes", {})},
        }
    finally:
        d.f.close()


if __name__ == "__main__":
    out = inventory(sys.argv[1], hash_source="--no-hash" not in sys.argv)
    txt = json.dumps(out, indent=1)
    if len(sys.argv) > 2 and not sys.argv[2].startswith("--"):
        Path(sys.argv[2]).write_text(txt)
    print(json.dumps({k: v for k, v in out.items() if k != "census"}, indent=1))
