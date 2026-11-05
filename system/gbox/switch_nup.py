"""Nintendo Switch 2 ``.nup`` container — partial map (what is confirmed so far).

Measured on ``The Legend of Zelda Ocarina of TIme [04004860224DEC000].nup`` (2026-11-05), 23.30 GiB:

* ``NUP`` + version byte at ``0x00`` (``4e 55 50 01``)
* a table-of-contents sub-header ``TOC\\x01`` at ``0x90``
* a title id (Switch 2 ``04…`` prefix) in the header around ``0xc0``
* ``NCZ`` magic at ``0x368bb2``, ``0x754db2``, ``0xcc7da6`` — NCZ is the Switch 2 native compressed block format

Full decryption needs the Switch 2 master keys (keygen 3+) and an NCZ decompressor; neither is on the Spark yet.
This module maps the container structure so the catalog can at least recognise and inventory ``.nup`` files while
the decryption and emulation work proceeds (see docs/research/switch2.md).

It never reads keys or decrypts anything; it only reads headers.
"""
from __future__ import annotations

import re
import struct
from pathlib import Path

NUP_MAGIC = b"NUP\x01"
TOC_MAGIC = b"TOC\x01"
NCZ_MAGIC = b"NCZ"
TITLE_RE = re.compile(r"\[([0-9A-Fa-f]{16,17})\]")


def is_nup(path: str | Path) -> bool:
    with open(path, "rb") as fh:
        return fh.read(4) == NUP_MAGIC


def toc_offset(data: bytes) -> int:
    """Offset of the TOC sub-header, or -1."""
    return data.find(TOC_MAGIC)


def ncz_offsets(path: str | Path, limit: int = 16, scan_limit: int = 1 << 30) -> list[int]:
    """Offsets of NCZ compressed blocks (bounded scan of the first scan_limit bytes)."""
    out: list[int] = []
    with open(path, "rb") as fh:
        data = fh.read(min(scan_limit, Path(path).stat().st_size))
    idx = 0
    while len(out) < limit:
        i = data.find(NCZ_MAGIC, idx)
        if i < 0:
            break
        out.append(i)
        idx = i + 1
    return out


def title_id(path: str | Path) -> str | None:
    """The Switch 2 title id from the bracketed tag in the filename, else None."""
    m = TITLE_RE.search(Path(path).name)
    if m:
        return m.group(1).upper()
    return None


def catalog_fields(path: str | Path) -> tuple[str | None, dict]:
    """The catalog fields switch_nsp.catalog_fields supplies for .nsp: a serial (title id) and launch extras.

    No keys are read, so this returns an empty launch dict — the same shape, ready for when the keys and title
    key arrive. This is what lets the switch2 library scan .nup files into the catalog today.
    """
    return title_id(path), {}


def structure(path: str | Path) -> dict:
    """The container's shape: magic, TOC location, title id, and the NCZ block table (partial)."""
    p = Path(path)
    with open(p, "rb") as fh:
        head = fh.read(0x200)
    return {
        "path": str(p), "size": p.stat().st_size, "magic": "NUP",
        "version": head[3] if len(head) > 3 and head[:3] == b"NUP" else None,
        "toc_offset": toc_offset(head), "title_id": title_id(p),
        "ncz_blocks": ncz_offsets(p),
        "note": "partial map; decryption and NCZ decompression are not implemented yet",
    }
