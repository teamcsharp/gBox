"""Minimal CRI CPK (@UTF) archive reader: header table + TOC file list.

Read-only; plain (non-encrypted) @UTF tables only.  CRILAYLA-compressed
members are reported via `extract_size != size` but not decompressed here.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

_FMT = {0: ("B", 1), 1: ("b", 1), 2: (">H", 2), 3: (">h", 2), 4: (">I", 4), 5: (">i", 4),
        6: (">Q", 8), 7: (">q", 8), 8: (">f", 4)}


def parse_utf(buf: bytes) -> tuple[str, list[dict]]:
    if buf[:4] != b"@UTF":
        raise ValueError("not @UTF (encrypted or corrupt)")
    size, rows_off, str_off, data_off, name_off, ncols, roww, nrows = struct.unpack_from(">IIIIIHHI", buf, 4)
    base = 8
    strings = buf[base + str_off: base + data_off]

    def s(off: int) -> str:
        e = strings.index(b"\0", off)
        return strings[off:e].decode("utf-8", "replace")

    p = base + 0x18
    cols = []
    for _ in range(ncols):
        flag = buf[p]; p += 1
        name = s(struct.unpack_from(">I", buf, p)[0]); p += 4
        stor, typ = flag & 0xF0, flag & 0x0F
        const = None
        if stor == 0x30:
            const, p = _val(buf, p, typ, s, base + data_off)
        cols.append((name, stor, typ, const))
    rows = []
    for r in range(nrows):
        q = base + rows_off + r * roww
        row = {}
        for name, stor, typ, const in cols:
            if stor == 0x50:
                row[name], q = _val(buf, q, typ, s, base + data_off)
            elif stor == 0x30:
                row[name] = const
            else:
                row[name] = None
        rows.append(row)
    return s(name_off), rows


def _val(buf, p, typ, s, data_base):
    if typ in _FMT:
        f, n = _FMT[typ]
        return struct.unpack_from(f if f[0] in ">" else "<" + f, buf, p)[0], p + n
    if typ == 0xA:
        return s(struct.unpack_from(">I", buf, p)[0]), p + 4
    if typ == 0xB:
        off, sz = struct.unpack_from(">II", buf, p)
        return (data_base + off, sz), p + 8
    raise ValueError(f"unknown @UTF column type {typ:#x}")


@dataclass
class CpkEntry:
    path: str
    offset: int
    size: int
    extract_size: int

    @property
    def compressed(self) -> bool:
        return self.extract_size != self.size


def read_cpk(read_at) -> tuple[dict, list[CpkEntry]]:
    """read_at(offset,size)->bytes. Returns (header row, TOC entries)."""
    head = read_at(0, 0x10)
    if head[:4] != b"CPK ":
        raise ValueError("not a CPK")
    tsize = struct.unpack_from("<Q", head, 8)[0]
    _, hrows = parse_utf(read_at(0x10, tsize))
    h = hrows[0]
    toc_off = h["TocOffset"]
    content = h["ContentOffset"]
    thead = read_at(toc_off, 0x10)
    if thead[:4] != b"TOC ":
        raise ValueError("bad TOC")
    tsz = struct.unpack_from("<Q", thead, 8)[0]
    _, rows = parse_utf(read_at(toc_off + 0x10, tsz))
    base = min(toc_off, content) if content else toc_off
    out = []
    for r in rows:
        d = r.get("DirName") or ""
        path = f"{d}/{r['FileName']}" if d else r["FileName"]
        out.append(CpkEntry(path, base + r["FileOffset"], r["FileSize"], r["ExtractSize"]))
    return h, out


# ---- CRILAYLA decompression ----------------------------------------------

def crilayla_decompress(data: bytes) -> bytes:
    """Decompress a CRILAYLA blob (as used for compressed CPK members)."""
    if data[:8] != b"CRILAYLA":
        raise ValueError("not CRILAYLA")
    usize, hoff = struct.unpack_from("<II", data, 8)
    prefix = data[0x10 + hoff: 0x10 + hoff + 0x100]
    if len(prefix) != 0x100:
        raise ValueError("truncated CRILAYLA header")
    out = bytearray(usize)
    pos = usize  # fill backwards
    src = 0x10 + hoff - 1  # last byte of compressed stream
    cur = 0
    nbits = 0

    def bits(n: int) -> int:
        nonlocal src, cur, nbits
        v = 0
        for _ in range(n):
            if nbits == 0:
                cur = data[src]; src -= 1; nbits = 8
            nbits -= 1
            v = (v << 1) | ((cur >> nbits) & 1)
        return v

    while pos > 0:
        if bits(1):
            off = bits(13) + 3
            length = 3
            for lvl in (2, 3, 5):
                t = bits(lvl); length += t
                if t != (1 << lvl) - 1:
                    break
            else:
                while True:
                    t = bits(8); length += t
                    if t != 255:
                        break
            for _ in range(length):
                if pos <= 0:
                    break
                pos -= 1
                out[pos] = out[pos + off]
        else:
            pos -= 1
            out[pos] = bits(8)
    return prefix + bytes(out)
