"""Thrasher: Skate and Destroy (PSX, USA, SLUS-00935) read-only disc inventory.

Analysis-stage evidence for request #6214: classifies the disc's ISO9660 files into boot EXE, level ZALs, shared
ZALs, character/level sound banks (ZSD) and movies (STR), and parses the PS-X EXE header of the boot executable.
Nothing is written to the disc image (``RawBin(writable=False)``).

``python -m gbox.thrasher_inventory <disc.bin>`` prints the JSON report.
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
import sys

BOOT_EXE = "SLUS_009.35"
BOOT_SHA256 = "56333fe9cadc2de64dffc69d0898528d11b13206c87edf853bfd35cbcbf14dfe"
ZAL_MAGIC = bytes.fromhex("1c51812a")            # first dword of every .ZAL container (0x2A81511C LE)
SHARED_ZALS = {"GEOMETRY", "MATERIAL", "MISCDATA", "MOTION", "RBINTART", "SYSTEM", "TABLES", "REPLAY"}
LEVEL_CITIES = {"HM": "Hometown", "IN": "Indus/Kol/Soba (Inner)", "LA": "Los Angeles", "NY": "New York",
                "SF": "San Francisco"}


def parse_psx_exe(b: bytes) -> dict:
    """PS-X EXE header fields (pc0, gp0, t_addr, t_size, sp)."""
    if b[:8] != b"PS-X EXE":
        raise ValueError("not a PS-X EXE")
    pc0, gp0, t_addr, t_size = struct.unpack_from("<4I", b, 0x10)
    sp_base = struct.unpack_from("<I", b, 0x30)[0]
    return {"pc0": pc0, "gp0": gp0, "t_addr": t_addr, "t_size": t_size, "sp_base": sp_base,
            "text_fits": len(b) >= 0x800 + t_size}


def parse_system_cnf(b: bytes) -> dict:
    out = {}
    for line in b.replace(b"\x1a", b"").decode("ascii", "replace").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip().upper()] = v.strip()
    return out


def classify(name: str) -> str:
    """Category of an ISO file name: boot/exe/level/shared/sfx_char/sfx_level/sfx_common/speech/music/movie/data/pad."""
    up = name.upper().split(";")[0]
    base = up.rsplit("/", 1)[-1]
    stem = base.rsplit(".", 1)[0]
    if up == "SYSTEM.CNF":
        return "boot_cnf"
    if base == BOOT_EXE.upper():
        return "boot_exe"
    if base.endswith(".EXE"):
        return "exe"
    if base.endswith(".ZAL"):
        return "shared_zal" if stem in SHARED_ZALS else "level_zal"
    if base.endswith(".ZSD"):
        if re.fullmatch(r"SFXCHR\d\d", stem):
            return "sfx_char"
        if re.fullmatch(r"SFXLEV\d\d", stem):
            return "sfx_level"
        if stem == "MUSIC":
            return "music"
        if stem == "SPEECH":
            return "speech"
        return "sfx_common"
    if base.endswith(".STR"):
        return "movie"
    if base.endswith(".NUL"):
        return "pad"
    return "data"


def level_city(name: str) -> str | None:
    stem = name.upper().split(";")[0].rsplit("/", 1)[-1].rsplit(".", 1)[0]
    m = re.match(r"([A-Z]{2})_", stem)
    return LEVEL_CITIES.get(m.group(1)) if m else None


def inventory(files: dict[str, tuple[int, int]]) -> dict:
    """Summarise an ISO file map {name: (lba, size)}."""
    cats: dict[str, dict] = {}
    for name, (lba, size) in sorted(files.items(), key=lambda kv: kv[1][0]):
        c = cats.setdefault(classify(name), {"count": 0, "bytes": 0, "files": []})
        c["count"] += 1
        c["bytes"] += size
        c["files"].append({"name": name, "lba": lba, "size": size})
    levels = [{"name": f["name"], "city": level_city(f["name"])} for f in cats.get("level_zal", {}).get("files", [])]
    return {"categories": cats, "levels": levels, "n_files": len(files),
            "characters": cats.get("sfx_char", {}).get("count", 0)}


def probe(disc) -> dict:
    """Full report from an opened RawBin/PSXDisc: inventory + boot EXE header + ZAL magic check."""
    exe = disc.read(BOOT_EXE)
    rep = inventory(disc.files)
    rep["system_cnf"] = parse_system_cnf(disc.read("SYSTEM.CNF"))
    rep["boot_exe"] = {"name": BOOT_EXE, "size": len(exe), "sha256": hashlib.sha256(exe).hexdigest(),
                       **parse_psx_exe(exe)}
    zals = [f["name"] for k in ("level_zal", "shared_zal") for f in rep["categories"].get(k, {}).get("files", [])]
    rep["zal_magic_ok"] = {n: disc.read(n)[:4] == ZAL_MAGIC for n in zals}
    return rep


def main(argv=None) -> int:
    from .psxdisc import RawBin
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(__doc__)
        return 2
    d = RawBin(argv[0], writable=False)
    try:
        rep = probe(d)
    finally:
        d.close()
    for c in rep["categories"].values():
        c.pop("files")
    print(json.dumps(rep, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
