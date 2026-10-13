"""Crazy Taxi 2 (Dreamcast; gBox game id 45e9455ca5487e7d and the other CT2 entries in GAME_IDS): the `pol*.bin` models
and the eight drivers as rigged, textured GLBs (request #1482).

Owned image: QuickSwap2 `Crazy Taxi 2.cdi` (DiscJuggler, 787688567 bytes; gbox.gdrom.CDIRom reads it), IP.BIN
MK-51136 V1.000 2001-05-24 "CRAZY TAXI 2", 1ST_READ.BIN sha256 69f7bd24... (FILES_SHA256 below).

Not Ninja and not the GameCube Crazy Taxi `.shp`: there is no NJCM/NJTL chunk anywhere in these files. Every
`POL*.BIN` is a run of little-endian objects in the Sega NAOMI-library layout (the PowerVR TA parameter words are
stored verbatim):

* object: u32 flags (1; 0xFFFFFFFF with second word 3 = an empty slot), u32 flags, f32 centre xyz, f32 bounding
  radius, then meshes, then u32 0 + u32 vertex-entry count (full vertices + references) as the terminator;
* mesh (0x50-byte header): u32 PCW (top bit set), ISP/TSP, TSP, TCW words, f32 centre xyz + radius @0x10, u32 texture
  index @0x20, u32 @0x24, f32 @0x28, base and offset ARGB (8 f32) @0x2c, u32 strip-data size @0x4c;
* strip data: u32 flags + u32 count; flags & 0x08 = a triangle list of `count` triangles, otherwise a strip of
  `count` vertices; an entry is a full vertex (8 f32: position, normal, u, v) or a reference (8 bytes: a word with
  top nibble 5, then a signed byte offset from the end of the reference to an earlier full vertex).

All 35 POL*.BIN of the owned disc walk to their exact end with this layout and every terminator count matches
(`walk`): 103625 triangles, of which 95 have zero area (80 in polDC3).

Drivers (request #1482; docs/crazy_taxi2.md has the offsets and evidence). polPP1A..D are the first game's drivers
(Axel, B.D. Joe, Gena, Gus) and polPP2A..D the new ones (Slash, Iceman, Cinnamon, Hot-D), checked on the decoded,
textured models; the `H` files are the high-detail models (the collection uses them), the plain ones the in-race LOD.

* 1ST_READ.BIN (yam_modelpack.c loader at 0x0C05AD20; its pointers use the 0x0C010000 mirror of the load address)
  holds, per player model, a slot table (one u32 object offset per slot, the slots sorted by part name: atama,
  kakato_l/r, kata_l/r, koshi, momo_l/r, mune, sune_l/r, te_l/_ch/_gu/_ok, te_r..., ude_l/r, empty objects standing
  in for names a driver lacks; polPP2CH has no gesture hands, polPP1D adds Gus's wristband ude_lB), the slot count,
  a texture table (16-byte entries: u16 w, u16 h, u8 pixel format, u8 PVR data format, u32 address in the 0x0CB60000
  load buffer, u32 0; 0xFFFFFFFF ends it; textures 32-byte aligned and laying the tex*.bin out exactly) and the pol
  buffer size in words. KNOWN_TABLES has the addresses for the owned CDI build and the retail GD-ROM; `find_tables`
  locates them by content in any other build.
* tex*.bin is headerless PowerVR texture data (twiddled / VQ, RGB565 / ARGB4444, with or without mipmaps); the mesh
  headers' TCW/TSP words disagree with the table in places (the loader fills them from the table), the table wins.
* The parts are rigid and bone-local (each starts at its own joint, x along the bone; frame conventions as in the
  GameCube game, gbox.crazy_taxi_look). The game poses them by IK from FCVDATA.BIN (FCV motions: root position,
  joint angles in degrees and elbow / wrist / knee / ankle positions as cubic segments); no stored bone table was
  found, so `measures`/`skeleton` derive the rest skeleton from the part meshes (bone length = parent's reach along
  x + the child's start), standing with arms hanging, soles on y = 0, facing +Z.
"""
from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

GAME_IDS = {"45e9455ca5487e7d", "b5dfa0c44de0ba90", "6a286986fe83b44a", "8b1922d90b5008c5", "e3f480866acf7465",
            "bed50bf430125ec7"}
READER_VERSION = 1
PRODUCT = "MK-51136"
FILES_SHA256 = {
    "1ST_READ.BIN": "69f7bd24cc82752d0b4995290e91b2e0de8eeda7efefadd4bd227ec6ba2b9042",
    "POLPP1A.BIN": "53c493c915903e0d3a625ef6e3eb9244866679ce03019755b98b3d7a7117cfb0",
    "POLPP2A.BIN": "5bef8e591478f5faf0d623b126ba1ab06ca52ea3f9e29d4148e161e57f3cd213",
    "POLPSG0.BIN": "bb79019b3785d387b4e8e3ef30251e3f2bb2c7b3f6ee3f110878fd4d427d8fdb",
    "POLPPL0.BIN": "2ffc1582bc4e8c6f1393555efa3e69950486a64ef25a50b0820668dbda971368",
    "POLDC0.BIN": "0a6f126a4c9197e9eb4a92b9cf73f41d16f125b0f114d3f662734eebd0d3df15",
}
# player model file -> driver. polPP1? are the first game's drivers, polPP2? the new ones (checked on the decoded
# models: polPP1A is Axel, green hair and shorts, part extents equal to the GameCube Axel's; polPP1D carries Gus's
# wristband ude_lB; polPP2A Slash, polPP2C Cinnamon). 1ST_READ.BIN's select screen lists the new four first.
DRIVERS = {"PP1A": "Axel", "PP1B": "B.D. Joe", "PP1C": "Gena", "PP1D": "Gus",
           "PP2A": "Slash", "PP2B": "Iceman", "PP2C": "Cinnamon", "PP2D": "Hot-D"}
SLUGS = {"PP1A": "axel", "PP1B": "bd_joe", "PP1C": "gena", "PP1D": "gus",
         "PP2A": "slash", "PP2B": "iceman", "PP2C": "cinnamon", "PP2D": "hot_d"}
KINDS = (("POLPP", "driver"), ("POLPC", "cab"), ("POLPSG", "passengers"), ("POLPPL", "pedestrians"),
         ("POLDC", "city"), ("POLPPTST", "test driver"))
