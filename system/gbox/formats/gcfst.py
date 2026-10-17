"""GameCube / Wii disc filesystem table (FST) and disc header, shared by gcdisc (ISO/GCM), the GCZ inventories and
the fingerprinter.

FST: 12-byte entries {u8 is_dir, u24 name offset, u32 file offset | parent, u32 size | next index}; entry 0 is the
root (its 'next' = entry count); the name table follows the entries. Disc header: game id at 0, title at 0x20,
main.dol offset at 0x420, FST offset / size at 0x424 / 0x428 (Wii shifts offsets by 2).
"""
from __future__ import annotations

import struct


def disc_header(h: bytes) -> dict:
    """The first 0x440 bytes of a GC disc -> id, title, dol and FST offsets."""
    dol, fst_off, fst_size = struct.unpack_from(">III", h, 0x420)
    return {"game_id": h[:6].decode("ascii", "replace"), "title": h[0x20:0x60].split(b"\0")[0].decode("latin-1"),
            "dol_offset": dol, "fst_offset": fst_off, "fst_size": fst_size}


def parse_fst(fst: bytes, fst_off: int = 0) -> list[tuple[str, int, int, int]]:
    """[(path, file offset, size, disc offset of the FST entry)] for every file, in FST order (gcdisc's walk)."""
    n = struct.unpack_from(">I", fst, 8)[0]
    names = fst[n * 12:]
    out = []
    stack = [("", n)]
    i = 1
    while i < n:
        while stack and i >= stack[-1][1]:
            stack.pop()
        flags_name, a, b = struct.unpack_from(">III", fst, i * 12)
        is_dir, name_off = flags_name >> 24, flags_name & 0xFFFFFF
        name = names[name_off:names.index(b"\0", name_off)].decode("latin-1")
        prefix = stack[-1][0] if stack else ""
        if is_dir:
            stack.append((f"{prefix}{name}/", b))
        else:
            out.append((f"{prefix}{name}", a, b, fst_off + i * 12))
        i += 1
    return out


def build_fst(files: list[tuple[str, int, int]]) -> bytes:
    """[(path, offset, size)] -> an FST (directories created from the paths, entries sorted): for tests and writers."""
    tree: dict = {}
    for path, off, size in files:
        node = tree
        parts = path.split("/")
        for d in parts[:-1]:
            node = node.setdefault(d, {})
        node[parts[-1]] = (off, size)
    entries, names = [], bytearray()

    def name(s):
        o = len(names)
        names.extend(s.encode("latin-1") + b"\0")
        return o

    def add(node, parent):
        for k in sorted(node, key=str.lower):
            v = node[k]
            if isinstance(v, dict):
                idx = len(entries)
                entries.append([1 << 24 | name(k), parent, 0])
                add(v, idx)
                entries[idx][2] = len(entries)
            else:
                entries.append([name(k), v[0], v[1]])
    entries.append([1 << 24, 0, 0])
    add(tree, 0)
    entries[0][2] = len(entries)
    return b"".join(struct.pack(">III", *e) for e in entries) + bytes(names)
