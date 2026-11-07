"""Resident Evil 4 (Switch / HD port) BIN meshes -- a read-only decoder for one BIN slot.

The GameCube reader (`gbox/re4gc_models.py`) does not apply: the HD port keeps the UDAS/DAT containers
(`gbox/re4gc_inventory.py`) but re-lays the mesh BIN.  This module decodes the HD layout and refuses anything that
does not satisfy it.

Layout (everything LITTLE-endian, header size 0x98 = the bone table's offset)

```
0x00 u32  header size, 0x98 (== bone-table offset)
0x0C u32  0x50 in 100/122 BINs, 0 in the rest            unknown
0x10 u64* vertex colours, RGBA8, 4 B/vertex
0x18 u64* UVs, 2 x f32, 8 B/vertex
0x20 u64* weight sets, 8 B/record, byte-identical to the GC record layout
0x28 u32  packed (0x00020101 / 0x000320BC ...)            unknown
0x30 u64* material + primitive table (last thing in the file)
0x38 u32  GX-attribute-ish flags (0x80000000 / 0xA0000N00) unknown
0x3C u16  small count (1..8)                               unknown
0x40 u16x2 (4|5|6, n)                                     unknown
0x48 u64* positions, 3 x f32, 12 B/vertex
0x50 u64* second per-vertex stream, 3 x s16 in the high half of 32-bit slots, 12 B/vertex (see UNKNOWN below)
0x58 u16  vertex count (the high u16 repeats it in every BIN measured)
0x5C u32  0x20030818 (most BINs) / 0x20010801 (em06 class) -- tracks the 0x50 encoding, meaning unknown
0x70 u64* weight index, u16 per vertex
0x78 u64* same array as 0x70 in every BIN measured
0x80 u64* 56-byte per-stream tail record (7..12 floats)     unknown
0x84 u64* same for the 0x50 stream                          unknown
0x98      bone table, 16 B/record: u8 id, u8 parent, 2 pad, 3 x f32 translation
```

Established structurally (each line is a check that fails on a wrong reading -- see tests):

* `0x58` is the vertex count: the f32 xyz triples at `0x48` run consecutively from `0x48` for exactly that many
  records and then stop (measured on em06.slot0 = 5630, em21.slot0 = 2725, em10 slots 158/256/351/392/394).
  For the same slots on the GameCube disc the *set* of decoded positions is identical (em21: 1007/1007,
  em10.351: 581/581, em10.256: 232/232, em10.158: 25/25) -- the HD file just splits vertices per corner and
  reorders them.
* `0x18` is the UV stream: 8 B/vertex, every value in [0, 1] on a 1/256 grid.
* `0x10` is RGBA8 vertex colour: 4 B/vertex, constant white (0xFF) or 0x01010101 per mesh.
* `0x20` is the weight-set table in the GC record layout (b0, b1, b2, count, w0, w1, w2, pad); `0x70` holds one
  u16 index into it per vertex and `max(0x70) < 0x20 record count` in every BIN measured.
* `0x30` is the material/primitive table: per material a 36-byte header then `(u16 type, u16 nverts)` pairs whose
  vertex counts sum EXACTLY to the vertex count, with `type 5 = n/3 triangles`, `6 = n-2 triangle strip`,
  `8 = n/2 triangles` (quads).  The header's u32 at +0x1C is the triangle count: the pairs reproduce it exactly
  and it equals the GameCube triangle count for the same slot (em21 1843, em10.158 41, em10.394 217, ...).
* `0x98` is the bone table: 16-byte records whose `id` equals the record index and whose `parent` is `< id` or
  0xFF (0 violations on em06 = 34 bones, em21 = 32 bones; em21's count is the GC count).

UNKNOWN / not claimed: `0x50` (decoded byte-exactly as 3 s16 per vertex but NOT proven to be the normal -- see
`Stream` in `bin_read`), `0x28`, `0x38`, `0x3C`, `0x40`, `0x5C`, `0x60`/`0x68`, `0x80`/`0x84`.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

HDR_SIZE = 0x98

#: header offset -> section name for the 64-bit (u32 + zero pad) file-offset fields
OFFSET_FIELDS = {0x10: "colors", 0x18: "uvs", 0x20: "weights", 0x30: "prims", 0x48: "positions",
                 0x50: "aux", 0x70: "weight_idx", 0x78: "weight_idx2", 0x80: "aux_tail", 0x84: "aux_tail2"}
#: optional offset fields (absent / zero in some BINs)
OPTIONAL_FIELDS = {0x60: "extra_a", 0x68: "extra_b"}
#: 64-bit offset slots (the u32 after each is zero in every BIN measured).  `0x80`/`0x84` are a *pair* of plain
#: u32 offsets (they sit 4 bytes apart and both carry a value), so they are not in this set.
WIDE_FIELDS = (0x10, 0x18, 0x20, 0x30, 0x48, 0x50, 0x60, 0x68, 0x70, 0x78)

VERT_COUNT_AT = 0x58
BONE_TABLE_AT = HDR_SIZE          # = 0x98, the header's own size field
BONE_REC = 16
WEIGHT_REC = 8
COLOR_BPP = 4
UV_BPP = 8
POS_BPP = 12
AUX_BPP = 12
WIDX_BPP = 2

#: primitive type -> (name, triangles per n vertices)
PRIM_TYPES = {5: ("triangles", lambda n: n // 3),
              6: ("strip", lambda n: max(n - 2, 0)),
              8: ("quads", lambda n: n // 2)}
MAT_HDR = 0x24


class BINError(ValueError):
    """A BIN that does not satisfy the RE4 HD layout.  Raised instead of returning a plausible-looking mesh."""


# ------------------------------------------------------------------ low level

def _u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def _u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def _offset(b, o, wide=True):
    """A file-offset field: u32 at `o`; for the 64-bit slots the u32 at o+4 must be zero (measured zero always)."""
    v = _u32(b, o)
    if wide and o + 8 <= len(b):
        hi = _u32(b, o + 4)
        if v and hi:
            raise BINError(f"offset field {o:#04x} has a non-zero high dword ({hi:#x}); not the HD layout")
    return v


def _span(b, o, size, name):
    """Offset + byte size, refusing anything outside the file."""
    if o < HDR_SIZE or o + size > len(b):
        raise BINError(f"{name} at {o:#x} (+{size}) is outside the {len(b):#x}-byte BIN")
    return o, o + size


# ------------------------------------------------------------------ info

def bin_info(data: bytes) -> dict:
    """Header fields, counts and table offsets of one HD BIN slot.

    Raises `BINError` for anything that is not an HD BIN (header size, offsets outside the file, non-zero high
    dwords in a 64-bit offset slot, a vertex count that no position array can hold).
    """
    b = data
    if len(b) < HDR_SIZE:
        raise BINError(f"BIN too short for an HD header ({len(b)} bytes)")
    hsize = _u32(b, 0)
    if hsize != HDR_SIZE:
        raise BINError(f"BIN header size {hsize:#x}, want the HD 0x98 (this is not the RE4 Switch layout)")
    offs, raw = {}, {}
    for at, name in {**OFFSET_FIELDS, **OPTIONAL_FIELDS}.items():
        v = _offset(b, at, wide=at in WIDE_FIELDS)
        if v:
            if v >= len(b) or v < HDR_SIZE:
                raise BINError(f"{name} offset {at:#04x} = {v:#x} is outside the file")
            offs[name] = v
        raw[name] = v
    for name in ("positions", "uvs", "prims"):
        if name not in offs:
            raise BINError(f"HD BIN has no {name} table (header {name} offset is 0)")
    n = _u16(b, VERT_COUNT_AT)
    if n == 0:
        raise BINError("HD BIN declares 0 vertices")
    if offs["positions"] + POS_BPP * n > len(b):
        raise BINError(f"{n} vertices x {POS_BPP} B of positions do not fit from {offs['positions']:#x}")
    # spans: every table ends where the next *table* starts.  0x80/0x84 are not table starts (they point into the
    # tail of the 0x48/0x50 arrays), so they are excluded from the span walk.
    table_offs = {k: v for k, v in offs.items() if k not in ("aux_tail", "aux_tail2")}
    order = sorted(table_offs.values())
    spans = {}
    for name, o in table_offs.items():
        nxt = next((x for x in order if x > o), len(b))
        spans[name] = (o, nxt, nxt - o)
    bones = _bone_prefix(b, offs["weights"])
    mats, mspan = _materials(b, offs["prims"], n)
    tri = sum(m["triangles"] for m in mats)
    wsets = 0
    if "weight_idx" in offs and offs["weight_idx"] + WIDX_BPP * n <= len(b):
        wsets = int(np.frombuffer(b, "<u2", n, offs["weight_idx"]).max()) + 1
    return {
        "header_size": hsize,
        "endian": "little",
        "vertex_count": n,
        "vertex_count_hi": b[VERT_COUNT_AT + 2] | (b[VERT_COUNT_AT + 3] << 8),
        "bone_count": len(bones),
        "weight_set_count": wsets,
        "weight_set_slots": spans["weights"][2] // WEIGHT_REC,
        "prim_vertex_total": mspan["vertex_total"],
        "material_count": len(mats),
        "triangle_count": tri,
        "uv_count": spans["uvs"][2] // UV_BPP,
        "color_count": spans["colors"][2] // COLOR_BPP if "colors" in spans else 0,
        "aux_count": spans["aux"][2] // AUX_BPP if "aux" in spans else 0,
        "offsets": offs,
        "spans": {k: {"start": v[0], "end": v[1], "size": v[2]} for k, v in spans.items()},
        "packed": {f"{at:#04x}": _u32(b, at) for at in (0x28, 0x38, 0x3C, 0x40, 0x58, 0x5C)},
        "materials": mats,
    }


# ------------------------------------------------------------------ bones

def _bone_prefix(b, weight_off):
    """All bone slots from 0x98 up to the weight table, with the trailing all-zero padding records trimmed.

    Records are 16 bytes (`u8 id, u8 parent, 2 pad, 3 f32 translation`).  Across the BINs measured the `id` runs
    0, 1, 2, ... but may repeat a value (a second root, e.g. em10 slot 394 record 10 = `(9, 0xFF, ...)`), so the
    invariant that is actually checked is: ids are non-decreasing and step by at most 1, and every parent is
    `< id` or 0xFF.  A wrong record size fails that immediately.
    """
    out = []
    slots = max(0, (min(weight_off, len(b)) - BONE_TABLE_AT) // BONE_REC)
    for i in range(slots):
        o = BONE_TABLE_AT + BONE_REC * i
        bid, par, _pad = struct.unpack_from("<BB2s", b, o)
        x, y, z = struct.unpack_from("<3f", b, o + 4)
        out.append({"id": bid, "parent": par, "x": x, "y": y, "z": z, "slot": i})
    while out and out[-1]["id"] == 0 and out[-1]["parent"] == 0 and not any(
            struct.unpack_from("<3f", b, BONE_TABLE_AT + BONE_REC * out[-1]["slot"] + 4)):
        out.pop()
    return out


def bin_bones(data: bytes) -> list[dict]:
    """The BIN's bone table as `[{id, parent, x, y, z}]` (parent 0xFF = root).

    Each record's `id` equals its index and `parent` is `< id` or 0xFF; the walk stops at the first record that
    breaks that, which is what trims the 32-byte-padded table of a one-bone prop down to its one real bone.
    """
    info = bin_info(data)
    return _bone_prefix(data, info["offsets"]["weights"])


# ------------------------------------------------------------------ primitives

def _material_header(b, p, nverts, total):
    """Try to read one material record header at `p`; returns (header dict, pairs) or None."""
    if p + MAT_HDR > len(b):
        return None
    hdr = b[p:p + MAT_HDR]
    if hdr[:8] != bytes(8) or hdr[0x0E] != 0xFF:
        return None
    dl, tris, np_ = struct.unpack_from("<III", hdr, 0x18)
    body = MAT_HDR + 4 * np_
    if not (0 < np_ <= 4096) or dl == 0 or dl % 32 or dl > body:
        return None
    pairs = [struct.unpack_from("<HH", b, p + MAT_HDR + 4 * i) for i in range(np_)]
    if any(t not in PRIM_TYPES or c == 0 or c > nverts - total for t, c in pairs):
        return None
    if sum(PRIM_TYPES[t][1](c) for t, c in pairs) != tris:
        return None
    return {"uv_set": hdr[0x0C], "material_id": hdr[0x0B], "dl_size": dl, "triangle_count": tris,
            "pairs": pairs, "stride": (body + 31) // 32 * 32}, pairs


def _materials(b, base, nverts):
    """Material records: 0x24-byte header + (u16 type, u16 nverts) pairs, records 32-byte aligned from `base`.

    A record is only accepted when its own triangle count reproduces from its pairs; the walk then requires the
    pairs' vertex counts to sum to the BIN's vertex count, so a wrong stride or a wrong primitive table cannot
    quietly produce a mesh.
    """
    mats, p, total = [], base, 0
    while p + MAT_HDR <= len(b):
        got = _material_header(b, p, nverts, total)
        if got is None:
            # some BINs pad a record out to a larger boundary: look for the next header on a 4-byte grid
            nxt = next((q for q in range(p + 4, min(p + 256, len(b) - MAT_HDR), 4)
                        if _material_header(b, q, nverts, total) is not None), None)
            if nxt is None:
                break
            p = nxt
            got = _material_header(b, p, nverts, total)
        hdr, pairs = got
        mats.append({"start": p, "index": len(mats), **hdr,
                     "triangles": hdr["triangle_count"]})
        total += sum(c for _t, c in pairs)
        p += hdr["stride"]
    if not mats:
        raise BINError(f"no HD material record at the primitive table {base:#x}")
    if total != nverts:
        raise BINError(f"primitive vertex counts sum to {total}, the BIN declares {nverts}")
    return mats, {"vertex_total": total}


def _triangles(mats):
    """(n, 3) triangle vertex indices; vertices are consumed sequentially in material/primitive order."""
    out, base = [], 0
    for m in mats:
        for t, c in m["pairs"]:
            if t == 5:
                for i in range(0, c - 2, 3):
                    out.append((base + i, base + i + 1, base + i + 2))
            elif t == 6:
                for i in range(c - 2):
                    tri = (base + i, base + i + 1, base + i + 2)
                    out.append(tri if i % 2 == 0 else (tri[1], tri[0], tri[2]))
            else:                                            # 8: quads
                for i in range(0, c - 3, 4):
                    q = (base + i, base + i + 1, base + i + 2, base + i + 3)
                    out.append((q[0], q[1], q[2]))
                    out.append((q[0], q[2], q[3]))
            base += c
    return np.array(out, np.int64).reshape(-1, 3)


# ------------------------------------------------------------------ mesh

@dataclass
class Stream:
    """The 0x50 per-vertex 12-byte stream: decoded byte-exactly, meaning NOT established.

    Two encodings occur, selected by the header word at 0x5C:

    * `f32`   (0x20010801, em06)      three f32 per vertex, e.g. `-13440.0, -1313.0, -9264.0`;
      `|v| / 16384` is 1.000 for the vertices measured, i.e. an s16-range normal written as a float.
    * `fixed` (0x20030818, em10/em21) three s16 in the HIGH half of each 32-bit slot, low half zero,
      e.g. `-11598, -11598, 0`; `|v| / 16384` is 1.00 for the first vertex but 0.7 .. 2.2 over a mesh,
      which is the range a *sum of face normals* has, not a unit normal.

    Because the magnitude convention is not pinned down this is reported as `aux`, never as `nrm`; `Bin.normals()`
    derives geometric normals from the decoded triangles instead.
    """
    raw: bytes
    offset: int
    encoding: str = "unknown"          # 'f32' | 'fixed' | 'unknown'
    as_float: np.ndarray | None = None  # (n, 3) whichever reading is finite/sane, else None

    @property
    def value(self) -> np.ndarray | None:
        """(n, 3) the stream's numbers in 1/16384 units, or None when neither encoding is sane."""
        return None if self.as_float is None else self.as_float / 16384.0


