"""Verified executable layer for Dead or Alive (Japan, Sega Saturn), game f01738d1a4522208.

Source: ISO9660 member ``00DOA.BIN`` (LBA 29, 734,684 B) of
"Dead or Alive (Japan).chd", read with ``gbox.chd.ChdDisc``. Authoritative
SHA-256 (streamed from the CHD, not copied from an earlier scratch file):
83729ccaaa72b5982b6010aabe7fe4dc160d00650f70b0e95a40ddab05fb7c72.
Earlier notes quoting b5f37a71... described the wrong bytes (an ISO directory
dump); do not reuse them.

Layout facts proven here: big-endian SH-2 code from file offset 0; the Saturn
IP.BIN header (sector 0) gives 1st-read address 0x06004000, so
``vaddr = 0x06004000 + file_offset``. Literal-pool words that point at inline
filename strings (``mov.l @(disp,PC),Rn``) are located with ``string_xrefs``.
This is an inventory/analysis aid, not a model reader or writer.
"""
from __future__ import annotations

import hashlib
import re
import struct

GAME_ID = "f01738d1a4522208"
EXE_NAME = "00DOA.BIN"
EXE_SIZE = 734684
EXE_SHA256 = "83729ccaaa72b5982b6010aabe7fe4dc160d00650f70b0e95a40ddab05fb7c72"
LOAD_BASE = 0x06004000
_NAME = re.compile(rb"[A-Z0-9_]{1,12}\.BIN")


def ip_header(sector0: bytes) -> dict:
    """Parse the Saturn IP.BIN header from the first 2048-byte data sector."""
    if sector0[:15] != b"SEGA SEGASATURN":
        raise ValueError("sector 0 is not a Saturn IP.BIN header")
    return {
        "product": sector0[0x20:0x2A].decode("ascii", "replace").strip(),
        "version": sector0[0x2A:0x30].decode("ascii", "replace").strip(),
        "date": sector0[0x30:0x38].decode("ascii", "replace").strip(),
        "title": sector0[0x60:0xD0].decode("ascii", "replace").strip(),
        "ip_size": struct.unpack_from(">I", sector0, 0xE0)[0],
        "first_read_addr": struct.unpack_from(">I", sector0, 0xF0)[0],
        "first_read_size": struct.unpack_from(">I", sector0, 0xF4)[0],
    }


def verify_exe(data: bytes) -> dict:
    sha = hashlib.sha256(data).hexdigest()
    return {"size": len(data), "sha256": sha, "ok": len(data) == EXE_SIZE and sha == EXE_SHA256}


def read_exe(chd_path) -> bytes:
    from gbox.chd import ChdDisc
    disc = ChdDisc(chd_path)
    try:
        return disc.read(EXE_NAME)
    finally:
        disc.close()


def name_table(data: bytes, start: int, stride: int = 12) -> list[str]:
    """Consecutive NUL-padded ``*.BIN`` entries starting at ``start``."""
    out, o = [], start
    while o + stride <= len(data):
        z = data[o:o + stride].split(b"\0")[0]
        if not _NAME.fullmatch(z):
            break
        out.append(z.decode())
        o += stride
    return out


def inline_strings(data: bytes, lo: int = 0) -> list[tuple[int, str]]:
    return [(m.start(), m.group().decode()) for m in _NAME.finditer(data, lo)]


def literal_words(data: bytes, base: int = LOAD_BASE) -> dict[int, list[int]]:
    """Map file offset -> offsets of 2-aligned big-endian words equal to base+offset."""
    out: dict[int, list[int]] = {}
    for o in range(0, len(data) - 3, 2):
        w = struct.unpack_from(">I", data, o)[0]
        if base <= w < base + len(data):
            out.setdefault(w - base, []).append(o)
    return out


def load_sites(data: bytes, literal_off: int) -> list[int]:
    """File offsets of ``mov.l @(disp,PC),Rn`` instructions reading the literal at ``literal_off``."""
    out = []
    for a in range(0, len(data) - 1, 2):
        w = (data[a] << 8) | data[a + 1]
        if w >> 12 == 0xD and ((a + 4) & ~3) + (w & 0xFF) * 4 == literal_off:
            out.append(a)
    return out


def string_xrefs(data: bytes, base: int = LOAD_BASE, lo: int = 0x3B000) -> list[dict]:
    """Inline filename strings referenced by a literal-pool pointer, with the loading instructions."""
    words = literal_words(data, base)
    res = []
    for off, name in inline_strings(data, lo):
        for lit in words.get(off, []):
            res.append({"name": name, "string_off": off, "literal_off": lit,
                        "load_sites": [base + s for s in load_sites(data, lit)]})
    return res
