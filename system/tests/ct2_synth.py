"""Synthetic Crazy Taxi 2 driver files for the tests: a pol file of box parts in the game's object layout, a tex file
with two textures, and a fake 1ST_READ.BIN carrying the slot table, slot count, texture table and pol buffer size the
way the owned builds do. No game data."""
import struct

import numpy as np

from gbox import crazy_taxi2 as c2

# part -> (x range, y range, z range) in its own joint frame (x along the bone)
BOXES = {
    "koshi": ((-0.2, 2.0), (-1.0, 1.0), (-1.5, 1.5)),
    "mune": ((0.0, 5.0), (-1.0, 1.0), (-1.8, 1.8)),
    "atama": ((-1.0, 1.0), (-0.8, 2.5), (-1.0, 1.0)),
    "kata_l": ((-0.5, 2.5), (-0.5, 0.5), (-0.4, 0.6)), "kata_r": ((-0.5, 2.5), (-0.5, 0.5), (-0.6, 0.4)),
    "ude_l": ((-0.3, 2.6), (-0.4, 0.4), (-0.4, 0.5)), "ude_r": ((-0.3, 2.6), (-0.4, 0.4), (-0.5, 0.4)),
    "te_l": ((-0.2, 1.5), (-0.6, 0.4), (-0.3, 0.4)), "te_r": ((-0.2, 1.5), (-0.6, 0.4), (-0.4, 0.3)),
    "momo_l": ((-0.8, 4.0), (-1.0, 1.0), (-0.6, 1.2)), "momo_r": ((-0.8, 4.0), (-1.0, 1.0), (-1.2, 0.6)),
    "sune_l": ((-0.6, 4.5), (-0.8, 0.8), (-0.6, 0.8)), "sune_r": ((-0.6, 4.5), (-0.8, 0.8), (-0.8, 0.6)),
    "kakato_l": ((0.0, 1.2), (-0.7, 2.0), (-0.6, 0.6)), "kakato_r": ((0.0, 1.2), (-0.7, 2.0), (-0.6, 0.6)),
}
for s in "lr":
    for pose in ("ch", "gu", "ok"):
        BOXES[f"te_{s}_{pose}"] = BOXES[f"te_{s}"]
ACCESSORY = ((2.0, 2.5), (-0.4, 0.4), (-0.4, 0.4))       # a wristband, far from its joint

TEX_BASE = 0x0CB60000
TEXTURES = [(16, 16, 1, 1), (16, 16, 2, 3)]              # (w, h, pixel format, data format): twiddled 565, VQ 4444
EXE_SIZE = 0x4000
VA = {"slots": 0x0C011000, "count": 0x0C011400, "tex": 0x0C011800, "alloc": 0x0C011C00,
      "slot_ptrs": 0x0C012000, "tex_ptrs": 0x0C012100}
VA_H = {k: v + 0x200 if k in ("slots", "count", "tex", "alloc") else v + 0x40 for k, v in VA.items()}   # high detail


def box(lo, hi):
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    P = np.array([[x, y, z] for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)], float)
    T = [(0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 4, 5), (0, 5, 1), (2, 3, 7), (2, 7, 6), (0, 2, 6), (0, 6, 4),
         (1, 5, 7), (1, 7, 3)]
    return P, T


def mesh_bytes(P, T, tex=0, w=16, h=16) -> bytes:
    hd = bytearray(c2.MESH_HEADER)
    tsp = 0x2009A400 | ((w.bit_length() - 4) << 3) | (h.bit_length() - 4)
    struct.pack_into("<4I", hd, 0, 0x800000AC, 0x83000000, tsp, 0x08000000)
    c = (P.min(0) + P.max(0)) / 2
    struct.pack_into("<4f", hd, 0x10, *c, float(np.linalg.norm(P - c, axis=1).max()))
    struct.pack_into("<I", hd, 0x20, tex)
    struct.pack_into("<f", hd, 0x28, 0.75)
    struct.pack_into("<8f", hd, 0x2C, 1, 1, 1, 1, 0, 1, 1, 1)
    body = struct.pack("<Ii", 0x6A, len(T))
    for t in T:
        for i in t:
            p = P[i]
            n = p / (np.linalg.norm(p) or 1)
            body += struct.pack("<8f", *p, *n, (p[0] % 1.0), (p[1] % 1.0))
    struct.pack_into("<I", hd, 0x4C, len(body))
    return bytes(hd) + body


