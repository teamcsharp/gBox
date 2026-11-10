"""DOA6 Arcade (TeknoParrot, muscle_apm3.exe) CharacterEditor.rdb slot probe.

Index entry names look like ``<hexoff>@<hexcrc>[#<bin>][&<sub>]`` and locate an
IDRK entry inside ``CharacterEditor.rdb.bin<bin>[_<sub>]`` at byte ``hexoff``.
Models are G1M (``_M1G7300``, little-endian chunk table), textures G1T (``GT1G``).
"""
from __future__ import annotations

import re
import struct
from pathlib import Path

from gbox import doa6_inventory as inv

NAME_RE = re.compile(r"([0-9a-f]+)@([0-9a-f]+)(?:#(\d+))?(?:&(\d+))?")


def parse_entry_name(name: str, rdb_stem: str = "CharacterEditor") -> dict:
    """Split an index entry name into payload bin file name and offset."""
    m = NAME_RE.fullmatch(name)
    if not m:
        raise ValueError(f"unrecognised DRK entry name {name!r}")
    bin_name = f"{rdb_stem}.rdb.bin" + (m[3] or "") + (f"_{m[4]}" if m[4] else "")
    return {"bin": bin_name, "offset": int(m[1], 16), "crc": int(m[2], 16)}


def g1m_chunks(buf: bytes) -> dict:
    """Walk the G1M chunk table; chunk = tag[4] version[4] size[4 LE]."""
    if buf[:8] != b"_M1G7300":
        raise ValueError(f"not a G1M v7300 (magic {buf[:8]!r})")
    total, hdr, _pad, count = struct.unpack_from("<4I", buf, 8)
    chunks, p = [], hdr
    for _ in range(count):
        if p + 12 > len(buf):
            raise ValueError("G1M chunk table runs past end of data")
        tag = buf[p:p + 4][::-1].decode("latin1")
        size = struct.unpack_from("<I", buf, p + 8)[0]
        if size < 12:
            raise ValueError(f"bad G1M chunk size {size} at {p:#x}")
        chunks.append({"tag": tag, "offset": p, "size": size})
        p += size
    return {"total": total, "header": hdr, "count": count, "chunks": chunks,
            "consistent": p <= total and total == len(buf)}


def g1t_header(buf: bytes) -> dict:
    if buf[:4] != b"GT1G":
        raise ValueError(f"not a G1T (magic {buf[:4]!r})")
    version = buf[4:8].decode("latin1")
    total, table_off, count = struct.unpack_from("<III", buf, 8)
    return {"version": version, "total": total, "table_offset": table_off, "textures": count}


def read_entry(root: str | Path, name: str, limit: int | None = None) -> bytes:
    loc = parse_entry_name(name)
    return inv.read_bin_entry(Path(root) / loc["bin"], loc["offset"], limit=limit)


def probe_target(root: str | Path, name: str) -> dict:
    """Decompress one named model entry and describe its chunk layout."""
    data = read_entry(root, name)
    info = g1m_chunks(data)
    info["name"] = name
    info["sha256"] = __import__("hashlib").sha256(data).hexdigest()
    info["size"] = len(data)
    return info