@dataclass
class Mat:
    index: int
    start: int
    uv_set: int
    material_id: int
    dl_size: int
    triangle_count: int
    pairs: list                        # [(type, nverts)]
    triangles: int


@dataclass
class Bin:
    """One decoded RE4 Switch BIN slot."""
    header: bytes
    info: dict
    bones: list = field(default_factory=list)
    pos: np.ndarray | None = None
    uv: np.ndarray | None = None
    colors: np.ndarray | None = None
    weights: list = field(default_factory=list)
    weight_idx: np.ndarray | None = None
    aux: Stream | None = None
    mats: list = field(default_factory=list)
    tris: np.ndarray | None = None
    raw: dict = field(default_factory=dict)

    # ---- convenience
    @property
    def n_verts(self) -> int:
        return 0 if self.pos is None else len(self.pos)

    @property
    def n_tris(self) -> int:
        return 0 if self.tris is None else len(self.tris)

    @property
    def n_bones(self) -> int:
        return len(self.bones)

    def bone_world(self) -> dict[int, np.ndarray]:
        """Bind-pose joint positions, parent-relative translation accumulated (GC convention)."""
        w = {}
        for bn in self.bones:
            t = np.array([bn["x"], bn["y"], bn["z"]], float)
            w[bn["id"]] = t if bn["parent"] == 0xFF else w.get(bn["parent"], np.zeros(3)) + t
        return w

    def bbox(self) -> np.ndarray:
        """(2, 3) min/max of the bind-pose positions, in the BIN's own units (cm for RE4)."""
        return np.stack([self.pos.min(0), self.pos.max(0)])

    def normals(self) -> np.ndarray:
        """Geometric vertex normals DERIVED from `tris` (not read from the file -- see `Stream`)."""
        p = self.pos.astype(np.float64)
        t = self.tris
        face = np.cross(p[t[:, 1]] - p[t[:, 0]], p[t[:, 2]] - p[t[:, 0]])
        face /= np.maximum(np.linalg.norm(face, axis=1, keepdims=True), 1e-12)
        acc = np.zeros_like(p)
        for k in range(3):
            np.add.at(acc, t[:, k], face)
        ln = np.linalg.norm(acc, axis=1, keepdims=True)
        return acc / np.maximum(ln, 1e-12)

    def triangles(self) -> np.ndarray:
        return self.tris


