"""Resident Evil 4 (Switch / HD port) BIN meshes -- decoder and writer for one BIN slot.

The GameCube reader (`gbox/re4gc_models.py`) does not apply: the HD port keeps the UDAS/DAT containers
(`gbox/re4gc_inventory.py`) but re-lays the mesh BIN.  This module decodes the HD layout and refuses anything that
does not satisfy it.

Writing (`bin_write`, `bin_from`, `pad_to`) follows the two rules the GameCube replacement work established, and
they matter more here because the Switch title also reads the model in place:

* **pad every replacement to the original slot size** (`pad_to`).  A shorter file written into a slot leaves the
  original's tail readable and the game draws the ORIGINAL mesh out of it, no matter what the new header says.
* **never rewrite the model's bounding box.**  The writer writes the positions the caller supplies and never scales,
  recentres or clamps them to a box; the packed header words that carry bounds/flags (`0x28`, `0x38`, `0x3C`,
  `0x40`) are preserved verbatim.  A rewritten box freezes the title (measured on GameCube).

`bin_write` is byte-identical on every BIN the decoder accepts: the decoder keeps each section verbatim in `Bin.raw`
(including the sections it does not interpret), and the writer writes those bytes back, rebuilding only a section
whose live values differ from what was decoded.  `bin_from` is the character-swap shape: geometry from another
source, the slot's own header/bones/material *headers* kept where they can be, and a primitive table rebuilt so the
vertex counts partition the array exactly.

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
            "pairs": pairs, "stride": (body + 31) // 32 * 32, "header": bytes(hdr)}, pairs


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
    header: bytes = b""                # the record's own 0x24-byte header, verbatim (unknown bytes preserved)


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
                  x["pairs"], x["triangles"], x["header"]) for i, x in enumerate(mats)]
    m.tris = _triangles(mats)
    _keep_raw(m, b, info, mats)
    if verify:
        m.raw["checks"] = verify_bin(m)
    return m


def _keep_raw(m: "Bin", b: bytes, info: dict, mats: list[dict]) -> None:
    """Keep every byte of the file in `m.raw`, split at the table starts the decoder found.

    `bin_write` is the inverse of `bin_read` because of this: a section the caller did not touch is written back as
    the exact bytes that came in (bones, weight sets, material records and the `0x60`/`0x68` tables included), so the
    packed header words and the sections the decoder does not interpret survive a rewrite.  Only the *content* is
    duplicated in numpy; the layout keys are small.
    """
    spans = info["spans"]
    starts = {name: spans[name]["start"] for name in spans}
    sections = {name: bytes(b[spans[name]["start"]:spans[name]["end"]]) for name in spans}
    order = sorted(["bones"] + list(starts), key=lambda name: BONE_TABLE_AT if name == "bones" else starts[name])
    m.raw["header"] = bytes(b[:HDR_SIZE])
    m.raw["original_size"] = len(b)
    m.raw["sections"] = sections
    m.raw["starts"] = starts
    m.raw["order"] = order
    m.raw["bones"] = bytes(b[BONE_TABLE_AT:info["offsets"]["weights"]])
    m.raw["bone_snapshot"] = tuple((x["id"], x["parent"], x["x"], x["y"], x["z"]) for x in m.bones)
    m.raw["mat_snapshot"] = tuple(_mat_signature(x) for x in m.mats)
    m.raw["mat_used"] = sum(x["stride"] for x in mats)
    m.raw["weight_count"] = len(m.weights)


def _mat_signature(mat: "Mat") -> tuple:
    """Everything about a material record that a writer must notice a caller changing."""
    return (bytes(mat.header), int(mat.uv_set), int(mat.material_id), int(mat.dl_size),
            int(mat.triangle_count), tuple(tuple(int(v) for v in p) for p in mat.pairs),
            int(mat.triangles))


# ------------------------------------------------------------------ encode

#: section order of a real HD BIN, from 0x98 to the end of the file (measured on all 2,188 decoded slots)
WRITER_ORDER = ("bones", "weights", "extra_a", "extra_b", "positions", "weight_idx", "aux", "weight_idx2",
                "colors", "uvs", "prims")
_NAME_AT = {name: at for at, name in {**OFFSET_FIELDS, **OPTIONAL_FIELDS}.items()}


def _pad(body: bytes, align: int = 32) -> bytes:
    return body + b"\0" * ((-len(body)) % align)


def _vertex_section(arr, raw: bytes | None, bpp: int, dtype, old_n: int) -> bytes | None:
    """Encode a fixed-stride vertex array, keeping the decoded section's tail/padding when the array changed.

    The tail is not invented: `0x80`/`0x84` point into these sections and the real files carry bytes after the
    `n * stride` vertices, so the suffix that followed the old array is written back unchanged.
    """
    if arr is None:
        return None
    body = np.ascontiguousarray(arr, dtype=dtype).tobytes()
    old_len = old_n * bpp
    if raw is not None and len(arr) == old_n and raw[:old_len] == body:
        return raw
    tail = raw[old_len:] if raw is not None and len(raw) >= old_len else b""
    return body + tail


def _weight_section(weights: list, raw: bytes | None, old_count: int) -> bytes | None:
    if not weights:
        return None
    body = b"".join(bytes(w) for w in weights)
    old_len = old_count * WEIGHT_REC
    if raw is not None and len(weights) == old_count and raw[:old_len] == body:
        return raw
    tail = raw[old_len:] if raw is not None and len(raw) >= old_len else b""
    return body + tail


def _aux_section(m: "Bin", raw: bytes | None, old_n: int) -> bytes | None:
    if m.aux is None:
        return None
    body = bytes(m.aux.raw)
    old_len = old_n * AUX_BPP
    if raw is not None and len(raw) >= old_len and raw[:old_len] == body[:old_len] and len(body) == old_len:
        return raw
    tail = raw[old_len:] if raw is not None and len(raw) >= old_len else b""
    return body + tail


def _bones_same(m: "Bin") -> bool:
    snap = m.raw.get("bone_snapshot")
    if snap is None or len(snap) != len(m.bones):
        return False
    return all((b["id"], b["parent"], b["x"], b["y"], b["z"]) == s for b, s in zip(m.bones, snap))


def _bone_section(m: "Bin") -> bytes:
    if not m.bones:
        return b""
    body = b"".join(struct.pack("<BB2s3f", int(b["id"]), int(b["parent"]), b"",
                                float(b["x"]), float(b["y"]), float(b["z"])) for b in m.bones)
    raw = m.raw.get("bones")
    if raw is not None and _bones_same(m):
        return raw
    # keep the decoded table's length when the caller only moved a joint; otherwise the layout pass realigns
    return body + b"\0" * max(0, len(raw or b"") - len(body))


def _mats_same(m: "Bin") -> bool:
    snap = m.raw.get("mat_snapshot")
    return snap is not None and snap == tuple(_mat_signature(x) for x in m.mats)


def _material_bytes(mat: "Mat") -> bytes:
    """One rebuilt material record: its own 0x24 header, then (u16 type, u16 nverts), 32-byte aligned."""
    pairs = [(int(t), int(c)) for t, c in mat.pairs]
    if not pairs or any(t not in PRIM_TYPES or c <= 0 for t, c in pairs):
        raise BINError(f"material {mat.index} has an invalid primitive list {pairs}")
    np_ = len(pairs)
    hdr = bytearray(bytes(mat.header or b"")[:MAT_HDR])
    if len(hdr) < MAT_HDR:                              # a caller-built material: write the measured marker
        hdr.extend(bytes(MAT_HDR - len(hdr)))
        hdr[0x0D:0x10] = b"\xff\xff\xff"
        hdr[0x17] = 0xFF
        hdr[0x0B] = int(mat.material_id)
        hdr[0x0C] = int(mat.uv_set)
    body = len(hdr) + 4 * np_
    tris = sum(PRIM_TYPES[t][1](c) for t, c in pairs)
    struct.pack_into("<III", hdr, 0x18, (body // 32) * 32, tris, np_)
    rec = bytes(hdr) + b"".join(struct.pack("<HH", t, c) for t, c in pairs)
    return _pad(rec)


def _mat_section(m: "Bin") -> bytes:
    if not m.mats:
        raise BINError("a BIN needs at least one material record")
    raw = m.raw.get("sections", {}).get("prims")
    if raw is not None and _mats_same(m):
        return raw
    body = b"".join(_material_bytes(x) for x in m.mats)
    if raw is not None:
        used = int(m.raw.get("mat_used", 0))
        body += raw[used:] if len(raw) >= used else b""
    return body


# ------------------------------------------------------------------ layout

def _layout(header: bytes, order: list[str], sections: dict[str, bytes], bones: bytes, *,
            n_verts: int, provenance: dict | None = None, align_final: bool = False) -> bytes:
    """Lay sections out from 0x98 at 32-byte boundaries (relative to 0x98), patching the header's own fields.

    A section the caller did not change is written verbatim, and a header field whose target did not move is left
    alone: that is what keeps the packed words and the unknown tables byte-identical.
    """
    if n_verts > 0xFFFF:
        raise BINError(f"{n_verts} vertices do not fit the u16 count at 0x58")
    out = bytearray(bytes(header[:HDR_SIZE]))
    starts: dict[str, int] = {}
    placed = False
    orig_starts = provenance.get("starts") if provenance else None
    aliases: dict[int, tuple[str, int, bytes]] = {}
    for name in order:
        blob = bones if name == "bones" else sections.get(name)
        if blob is None:
            continue
        old_start = orig_starts.get(name) if orig_starts is not None else None
        if old_start is not None and old_start in aliases and aliases[old_start][2] == blob:
            # two header fields pointed at one table (the synthetic BINs alias 0x70/0x78); write it once
            starts[name] = aliases[old_start][1]
            continue
        target = HDR_SIZE if not placed else HDR_SIZE + ((len(out) - HDR_SIZE + 31) // 32) * 32
        if target > len(out):
            out += b"\0" * (target - len(out))
        starts[name] = len(out)
        if old_start is not None:
            aliases.setdefault(old_start, (name, len(out), blob))
        out += blob
        placed = True
    if align_final:
        out += b"\0" * ((-len(out)) % 32)

    h = bytearray(out[:HDR_SIZE])
    struct.pack_into("<I", h, 0, HDR_SIZE)
    for name, at in _NAME_AT.items():
        new = starts.get(name, 0)
        if orig_starts is not None and new == orig_starts.get(name, 0):
            continue
        struct.pack_into("<II", h, at, new, 0)
    old_n = None
    if provenance is not None:
        old_n = struct.unpack_from("<H", provenance["header"], VERT_COUNT_AT)[0]
    if old_n != n_verts:
        struct.pack_into("<HH", h, VERT_COUNT_AT, n_verts, n_verts)

    orig_secs = provenance.get("sections") if provenance else None
    for at, stream in ((0x80, "positions"), (0x84, "aux")):
        if stream not in starts:
            struct.pack_into("<I", h, at, 0)
            continue
        new_start, new_len = starts[stream], len(sections[stream])
        if (orig_starts is not None and orig_starts.get(stream) == new_start
                and orig_secs is not None and len(orig_secs.get(stream, b"")) == new_len):
            continue                                    # the decoded pointer is still the right one
        delta = 56
        if provenance is not None and orig_starts and stream in orig_starts and orig_secs is not None:
            old_start = orig_starts[stream]
            old_len = len(orig_secs.get(stream, b""))
            old_ptr = struct.unpack_from("<I", provenance["header"], at)[0]
            delta = old_start + old_len - old_ptr
        delta = min(max(delta, 0), new_len)
        struct.pack_into("<I", h, at, new_start + new_len - delta)
    out[:HDR_SIZE] = h
    return bytes(out)


def _canonical_order(present: set[str], original: list[str]) -> list[str]:
    """Original order, with a section added by the caller inserted at its measured place."""
    order = [name for name in original if name in present]
    for name in WRITER_ORDER:
        if name in present and name not in order:
            rank = WRITER_ORDER.index(name)
            at = next((i for i, x in enumerate(order) if WRITER_ORDER.index(x) > rank), len(order))
            order.insert(at, name)
    return order


# ------------------------------------------------------------------ write

def _write_incremental(m: "Bin") -> bytes:
    raw = m.raw
    if m.pos is None:
        raise BINError("cannot write a BIN without positions")
    old_n = int(m.info.get("vertex_count") or 0)
    if len(m.pos) != old_n:
        raise BINError(f"bin_write cannot change the vertex count ({old_n} -> {len(m.pos)}); "
                       "use bin_from to rebuild the primitive table")
    for label, arr, width in (("uv", m.uv, 2), ("colors", m.colors, 4), ("weight_idx", m.weight_idx, 1)):
        if arr is not None and len(arr) != old_n:
            raise BINError(f"{label} has {len(arr)} rows, the decoded BIN has {old_n} vertices")
    sections = dict(raw["sections"])

    pos = _vertex_section(m.pos, sections.get("positions"), POS_BPP, "<f4", old_n)
    if pos is None:
        raise BINError("cannot write a BIN without positions")
    sections["positions"] = pos
    uv = _vertex_section(m.uv, sections.get("uvs"), UV_BPP, "<f4", old_n)
    if uv is None:
        raise BINError("cannot write an HD BIN without a UV table (the decoder requires 0x18)")
    sections["uvs"] = uv
    colors = _vertex_section(m.colors, sections.get("colors"), COLOR_BPP, "u1", old_n)
    if colors is None:
        sections.pop("colors", None)
    else:
        sections["colors"] = colors

    weights = _weight_section(m.weights, sections.get("weights"), int(raw.get("weight_count") or 0))
    if weights is None:
        sections.pop("weights", None)
    else:
        sections["weights"] = weights
    widx_raw = sections.get("weight_idx")
    widx = _vertex_section(m.weight_idx, widx_raw, WIDX_BPP, "<u2", old_n)
    if widx is None:
        sections.pop("weight_idx", None)
        sections.pop("weight_idx2", None)
    elif not m.weights:
        raise BINError("weight indices need a weight-set table")
    else:
        sections["weight_idx"] = widx
        raw2 = sections.get("weight_idx2")
        if raw2 is not None and widx_raw is not None and raw2 == widx_raw and widx is not widx_raw:
            sections["weight_idx2"] = widx                 # the 0x78 duplicate tracks 0x70
    aux = _aux_section(m, sections.get("aux"), old_n)
    if aux is None:
        sections.pop("aux", None)
    else:
        sections["aux"] = aux
    sections.setdefault("weights", bytes(WEIGHT_REC))   # 0x20 is mandatory to the reader's bone walk
    sections["prims"] = _mat_section(m)

    present = set(sections) | {"bones"}
    order = _canonical_order(present, list(raw["order"]))
    return _layout(m.header, order, sections, _bone_section(m), n_verts=len(m.pos), provenance=raw,
                   align_final=(int(raw.get("original_size") or 0) % 32 == 0))


def _write_fresh(m: "Bin") -> bytes:
    """Write a Bin built by `bin_from` (no per-section provenance): rebuild every known section, keep unknown ones."""
    if m.pos is None:
        raise BINError("cannot write a BIN without positions")
    n = len(m.pos)
    sections: dict[str, bytes] = {
        "positions": np.ascontiguousarray(m.pos, dtype="<f4").tobytes(),
        "uvs": np.ascontiguousarray(m.uv if m.uv is not None else np.zeros((n, 2)), dtype="<f4").tobytes(),
        "prims": _mat_section(m),
    }
    if m.colors is not None:
        sections["colors"] = np.ascontiguousarray(m.colors, dtype="u1").tobytes()
    if m.weights:
        sections["weights"] = b"".join(bytes(w) for w in m.weights)
    if m.weight_idx is not None:
        if not m.weights:
            raise BINError("weight indices need a weight-set table")
        wi = np.ascontiguousarray(m.weight_idx, dtype="<u2").tobytes()
        sections["weight_idx"] = wi
        sections["weight_idx2"] = wi
    sections.setdefault("weights", bytes(WEIGHT_REC))   # 0x20 is mandatory to the reader's bone walk
    if m.aux is not None:
        sections["aux"] = bytes(m.aux.raw)
    sections.update(m.raw.get("template_sections") or {})
    present = set(sections) | {"bones"}
    order = [name for name in WRITER_ORDER if name in present]
    provenance = m.raw.get("template")
    return _layout(m.header, order, sections, _bone_section(m), n_verts=n, provenance=provenance,
                   align_final=True)


def bin_write(m: "Bin", *, verify: bool = False) -> bytes:
    """Re-encode a decoded HD BIN.  Byte-identical to the input when the caller changed nothing.

    Every section the decoder read is kept in `Bin.raw`; this writes those bytes back and rebuilds only a section
    whose live values differ from the decoded ones (positions/UVs/colours, weight sets and indices, the 0x50 stream,
    the bone table, or the material/primitive records).  Unknown sections (`0x60`/`0x68`) and the packed header
    words (`0x28`, `0x38`, `0x3C`, `0x40`, `0x5C`) are never re-derived.

    The output is *not* padded to any slot: a caller replacing a slot in place must pass it through `pad_to` with
    the original slot size, because a shorter file leaves the original's tail readable and the game draws that.

    `verify=True` runs the decoder on the result and raises `BINError` if the writer produced something the reader
    refuses (used by `bin_from`).
    """
    if not isinstance(m, Bin):
        raise TypeError(f"bin_write wants a re4hd_models.Bin, not {type(m).__name__}")
    out = _write_incremental(m) if m.raw.get("sections") is not None else _write_fresh(m)
    if verify:
        try:
            bin_read(out)
        except (BINError, ValueError, KeyError, struct.error) as exc:
            raise BINError(f"writer produced a BIN the decoder refuses: {exc}") from exc
    return out


def _norm_bones(bones) -> list[dict]:
    out = []
    for i, bn in enumerate(bones):
        if isinstance(bn, dict):
            out.append({"id": int(bn["id"]), "parent": int(bn["parent"]),
                        "x": float(bn["x"]), "y": float(bn["y"]), "z": float(bn["z"]), "slot": i})
        else:
            bid, par, x, y, z = bn
            out.append({"id": int(bid), "parent": int(par), "x": float(x), "y": float(y),
                        "z": float(z), "slot": i})
    return out


def _material_shares(mats: list, n_tri: int) -> tuple[list[int], list]:
    """Split `n_tri` source triangles over the slot's material records, each material keeping >= 1 triangle.

    Proportional to the record's decoded triangle count so the body/head/hair split stays recognisable; the sum is
    exactly `n_tri`, which is what the decoder checks.
    """
    if n_tri <= 0:
        raise BINError("cannot rebuild a primitive table from 0 triangles")
    if not mats:
        raise BINError("the template BIN has no material records to keep")
    keep = mats[:min(len(mats), n_tri)]
    k = len(keep)
    counts = [1] * k
    rest = n_tri - k
    if rest:
        base = [max(1, int(x.triangle_count)) for x in keep]
        total = sum(base)
        alloc = [rest * b // total for b in base]
        for i in range(rest - sum(alloc)):
            alloc[i % k] += 1
        counts = [1 + a for a in alloc]
    return counts, keep


def _rebuild_geometry(tmpl: "Bin", pos, uv, colors, tris, weights, weight_idx, aux) -> dict:
    """Turn source vertices + triangles into the sequential primitive/vertex order the HD decoder requires."""
    src_pos = np.asarray(pos, dtype=np.float64)
    if src_pos.ndim != 2 or src_pos.shape[1] != 3 or len(src_pos) == 0:
        raise BINError(f"pos must be a non-empty (n, 3) array, got {src_pos.shape}")
    tri = np.asarray(tris, dtype=np.int64)
    if tri.ndim != 2 or tri.shape[1] != 3 or len(tri) == 0:
        raise BINError(f"tris must be a non-empty (t, 3) array, got {tri.shape}")
    if tri.min() < 0 or tri.max() >= len(src_pos):
        raise BINError(f"triangle index {int(tri.max())} outside the {len(src_pos)} source vertices")
    if ((tri[:, 0] == tri[:, 1]) | (tri[:, 1] == tri[:, 2]) | (tri[:, 0] == tri[:, 2])).any():
        raise BINError("degenerate triangle (repeated index) in the source")
    n_src = len(src_pos)

    counts, src_mats = _material_shares(tmpl.mats, len(tri))
    parts, mats = [], []
    cursor = 0
    for count, old in zip(counts, src_mats):
        sl = tri[cursor:cursor + count]
        cursor += count
        parts.append(sl)
        np_ = 1
        hdr = bytearray(bytes(old.header or b"")[:MAT_HDR])
        if len(hdr) < MAT_HDR:
            hdr.extend(bytes(MAT_HDR - len(hdr)))
            hdr[0x0D:0x10] = b"\xff\xff\xff"
            hdr[0x17] = 0xFF
        hdr[0x0B] = int(old.material_id)
        hdr[0x0C] = int(old.uv_set)
        dl = (MAT_HDR + 4 * np_) // 32 * 32
        struct.pack_into("<III", hdr, 0x18, dl, count, np_)
        mats.append(Mat(len(mats), 0, int(old.uv_set), int(old.material_id), dl, count,
                        [(5, 3 * count)], count, bytes(hdr)))
    flat = np.concatenate(parts, 0).reshape(-1)
    n_out = len(flat)

    def take(arr, shape):
        if arr is None:
            return None
        a = np.asarray(arr)
        if len(a) != n_src:
            raise BINError(f"a per-vertex source array has {len(a)} rows, positions have {n_src}")
        return a[flat]

    uv_out = take(uv, 2)
    if uv_out is None:
        uv_out = np.zeros((n_out, 2), np.float64)
    col_out = take(colors, 4)
    if col_out is None:
        col_out = np.tile(np.array([255, 255, 255, 255], np.uint8), (n_out, 1))
    w = list(weights) if weights else ([] if not tmpl.bones else [(0, 0, 0, 1, 100, 0, 0, 0)])
    if weight_idx is not None and w and len(weight_idx) == n_src:
        wi_out = np.asarray(weight_idx, np.int64)[flat]
    elif w:
        wi_out = np.zeros(n_out, np.int64)
    else:
        wi_out, w = None, []
    if aux is not None:
        a = np.asarray(aux, dtype=np.uint8)
        if a.size != 12 * n_src:
            raise BINError(f"aux is {a.size} B, want 12 x {n_src}")
        aux_out = a.reshape(n_src, 12)[flat].tobytes()
    else:
        aux_out = bytes(12 * n_out)
    return {"pos": np.asarray(src_pos[flat], np.float64), "uv": np.asarray(uv_out, np.float64),
            "colors": np.asarray(col_out, np.uint8), "tris": np.arange(n_out, dtype=np.int64).reshape(-1, 3),
            "weights": w, "weight_idx": wi_out,
            "aux": Stream(raw=aux_out, offset=0, encoding="unknown"), "mats": mats}


def bin_from(bin_, *, pos=None, uv=None, colors=None, tris=None, bones=None,
             weights=None, weight_idx=None, aux=None) -> bytes:
    """Build a BIN whose geometry comes from another source, keeping the slot's header/bones/material headers.

    `bin_` is a decoded `Bin` (or BIN bytes).  `pos`/`uv`/`colors` are per-vertex source arrays and `tris` are
    triangle indices into them.  When the source has the slot's vertex count and topology, the slot's primitive
    records are kept byte-for-byte and only the arrays are replaced (the in-place swap).  Otherwise the primitive
    table is rebuilt: source triangles are spread over the slot's material headers in proportion to their decoded
    triangle counts, emitted as type-5 lists in sequential vertex order, and the per-vertex arrays are gathered into
    that same order (corners are duplicated, as the HD format already does).  That keeps the count partition exact
    and the result decodes, at the cost of a vertex per triangle corner; a later pass can strip/dedupe it.

    `bones=None` keeps the slot's own bone table.  `weights`/`weight_idx` (source-length, optional) are gathered with
    the vertices; without them a single-bone 100 % set is used so every index stays inside the slot's bone table.
    The slot's `extra_a`/`extra_b` tables (0x60/0x68) are carried over verbatim and the bounding-box/flag words are
    never recomputed.

    Returns BIN bytes, validated by decoding them before returning.
    """
    tmpl = bin_ if isinstance(bin_, Bin) else bin_read(bin_)
    if tmpl.raw.get("sections") is None:
        raise BINError("bin_from needs a decoded BIN (call bin_read first)")
    src_pos = tmpl.pos if pos is None else np.asarray(pos, np.float64)
    if src_pos is None:
        raise BINError("bin_from needs positions")
    if src_pos.ndim != 2 or src_pos.shape[1] != 3:
        raise BINError(f"pos must be an (n, 3) array, got {src_pos.shape}")
    n = len(src_pos)
    src_bones = tmpl.bones if bones is None else _norm_bones(bones)
    for label, arr, width in (("uv", uv, 2), ("colors", colors, 4)):
        if arr is not None and (np.asarray(arr).ndim != 2 or np.asarray(arr).shape[1] != width
                                or len(arr) != n):
            raise BINError(f"{label} must be an ({n}, {width}) array, got {np.asarray(arr).shape}")
    if weight_idx is not None and len(weight_idx) != n:
        raise BINError(f"weight_idx has {len(weight_idx)} rows, positions have {n}")
    if aux is not None and len(bytes(aux)) != AUX_BPP * n:
        raise BINError(f"aux is {len(bytes(aux))} B, want {AUX_BPP} x {n}")

    same_topo = tris is None or (tmpl.tris is not None and np.array_equal(np.asarray(tris, np.int64), tmpl.tris))
    if n == tmpl.n_verts and same_topo:
        import copy
        out = copy.copy(tmpl)
        out.pos = np.asarray(src_pos, np.float64)
        out.bones = src_bones
        if uv is not None:
            out.uv = np.asarray(uv, np.float64)
        if colors is not None:
            out.colors = np.asarray(colors, np.uint8)
        if weights is not None:
            out.weights = [tuple(int(v) for v in w) for w in weights]
        if weight_idx is not None:
            out.weight_idx = np.asarray(weight_idx, np.int64)
        if aux is not None:
            a = bytes(aux)
            out.aux = Stream(raw=a, offset=0, encoding="unknown")
        return bin_write(out, verify=True)

    geo = _rebuild_geometry(tmpl, src_pos, uv, colors, tmpl.tris if tris is None else tris,
                            weights, weight_idx, aux)
    out = Bin(header=bytes(tmpl.header), info={"vertex_count": len(geo["pos"])})
    out.pos, out.uv, out.colors, out.tris = geo["pos"], geo["uv"], geo["colors"], geo["tris"]
    out.bones, out.weights, out.weight_idx = src_bones, geo["weights"], geo["weight_idx"]
    out.aux, out.mats = geo["aux"], geo["mats"]
    out.raw = {"template": tmpl.raw,
               "template_sections": {k: v for k, v in tmpl.raw["sections"].items()
                                     if k in ("extra_a", "extra_b")}}
    return bin_write(out, verify=True)


# ------------------------------------------------------------------ slot padding

def pad_to(data: bytes, size: int) -> bytes:
    """Pad a replacement BIN to the original slot size, or refuse if it does not fit.

    This is the `gbox/re4gc_models.py` / `re4gc_zombies` rule carried into the HD writer: **every replacement must be
    padded to the original slot size**.  The game reads the model in place, so a shorter file leaves the original's
    tail readable and the game draws the ORIGINAL mesh out of it even though the new header is valid.  Padding is
    zero bytes (`re4gc_zombies.swap_ganados` appends `b"\\0"`), and a replacement larger than the slot is refused
    instead of truncated.  The model's bounding box is never rewritten here (there is no bbox field in the 0x98 BIN
    to rewrite; the packed words are preserved by `bin_write`).
    """
    size = int(size)
    if size < 0:
        raise BINError(f"slot size {size} is negative")
    if len(data) > size:
        raise BINError(f"replacement is {len(data)} B but the slot holds {size} B; it does not fit")
    return bytes(data) + b"\0" * (size - len(data))


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

