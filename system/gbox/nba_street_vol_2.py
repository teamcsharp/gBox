"""NBA Street Vol. 2 (USA, GameCube GNZE69): inventory reader. Engine: EA EAGL.

Stage 1 (inventory) only. Verified on the owned build: ``xf/xf000001`` and ``xf/xf000002`` are BIGF archives with
empty member names whose members are little-endian-header 32-bit ELF relocatable objects (.data/.rel.data/.symtab).
The ELF *symbol table* carries the identity: ``__Model:<name>``, ``__BBOX:<name>``, ``__EAGL::TAR:::tar_<part>_<id>``
(texture-attachment records per body part) and ``__Morph:::morph.modelname``; the ``.data`` section holds EAGL
``__geoprimdata_*`` display-list geometry. No model reader exists yet: this module only counts what is provable.
"""
from __future__ import annotations

import re
import struct
from typing import Callable, Iterable

ReadFn = Callable[[int, int], bytes]   # read(absolute_offset, size)


def parse_bigf(read: ReadFn, base: int, size: int) -> list[dict]:
    """Parse a BIGF archive at ``base``; offsets are relative to the archive start, big-endian."""
    magic, _total, count, hdr = struct.unpack(">4sIII", read(base, 16))
    if magic != b"BIGF":
        raise ValueError("not a BIGF archive")
    buf = read(base + 16, hdr - 16)
    out, p = [], 0
    for _ in range(count):
        off, sz = struct.unpack_from(">II", buf, p)
        end = buf.index(b"\0", p + 8)
        out.append({"name": buf[p + 8:end].decode("latin1"), "off": off, "size": sz, "ok": off + sz <= size})
        p = end + 1
    return out


def elf_symbols(b: bytes) -> list[tuple[str, int, int, int]]:
    """(name, value, size, shndx) for an EA little-endian-header ELF32 relocatable object; [] if not ELF."""
    if b[:4] != b"\x7fELF" or len(b) < 0x34:
        return []
    e = "<" if b[5] == 1 else ">"
    shoff, = struct.unpack_from(e + "I", b, 0x20)
    shentsize, shnum = struct.unpack_from(e + "HH", b, 0x2E)
    if shoff + shnum * shentsize > len(b):   # e.g. xf000003 IABody.ord: section table past member end
        return []
    secs = [struct.unpack_from(e + "10I", b, shoff + i * shentsize) for i in range(shnum)]
    tabs = [s for s in secs if s[1] == 2]
    if not tabs:
        return []
    st = tabs[0]
    sr = secs[st[6]]
    strs = b[sr[4]:sr[4] + sr[5]]
    out = []
    for i in range(st[5] // 16):
        nm, val, sz, _info, _oth, shn = struct.unpack_from(e + "IIIBBH", b, st[4] + i * 16)
        out.append((strs[nm:strs.index(b"\0", nm)].decode("latin1"), val, sz, shn))
    return out


_TAR = re.compile(r"^__EAGL::TAR:::tar_([a-z0-9]{4})_(\d+)$")


def describe_object(b: bytes) -> dict:
    """Classify one ELF member by its EAGL symbols (models, bounding boxes, per-part texture records)."""
    syms = elf_symbols(b)
    models = sorted(n[len("__Model:::"):] for n, *_ in syms if n.startswith("__Model:::"))
    bbox = sorted(n[len("__BBOX:::"):] for n, *_ in syms if n.startswith("__BBOX:::"))
    parts = sorted({m.group(1) for n, *_ in syms if (m := _TAR.match(n))})
    morph = [n for n, *_ in syms if n.startswith("__Morph:::")]
    return {"size": len(b), "models": models, "bbox": bbox, "tar_parts": parts, "morph": morph,
            "geoprim": b.count(b"__geoprimdata"), "player_like": "head" in parts and "legs" in parts}


def census(members: Iterable[tuple[int, bytes]]) -> dict:
    """Count assets across (index, bytes) members; only ELF members with __Model symbols count as models."""
    n_elf = n_models = n_player = 0
    for _i, b in members:
        if b[:4] != b"\x7fELF":
            continue
        n_elf += 1
        d = describe_object(b)
        n_models += len(d["models"])
        n_player += d["player_like"]
    return {"elf_members": n_elf, "model_symbols": n_models, "player_like_objects": n_player}
