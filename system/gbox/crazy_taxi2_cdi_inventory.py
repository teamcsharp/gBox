"""Owned-build manifest for the QuickSwap2 ``Crazy Taxi 2.cdi`` Dreamcast image (gBox game 45e9455ca5487e7d).

The reader in :mod:`gbox.crazy_taxi2` was written against this image, but the request's acceptance criteria
demand an *authoritative owned-build manifest*: the real source identity streamed from the bytes on disk, the
container's member table, the driver banks with hashes computed from the bytes actually read back, the
comparison against the reader's pinned ``crazy_taxi2.FILES_SHA256``, and one identified native target slot
(Axel, ``PP1A`` high-detail) with its slot and texture tables taken from 1ST_READ.BIN.

Everything here is read-only: the image is opened through :class:`gbox.gdrom.CDIRom` and the disc file is
opened for hashing only. Nothing is written to the disc, to the share or to any owned ROM.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

from . import crazy_taxi2 as c2

GAME_ID = "45e9455ca5487e7d"
TITLE = "Crazy Taxi 2"
PLATFORM = "dreamcast"
PRODUCT = c2.PRODUCT
DISC_NAME = "Crazy Taxi 2.cdi"
DISC_REL = "quickswap2/Emulation/_emulation/_dc iso/Crazy Taxi 2.cdi"
READER = "gbox.crazy_taxi2"
READER_VERSION = c2.READER_VERSION
CHUNK = 1 << 20

POL_RE = re.compile(r"^POL(PP[12][A-D])(H?)\.BIN$")
TEX_RE = re.compile(r"^TEX(PP[12][A-D])(H?)\.BIN$")

#: The one native target slot this ticket advances towards: Axel, high-detail model bank.
TARGET = {"key": "PP1A", "high": True, "driver": "Axel", "slot": "driver:axel"}


def sha256_bytes(b: bytes) -> str:
    """sha256 of a byte string."""
    return hashlib.sha256(b).hexdigest()


def file_sha256(path) -> str:
    """sha256 of a file on disk, streamed in 1 MiB chunks (never loads the whole image)."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _jsonable(v):
    """JSON-safe view of parser output (bytes -> digest, numpy -> python scalars)."""
    if isinstance(v, (bytes, bytearray)):
        return {"bytes": len(v), "sha256": sha256_bytes(bytes(v))}
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if not isinstance(v, (str, int, float, bool)) and hasattr(v, "tolist"):
        return _jsonable(v.tolist())
    if not isinstance(v, (str, int, float, bool)) and hasattr(v, "item"):
        return _jsonable(v.item())
    if isinstance(v, (int, float, str, bool)) or v is None:
        return v
    return repr(v)


class CachedDisc:
    """Disc reader that keeps every member it has read, so each bank is fetched once."""

    def __init__(self, disc):
        self._d = disc
        self._c: dict[str, bytes] = {}
        self.files = list(disc.files)

    def read(self, name: str) -> bytes:
        if name not in self._c:
            self._c[name] = self._d.read(name)
        return self._c[name]


def _executable(d, names) -> dict:
    """The image's own load executable (Dreamcast: 1ST_READ.BIN): identity plus ELF header facts."""
    n = "1ST_READ.BIN"
    if n not in names:
        return {"member": None}
    b = d.read(n)
    out = {"member": n, "bytes": len(b), "sha256": sha256_bytes(b), "elf_magic": b[:4] == b"\x7fELF"}
    if out["elf_magic"] and len(b) >= 28:
        end = "little" if b[5] == 1 else "big"
        out["class"] = "ELF32" if b[4] == 1 else "ELF64"
        out["byte_order"] = end
        out["e_type"] = int.from_bytes(b[16:18], end)
        out["e_machine"] = int.from_bytes(b[18:20], end)
        out["e_entry"] = hex(int.from_bytes(b[24:28], end))
    return out


