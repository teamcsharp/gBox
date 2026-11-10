"""Wii/GameCube DOL executable header parser (read-only)."""
from __future__ import annotations

import struct


def parse_dol(data: bytes) -> dict:
    """Return {text, data, bss_addr, bss_size, entry, size}; sections are [{index, file_off, addr, size}].

    Header: 7 text + 11 data sections; offsets @0x00, load addrs @0x48, sizes @0x90 (u32 BE), bss @0xD8, entry @0xE0.
    """
    if len(data) < 0x100:
        raise ValueError("dol: header truncated")
    offs = struct.unpack_from(">18I", data, 0)
    addrs = struct.unpack_from(">18I", data, 0x48)
    sizes = struct.unpack_from(">18I", data, 0x90)
    bss_addr, bss_size, entry = struct.unpack_from(">III", data, 0xD8)
    text, dat, end = [], [], 0x100
    for i in range(18):
        if not sizes[i]:
            continue
        if offs[i] < 0x100 or offs[i] + sizes[i] > len(data):
            raise ValueError(f"dol: section {i} out of range")
        sec = {"index": i, "file_off": offs[i], "addr": addrs[i], "size": sizes[i]}
        (text if i < 7 else dat).append(sec)
        end = max(end, offs[i] + sizes[i])
    if not text:
        raise ValueError("dol: no text section")
    if not any(s["addr"] <= entry < s["addr"] + s["size"] for s in text):
        raise ValueError("dol: entry point outside text sections")
    return {"text": text, "data": dat, "bss_addr": bss_addr, "bss_size": bss_size,
            "entry": entry, "size": end}


def find_strings(data: bytes, suffixes=(b".arc", b".rel", b".tpl", b".bin", b".dat"), minlen: int = 5) -> list[str]:
    """Printable path-like strings ending in one of `suffixes` (asset-loader hints), de-duplicated in order."""
    import re

    pat = re.compile(rb"[\x20-\x7e]{%d,}" % minlen)
    out: list[str] = []
    for m in pat.finditer(data):
        s = m.group()
        if s.lower().endswith(tuple(suffixes)) and s.decode() not in out:
            out.append(s.decode())
    return out