EMPTY = 0xFFFFFFFF
MESH_HEADER = 0x50
VERTEX = 32


@dataclass
class Mesh:
    offset: int
    pcw: int
    texture: int
    pos: list = field(default_factory=list)       # full vertices: (x, y, z)
    nrm: list = field(default_factory=list)
    uv: list = field(default_factory=list)
    tris: list = field(default_factory=list)      # vertex indices into pos
    refs: int = 0


@dataclass
class Obj:
    offset: int
    flags: tuple
    centre: tuple
    radius: float
    meshes: list = field(default_factory=list)
    entries: int = 0                              # the terminator's count

    @property
    def empty(self) -> bool:
        return not self.meshes

    def tris(self) -> int:
        return sum(len(m.tris) for m in self.meshes)


def _u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def read_mesh(b: bytes, o: int) -> tuple[Mesh, int]:
    """One mesh at `o` -> (Mesh, end offset). References resolve to the full vertex they point at."""
    if o + MESH_HEADER > len(b):
        raise ValueError(f"mesh header at {o:#x} runs past the end")
    pcw = _u32(b, o)
    size = _u32(b, o + 0x4C)
    end = o + MESH_HEADER + size
    if end > len(b):
        raise ValueError(f"mesh at {o:#x}: {size:#x} bytes of strips run past the end")
    m = Mesh(o, pcw, _u32(b, o + 0x20))
    at: dict[int, int] = {}                       # file offset of a full vertex -> index
    p = o + MESH_HEADER
    while p < end:
        flags, count = struct.unpack_from("<Ii", b, p)
        if count < 0 or count > 0x10000:
            raise ValueError(f"mesh at {o:#x}: bad strip count {count} at {p:#x}")
        p += 8
        n = 3 * count if flags & 0x08 else count
        idx = []
        for _ in range(n):
            if p + 8 > end:
                raise ValueError(f"mesh at {o:#x}: strip at {p:#x} runs past the mesh")
            w = _u32(b, p)
            if w >> 28 == 5:                      # reference: signed byte offset from the entry's end
                tgt = p + 8 + struct.unpack_from("<i", b, p + 4)[0]
                if tgt not in at:
                    raise ValueError(f"mesh at {o:#x}: reference at {p:#x} points at {tgt:#x}, not a vertex")
                idx.append(at[tgt])
                m.refs += 1
                p += 8
            else:
                if p + VERTEX > end:
                    raise ValueError(f"mesh at {o:#x}: vertex at {p:#x} runs past the mesh")
                v = struct.unpack_from("<8f", b, p)
                at[p] = len(m.pos)
                idx.append(len(m.pos))
                m.pos.append(v[0:3])
                m.nrm.append(v[3:6])
                m.uv.append(v[6:8])
                p += VERTEX
        if flags & 0x08:
            m.tris += [tuple(idx[i:i + 3]) for i in range(0, len(idx), 3)]
        else:
            for i in range(len(idx) - 2):
                a, c, d = idx[i], idx[i + 1], idx[i + 2]
                m.tris.append((a, c, d) if i % 2 == 0 else (c, a, d))
    if p != end:
        raise ValueError(f"mesh at {o:#x}: strips end at {p:#x}, header says {end:#x}")
    return m, end


def walk(b: bytes) -> list[Obj]:
    """Every object of a POL*.BIN, in slot order (empty slots included). Raises ValueError when the layout breaks or
    the file does not end exactly after the last object."""
    out, o = [], 0
    while o < len(b):
        if o + 0x18 > len(b):
            raise ValueError(f"{len(b) - o} trailing bytes at {o:#x}")
        f0, f1 = struct.unpack_from("<II", b, o)
        cx, cy, cz, r = struct.unpack_from("<4f", b, o + 8)
        ob = Obj(o, (f0, f1), (cx, cy, cz), r)
        p = o + 0x18
        while True:
            if p + 8 > len(b):
                raise ValueError(f"object at {o:#x} has no terminator")
            w = _u32(b, p)
            if w == 0:
                ob.entries = _u32(b, p + 4)
                p += 8
                break
            if not w >> 31:
                raise ValueError(f"object at {o:#x}: {w:#x} at {p:#x} is neither a mesh nor the terminator")
            m, p = read_mesh(b, p)
            ob.meshes.append(m)
        if ob.entries != sum(len(m.pos) + m.refs for m in ob.meshes):
            raise ValueError(f"object at {o:#x}: terminator counts {ob.entries} entries, meshes hold "
                             f"{sum(len(m.pos) + m.refs for m in ob.meshes)}")
        if f0 == EMPTY and ob.meshes:
            raise ValueError(f"object at {o:#x} is flagged empty but has meshes")
        out.append(ob)
        o = p
    return out


def to_obj(objs: list[Obj], name: str = "model") -> str:
    """The drawn objects as one OBJ, one `o` group per slot, in each part's own (bone-local) frame."""
    lines, base = [], 1
    for i, ob in enumerate(objs):
        if ob.empty:
            continue
        lines.append(f"o {name}_{i:02d}")
        for m in ob.meshes:
            lines += [f"v {x:.6f} {y:.6f} {z:.6f}" for x, y, z in m.pos]
            lines += [f"f {a + base} {c + base} {d + base}" for a, c, d in m.tris]
            base += len(m.pos)
    return "\n".join(lines) + "\n"


def kind_of(name: str) -> str:
    n = Path(name).name.upper()
    return next((k for pre, k in sorted(KINDS, key=lambda t: -len(t[0])) if n.startswith(pre)), "other")


def summary(name: str, b: bytes) -> dict:
    objs = walk(b)
    stem = Path(name).stem.upper()
    key = stem[3:7] if stem.startswith("POLPP") else ""
    row = {"file": name, "bytes": len(b), "kind": kind_of(name), "slots": len(objs),
           "drawn": sum(not o.empty for o in objs), "meshes": sum(len(o.meshes) for o in objs),
           "triangles": sum(o.tris() for o in objs), "textures": sorted({m.texture for o in objs for m in o.meshes})}
    if key in DRIVERS:
        row |= {"driver": DRIVERS[key], "detail": "high" if stem.endswith("H") else "normal"}
    return row