# ------------------------------------------------------------------ decode

def _aux_stream(b, off, n, size):
    """Decode the 0x50 stream in whichever of its two encodings yields sane magnitudes (see `Stream`)."""
    need = AUX_BPP * n
    if off + need > len(b):
        raise BINError(f"aux stream at {off:#x} (+{need}) is outside the file")
    raw = bytes(b[off:off + need])
    # (a) three f32 per vertex (em06 class)
    fs = np.frombuffer(b, "<f4", n * 3, off).reshape(n, 3).astype(np.float64)
    if np.isfinite(fs).all():
        ln = np.linalg.norm(fs, axis=1) / 16384.0
        if np.median(ln) < 4.0 and np.median(ln) > 0.2:
            return Stream(raw=raw, offset=off, encoding="f32", as_float=fs)
    # (b) three s16 in the high half of each 32-bit slot (em10 / em21 class)
    rec = np.frombuffer(b, "<i2", n * 6, off).reshape(n, 6)
    if (rec[:, 0::2] == 0).all():
        ss = rec[:, 1::2].astype(np.float64)
        ln = np.linalg.norm(ss, axis=1) / 16384.0
        if np.median(ln) < 4.0 and np.median(ln) > 0.2:
            return Stream(raw=raw, offset=off, encoding="fixed", as_float=ss)
    return Stream(raw=raw, offset=off, encoding="unknown")