def object_bytes(P, T, tex=0) -> bytes:
    c = (P.min(0) + P.max(0)) / 2
    return struct.pack("<II4f", 1, 1, *c, float(np.linalg.norm(P - c, axis=1).max())) + mesh_bytes(P, T, tex) + \
        struct.pack("<II", 0, 3 * len(T))


EMPTY = struct.pack("<II4f", c2.EMPTY, 3, 0, 0, 0, 0) + struct.pack("<II", 0, 0)


def driver(parts=c2.PARTS, accessory: bool = False, empties: int = 3) -> dict:
    """{pol, tex, exe, tables, names}: the parts in reverse name order in the file (as the game's files are not in
    slot order), `empties` empty objects, the slot table sorted by part name with the empties first."""
    names = list(parts) + (["ude_lB"] if accessory else [])
    order = sorted(names, reverse=True)
    chunks, offs = [], {}
    o = 0
    for k in range(empties):
        offs[f"zz_empty{k}"] = o
        chunks.append(EMPTY)
        o += len(EMPTY)
    for n in order:
        lo, hi = zip(*(ACCESSORY if n == "ude_lB" else BOXES[n]))
        P, T = box(lo, hi)
        b = object_bytes(P, T, tex=(1 if n == "atama" else 0))
        offs[n] = o
        chunks.append(b)
        o += len(b)
    pol = b"".join(chunks)
    slot_names = [f"zz_empty{k}" for k in range(empties)][:1] + sorted(names) + \
        [f"zz_empty{k}" for k in range(1, empties)]
    slots = [offs[n] for n in slot_names]
    tex, table, off = b"", [], 0
    rng = np.random.default_rng(3)
    for w, h, pix, fmt in TEXTURES:
        size = c2.tex_size(w, h, pix, fmt)
        off = (off + 31) & ~31
        tex = tex.ljust(off, b"\0") + bytes(rng.integers(0, 256, size, dtype=np.uint8))
        table.append({"w": w, "h": h, "pix": pix, "fmt": fmt, "offset": off, "size": size})
        off += size
    exe = bytearray(EXE_SIZE)

    def put(va, fmt, *v):
        struct.pack_into(fmt, exe, va - c2.EXE_BASE, *v)
    for va in (VA, VA_H):                                    # the same model at both detail levels
        put(va["slots"], f"<{len(slots)}I", *slots)
        put(va["count"], "<I", len(slots))
        for i, t in enumerate(table):
            put(va["tex"] + 16 * i, "<HHBBHII", t["w"], t["h"], t["pix"], t["fmt"], 0, TEX_BASE + t["offset"], 0)
        put(va["tex"] + 16 * len(table), "<4I", *[0xFFFFFFFF] * 4)
        put(va["alloc"], "<I", ((len(pol) + 31) & ~31) // 4)
        put(va["slot_ptrs"], "<I", va["slots"])
        put(va["tex_ptrs"], "<I", va["tex"])
    tables = {"slots": slots, "textures": table, "alloc": (len(pol) + 31) & ~31,
              "va": {"slots": VA["slots"], "textures": VA["tex"], "alloc": VA["alloc"]}}
    return {"pol": pol, "tex": tex, "exe": bytes(exe), "tables": tables, "offsets": offs}


def known(monkeypatch, alloc_extra: int = 0):
    """Make the synthetic 1ST_READ.BIN a known build (model 0 of every player key)."""
    entry = {"normal": (VA["slot_ptrs"], VA["count"], VA["tex_ptrs"], VA["alloc"]),
             "high": (VA_H["slot_ptrs"], VA_H["count"], VA_H["tex_ptrs"], VA_H["alloc"])}
    monkeypatch.setattr(c2, "known_build", lambda exe: entry)
    monkeypatch.setattr(c2, "PLAYER_KEYS", ("PP2A",))