def inventory(disc) -> dict:
    """A disc (gbox.gdrom.CDIRom / GDRom: `.files`, `.read`) -> every POL*.BIN summarised."""
    rows = [summary(n, disc.read(n)) for n in sorted(disc.files) if Path(n).name.upper().startswith("POL")]
    return {"files": rows, "drivers": {r["driver"]: r for r in rows if r.get("detail") == "normal"},
            "triangles": sum(r["triangles"] for r in rows)}

# ----------------------------------------------------------------------------------------------- 1ST_READ.BIN tables
# yam_modelpack.c's loader (0x0C05AD20 in the owned 1ST_READ.BIN) picks, per model group (basic / car / car parts /
# player / player high), four parallel arrays indexed by the model number: the slot table, the slot count, the
# texture table and the pol/tex file names. 1ST_READ.BIN's own pointers use the 0x0C010000 mirror of its load address.
EXE_BASE = 0x0C010000
TEX_LOAD = 0x0CB60000            # the loader reads tex*.bin here (0x0C05AF64) before the textures go to VRAM
# 1ST_READ.BIN sha256 -> per detail: (slot-table pointers, slot counts, texture-table pointers, pol buffer words).
# The owned CDI repack and the retail GD-ROM (HyperSpin `Crazy Taxi 2 (USA).chd`) are different builds (1460116 vs
# 1452148 bytes) with the same tables 0x1F30 (texture tables 0x1F30) apart; their pol/tex files are identical.
KNOWN_TABLES = {
    FILES_SHA256["1ST_READ.BIN"]: {"normal": (0x0C135D78, 0x0C135DF4, 0x0C13F3F4, 0x0C135E70),
                                   "high": (0x0C135D98, 0x0C135E14, 0x0C13F414, 0x0C135E90)},
    "8057a8e37636ad78b1fc70ee590bd314686546b13ffe100623d86b572aec53c1": {
        "normal": (0x0C133E48, 0x0C133EC4, 0x0C13D4C4, 0x0C133F40),
        "high": (0x0C133E68, 0x0C133EE4, 0x0C13D4E4, 0x0C133F60)},
}
PLAYER_KEYS = ("PP1A", "PP1B", "PP1C", "PP1D", "PP2A", "PP2B", "PP2C", "PP2D")   # model numbers 0..7 of the player groups
TEX_ENTRY = 16                   # u16 width, u16 height, u8 pixel format, u8 data format, u16 0, u32 address, u32 0
TEX_END = 0xFFFFFFFF


def _exe_u32(exe: bytes, va: int) -> int:
    o = va - EXE_BASE
    if not 0 <= o <= len(exe) - 4:
        raise ValueError(f"{va:#x} is outside 1ST_READ.BIN")
    return struct.unpack_from("<I", exe, o)[0]