def build(disc, disc_path=None) -> dict:
    """The authoritative owned-build manifest for the Crazy Taxi 2 image behind ``disc``."""
    d = disc if isinstance(disc, CachedDisc) else CachedDisc(disc)
    names = sorted(d.files)

    rows: dict[str, dict] = {}
    for key, driver in c2.DRIVERS.items():
        rows[key] = {"driver": driver, "slot": f"driver:{c2.SLUGS[key]}", "model": None, "high_model": None,
                     "texture": None, "high_texture": None}
    for n in names:
        m = POL_RE.match(n)
        if m:
            rows[m.group(1)]["high_model" if m.group(2) else "model"] = n
            continue
        m = TEX_RE.match(n)
        if m:
            rows[m.group(1)]["high_texture" if m.group(2) else "texture"] = n

    hashes: dict[str, str] = {}
    for key, row in rows.items():
        for field in ("model", "high_model", "texture", "high_texture"):
            n = row[field]
            if n:
                b = d.read(n)
                row[field + "_bytes"] = len(b)
                row[field + "_sha256"] = sha256_bytes(b)
                hashes[n] = row[field + "_sha256"]
    if "1ST_READ.BIN" in names:
        hashes["1ST_READ.BIN"] = sha256_bytes(d.read("1ST_READ.BIN"))
    for n in c2.FILES_SHA256:              # pinned members that are not a driver bank (POLPPL0, POLPSG0, ...)
        if n not in hashes and n in d.files:
            hashes[n] = sha256_bytes(d.read(n))

    identical = sorted(n for n, h in c2.FILES_SHA256.items() if hashes.get(n) == h)
    different = sorted(n for n, h in c2.FILES_SHA256.items() if n in hashes and hashes[n] != h)
    missing = sorted(n for n in c2.FILES_SHA256 if n not in hashes)

    walk: dict[str, dict] = {}
    for n in names:
        if n.startswith("POL") and n.endswith(".BIN"):
            try:
                objs = c2.walk(d.read(n))
            except Exception as exc:  # noqa: BLE001 - a malformed bank is a finding, not a crash
                walk[n] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            else:
                walk[n] = {"ok": True, "objects": len(objs)}

    target = _target(d, rows)
    exe = _executable(d, names)

    src = {"path": str(disc_path) if disc_path else None, "relative": DISC_REL,
           "container": "DiscJuggler .cdi, read by gbox.gdrom.CDIRom", "bytes": None, "sha256": None}
    if disc_path:
        p = Path(disc_path)
        src["bytes"] = p.stat().st_size
        src["sha256"] = file_sha256(p)

    return {
        "game_id": GAME_ID, "title": TITLE, "platform": PLATFORM, "product": PRODUCT,
        "source": src,
        "reader": {"module": READER, "version": READER_VERSION},
        "members": len(names),
        "executable": exe,
        "byte_order": exe.get("byte_order"),
        "offset_base": target.get("tables", {}).get("va") if isinstance(target.get("tables"), dict) else None,
        "banks": rows,
        "pinned_comparison": {"pinned_count": len(c2.FILES_SHA256), "identical": identical,
                              "different": different, "missing": missing,
                              "same_build": not different and not missing},
        "walk": walk,
        "target": target,
    }


def _target(d, rows: dict) -> dict:
    """The identified native target slot: its banks, hashes and the 1ST_READ.BIN slot/texture tables."""
    key, hi = TARGET["key"], TARGET["high"]
    t = {"key": key, "driver": TARGET["driver"], "slot": TARGET["slot"],
         "model": rows[key]["high_model"] if hi else rows[key]["model"],
         "texture": rows[key]["high_texture"] if hi else rows[key]["texture"],
         "tables": None, "error": None}
    try:
        files = c2.driver_files(d, key, hi)
        t["tables"] = _jsonable(files["tables"])
        t["pol_sha256"] = sha256_bytes(files["pol"])
        t["tex_sha256"] = sha256_bytes(files["tex"])
        t["executable_sha256"] = sha256_bytes(files["exe"])
    except Exception as exc:  # noqa: BLE001
        t["error"] = f"{type(exc).__name__}: {exc}"
    return t


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Crazy Taxi 2 (DC) owned-build manifest")
    ap.add_argument("cdi")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    from .gdrom import CDIRom
    t0 = time.time()
    man = build(CDIRom(a.cdi), Path(a.cdi))
    man["elapsed_s"] = round(time.time() - t0, 2)
    text = json.dumps(man, indent=1)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