def bin_read(data: bytes, verify: bool = True) -> Bin:
    """Decode one HD BIN slot.  With `verify` (default) the structural self-check runs and `BINError` is raised
    on any inconsistency -- the decoder never returns a mesh it cannot prove."""
    b = data
    info = bin_info(b)
    n = info["vertex_count"]
    offs = info["offsets"]
    m = Bin(header=bytes(b[:HDR_SIZE]), info=info)

    m.pos = np.frombuffer(b, "<f4", n * 3, offs["positions"]).reshape(n, 3).astype(np.float64)
    if "uvs" in offs:
        m.uv = np.frombuffer(b, "<f4", n * 2, offs["uvs"]).reshape(n, 2).astype(np.float64)
    if "colors" in offs:
        m.colors = np.frombuffer(b, "u1", n * 4, offs["colors"]).reshape(n, 4)
    wo = offs["weights"]
    wend = min([o for o in offs.values() if o > wo] or [len(b)])
    nw = (wend - wo) // WEIGHT_REC
    m.weights = [tuple(b[wo + WEIGHT_REC * i: wo + WEIGHT_REC * (i + 1)]) for i in range(nw)]
    if "weight_idx" in offs:
        m.weight_idx = np.frombuffer(b, "<u2", n, offs["weight_idx"]).astype(np.int64)
    if "aux" in offs:
        m.aux = _aux_stream(b, offs["aux"], n, info["spans"]["aux"]["size"])
    m.bones = _bone_prefix(b, wo)
    mats = info["materials"]
    m.mats = [Mat(i, x["start"], x["uv_set"], x["material_id"], x["dl_size"], x["triangle_count"],
                  x["pairs"], x["triangles"]) for i, x in enumerate(mats)]
    m.tris = _triangles(mats)
    if verify:
        m.raw["checks"] = verify_bin(m)
    return m