def tex_size(w: int, h: int, pix: int, dfmt: int) -> int:
    """Bytes of one PowerVR texture as the loader lays it out (before the 32-byte alignment of the next one)."""
    bpp = {5: 4, 6: 8}.get(pix, 16)
    mip = dfmt in (2, 4, 0x11, 0x12)
    if dfmt in (3, 4, 0x10, 0x11):                                  # VQ: 2 KB codebook + one index byte per 2x2 block
        n, s = (w // 2) * (h // 2), 1
        if mip:
            while s < w:
                n += max(1, (s // 2) ** 2)
                s *= 2
        return 2048 + n
    n = w * h * bpp // 8
    if mip:                                                          # 16 bpp: the 1x1 level sits at offset 6
        s, pre = 1, 6 if bpp == 16 else 3
        while s < w:
            pre += s * s * bpp // 8 if s > 1 or bpp != 16 else 2
            s *= 2
        n += pre
    return n


def _align32(n: int) -> int:
    return (n + 31) & ~31


def read_tex_table(exe: bytes, va: int) -> list[dict]:
    """One driver's texture table: [{w, h, pix, fmt, offset, size}] (offset into its tex*.bin)."""
    out, base = [], None
    while True:
        wh = _exe_u32(exe, va)
        if wh == TEX_END:
            return out
        kind, addr = _exe_u32(exe, va + 4), _exe_u32(exe, va + 8)
        w, h, pix, dfmt = wh & 0xFFFF, wh >> 16, kind & 0xFF, (kind >> 8) & 0xFF
        if not (8 <= w <= 1024 and 8 <= h <= 1024 and not w & (w - 1) and not h & (h - 1)) or len(out) > 256:
            raise ValueError(f"texture table at {va:#x}: entry {len(out)} is not a texture ({wh:#x})")
        base = addr if base is None else base
        out.append({"w": w, "h": h, "pix": pix, "fmt": dfmt, "offset": addr - base, "size": tex_size(w, h, pix, dfmt)})
        va += TEX_ENTRY


def _tex_tables(exe: bytes) -> list[tuple[int, list[dict]]]:
    """Every texture table in 1ST_READ.BIN: runs of plausible 16-byte entries ending in the 0xFFFFFFFF terminator."""
    n = len(exe) // 4
    w = np.frombuffer(exe[:n * 4], "<u4")
    term = np.flatnonzero((w[:-3] == TEX_END) & (w[1:-2] == TEX_END) & (w[2:-1] == TEX_END) & (w[3:] == TEX_END))
    out = []
    for t in term:
        start = t
        while start >= 4:
            wh, kind, addr, zero = (int(x) for x in w[start - 4:start])
            ww, hh = wh & 0xFFFF, wh >> 16
            if zero or not (8 <= ww <= 1024 and 8 <= hh <= 1024) or ww & (ww - 1) or hh & (hh - 1)                     or kind >> 16 or (kind & 0xFF) > 6 or not 1 <= (kind >> 8) <= 0x12 or addr >> 28:
                break
            start -= 4
        if start < t:
            try:
                out.append((EXE_BASE + 4 * int(start), read_tex_table(exe, EXE_BASE + 4 * int(start))))
            except ValueError:
                pass
    return out


def find_tables(exe: bytes, pol: bytes, tex: bytes | None) -> dict:
    """Locate a player model's slot and texture tables in any 1ST_READ.BIN build by content: the slot table is the
    run of words that is a permutation of the pol file's object offsets, the texture table the one that lays the
    tex file out exactly. Raises ValueError when either is missing or ambiguous."""
    offs = [o.offset for o in walk(pol)]
    n = len(exe) // 4
    w = np.frombuffer(exe[:n * 4], "<u4")
    hit = np.isin(w, np.asarray(offs, np.uint32))
    want = sorted(offs)
    found = []
    run = np.convolve(hit.astype(np.int32), np.ones(len(offs), np.int32), "valid")
    for i in np.flatnonzero(run == len(offs)):
        if sorted(int(x) for x in w[i:i + len(offs)]) == want:
            found.append([int(x) for x in w[i:i + len(offs)]])
    if len(found) > 1:                     # a window shifted into the next table can match too: keep pointed-at ones
        ptr = set(int(x) for x in w)
        starts = [EXE_BASE + 4 * int(i) for i in np.flatnonzero(run == len(offs))
                  if sorted(int(x) for x in w[i:i + len(offs)]) == want]
        found = [f for f, va in zip(found, starts) if va in ptr]
    if len({tuple(f) for f in found}) != 1:
        raise ValueError(f"{len(found)} slot tables match this pol file")
    out = {"slots": found[0], "textures": []}
    if tex is not None:
        tabs = [t for _va, t in _tex_tables(exe)
                if t and _align32(t[-1]["offset"] + t[-1]["size"]) == _align32(len(tex))]
        if len({tuple(tuple(sorted(e.items())) for e in t) for t in tabs}) > 1:    # same size: pick by the meshes'
            used = {}                                                            # TCW pixel format + VQ bit
            for o in walk(pol):
                for m in o.meshes:
                    tcw = struct.unpack_from("<I", pol, m.offset + 12)[0]
                    used[m.texture] = ((tcw >> 27) & 7, (tcw >> 30) & 1)

            def score(t):
                return sum(k < len(t) and (t[k]["pix"], int(t[k]["fmt"] in (3, 4, 0x10, 0x11))) == v
                           for k, v in used.items())
            best = max(score(t) for t in tabs)
            tabs = [t for t in tabs if score(t) == best]
        if len({tuple(tuple(sorted(e.items())) for e in t) for t in tabs}) != 1:
            raise ValueError(f"{len(tabs)} texture tables lay out a {len(tex)}-byte tex file")
        out["textures"] = tabs[0]
    return out


def player_tables(exe: bytes, key: str, high: bool = False, pol: bytes | None = None, tex: bytes | None = None) -> dict:
    """{slots: [object offset per sorted part name], textures: [...], alloc: pol buffer bytes} of player model `key`
    (PP1A..PP2D). The owned build's addresses are known (KNOWN_TABLES); any other build is searched by content
    (`find_tables`, needs pol + tex)."""
    import hashlib
    t = KNOWN_TABLES.get(hashlib.sha256(exe).hexdigest())
    if t is None:
        if pol is None:
            raise ValueError("unknown 1ST_READ.BIN build: pass the pol/tex files to locate the tables by content")
        return find_tables(exe, pol, tex) | {"alloc": None}
    slots_va, count_va, tex_va, alloc_va = t["high" if high else "normal"]
    i = PLAYER_KEYS.index(key)
    n = _exe_u32(exe, count_va + 4 * i)
    tab = _exe_u32(exe, slots_va + 4 * i)
    if not 0 < n <= 256:
        raise ValueError(f"{key}: implausible slot count {n}")
    return {"slots": [_exe_u32(exe, tab + 4 * k) for k in range(n)],
            "textures": read_tex_table(exe, _exe_u32(exe, tex_va + 4 * i)),
            "alloc": 4 * _exe_u32(exe, alloc_va + 4 * i),          # pol buffer: file size rounded up to 32 bytes
            "va": {"slots": tab, "textures": _exe_u32(exe, tex_va + 4 * i), "alloc": alloc_va + 4 * i}}


# ----------------------------------------------------------------------------------------------- textures

def _morton(w: int, h: int) -> np.ndarray:
    """(h, w) -> twiddled texel index (square Morton blocks laid along the longer side, as gbox.formats.texture)."""
    s = min(w, h)
    y, x = np.mgrid[0:h, 0:w]
    xs, ys = x % s, y % s
    m = np.zeros((h, w), np.int64)
    for b in range(11):
        m |= ((ys >> b) & 1) << (2 * b) | ((xs >> b) & 1) << (2 * b + 1)
    blk = (x // s) if w >= h else (y // s)
    return blk * s * s + m


def _pixels(words: np.ndarray, pix: int) -> np.ndarray:
    v = words.astype(np.uint32)
    if pix == 0:                                                     # ARGB1555
        r, g, b, a = (v >> 10) & 31, (v >> 5) & 31, v & 31, np.where(v & 0x8000, 255, 0)
        return np.stack([r * 255 // 31, g * 255 // 31, b * 255 // 31, a], -1).astype(np.uint8)
    if pix == 1:                                                     # RGB565
        r, g, b = (v >> 11) & 31, (v >> 5) & 63, v & 31
        return np.stack([r * 255 // 31, g * 255 // 63, b * 255 // 31, np.full_like(v, 255)], -1).astype(np.uint8)
    if pix == 2:                                                     # ARGB4444
        return np.stack([((v >> 8) & 15) * 17, ((v >> 4) & 15) * 17, (v & 15) * 17, ((v >> 12) & 15) * 17],
                        -1).astype(np.uint8)
    raise ValueError(f"pixel format {pix} not decoded")


def decode_texture(data: bytes, t: dict) -> np.ndarray:
    """One table entry's bytes (data = the whole tex*.bin) -> RGBA (h, w, 4), top row first."""
    w, h, pix, fmt = t["w"], t["h"], t["pix"], t["fmt"]
    body = data[t["offset"]:t["offset"] + t["size"]]
    if len(body) != t["size"]:
        raise ValueError(f"texture at {t['offset']:#x} runs past the file")
    if fmt in (3, 4):
        book = _pixels(np.frombuffer(body[:2048], "<u2"), pix).reshape(256, 4, 4)
        idx = np.frombuffer(body[2048:], np.uint8)
        if fmt == 4:
            idx = idx[len(idx) - (w // 2) * (h // 2):]
        blocks = book[idx[_morton(w // 2, h // 2)]]                   # (h/2, w/2, 4 texels, rgba); texel k = (x, y)
        out = np.zeros((h, w, 4), np.uint8)                           # order (0,0) (0,1) (1,0) (1,1)
        out[0::2, 0::2], out[1::2, 0::2] = blocks[:, :, 0], blocks[:, :, 1]
        out[0::2, 1::2], out[1::2, 1::2] = blocks[:, :, 2], blocks[:, :, 3]
        return out
    if fmt in (1, 2, 0x0D):
        words = np.frombuffer(body, "<u2")
        if fmt == 2:
            words = words[len(words) - w * h:]
        return _pixels(words[_morton(w, h)], pix)
    if fmt in (9, 0x0B):
        return _pixels(np.frombuffer(body, "<u2")[:w * h].reshape(h, w), pix)
    raise ValueError(f"texture data format {fmt:#x} not decoded")


def textures(tex: bytes, table: list[dict]) -> list[np.ndarray]:
    """Every texture of a driver's tex*.bin; checks the table lays the file out exactly (32-byte aligned)."""
    end = 0
    for t in table:
        if t["offset"] != _align32(end) and t["offset"] != end:
            raise ValueError(f"texture table leaves a gap at {end:#x}")
        end = t["offset"] + t["size"]
    if _align32(end) != _align32(len(tex)):
        raise ValueError(f"texture table ends at {end:#x}, tex file is {len(tex):#x}")
    return [decode_texture(tex, t) for t in table]


# ----------------------------------------------------------------------------------------------- parts and rig
# The slot table lists a driver's objects sorted by part name (ASCII), with empty objects standing for names this
# driver lacks. The drawn ones are always these 21 in this order (+ accessory parts, see `part_names`):
PARTS = ("atama", "kakato_l", "kakato_r", "kata_l", "kata_r", "koshi", "momo_l", "momo_r", "mune", "sune_l", "sune_r",
         "te_l", "te_l_ch", "te_l_gu", "te_l_ok", "te_r", "te_r_ch", "te_r_gu", "te_r_ok", "ude_l", "ude_r")
HAND_POSES = ("te_l_ch", "te_l_gu", "te_l_ok", "te_r_ch", "te_r_gu", "te_r_ok")     # gesture hands, not drawn at rest
ACCESSORY_REACH = 0.8           # a part whose bounding box stays this far from its joint is an accessory sub-part
# joint -> parent (None = root); `kubi` (neck) and `sakotsu_*` (clavicles) carry no geometry, they give the 18 roles
RIG = {"koshi": None, "momo_l": "koshi", "sune_l": "momo_l", "kakato_l": "sune_l",
       "momo_r": "koshi", "sune_r": "momo_r", "kakato_r": "sune_r", "mune": "koshi", "kubi": "mune", "atama": "kubi",
       "sakotsu_l": "mune", "kata_l": "sakotsu_l", "ude_l": "kata_l", "te_l": "ude_l",
       "sakotsu_r": "mune", "kata_r": "sakotsu_r", "ude_r": "kata_r", "te_r": "ude_r"}
ROLES = {"hip": "koshi", "chest": "mune", "neck": "kubi", "head": "atama",
         "l_clav": "sakotsu_l", "l_upper": "kata_l", "l_fore": "ude_l", "l_hand": "te_l",
         "r_clav": "sakotsu_r", "r_upper": "kata_r", "r_fore": "ude_r", "r_hand": "te_r",
         "l_thigh": "momo_l", "l_shin": "sune_l", "l_foot": "kakato_l",
         "r_thigh": "momo_r", "r_shin": "sune_r", "r_foot": "kakato_r"}
# Rest orientation of every part's local axes in glTF space (+Y up, facing +Z, character's left = +X), columns = the
# world direction of the part's x, y, z. Read off the GameCube game's in-game probe (gbox.crazy_taxi_look: the same
# rig and part frames): z is the character's right in every part; koshi, legs, arms, hands and feet hang x down with
# y forward (kakato: y toward the toes), mune runs x up the spine with y backward, atama has x forward, y up.
_DOWN = np.array([[0.0, 0.0, -1.0], [-1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
FRAMES = {"mune": np.array([[0.0, 0.0, -1.0], [1.0, 0.0, 0.0], [0.0, -1.0, 0.0]]),
          "atama": np.array([[0.0, 0.0, -1.0], [0.0, 1.0, 0.0], [1.0, 0.0, 0.0]])}


def frame_of(part: str) -> np.ndarray:
    return FRAMES.get(part, _DOWN)


def part_names(objs: list[Obj], slots: list[int]) -> dict[str, int]:
    """{part name: object index} from the name-sorted slot table. A drawn object whose bounding box stays more than
    ACCESSORY_REACH from its own joint (Gus's wristband, ude_lB x 2.04..2.50) is an accessory: it is named after the
    part sorted just before it with a `+` suffix and rides that part's joint."""
    at = {o.offset: i for i, o in enumerate(objs)}
    try:
        order = [at[s] for s in slots]
    except KeyError as e:
        raise ValueError(f"slot table names an offset that is no object: {e}") from None
    drawn = [i for i in order if not objs[i].empty]

    def reach(i):
        P = np.array([p for m in objs[i].meshes for p in m.pos])
        return float(np.linalg.norm(np.maximum(0.0, np.maximum(P.min(0), -P.max(0)))))
    main = [i for i in drawn if reach(i) <= ACCESSORY_REACH]
    plain = tuple(p for p in PARTS if p not in HAND_POSES)            # polPP2CH draws no gesture hands
    if len(main) not in (len(PARTS), len(plain)):
        raise ValueError(f"{len(main)} drawn main parts, the rig has {len(PARTS)} (or {len(plain)})")
    out, last = {}, None
    names = iter(PARTS if len(main) == len(PARTS) else plain)
    for i in drawn:
        if i in main:
            last = next(names)
            out[last] = i
        else:
            k = 1
            while f"{last}+{k}" in out:
                k += 1
            out[f"{last}+{k}"] = i
    return out


def _cloud(objs, idx) -> np.ndarray:
    return np.array([p for m in objs[idx].meshes for p in m.pos], float)


def measures(objs: list[Obj], names: dict[str, int]) -> dict:
    """Rest-skeleton lengths from the part meshes (each part starts at its own joint, x along the bone): a bone is
    the parent's reach along x plus the child's start (negative where the meshes overlap), as gbox.crazy_taxi_look's
    stock_measures; lateral offsets put the hip joints where the thighs' inner sides meet and the shoulders at the
    chest's outer edge."""
    lo = {p: _cloud(objs, i).min(0) for p, i in names.items() if "+" not in p}
    hi = {p: _cloud(objs, i).max(0) for p, i in names.items() if "+" not in p}
    m = {}
    for s in "lr":
        m[f"thigh_{s}"] = max(0.5, hi[f"momo_{s}"][0] + lo[f"sune_{s}"][0])
        m[f"shin_{s}"] = max(0.5, hi[f"sune_{s}"][0] + min(0.0, lo[f"kakato_{s}"][0]))
        m[f"sole_{s}"] = max(0.3, hi[f"kakato_{s}"][0])
        m[f"upper_{s}"] = max(0.5, hi[f"kata_{s}"][0] + lo[f"ude_{s}"][0])
        m[f"fore_{s}"] = max(0.5, hi[f"ude_{s}"][0] + lo[f"te_{s}"][0])
    m["hips"] = max(0.3, hi["koshi"][0] + 0.5 * (lo["momo_l"][0] + lo["momo_r"][0]))
    m["hip_w"] = 0.5 * (hi["momo_l"][2] - lo["momo_r"][2]) + 0.02         # inner side of each thigh at the midline
    chest = _cloud(objs, names["mune"])
    m["neck"] = float(chest[np.abs(chest[:, 2]) < 0.35 * np.abs(chest[:, 2]).max(), 0].max())
    outer = chest[np.abs(chest[:, 2]) > 0.75 * np.abs(chest[:, 2]).max()]
    m["shoulder_h"] = float(outer[:, 0].max()) + 0.5 * float(lo["kata_l"][0] + lo["kata_r"][0])
    m["shoulder_w"] = float(np.abs(outer[:, 2]).mean())
    m["head_drop"] = 0.0
    m["legs"] = m["hips"] + 0.5 * (m["thigh_l"] + m["thigh_r"] + m["shin_l"] + m["shin_r"] + m["sole_l"] + m["sole_r"])
    return {k: float(v) for k, v in m.items()}


def skeleton(m: dict) -> dict[str, np.ndarray]:
    """{joint: 4x4 world matrix} of the rest pose: standing, soles on y = 0, arms hanging, facing +Z."""
    U, Rt = np.array([0.0, 1.0, 0.0]), np.array([-1.0, 0.0, 0.0])        # up, the character's right
    pos = {"koshi": U * m["legs"]}
    pos["mune"] = pos["koshi"]
    for s, side in (("l", -1.0), ("r", 1.0)):
        pos[f"momo_{s}"] = pos["koshi"] - U * m["hips"] + side * m["hip_w"] * Rt
        pos[f"sune_{s}"] = pos[f"momo_{s}"] - U * m[f"thigh_{s}"]
        pos[f"kakato_{s}"] = pos[f"sune_{s}"] - U * m[f"shin_{s}"]
        sh = pos["koshi"] + U * m["shoulder_h"]
        pos[f"sakotsu_{s}"] = sh + side * 0.3 * m["shoulder_w"] * Rt
        pos[f"kata_{s}"] = sh + side * m["shoulder_w"] * Rt
        pos[f"ude_{s}"] = pos[f"kata_{s}"] - U * m[f"upper_{s}"]
        pos[f"te_{s}"] = pos[f"ude_{s}"] - U * m[f"fore_{s}"]
    pos["kubi"] = pos["koshi"] + U * m["shoulder_h"]
    pos["atama"] = pos["koshi"] + U * (m["neck"] - m["head_drop"])
    out = {}
    for j in RIG:
        M = np.eye(4)
        M[:3, :3] = frame_of(j) if j not in ("kubi", "sakotsu_l", "sakotsu_r") else frame_of("mune")
        M[:3, 3] = pos[j]
        out[j] = M
    return out


def joint_of(part: str) -> str:
    base = part.split("+")[0]
    return {"te_l_ch": "te_l", "te_l_gu": "te_l", "te_l_ok": "te_l",
            "te_r_ch": "te_r", "te_r_gu": "te_r", "te_r_ok": "te_r"}.get(base, base)


def assemble(pol: bytes, tex: bytes | None, tables: dict, hands: str = "") -> dict:
    """A driver's pol*.bin (+ tex*.bin and its 1ST_READ tables) -> {joints, parts, materials, textures, measures}.
    Every part's vertices go to the rest pose through its joint (rigid, one joint per part). hands = "" draws the
    open hands; "gu"/"ch"/"ok" draws that gesture instead."""
    objs = walk(pol)
    names = part_names(objs, tables["slots"])
    m = measures(objs, names)
    W = skeleton(m)
    texs = textures(tex, tables["textures"]) if tex is not None else []
    skip = {p for p in HAND_POSES if not hands or not p.endswith("_" + hands)}
    if hands:
        skip |= {"te_l", "te_r"}
    parts, mats, key_of = [], [], {}
    for name, i in names.items():
        if name.split("+")[0] in skip:
            continue
        j = joint_of(name)
        R, t = W[j][:3, :3], W[j][:3, 3]
        for mesh in objs[i].meshes:
            if not mesh.tris:
                continue
            key = _material_key(pol, mesh)
            if key not in key_of:
                key_of[key] = len(mats)
                mats.append(_material(key))
            P = np.asarray(mesh.pos, float) @ R.T + t
            N = np.asarray(mesh.nrm, float)
            ln = np.linalg.norm(N, axis=1)
            N = np.where(ln[:, None] > 1e-6, N / np.maximum(ln, 1e-9)[:, None], 0.0) @ R.T
            parts.append({"part": name, "joint": j, "material": key_of[key], "pos": P, "nrm": N,
                          "uv": np.asarray(mesh.uv, float), "tris": np.asarray(mesh.tris, int)})
    return {"joints": W, "parts": parts, "materials": mats, "textures": texs, "measures": m, "names": names,
            "objects": len(objs)}


def _material_key(pol: bytes, mesh: Mesh) -> tuple:
    pcw, isp, tsp = struct.unpack_from("<3I", pol, mesh.offset)
    base = struct.unpack_from("<4f", pol, mesh.offset + 0x2C)                # A, R, G, B
    tex = mesh.texture if mesh.texture != 0xFFFFFFFF and pcw & 0x08 else -1
    blend = (pcw >> 24) & 7 == 2 or (tsp >> 29, (tsp >> 26) & 7) == (4, 5)    # translucent list / src-alpha blending
    punch = (pcw >> 24) & 7 == 4
    cull = (isp >> 27) & 3
    return tex, "BLEND" if blend else "MASK" if punch else "OPAQUE", cull == 0 or cull == 1, \
        tuple(round(min(1.0, max(0.0, c)), 3) for c in (base[1], base[2], base[3], base[0]))


def _material(key: tuple) -> dict:
    tex, mode, double, rgba = key
    return {"texture": tex, "alpha": mode, "double_sided": double, "colour": rgba if tex < 0 else (1, 1, 1, 1)}


# ----------------------------------------------------------------------------------------------- glTF

def _quat(R: np.ndarray) -> list:
    w = np.sqrt(max(0.0, 1.0 + R[0, 0] + R[1, 1] + R[2, 2])) / 2
    x = np.sqrt(max(0.0, 1.0 + R[0, 0] - R[1, 1] - R[2, 2])) / 2
    y = np.sqrt(max(0.0, 1.0 - R[0, 0] + R[1, 1] - R[2, 2])) / 2
    z = np.sqrt(max(0.0, 1.0 - R[0, 0] - R[1, 1] + R[2, 2])) / 2
    x, y, z = np.copysign(x, R[2, 1] - R[1, 2]), np.copysign(y, R[0, 2] - R[2, 0]), np.copysign(z, R[1, 0] - R[0, 1])
    q = np.array([x, y, z, w])
    return (q / np.linalg.norm(q)).tolist()


def _png(rgba: np.ndarray) -> bytes:
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, "PNG", optimize=True)
    return buf.getvalue()


def write_glb(path, a: dict, name: str, extras: dict | None = None) -> Path:
    """Assembled driver -> skinned GLB: one joint node per RIG entry (rest TRS), every vertex weighted 1.0 to its
    part's joint, one primitive per material, the driver's own textures as PNG."""
    import json
    blob, views, accs = bytearray(), [], []

    def view(data: bytes, target=None) -> int:
        while len(blob) % 4:
            blob.append(0)
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(data), **({"target": target} if target else {})})
        blob.extend(data)
        return len(views) - 1

    def acc(arr, typ, ctype=5126, target=34962, minmax=False) -> int:
        arr = np.ascontiguousarray(arr)
        x = {"bufferView": view(arr.tobytes(), target), "componentType": ctype, "count": len(arr), "type": typ}
        if minmax:
            x["min"] = arr.reshape(len(arr), -1).min(0).tolist()
            x["max"] = arr.reshape(len(arr), -1).max(0).tolist()
        accs.append(x)
        return len(accs) - 1

    joints = list(RIG)
    jix = {j: k for k, j in enumerate(joints)}
    W = a["joints"]
    nodes = []
    for j in joints:
        p = RIG[j]
        L = W[j] if p is None else np.linalg.inv(W[p]) @ W[j]
        nodes.append({"name": j, "translation": L[:3, 3].tolist(), "rotation": _quat(L[:3, :3])})
    for j in joints:
        if RIG[j] is not None:
            nodes[jix[RIG[j]]].setdefault("children", []).append(jix[j])
    images, texmap = [], {}
    for k, img in enumerate(a["textures"]):
        if any(m["texture"] == k for m in a["materials"]):
            texmap[k] = len(images)
            images.append({"bufferView": view(_png(img)), "mimeType": "image/png", "name": f"{name}_tex{k}"})
    materials, prims = [], []
    for mi, mat in enumerate(a["materials"]):
        pbr = {"metallicFactor": 0.0, "roughnessFactor": 0.9, "baseColorFactor": list(mat["colour"])}
        if mat["texture"] >= 0 and mat["texture"] in texmap:
            pbr["baseColorTexture"] = {"index": texmap[mat["texture"]]}
        mm = {"name": f"{name}_mat{mi}", "pbrMetallicRoughness": pbr, "doubleSided": bool(mat["double_sided"])}
        if mat["alpha"] == "BLEND":
            mm["alphaMode"] = "BLEND"
        elif mat["alpha"] == "MASK":
            mm.update(alphaMode="MASK", alphaCutoff=0.5)
        materials.append(mm)
        ps = [p for p in a["parts"] if p["material"] == mi]
        if not ps:
            continue
        P = np.concatenate([p["pos"] for p in ps]).astype(np.float32)
        N = np.concatenate([p["nrm"] for p in ps]).astype(np.float32)
        UV = np.concatenate([p["uv"] for p in ps]).astype(np.float32)
        J = np.zeros((len(P), 4), np.uint16)
        J[:, 0] = np.concatenate([np.full(len(p["pos"]), jix[p["joint"]]) for p in ps])
        Wt = np.zeros((len(P), 4), np.float32)
        Wt[:, 0] = 1.0
        base, idx = 0, []
        for p in ps:
            idx.append(p["tris"] + base)
            base += len(p["pos"])
        I = np.concatenate(idx).astype(np.uint32).reshape(-1)
        bad = np.linalg.norm(N, axis=1) < 0.5                       # meshes without normals: face normals
        if bad.any():
            T = I.reshape(-1, 3)
            fn = np.cross(P[T[:, 1]] - P[T[:, 0]], P[T[:, 2]] - P[T[:, 0]])
            acc_n = np.zeros_like(P)
            for c in range(3):
                np.add.at(acc_n, T[:, c], fn)
            ln = np.linalg.norm(acc_n, axis=1, keepdims=True)
            fixed = np.where(ln > 1e-9, acc_n / np.maximum(ln, 1e-9), [0, 1, 0]).astype(np.float32)
            N[bad] = fixed[bad]
        prims.append({"attributes": {"POSITION": acc(P, "VEC3", minmax=True), "NORMAL": acc(N, "VEC3"),
                                     "TEXCOORD_0": acc(UV, "VEC2"), "JOINTS_0": acc(J, "VEC4", 5123),
                                     "WEIGHTS_0": acc(Wt, "VEC4")},
                      "indices": acc(I, "SCALAR", 5125, 34963), "material": mi})
    ibm = np.array([np.linalg.inv(W[j]).T.reshape(16) for j in joints], np.float32)
    nodes.append({"name": name, "mesh": 0, "skin": 0})
    gl = {"asset": {"version": "2.0", "generator": "gbox.crazy_taxi2", **({"extras": extras} if extras else {})},
          "scene": 0, "scenes": [{"name": name, "nodes": [jix["koshi"], len(nodes) - 1]}], "nodes": nodes,
          "meshes": [{"name": name, "primitives": prims}],
          "skins": [{"name": f"{name}_rig", "joints": list(range(len(joints))), "skeleton": jix["koshi"],
                     "inverseBindMatrices": acc(ibm, "MAT4", target=None)}],
          "materials": materials, "accessors": accs, "bufferViews": views, "buffers": [{"byteLength": 0}]}
    if images:
        gl["images"] = images
        gl["textures"] = [{"source": k, "sampler": 0} for k in range(len(images))]
        gl["samplers"] = [{"magFilter": 9729, "minFilter": 9729, "wrapS": 10497, "wrapT": 10497}]
        for mm in materials:
            t = mm["pbrMetallicRoughness"].get("baseColorTexture")
            if t is not None:
                t["index"] = t["index"]
    while len(blob) % 4:
        blob.append(0)
    gl["buffers"][0]["byteLength"] = len(blob)
    js = json.dumps(gl, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    out = struct.pack("<3I", 0x46546C67, 2, 28 + len(js) + len(blob))
    out += struct.pack("<2I", len(js), 0x4E4F534A) + js + struct.pack("<2I", len(blob), 0x004E4942) + bytes(blob)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(out)
    return path



# ----------------------------------------------------------------------------------------------- collection

def title_test(t: str, p: str) -> bool:
    """characters.DEDICATED: every Crazy Taxi 2 Dreamcast catalog title (`Crazy Taxi 2`, `(USA)`, the PAL repack
    `2004-06-28-Crazy-Taxi-2-Pal-DCP`)."""
    return re.search(r"crazy[ _-]?taxi[ _-]?2\b", t) is not None and p == "dreamcast"


def roster() -> list[dict]:
    """The eight drivers (high-detail polPP??H models; the normal ones are the in-race LOD)."""
    return [{"key": k, "slug": f"ct2_{SLUGS[k]}", "name": f"{n} (Crazy Taxi 2)", "aliases": [n, f"CT2 {n}"],
             "kind": "character", "collect": True} for k, n in DRIVERS.items()]


def open_disc(path):
    """A .cdi (CDIRom) or .gdi (GDRom) Crazy Taxi 2 image."""
    from .gdrom import CDIRom, GDRom
    path = Path(path)
    return CDIRom(path) if path.suffix.lower() == ".cdi" else GDRom(str(path))


def driver_files(disc, key: str, high: bool = True) -> dict:
    """{exe, pol, tex, tables, stem} of one driver from a disc."""
    stem = key + ("H" if high else "")
    exe, pol, tex = disc.read("1ST_READ.BIN"), disc.read(f"POL{stem}.BIN"), disc.read(f"TEX{stem}.BIN")
    return {"exe": exe, "pol": pol, "tex": tex, "tables": player_tables(exe, key, high, pol, tex), "stem": stem}


def export(files: dict, out: Path, name: str, extras: dict | None = None) -> dict:
    a = assemble(files["pol"], files["tex"], files["tables"])
    write_glb(out, a, name, extras)
    return {"glb": Path(out), "joints": len(RIG), "parts": sorted({p["part"] for p in a["parts"]}),
            "triangles": sum(len(p["tris"]) for p in a["parts"]), "textures": len(a["textures"]),
            "measures": a["measures"], "accessories": sorted(n for n in a["names"] if "+" in n)}


def extract_run(ctx, game: dict, e: dict, work) -> dict:
    """characters op=collect / extract: one driver as a rigged, textured GLB (one joint per rigid part)."""
    import hashlib
    import json
    from . import characters as C
    disc = open_disc(C._dc_gdi(ctx, game))
    key = e["key"]
    files = driver_files(disc, key, True)
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    r = export(files, work / f"{e['slug']}.glb", e["slug"],
               extras={"source": f"Crazy Taxi 2 (DC) POL{files['stem']}.BIN + TEX{files['stem']}.BIN",
                       "driver": DRIVERS[key], "frame": "left +X, up +Y, facing +Z; model units (a driver is ~16 tall)",
                       "rig": "rest skeleton derived from the part meshes (docs/crazy_taxi2.md)"})
    manifest = {"driver": DRIVERS[key], "key": key, "file": files["stem"], "reader": "gbox.crazy_taxi2",
                "reader_version": READER_VERSION, "joints": r["joints"], "triangles": r["triangles"],
                "parts": r["parts"], "accessories": r["accessories"], "measures": r["measures"],
                "roles": ROLES, "executable_sha256": hashlib.sha256(files["exe"]).hexdigest(),
                "pol_sha256": hashlib.sha256(files["pol"]).hexdigest()}
    (work / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return {"files": [r["glb"], work / "manifest.json"], "tool": "gbox.crazy_taxi2", "roles": dict(ROLES),
            "source_files": [f"POL{files['stem']}.BIN", f"TEX{files['stem']}.BIN",
                             "1ST_READ.BIN (slot + texture tables)"],
            "extra": {"ct2_reader": READER_VERSION, "slot": f"driver:{SLUGS[key]}"},
            "notes": f"{DRIVERS[key]}: {r['triangles']} triangles in {len(r['parts'])} rigid parts on an 18-joint rig "
                     f"(one joint per part + neck and clavicles), {r['textures']} PowerVR textures. Part names from "
                     "1ST_READ.BIN's name-sorted slot table; rest skeleton derived from the part meshes (the game "
                     "poses the parts by IK from FCVDATA.BIN, no stored bone table found)."}


def main(argv=None):
    import argparse
    import json
    from .gdrom import CDIRom
    ap = argparse.ArgumentParser(description="Crazy Taxi 2 (DC) POL*.BIN inventory")
    ap.add_argument("cdi")
    ap.add_argument("--obj", type=Path, help="write each driver file's parts as an OBJ here")
    a = ap.parse_args(argv)
    disc = CDIRom(a.cdi)
    inv = inventory(disc)
    if a.obj:
        a.obj.mkdir(parents=True, exist_ok=True)
        for r in inv["files"]:
            if r["kind"] == "driver":
                stem = Path(r["file"]).stem
                (a.obj / f"{stem}.obj").write_text(to_obj(walk(disc.read(r["file"])), stem))
    print(json.dumps(inv, indent=1))


if __name__ == "__main__":
    main()