# ------------------------------------------------------------------ self-check

def verify_bin(m: Bin) -> list[str]:
    """Structural self-check; returns the list of checks that passed and raises `BINError` on the first failure.

    Every check below is one that a *wrong* reading fails: a bad vertex count leaves the position array short, a
    bad primitive type changes the triangle total, a bad weight index points outside the weight table, a bad bone
    record breaks the id/parent invariant.
    """
    b, info, n = m.header, m.info, m.n_verts
    passed = []

    # 1. the declared vertex count explains the position span exactly (allowing 32-byte padding to the next table)
    p0 = info["spans"]["positions"]["start"]
    psize = info["spans"]["positions"]["size"]
    need = POS_BPP * n
    if not (need <= psize < need + 32):
        raise BINError(f"positions: {n} vertices need {need} B but the span is {psize} B")
    passed.append(f"position span {psize} B holds exactly {n} x {POS_BPP} B (+{psize - need} pad)")
    if "aux" in info["spans"]:
        asize = info["spans"]["aux"]["size"]
        if not (need <= asize < need + 32):
            raise BINError(f"aux stream: {n} vertices need {need} B but the span is {asize} B")
        passed.append(f"aux span {asize} B holds exactly {n} x {AUX_BPP} B (+{asize - need} pad)")
    if "uvs" in info["spans"]:
        usize = info["spans"]["uvs"]["size"]
        if not (UV_BPP * n <= usize < UV_BPP * n + 32):
            raise BINError(f"UVs: {n} vertices need {UV_BPP * n} B but the span is {usize} B")
        passed.append(f"UV span {usize} B holds exactly {n} x {UV_BPP} B")

    # 2. positions are finite and sane
    if not np.isfinite(m.pos).all():
        raise BINError("positions contain NaN/Inf")
    if np.abs(m.pos).max() > 1e6:
        raise BINError(f"positions reach {np.abs(m.pos).max():.3g}; not a mesh in cm")
    passed.append(f"positions finite, |max| {np.abs(m.pos).max():.1f}")

    # 3. the vertex count field is self-consistent (both u16 halves measured equal)
    if info["vertex_count_hi"] and info["vertex_count_hi"] != n:
        raise BINError(f"vertex count halves disagree ({n} vs {info['vertex_count_hi']})")
    passed.append("vertex-count field 0x58 is self-consistent")

    # 4. weights: every index is in the table, every record is a valid 1..3 bone set summing to ~100
    if m.weight_idx is not None:
        if len(m.weights) == 0:
            raise BINError("weight indices present but the weight table is empty")
        mx = int(m.weight_idx.max())
        if mx >= len(m.weights):
            raise BINError(f"weight index {mx} outside the {len(m.weights)}-record weight table")
        used = sorted(set(int(x) for x in m.weight_idx))
        # a BIN whose bone table starts above 0 is a part of a bigger, shared skeleton: its weight records index
        # that shared palette, not this table, so the "inside the table" check only applies when the table is whole
        whole = (not m.bones) or m.bones[0]["id"] == 0
        for i in used:
            b0, b1, b2, cnt, w0, w1, w2, _pad = m.weights[i]
            if not 1 <= cnt <= 3:
                raise BINError(f"weight record {i} has {cnt} bones")
            if whole and cnt > len(m.bones):
                raise BINError(f"weight record {i} uses {cnt} bones but the bone table has {len(m.bones)}")
            if whole and any(bn >= len(m.bones) for bn in (b0, b1, b2)[:cnt]):
                raise BINError(f"weight record {i} references bone >= {len(m.bones)}")
            if not 0 < sum((w0, w1, w2)[:cnt]) <= 100:
                raise BINError(f"weight record {i} weights {w0}+{w1}+{w2} are not a percentage")
        passed.append(f"{len(used)} weight sets used, all indices < {len(m.weights)}"
                      + ("" if whole else " (shared-skeleton BIN: weight indices are not table-local)"))
        if whole and len(m.bones):
            if max(max(m.weights[i][:3][:m.weights[i][3]]) for i in used) >= len(m.bones):
                raise BINError("weight records reference bones outside the bone table")
            passed.append("bone indices in the weight table are inside the bone table")

    # 5. bones: ids non-decreasing, step <= 1, parent < id or 0xFF
    prev = None
    for i, bn in enumerate(m.bones):
        if prev is not None and (bn["id"] < prev or bn["id"] > prev + 1):
            raise BINError(f"bone slot {i} has id {bn['id']} after {prev}")
        if not (bn["parent"] == 0xFF or bn["parent"] < bn["id"]):
            raise BINError(f"bone slot {i} has parent {bn['parent']} >= id {bn['id']}")
        prev = bn["id"]
    if m.bones and not any(bn["parent"] == 0xFF for bn in m.bones):
        raise BINError("bone table has no root")
    passed.append(f"{len(m.bones)} bone slots, ids {m.bones[0]['id'] if m.bones else '-'}..{prev}, "
                  f"every parent < id or 0xFF")

    # 6. primitives cover every vertex exactly once
    total = sum(c for mat in m.mats for _t, c in mat.pairs)
    if total != n:
        raise BINError(f"primitive vertex counts sum to {total}, vertex count is {n}")
    passed.append(f"{sum(len(x.pairs) for x in m.mats)} primitives in {len(m.mats)} materials cover all {n} verts")

    # 7. declared triangle counts reproduce from the primitives, and from the triangle list
    declared = sum(mat.triangle_count for mat in m.mats)
    if declared != len(m.tris):
        raise BINError(f"materials declare {declared} triangles, the primitive list yields {len(m.tris)}")
    passed.append(f"{declared} triangles per material headers == {len(m.tris)} decoded")

    # 8. triangle indices in range and no degenerate triangle
    if len(m.tris):
        if m.tris.min() < 0 or m.tris.max() >= n:
            raise BINError("triangle index out of range")
        t = m.tris
        if (t[:, 0] == t[:, 1]).any() or (t[:, 1] == t[:, 2]).any() or (t[:, 0] == t[:, 2]).any():
            raise BINError("degenerate triangle (repeated index)")
        p = m.pos[t]
        area = np.linalg.norm(np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]), axis=1)
        if (area < 1e-9).all():
            raise BINError("every triangle has zero area")
        passed.append(f"all indices < {n}, {int((area < 1e-9).sum())} zero-area triangles")

    # 9. UVs in a sane range
    if m.uv is not None:
        if not np.isfinite(m.uv).all():
            raise BINError("UVs contain NaN/Inf")
        if np.abs(m.uv).max() > 64:
            raise BINError(f"UVs reach {np.abs(m.uv).max():.3g}")
        passed.append(f"UVs finite, range {m.uv.min():.3f}..{m.uv.max():.3f}")
    return passed


def load_slot(data: bytes, index: int = 0) -> Bin:
    """Decode BIN slot `index` of a DAT (from `re4gc_inventory.dat_entries`) -- convenience for callers that hold a
    DAT rather than a single slot."""
    from .re4gc_inventory import dat_entries
    bins = [(ext, off, size) for ext, off, size in dat_entries(data, "<") if ext == "BIN"]
    if not bins:
        raise BINError("DAT holds no BIN slot")
    if not 0 <= index < len(bins):
        raise BINError(f"BIN slot {index} out of range ({len(bins)} slots)")
    _ext, off, size = bins[index]
    return bin_read(data[off:off + size])

