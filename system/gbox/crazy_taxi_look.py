"""Crazy Taxi (GameCube, GCTE51) driver look writer, v2: the donor's own colours and textures, its full mesh, and the
right orientation per body part.

The v1 writer (gbox.crazy_taxi.encode_shape via gbox.crazy_taxi_swap.fit_blob) kept every part blob at its stock size
and the driver's stock textures, sampling one texel per material, so a donor came out as a few low-poly blocks in the
stock driver's colours (cast_crazy_taxi_usa_sonic_adventure_us_82d27070_fix: "Sonic" in Axel's green, red and skin
tones). What main.dol actually does (GCTE51, read from the disassembly):

* **Archives grow.** ``polDC0.all`` and ``texDc0.all`` are opened by the archive loader at 0x800066e0: DVDOpen, then
  ``malloc(file length)``, DVDRead, then every entry is registered **by name** (0x80006d24) at
  ``base + align32(0x10 + count * 0x44 + 0x1f)`` plus the running sum of the sizes. Shapes are then fetched by name
  (0x800062d0, the ``sShape`` lookups at 0x80086728), so a blob may change size as long as names, count and 32-byte
  sizes stay valid. On the disc the file may then move past the last file (gbox.romexport.gc_put_file rewrites the FST
  entry); ``sizes.dat`` only budgets the per-level banks (polDC1..3, texDC1..3, ...), not these two.
* **Texture binding.** A ``.shp`` header word 0x10 is the number of entries in its texture table at 0x11c; each entry
  is 0x2c bytes: name[0x28] + a pointer word the loader fills. The shape fix-up (0x8000b6bc) looks every name up by
  name (0x800062d0) and **hangs forever when one is missing** (``b .`` at 0x8000b794), then replaces each draw record's
  texture index with that entry's texture object. Driver parts name their own textures (TY_plyrA_face1.tex ...), not
  just white.tex.
* **Material records** are 0x24 bytes at 0x110, ``header[0x14] + header[0x18] + header[0x1c]`` of them (three draw
  groups: the opaque pass, then the ``_tr`` pass). A record whose first word is 0x38 is a state record (it points at
  the header's VAT word pair); every other record is ``(display list offset, size, texture index, 3 words, draw type,
  2 words)``. 1584/1586 shapes of the bank parse this way, every people part among them.
* **.tex** (in texDc0.all): w, h, flags, GX format, wrap s, wrap t, mipmap flag, then pixel data at 0x60. The loader
  (0x8000d790) calls GXInitTexObj(tex + 0x24, tex + 0x60, w, h, fmt, wrap_s, wrap_t, mip) on first use, so a texture
  may change size and format. The bank holds CMPR (14) and RGBA8 (6) textures.
* **Vertex formats.** Positions s16 * scale / 256 + header centre, normals s16 / 16384, TEX0 s16 / 128 (stock driver
  UVs span 0..128, the whole texture), CLR0 RGB8; one u16 index per attribute in the display lists.

So this writer gives each driver one texture atlas (its own exclusive texture, resized, holding every donor texture
and flat colour), renames each part's texture-table entries to it, writes the donor's per-vertex UVs into it, and
writes every part with the donor segment at full detail (blobs grow; the bank and the archive are rebuilt).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

from . import crazy_taxi as ct

ARCHIVE_WORD1 = 0x00410020
TEX_HEADER = 0x60
GX_RGBA8, GX_CMPR = 6, 14
POS_FRAC, NRM_SCALE, UV_SCALE = 8, 16384.0, 128.0
STATE_RECORD = 0x38                       # a material record whose first word points at the header's VAT pair
RECORD = 0x24
TEX_ENTRY, TEX_NAME = 0x2C, 0x28
TEXBANK = "ct/texDC0.all"


# ----------------------------------------------------------------------------------------------- archives

def archive_data_start(count: int) -> int:
    """Where the first blob starts: main.dol 0x8000682c, (count * 0x44 + 0x2f) & ~0x1f past the archive start."""
    return (0x10 + count * 0x44 + 0x1F) & ~0x1F


def read_archive(data: bytes) -> list[tuple[str, bytes]]:
    """polDC0.all / texDc0.all -> [(name, blob)] in record order. Raises when the sizes do not end at EOF."""
    if len(data) < 0x10:
        raise ValueError("archive too small")
    count = struct.unpack_from("<I", data, 0)[0]
    off = archive_data_start(count)
    if count <= 0 or off > len(data):
        raise ValueError(f"bad archive count {count}")
    out = []
    for i in range(count):
        p = 0x10 + i * 0x44
        name = data[p:p + 64].split(b"\0")[0].decode("latin-1")
        size = struct.unpack_from("<I", data, p + 64)[0]
        out.append((name, data[off:off + size]))
        off += size
    if off != len(data):
        raise ValueError(f"archive sizes end at {off:#x}, file is {len(data):#x}")
    return out


def write_archive(entries, word1: int = ARCHIVE_WORD1) -> bytes:
    """Inverse of read_archive. Every blob must be a multiple of 0x20 (the loader keeps blobs 32-byte aligned for GX)."""
    hdr = bytearray(struct.pack("<4I", len(entries), word1, 0, 0))
    for name, blob in entries:
        nm = name.encode("latin-1")
        if len(nm) >= 64:
            raise ValueError(f"name too long: {name}")
        if len(blob) % 0x20:
            raise ValueError(f"{name}: {len(blob)} bytes is not a multiple of 0x20")
        hdr += nm.ljust(64, b"\0") + struct.pack("<I", len(blob))
    hdr += b"\0" * (archive_data_start(len(entries)) - len(hdr))
    return bytes(hdr) + b"".join(b for _, b in entries)


def replace_entries(data: bytes, new: dict[str, bytes]) -> bytes:
    """The archive with the named blobs replaced (any size); names and order stay. Raises for an unknown name."""
    entries = read_archive(data)
    have = {n for n, _ in entries}
    missing = sorted(set(new) - have)
    if missing:
        raise ValueError(f"not in the archive: {', '.join(missing[:5])}")
    return write_archive([(n, new.get(n, b)) for n, b in entries])


# ----------------------------------------------------------------------------------------------- .tex

def _pad32(b: bytes) -> bytes:
    return b + b"\0" * ((0x20 - len(b) % 0x20) % 0x20)


def tex_info(blob: bytes) -> dict:
    w, h, _flags, fmt, ws, wt, mip = struct.unpack_from(">7I", blob, 0)
    return {"w": w, "h": h, "fmt": fmt, "wrap_s": ws, "wrap_t": wt, "mip": mip}


def tex_data_size(w: int, h: int, fmt: int) -> int:
    if fmt == GX_CMPR:
        return -(-w // 8) * -(-h // 8) * 32
    if fmt == GX_RGBA8:
        return -(-w // 4) * -(-h // 4) * 64
    raise ValueError(f"GX format {fmt} not written here")


def tex_rgba(blob: bytes) -> np.ndarray:
    """A .tex blob -> (h, w, 4) uint8."""
    from .re4gc_models import tpl_decode_image
    i = tex_info(blob)
    return np.asarray(tpl_decode_image(i["fmt"], i["w"], i["h"], blob[TEX_HEADER:]), np.uint8)


def make_tex(rgba: np.ndarray, template: bytes | None = None, fmt: int = GX_CMPR) -> bytes:
    """(h, w, 4) uint8 -> a .tex blob: the template's header words (wrap modes) with the new size and format, the
    loader's runtime words zeroed, CMPR or RGBA8 data at 0x60, padded to 0x20."""
    from .re4gc_models import cmpr_encode
    img = np.asarray(rgba, np.uint8)
    h, w = img.shape[:2]
    if w & (w - 1) or h & (h - 1) or not (4 <= w <= 1024 and 4 <= h <= 1024):
        raise ValueError(f"texture size {w}x{h} is not a power of two in 4..1024")
    if img.shape[2] == 3:
        img = np.concatenate([img, np.full((h, w, 1), 255, np.uint8)], 2)
    if fmt == GX_CMPR:
        data = cmpr_encode(np.concatenate([img[..., :3], np.full((h, w, 1), 255, np.uint8)], 2))
    elif fmt == GX_RGBA8:
        out = bytearray()
        for by in range(0, h, 4):
            for bx in range(0, w, 4):
                blk = img[by:by + 4, bx:bx + 4].reshape(16, 4)
                out += bytes(v for px in blk for v in (px[3], px[0]))
                out += bytes(v for px in blk for v in (px[1], px[2]))
        data = bytes(out)
    else:
        raise ValueError(f"GX format {fmt} not written here")
    assert len(data) == tex_data_size(w, h, fmt)
    hdr = bytearray(TEX_HEADER)
    ws, wt = (struct.unpack_from(">2I", template, 0x10) if template else (1, 1))
    struct.pack_into(">7I", hdr, 0, w, h, 0, fmt, ws, wt, 0)
    return _pad32(bytes(hdr) + data)


# ----------------------------------------------------------------------------------------------- .shp structure

@dataclass
class Record:
    index: int          # record number (0-based) in the material block
    at: int             # blob offset of the record
    state: bool         # True: a state record (first word 0x38)
    group: int          # 0 opaque, 1 / 2 the later passes (header 0x14 / 0x18 / 0x1c counts)
    dl_off: int = 0
    dl_size: int = 0
    tex: int = 0
    vat: int = 0


def records(b: bytes) -> list[Record]:
    """The material records of a .shp (see the module doc). Raises when they do not parse."""
    mat, dl_base, tex_off = ct._u32(b, 0x110), ct._u32(b, 0x118), ct._u32(b, 0x11C) or len(b)
    counts = struct.unpack_from(">3I", b, 0x14)
    n = sum(counts)
    if not 0 < n < 512 or mat + RECORD * n > dl_base:
        raise ValueError(f"material records do not fit: {n} at {mat:#x}, lists at {dl_base:#x}")
    out = []
    for k in range(n):
        at = mat + RECORD * k
        group = 0 if k < counts[0] else 1 if k < counts[0] + counts[1] else 2
        w0, w1, w2 = struct.unpack_from(">3I", b, at)
        if w0 == STATE_RECORD:
            out.append(Record(k, at, True, group))
            continue
        if not (dl_base <= w0 and w0 + w1 <= tex_off and w1 > 0):
            raise ValueError(f"record {k} at {at:#x}: list {w0:#x}+{w1:#x} outside [{dl_base:#x}, {tex_off:#x})")
        out.append(Record(k, at, False, group, w0, w1, w2, b[w0] & 7))
    return out


def texture_names(b: bytes) -> list[str]:
    tex_off, n = ct._u32(b, 0x11C), ct._u32(b, 0x10)
    return [b[tex_off + TEX_ENTRY * i:tex_off + TEX_ENTRY * i + TEX_NAME].split(b"\0")[0].decode("latin-1")
            for i in range(n)]


def attrs_of(b: bytes) -> list[str]:
    return [a for a, o in ct.ATTR_OFFS if ct._u32(b, o)]


def array_counts(b: bytes) -> dict[str, int]:
    """Entries per present GX array (POS/NRM 6 bytes, CLR0 3, TEX0 4), bounded by the next array or the records."""
    mat = ct._u32(b, 0x110)
    offs = {a: ct._u32(b, o) for a, o in ct.ATTR_OFFS if ct._u32(b, o)}
    bounds = sorted(set(offs.values()) | {mat})
    stride = {"pos": 6, "nrm": 6, "clr": 3, "tex": 4}
    return {a: (min(x for x in bounds if x > o) - o) // stride[a] for a, o in offs.items()}


# ----------------------------------------------------------------------------------------------- .shp writer

def _align(n: int, a: int = 0x20) -> int:
    return (n + a - 1) // a * a


def stripify(tris: list[tuple]) -> tuple[list[list], list[tuple]]:
    """Greedy GX triangle strips over hashable corners, winding kept: strip triangle n is (v[n], v[n+1], v[n+2]) for
    even n and (v[n+1], v[n], v[n+2]) for odd n (gbox.crazy_taxi.decode_dl). Each seed tries its three rotations and
    keeps the longest. Returns (strips of >= 2 triangles, leftover triangles). Linear in the triangle count."""
    edge: dict = {}
    for i, (a, b, c) in enumerate(tris):
        for e, w in (((a, b), c), ((b, c), a), ((c, a), b)):
            edge.setdefault(e, []).append((i, w))
    used = [False] * len(tris)

    def grow(seq: list, taken: set) -> list:
        n = len(seq) - 2
        while True:
            e = (seq[-1], seq[-2]) if n % 2 else (seq[-2], seq[-1])
            nxt = next(((j, w) for j, w in edge.get(e, ()) if not used[j] and j not in taken), None)
            if nxt is None or len(seq) >= 0xFFFF:
                return seq
            taken.add(nxt[0])
            seq.append(nxt[1])
            n += 1

    strips, singles = [], []
    for i, t in enumerate(tris):
        if used[i]:
            continue
        best, best_taken = None, None
        for rot in range(3):
            taken = {i}
            seq = grow([t[rot], t[(rot + 1) % 3], t[(rot + 2) % 3]], taken)
            if best is None or len(seq) > len(best):
                best, best_taken = seq, taken
        for j in best_taken:
            used[j] = True
        if len(best) > 3:
            strips.append(best)
        else:
            singles.append(tuple(best))
    return strips, singles


def gx_list(corner_tris: list[tuple], vat: int, nattr: int) -> bytes:
    """GX display list for triangles of corners (one index tuple per corner, one u16 per attribute): 0x98|vat strips,
    then one 0x90|vat list of the leftovers."""
    strips, singles = stripify(corner_tris)
    out = bytearray()
    for s in strips:
        out += bytes([0x98 | vat]) + struct.pack(">H", len(s))
        for c in s:
            out += struct.pack(f">{nattr}H", *c)
    for s in range(0, len(singles), 0xFFFF // 3):
        chunk = singles[s:s + 0xFFFF // 3]
        out += bytes([0x90 | vat]) + struct.pack(">H", 3 * len(chunk))
        for t in chunk:
            for c in t:
                out += struct.pack(f">{nattr}H", *c)
    return bytes(out)


def encode_part(template: bytes, pos, nrm, uv, groups, *, name: str = "", tex_index=None, tex_names=None,
                scale: float | None = None, colour=(255, 255, 255), material_colour: int | None = None) -> bytes:
    """A driver part written from a template part, any size.

    pos (N, 3): vertices in the part's own frame with the header centre *included* (what gbox.crazy_taxi decodes);
    nrm (N, 3) unit normals; uv (N, 2) texture coordinates (0..1 = the whole texture). Vertex i is POS/NRM/TEX0 entry i
    (a CLR0 part gets one entry, `colour`). groups: one triangle list per draw record (record order); an empty list
    draws one zero-area triangle. tex_index: per draw record, the texture-table entry it binds (default: the template's).
    tex_names: replacement texture-table names (same count). scale: a new quantisation scale (radius follows it as on the
    disc: radius = scale * 32767 / 256); default the template's. material_colour: RGBA word for every draw record's
    +0x20, the material colour the game multiplies the texture by (Gena's jeans parts carry 0x617FB2FF, a blue that
    turned Amy's skirt and legs purple; Axel's untextured hair record 0x004901FF, green); default the template's.

    Kept from the template: the header (except array/region offsets, and scale/radius when given), every material
    record but its list pointer and texture index, the texture table's layout and count. Every list is written on the
    stock record's VAT."""
    recs = records(template)
    draws = [r for r in recs if not r.state]
    if len(groups) != len(draws):
        raise ValueError(f"{name}: {len(groups)} triangle groups for {len(draws)} draw records")
    attrs = attrs_of(template)
    if "pos" not in attrs or "tex" not in attrs:
        raise ValueError(f"{name}: needs POS and TEX0 arrays")
    pos, uv = np.asarray(pos, float).reshape(-1, 3), np.asarray(uv, float).reshape(-1, 2)
    nrm = np.asarray(nrm, float).reshape(-1, 3) if len(nrm) else np.tile([0.0, 1.0, 0.0], (len(pos), 1))
    V = len(pos)
    if V < 3 or len(uv) != V or len(nrm) != V:
        raise ValueError(f"{name}: {V} positions, {len(nrm)} normals, {len(uv)} UVs")
    if V > 0xFFFF:
        raise ValueError(f"{name}: {V} vertices > 65535 (u16 indices)")
    centre = np.asarray(struct.unpack_from(">3f", template, 0x20), float)
    sc = float(scale) if scale else struct.unpack_from(">f", template, 0x2C)[0]
    q = np.rint((pos - centre) * ((1 << POS_FRAC) / sc))
    if np.abs(q).max() > 32767:
        raise ValueError(f"{name}: a vertex lies {np.abs(pos - centre).max():.3f} from the centre, the s16 range at "
                         f"scale {sc:g} is {sc * 32767 / (1 << POS_FRAC):.3f}")
    qn = np.clip(np.rint(nrm * NRM_SCALE), -32767, 32767)
    qu = np.rint(uv * UV_SCALE)
    if np.abs(qu).max() > 32767:
        raise ValueError(f"{name}: UVs out of the s16 range")
    # GX indexes every attribute separately: keep each array's distinct quantised values once
    uq, pi = np.unique(q.astype(np.int64), axis=0, return_inverse=True)
    un, ni = np.unique(qn.astype(np.int64), axis=0, return_inverse=True)
    ut, ti = np.unique(qu.astype(np.int64), axis=0, return_inverse=True)
    pi, ni, ti = pi.reshape(-1), ni.reshape(-1), ti.reshape(-1)
    if max(len(uq), len(un), len(ut)) > 0xFFFF:
        raise ValueError(f"{name}: more than 65535 distinct positions, normals or UVs")
    out = bytearray(template[:0x120])
    if scale:
        struct.pack_into(">f", out, 4, sc * 32767 / (1 << POS_FRAC))
        struct.pack_into(">3f", out, 0x2C, sc, sc, sc)
    cur = 0x120
    offs = {}
    arrays = {"pos": uq.astype(">i2").tobytes(), "nrm": un.astype(">i2").tobytes(),
              "clr": bytes(colour[:3]) + b"\0", "tex": ut.astype(">i2").tobytes()}

    def corner(v: int) -> tuple:
        return tuple(int(pi[v]) if a == "pos" else int(ni[v]) if a == "nrm" else int(ti[v]) if a == "tex" else 0
                     for a in attrs)
    body = bytearray()
    for a in ("pos", "nrm", "clr", "tex"):
        if a in attrs:
            offs[a] = cur
            body += arrays[a]
            body += b"\0" * (_align(len(body)) - len(body))
            cur = 0x120 + len(body)
    for a, o in ct.ATTR_OFFS:
        struct.pack_into(">I", out, o, offs.get(a, 0))
    t_mat, t_dl, t_tex = ct._u32(template, 0x110), ct._u32(template, 0x118), ct._u32(template, 0x11C)
    mat_block = bytearray(template[t_mat:t_dl])
    mat_off = cur
    dl_base = _align(mat_off + len(mat_block))
    lists = bytearray()
    for k, (r, tris) in enumerate(zip(draws, groups)):
        tris = [tuple(int(i) for i in t) for t in tris] or [(0, 0, 0)]
        if any(not 0 <= i < V for t in tris for i in t):
            raise ValueError(f"{name}: record {r.index} indexes past {V} vertices")
        dl = gx_list([tuple(corner(i) for i in t) for t in tris], r.vat, len(attrs))
        dl += b"\0" * (_align(len(dl)) - len(dl))
        at = r.at - t_mat
        struct.pack_into(">II", mat_block, at, dl_base + len(lists), len(dl))
        if tex_index is not None:
            struct.pack_into(">I", mat_block, at + 8, int(tex_index[k]))
        if material_colour is not None:
            struct.pack_into(">I", mat_block, at + 0x20, int(material_colour) & 0xFFFFFFFF)
        lists += dl
    tex_off = dl_base + len(lists)
    table = bytearray(template[t_tex:])
    if tex_names is not None:
        if len(tex_names) != ct._u32(template, 0x10):
            raise ValueError(f"{name}: {len(tex_names)} texture names for {ct._u32(template, 0x10)} table entries")
        for i, nm in enumerate(tex_names):
            raw = nm.encode("latin-1")
            if not raw.endswith(b".tex") or len(raw) >= TEX_NAME:
                raise ValueError(f"{name}: bad texture name {nm!r}")
            table[TEX_ENTRY * i:TEX_ENTRY * i + TEX_NAME] = raw.ljust(TEX_NAME, b"\0")
    struct.pack_into(">4I", out, 0x110, mat_off, 0x120, dl_base, tex_off)
    blob = bytes(out) + bytes(body) + bytes(mat_block) + b"\0" * (dl_base - mat_off - len(mat_block)) + bytes(lists) \
        + bytes(table)
    blob = _pad32(blob)
    check_part(template, blob, name)
    return blob


def check_part(template: bytes, blob: bytes, name: str = "", texture_bank: set | None = None) -> dict:
    """The GPU / loader validator for a written part of any size (gbox.crazy_taxi.check_written is the same-size form).

    Raises ValueError unless: the blob is 32-byte sized; the header outside the offset words and the scale/radius is the
    template's; the material records parse with the template's count, groups, state records and per-list VAT; every
    draw record's list is 32-byte aligned, inside the display-list region, overlaps no other list, is whole GX primitives
    on the stock VAT, and every index of every attribute is inside its array; every texture index names a table entry;
    and (with `texture_bank`, the set of loadable texture names) every table name exists - a missing name hangs the
    shape fix-up forever. Returns counts."""
    if len(blob) % 0x20:
        raise ValueError(f"{name}: {len(blob)} bytes is not a multiple of 0x20")
    for lo, hi in ((0, 4), (8, 0x2C), (0x38, 0xCC)):
        if blob[lo:hi] != template[lo:hi]:
            raise ValueError(f"{name}: header bytes {lo:#x}..{hi:#x} differ from the stock part")
    for o in range(0xA8, 0x110, 4):
        if o not in (0xCC, 0xD0, 0xD4, 0xDC) and blob[o:o + 4] != template[o:o + 4]:
            raise ValueError(f"{name}: header word {o:#x} differs from the stock part")
    if attrs_of(blob) != attrs_of(template):
        raise ValueError(f"{name}: attributes {attrs_of(blob)} differ from the stock {attrs_of(template)}")
    tr, br = records(template), records(blob)
    if [(r.state, r.group) for r in tr] != [(r.state, r.group) for r in br]:
        raise ValueError(f"{name}: material records differ in count, kind or group")
    attrs = attrs_of(blob)
    stride = 2 * len(attrs)
    counts = array_counts(blob)
    dl_base, tex_off = ct._u32(blob, 0x118), ct._u32(blob, 0x11C)
    ntex = ct._u32(blob, 0x10)
    spans, tris = [], 0
    for t, r in zip(tr, br):
        if r.state:
            continue
        if r.dl_off % 0x20 or r.dl_size % 0x20 or r.dl_off < dl_base or r.dl_off + r.dl_size > tex_off:
            raise ValueError(f"{name}: record {r.index} list {r.dl_off:#x}+{r.dl_size:#x} is not 32-byte aligned "
                             f"inside [{dl_base:#x}, {tex_off:#x})")
        if any(r.dl_off < b and a < r.dl_off + r.dl_size for a, b in spans):
            raise ValueError(f"{name}: record {r.index} list overlaps another")
        spans.append((r.dl_off, r.dl_off + r.dl_size))
        if not r.tex < ntex:
            raise ValueError(f"{name}: record {r.index} binds texture entry {r.tex} of {ntex}")
        dl = blob[r.dl_off:r.dl_off + r.dl_size]
        if not ct.dl_whole(dl, stride):
            raise ValueError(f"{name}: record {r.index} list is not whole GX primitives")
        p = 0
        while p < len(dl):
            if dl[p] == 0:
                p += 1
                continue
            if dl[p] & 7 != t.vat:
                raise ValueError(f"{name}: record {r.index} draws on VAT {dl[p] & 7}, the stock list used VAT {t.vat}")
            p += 3 + struct.unpack_from(">H", dl, p + 1)[0] * stride
        for tri in ct.decode_dl(dl, attrs):
            tris += 1
            for c in tri:
                for a in attrs:
                    if c[a] >= counts[a]:
                        raise ValueError(f"{name}: record {r.index} indexes {a} {c[a]} of {counts[a]}")
    names = texture_names(blob)
    if len(names) != ct._u32(template, 0x10) or any(not n.endswith(".tex") for n in names):
        raise ValueError(f"{name}: texture table {names}")
    if texture_bank is not None:
        lost = [n for n in names if n not in texture_bank]
        if lost:
            raise ValueError(f"{name}: texture {lost[0]} is in no loaded texture archive (the shape fix-up would hang)")
    return {"bytes": len(blob), "triangles": tris, "vertices": counts.get("pos", 0)}


# ----------------------------------------------------------------------------------------------- texture atlas

FLAT = 8                   # a flat colour is one 8x8 cell: CMPR-exact, and its centre (+4) is on the TEX0 grid
GUTTER = 4                 # texels of wrapped content around a textured region (bilinear + CMPR block bleed)
ATLAS_SIZES = ((64, 64), (128, 64), (128, 128), (256, 128), (256, 256), (512, 256), (512, 512))


@dataclass
class Region:
    """Where one donor material lives in the atlas. Textured: content rect (x, y, cw * tiles_u, ch * tiles_v) holding
    the texture repeated over UV tiles [u0, u0 + tiles_u) x [v0, v0 + tiles_v). Flat: an 8x8 cell of one colour."""
    x: int = 0
    y: int = 0
    cw: int = FLAT          # texels per UV unit (one tile) across
    ch: int = FLAT
    u0: int = 0
    v0: int = 0
    tiles_u: int = 1
    tiles_v: int = 1
    flat: bool = True
    colour: tuple = (255, 255, 255)

    @property
    def w(self) -> int:
        return FLAT if self.flat else self.cw * self.tiles_u

    @property
    def h(self) -> int:
        return FLAT if self.flat else self.ch * self.tiles_v

    @property
    def gutter(self) -> int:
        return 0 if self.flat else GUTTER


def _resize(img: np.ndarray, w: int, h: int) -> np.ndarray:
    from PIL import Image
    if img.shape[1] == w and img.shape[0] == h:
        return img
    return np.asarray(Image.fromarray(np.asarray(img, np.uint8)).resize(
        (w, h), Image.BOX if w < img.shape[1] else Image.NEAREST))


def material_regions(materials: list[dict], uv_ranges: dict[int, tuple], scale: float = 1.0) -> dict[int, Region]:
    """One Region per used material. materials[i]: {"tex": (h, w, 4) uint8 | None, "colour": (r, g, b, a)};
    uv_ranges[i] = (umin, vmin, umax, vmax) over that material's corners. A texture that is (nearly) one colour over
    the texels it samples, or no texture, becomes a flat cell (exact colour, no UV error)."""
    out = {}
    for i, (umin, vmin, umax, vmax) in uv_ranges.items():
        m = materials[i]
        col = np.asarray(m.get("colour", (255, 255, 255, 255))[:3], float)
        tex = m.get("tex")
        if tex is None:
            out[i] = Region(colour=tuple(int(c) for c in col))
            continue
        t = np.asarray(tex, np.uint8)[..., :3].astype(float) * col / 255.0
        u0, v0 = int(np.floor(umin + 1e-6)), int(np.floor(vmin + 1e-6))
        tu = max(1, min(4, int(np.ceil(umax - 1e-6)) - u0))
        tv = max(1, min(4, int(np.ceil(vmax - 1e-6)) - v0))
        th, tw = t.shape[:2]
        if (umax - umin) < 1 and (vmax - vmin) < 1:          # the texels the material actually samples
            xs = np.unique(np.clip(np.floor((np.linspace(umin, umax, 17) % 1.0) * tw).astype(int), 0, tw - 1))
            ys = np.unique(np.clip(np.floor((np.linspace(vmin, vmax, 17) % 1.0) * th).astype(int), 0, th - 1))
            used = t[np.ix_(ys, xs)].reshape(-1, 3)
        else:
            used = t.reshape(-1, 3)
        if used.std(0).max() < 6.0:
            out[i] = Region(colour=tuple(int(c) for c in used.mean(0).round()))
            continue
        out[i] = Region(cw=max(4, int(round(tw * scale))), ch=max(4, int(round(th * scale))), u0=u0, v0=v0,
                        tiles_u=tu, tiles_v=tv, flat=False)
    return out


def _pack(regions: dict[int, Region], W: int, H: int) -> bool:
    """Shelf-pack the regions (gutter included, every cell 8-aligned) into W x H; sets x, y. False when they don't fit."""
    order = sorted(regions, key=lambda i: (-(regions[i].h + 2 * regions[i].gutter), i))
    x = y = shelf = 0
    for i in order:
        r = regions[i]
        cw = -(-(r.w + 2 * r.gutter) // 8) * 8
        chh = -(-(r.h + 2 * r.gutter) // 8) * 8
        if cw > W:
            return False
        if x + cw > W:
            x, y, shelf = 0, y + shelf, 0
        if y + chh > H:
            return False
        r.x, r.y = x + r.gutter, y + r.gutter
        x += cw
        shelf = max(shelf, chh)
    return True


def build_atlas(materials: list[dict], uv_ranges: dict[int, tuple], max_size=(512, 256)) -> tuple[np.ndarray, dict]:
    """Every used donor material in one atlas image: (rgba (H, W, 4) uint8, {material: Region}). The smallest listed
    size that holds the textures at full resolution wins; past max_size the textures are halved until they fit."""
    scale = 1.0
    while scale >= 1 / 16:
        for W, H in ATLAS_SIZES:
            if W > max_size[0] or H > max_size[1]:
                continue
            regs = material_regions(materials, uv_ranges, scale)
            if _pack(regs, W, H):
                return _paint(materials, regs, W, H), regs
        scale /= 2
    raise ValueError(f"{len(uv_ranges)} materials do not fit a {max_size[0]}x{max_size[1]} atlas")


def _paint(materials, regs, W, H) -> np.ndarray:
    img = np.zeros((H, W, 4), np.uint8)
    img[..., 3] = 255
    img[..., :3] = 128
    for i, r in regs.items():
        if r.flat:
            img[r.y:r.y + FLAT, r.x:r.x + FLAT, :3] = r.colour
            continue
        m = materials[i]
        col = np.asarray(m.get("colour", (255, 255, 255, 255))[:3], float)
        tile = _resize(np.asarray(m["tex"], np.uint8)[..., :3], r.cw, r.ch).astype(float) * col / 255.0
        g = r.gutter
        ys = np.arange(-g, r.h + g) % r.ch
        xs = np.arange(-g, r.w + g) % r.cw
        img[r.y - g:r.y + r.h + g, r.x - g:r.x + r.w + g, :3] = np.clip(tile[np.ix_(ys, xs)], 0, 255).astype(np.uint8)
    return img


def atlas_uv(r: Region, uv: np.ndarray, W: int, H: int) -> np.ndarray:
    """Donor UVs of one material -> atlas UVs (0..1 over the whole atlas)."""
    uv = np.asarray(uv, float).reshape(-1, 2)
    if r.flat:
        return np.tile([(r.x + FLAT / 2) / W, (r.y + FLAT / 2) / H], (len(uv), 1))
    u = np.clip(uv[:, 0] - r.u0, 0, r.tiles_u)
    v = np.clip(uv[:, 1] - r.v0, 0, r.tiles_v)
    return np.stack([(r.x + u * r.cw) / W, (r.y + v * r.ch) / H], 1)


# ----------------------------------------------------------------------------------------------- donor

# Rest-pose meaning of every driver part's local axes (read off an in-game probe: each part drawn as an RGB axis gizmo
# on the select screen, plus Axel's face texture and toe geometry). z is the character's right in every part; left and
# right parts share their frames, which is why their meshes are mirror images in z.
#   koshi: x down from the waist (toward the crotch), y forward;  mune: x up the spine from the waist, y backward;
#   atama: x forward (the face), y up;
#   arms and legs: x along the bone (down in the rest pose), y forward;  kakato: x down, y toward the toes.
HEAD_CAP = 2.0             # the donor's crown is at most this many times the stock crown above the neck


@dataclass
class Donor:
    pos: np.ndarray                 # (V, 3) bind-pose positions
    nrm: np.ndarray                 # (V, 3)
    uv: np.ndarray                  # (V, 2)
    tris: np.ndarray                # (T, 3)
    mat: np.ndarray                 # (T,) material per triangle
    owner: np.ndarray               # (V,) skin joint index
    materials: list                 # [{"tex", "colour"}]
    joints: np.ndarray              # (J, 3)
    parent: list
    role_joint: dict                # CT part -> joint index
    up: np.ndarray = field(default_factory=lambda: np.array([0.0, 1.0, 0.0]))
    fwd: np.ndarray = field(default_factory=lambda: np.array([0.0, 0.0, 1.0]))

    def children(self, j: int) -> list[int]:
        return [k for k, p in enumerate(self.parent) if p == j]

    def subtree(self, j: int) -> set[int]:
        out, todo = set(), [j]
        while todo:
            k = todo.pop()
            out.add(k)
            todo += self.children(k)
        return out


def load_donor(glb, joint_roles: dict) -> Donor:
    """A library GLB + its rig roles -> Donor (all primitives concatenated, one material per primitive)."""
    from pathlib import Path
    from .characters import rig_from_gltf
    part_role = ct.resolve_roles(joint_roles)               # CT part -> donor role name
    rig = rig_from_gltf(Path(glb), dict(joint_roles))
    P, N, U, T, M, O, mats = [], [], [], [], [], [], []
    base = 0
    for k, pr in enumerate(rig["prims"]):
        p = np.asarray(pr["pos"], float)
        P.append(p)
        N.append(np.asarray(pr["nrm"], float))
        U.append(np.asarray(pr["uv"], float))
        t = np.asarray(pr["tris"], int).reshape(-1, 3)
        T.append(t + base)
        M.append(np.full(len(t), k))
        O.append(np.asarray(pr["owner"], int))
        mats.append({"tex": pr.get("tex"), "colour": tuple(pr.get("color") or (255, 255, 255, 255))})
        base += len(p)
    rj = {part: rig["roles"][role] for part, role in part_role.items() if role in rig["roles"]}
    missing = [p for p in ct.CT_ROLE if p not in rj]
    if missing:
        raise ValueError(f"the donor rig has no joint for {', '.join(missing)}")
    d = Donor(np.concatenate(P), np.concatenate(N), np.concatenate(U), np.concatenate(T), np.concatenate(M),
              np.concatenate(O), mats, np.asarray(rig["joints"], float), list(rig["parent"]), rj)
    d.fwd = facing(d)
    return d


def facing(d: Donor) -> np.ndarray:
    """The donor's forward: the horizontal axis (+-X or +-Z) its feet extend along from the ankles, with the head mass
    in front of the head joint as a lighter vote."""
    votes = np.zeros(3)
    for part in ("kakato_l", "kakato_r"):
        j = d.role_joint[part]
        sel = np.isin(d.owner, list(d.subtree(j)))
        if sel.any():
            votes += d.pos[sel].mean(0) - d.joints[j]
    h = d.role_joint["atama"]
    sel = np.isin(d.owner, list(d.subtree(h)))
    if sel.any():
        votes += 0.25 * (d.pos[sel].mean(0) - d.joints[h])
    votes[1] = 0.0
    ax = int(np.argmax(np.abs(votes)))
    f = np.zeros(3)
    f[ax] = 1.0 if votes[ax] >= 0 else -1.0
    return f


def ankle_joint(d: Donor, foot: int) -> int:
    """The joint the shoe pivots on: in the foot joint's subtree, the joint whose child points furthest forward (the
    toe). SA1 rigs put the role 'foot' joint at the bottom of the shin with the shoe two joints further down."""
    best, score = foot, 1e-6
    for j in sorted(d.subtree(foot)):
        for c in d.children(j):
            s = float((d.joints[c] - d.joints[j]) @ d.fwd)
            if s > score:
                best, score = j, s
    return best


def assign_parts(d: Donor) -> np.ndarray:
    """CT part name per donor triangle: the role of the nearest role joint above each corner's owner joint (majority
    of the three corners; joints outside every role ride the hips), then the foot role's triangles that are not on
    the shoe (`ankle_joint`'s subtree) go to the shin."""
    by_joint = {j: p for p, j in d.role_joint.items()}
    part_of_joint = {}
    for j in range(len(d.joints)):
        k, part = j, None
        while k is not None and k != -1:
            if k in by_joint:
                part = by_joint[k]
                break
            k = d.parent[k]
        part_of_joint[j] = part or "koshi"
    vp = np.array([part_of_joint[int(o)] for o in d.owner], dtype=object)
    out = np.empty(len(d.tris), dtype=object)
    for i, t in enumerate(d.tris):
        a, b, c = vp[t]
        out[i] = a if a in (b, c) else b if b == c else a
    for s in "lr":
        shoe = d.subtree(ankle_joint(d, d.role_joint[f"kakato_{s}"]))
        owned = np.array([int(o) in shoe for o in d.owner])
        for i in np.flatnonzero(out == f"kakato_{s}"):
            if owned[d.tris[i]].sum() < 2:
                out[i] = f"sune_{s}"
    return drop_held_props(d, out)


PROP_REACH = 3.25           # a hand material further than this many forearm lengths from the wrist is a held prop


def drop_held_props(d: Donor, parts_of: np.ndarray) -> np.ndarray:
    """Clear (part "") the hand materials whose vertices lie on average more than PROP_REACH forearm lengths from the
    wrist: a held prop (Amy's hammer sits 6-9 forearms out, its handle 3.6) that would ride the hand through the cab.
    Gloves stay: Sonic's sit at most 2.9 forearms out, Knuckles' 2.6."""
    out = parts_of.copy()
    for s in "lr":
        hand = f"te_{s}"
        wrist = d.joints[d.role_joint[hand]]
        fore = float(np.linalg.norm(wrist - d.joints[d.role_joint[f"ude_{s}"]])) or 1.0
        sel = parts_of == hand
        for mi in np.unique(d.mat[sel]):
            rows = np.flatnonzero(sel & (d.mat == mi))
            dist = np.linalg.norm(d.pos[d.tris[rows].reshape(-1)] - wrist, axis=1).mean() / fore
            if dist > PROP_REACH:
                out[rows] = ""
    return out


# ----------------------------------------------------------------------------------------------- driver measures

def stock_measures(parts: dict[str, bytes]) -> dict:
    """Lengths of the stock driver's rest skeleton, read off its 15 main parts: a bone is the parent's reach along x
    plus the child's start (negative where the two overlap)."""
    lo, hi = {}, {}
    for p, blob in parts.items():
        sh = ct.read_shape(blob, p)
        P = np.asarray(sh.positions(POS_FRAC))
        used = sorted({c["pos"] for t in sh.tris for c in t})
        Q = P[used] if used else P
        lo[p], hi[p] = Q.min(0), Q.max(0)
    m = {}
    for s in "lr":
        m[f"thigh_{s}"] = max(0.5, hi[f"momo_{s}"][0] + lo[f"sune_{s}"][0])
        m[f"shin_{s}"] = max(0.5, hi[f"sune_{s}"][0] + lo[f"kakato_{s}"][0])
        m[f"sole_{s}"] = max(0.3, hi[f"kakato_{s}"][0])
        m[f"upper_{s}"] = max(0.5, hi[f"kata_{s}"][0] + lo[f"ude_{s}"][0])
        m[f"fore_{s}"] = max(0.5, hi[f"ude_{s}"][0] + lo[f"te_{s}"][0])
        m[f"hand_{s}"] = max(0.3, hi[f"te_{s}"][0] - lo[f"te_{s}"][0])
    m["hips"] = max(0.5, hi["koshi"][0] + lo[f"momo_l"][0])        # waist joint down to the hip sockets
    m["chest"] = max(0.5, hi["mune"][0])
    m["chest_width"] = float(hi["mune"][2] - lo["mune"][2])
    m["chest_depth"] = float(hi["mune"][1] - lo["mune"][1])
    m["head_height"] = float(hi["atama"][1] - lo["atama"][1])
    m["head_top"] = max(0.5, float(hi["atama"][1]))
    m["legs"] = (m["thigh_l"] + m["shin_l"] + m["sole_l"] + m["thigh_r"] + m["shin_r"] + m["sole_r"]) / 2
    return {k: float(v) for k, v in m.items()}


# ----------------------------------------------------------------------------------------------- donor -> parts

def _unit(v) -> np.ndarray:
    v = np.asarray(v, float)
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-9 else v


def _frame(x_dir, y_hint) -> np.ndarray:
    """Rows: unit x along x_dir, y = y_hint orthogonalised (a fallback when parallel), z = x cross y."""
    x = _unit(x_dir)
    y = np.asarray(y_hint, float) - (np.asarray(y_hint, float) @ x) * x
    if np.linalg.norm(y) < 1e-6:
        alt = np.array([0.0, 1.0, 0.0]) if abs(x[1]) < 0.9 else np.array([1.0, 0.0, 0.0])
        y = alt - (alt @ x) * x
    y = _unit(y)
    return np.stack([x, y, np.cross(x, y)])


@dataclass
class PartMap:
    """local = (p - origin) @ A.T + offset (A: donor world -> the part's frame, a rotation times a scale)."""
    origin: np.ndarray
    A: np.ndarray
    offset: np.ndarray = field(default_factory=lambda: np.zeros(3))

    def points(self, P) -> np.ndarray:
        return (np.asarray(P, float) - self.origin) @ self.A.T + self.offset

    def normals(self, N) -> np.ndarray:
        n = np.asarray(N, float) @ np.linalg.inv(self.A)
        return n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)


def part_maps(d: Donor, parts_of: np.ndarray, m: dict, head_scale: float = 1.0, hand_scale: float = 1.25,
              torso_conform: float = 0.75) -> tuple[dict[str, PartMap], dict]:
    """Every CT part's map from the donor. g = the driver's leg length over the donor's (hip sockets to soles). Legs
    and arms keep their bones joint to joint (stretched to the driver's bone lengths, cross-section at g); the foot
    keeps the shoe's shape (ankle-to-sole height scaled to the driver's); hands and head keep their shape at g times
    hand_scale / head_scale; the torso spans hip sockets to neck (stretched to the driver's), widened toward the
    driver's chest width by torso_conform so the shoulders meet the arms, and is split between koshi and mune at the
    driver's waist (`split_torso`)."""
    U, F = d.up, d.fwd
    R = np.cross(F, U)
    J = d.joints
    ankle = {s: J[ankle_joint(d, d.role_joint[f"kakato_{s}"])] for s in "lr"}
    sole = {}
    for s in "lr":
        sel = d.tris[parts_of == f"kakato_{s}"].reshape(-1)
        sole[s] = float((d.pos[sel] @ U).min()) if len(sel) else float(ankle[s] @ U) - 0.1
    hip_h = float(np.mean([J[d.role_joint[f"momo_{s}"]] @ U for s in "lr"]))
    leg_d = float(np.mean([hip_h - sole[s] for s in "lr"]))
    g = m["legs"] / max(leg_d, 1e-6)
    maps: dict[str, PartMap] = {}
    for s in "lr":
        chain = [(f"momo_{s}", J[d.role_joint[f"momo_{s}"]], J[d.role_joint[f"sune_{s}"]], m[f"thigh_{s}"]),
                 (f"sune_{s}", J[d.role_joint[f"sune_{s}"]], ankle[s], m[f"shin_{s}"]),
                 (f"kata_{s}", J[d.role_joint[f"kata_{s}"]], J[d.role_joint[f"ude_{s}"]], m[f"upper_{s}"]),
                 (f"ude_{s}", J[d.role_joint[f"ude_{s}"]], J[d.role_joint[f"te_{s}"]], m[f"fore_{s}"])]
        for part, j0, j1, L in chain:
            length = float(np.linalg.norm(j1 - j0))
            along = L / length if length > 1e-6 else g
            maps[part] = PartMap(j0, np.diag([along, g, g]) @ _frame(j1 - j0, F))
        wrist = J[d.role_joint[f"te_{s}"]]
        sel = d.tris[parts_of == f"te_{s}"].reshape(-1)
        fore = wrist - J[d.role_joint[f"ude_{s}"]]
        axis = d.pos[sel].mean(0) - wrist if len(sel) else fore
        if np.linalg.norm(axis) < 0.25 * np.linalg.norm(fore):
            axis = fore
        maps[f"te_{s}"] = PartMap(wrist, g * hand_scale * _frame(axis, F))
        h = float(ankle[s] @ U) - sole[s]
        sf = float(np.clip(m[f"sole_{s}"] / h, 0.6 * g, 1.8 * g)) if h > 1e-6 else g
        maps[f"kakato_{s}"] = PartMap(ankle[s], sf * np.stack([-U, F, R]))
    neck = J[d.role_joint["atama"]]
    hips = J[d.role_joint["koshi"]]
    o = hips + (hip_h - float(hips @ U)) * U
    span = float(neck @ U) - hip_h
    st = (m["hips"] + m["chest"]) / span if span > 1e-6 else g
    sel = d.tris[np.isin(parts_of, ("koshi", "mune"))].reshape(-1)
    wd = dd = 1.0
    if len(sel):
        Q = d.pos[sel] - o
        wd = float(np.ptp(Q @ R)) or 1.0
        dd = float(np.ptp(Q @ F)) or 1.0
    sw = max(g, torso_conform * m["chest_width"] / wd)
    sd = max(g, 0.6 * torso_conform * m["chest_depth"] / dd)
    # both torso parts hang from the waist joint, m["hips"] above the hip sockets: koshi points down, mune up
    maps["koshi"] = PartMap(o, np.diag([st, sd, sw]) @ np.stack([-U, F, R]), np.array([m["hips"], 0.0, 0.0]))
    maps["mune"] = PartMap(o, np.diag([st, sd, sw]) @ np.stack([U, -F, R]), np.array([-m["hips"], 0.0, 0.0]))
    # head: the donor's own shape at g, but never taller than HEAD_CAP stock heads (a cartoon head at the legs' scale
    # is two to three times a driver's and leaves the select screen's frame)
    sel = d.tris[parts_of == "atama"].reshape(-1)
    hh = float((d.pos[sel] @ U).max() - neck @ U) if len(sel) else 0.0      # crown above the neck (not hanging dreads)
    sh = g * head_scale
    if hh > 1e-6:
        sh = min(sh, HEAD_CAP * head_scale * m["head_top"] / hh)
    maps["atama"] = PartMap(neck, sh * np.stack([F, U, R]))
    return maps, {"g": round(g, 4), "torso_stretch": round(st / g, 3), "torso_width": round(sw / g, 3),
                  "head": round(sh / g, 3), "forward": [float(x) for x in F]}


def split_torso(d: Donor, parts_of: np.ndarray, maps: dict) -> np.ndarray:
    """Torso triangles (hips or chest roles) to koshi below the driver's waist, mune above (by mapped centroid)."""
    out = parts_of.copy()

    for i in np.flatnonzero(np.isin(parts_of, ("koshi", "mune"))):
        c = maps["mune"].points(d.pos[d.tris[i]]).mean(0)
        out[i] = "koshi" if c[0] < 0 else "mune"
    return out


def part_geometry(d: Donor, parts_of: np.ndarray, maps: dict, regions: dict, W: int, H: int,
                  reverse: bool) -> dict[str, tuple]:
    """{part: (local positions (n, 3), normals, atlas UVs, triangles)}, every used donor vertex once per part."""
    out = {}
    for part, pm in maps.items():
        idx = np.flatnonzero(parts_of == part)
        if not len(idx):
            continue
        T = d.tris[idx]
        used, inv = np.unique(T.reshape(-1), return_inverse=True)
        tris = inv.reshape(-1, 3)
        if reverse:
            tris = tris[:, [0, 2, 1]]
        uv = np.zeros((len(used), 2))
        vmat = np.zeros(len(used), int)
        vmat[inv.reshape(-1)] = np.repeat(d.mat[idx], 3)
        for mi in np.unique(vmat):
            sel = vmat == mi
            uv[sel] = atlas_uv(regions[int(mi)], d.uv[used[sel]], W, H)
        out[part] = (pm.points(d.pos[used]), pm.normals(d.nrm[used]), uv, [tuple(map(int, t)) for t in tris])
    return out


def signed_volume(P, T) -> float:
    P = np.asarray(P, float)
    T = np.asarray(T, int).reshape(-1, 3)
    if not len(T):
        return 0.0
    return float(np.einsum("ij,ij->i", P[T[:, 0]], np.cross(P[T[:, 1]], P[T[:, 2]])).sum() / 6.0)


# ----------------------------------------------------------------------------------------------- the driver writer

# Each driver's atlas goes into a texture only that driver's parts name (TY_plyrA_hada1.tex, for one, is also Gena's
# and pedestrian pplWA's skin, and TY_plyrD_koshi1/momo1 are fare psgAL's).
ATLAS = {"A": "TY_plyrA_face1.tex", "B": "TY_plyrB_fb1.tex", "C": "TY_plyrC_face1.tex", "D": "TY_plyrD_fb1.tex"}


def fit_scale(template: bytes, P) -> float:
    """The tightest quantisation scale that holds every vertex: the furthest one (Euclidean, so the header radius stays
    a bounding sphere) from the header centre, 2 % spare."""
    centre = np.asarray(struct.unpack_from(">3f", template, 0x20), float)
    far = float(np.linalg.norm(np.asarray(P, float) - centre, axis=1).max()) if len(P) else 0.0
    return max(far * 1.02, 0.05) * (1 << POS_FRAC) / 32767.0


def write_driver(bank: bytes, texbank: bytes, glb, joint_roles: dict, letter: str, *, head_scale: float = 1.0,
                 hand_scale: float = 1.25, max_atlas=(512, 256), progress=None) -> tuple[bytes, bytes, dict]:
    """The donor as driver `letter` (A Axel, B B.D. Joe, C Gena, D Gus): every MP_YH_plyr<letter>_ blob of polDC0.all
    rewritten at whatever size it needs (main parts, sl_ twins and hand poses carry the donor's part; accessory
    sub-parts draw nothing) and the driver's atlas texture in texDc0.all replaced. Returns (polDC0.all, texDc0.all,
    report)."""
    from . import crazy_taxi_swap as cs
    progress = progress or (lambda p, msg: None)
    if letter not in ATLAS:
        raise ValueError(f"driver letter {letter!r}: A, B, C or D")
    entries = read_archive(bank)
    by = dict(entries)
    group = f"plyr{letter}"
    main = {p: by[f"MP_YH_{group}_{p}.shp"] for p in ct.PARTS}
    m = stock_measures(main)
    progress(5, "Reading the donor")
    d = load_donor(glb, joint_roles)
    parts_of = assign_parts(d)
    maps, info = part_maps(d, parts_of, m, head_scale, hand_scale)
    parts_of = split_torso(d, parts_of, maps)
    uv_ranges = {}
    for mi in sorted(set(int(x) for x in d.mat)):
        uv = d.uv[d.tris[d.mat == mi].reshape(-1)]
        if len(uv):
            uv_ranges[mi] = (float(uv[:, 0].min()), float(uv[:, 1].min()), float(uv[:, 0].max()), float(uv[:, 1].max()))
    progress(20, "Painting the texture atlas")
    atlas, regions = build_atlas(d.materials, uv_ranges, max_atlas)
    H, W = atlas.shape[:2]
    reverse = signed_volume(d.pos, d.tris) > 0              # glTF faces are counter-clockwise; the game's clockwise
    geo = part_geometry(d, parts_of, maps, regions, W, H, reverse)
    tex_entries = dict(read_archive(texbank))
    atlas_name = ATLAS[letter]
    new_tex = make_tex(atlas, tex_entries[atlas_name])
    loadable = set(tex_entries) | {"white.tex"}
    new, stats = {}, {}
    todo = [(n, b, c) for n, b in entries for c in [cs.classify(n)] if c and c["group"] == group]
    for k, (name, blob, c) in enumerate(todo):
        draws = [r for r in records(blob) if not r.state]
        names = texture_names(blob)
        tex_names = [n if n == "white.tex" else atlas_name for n in names]
        if atlas_name not in tex_names:
            raise ValueError(f"{name}: its texture table {names} has no entry to bind the atlas to")
        ti = tex_names.index(atlas_name)
        first = next((i for i, r in enumerate(draws) if r.group == 0), 0)
        hide = c["accessory"] or c["part"] not in geo
        if hide:
            centre = np.asarray(struct.unpack_from(">3f", blob, 0x20), float)
            P, N, UV, T = np.tile(centre, (3, 1)), np.tile([0.0, 1.0, 0.0], (3, 1)), np.zeros((3, 2)), []
        else:
            P, N, UV, T = geo[c["part"]]
        groups = [list(T) if i == first else [] for i in range(len(draws))]
        out = encode_part(blob, P, N, UV, groups, name=name, tex_index=[ti] * len(draws), tex_names=tex_names,
                          scale=fit_scale(blob, P), material_colour=0xFFFFFFFF)
        st = check_part(blob, out, name, loadable)
        new[name] = out
        stats[name] = {"part": c["part"], "hidden": hide, "verts": len(P) if not hide else 0,
                       "tris": len(T), "bytes": len(out), "stock_bytes": len(blob), "checked": st["triangles"]}
        progress(25 + 70 * (k + 1) / len(todo), f"Writing {name}")
    nb = replace_entries(bank, new)
    ntb = replace_entries(texbank, {atlas_name: new_tex})
    shown = {v["part"]: v for v in stats.values() if not v["hidden"]}
    report = {"driver": letter, "blobs": len(stats), "hidden": sum(v["hidden"] for v in stats.values()),
              "parts": {p: {"verts": v["verts"], "tris": v["tris"]} for p, v in sorted(shown.items())},
              "triangles": sum(v["tris"] for v in shown.values()), "donor_triangles": int(len(d.tris)),
              "atlas": {"name": atlas_name, "size": [W, H], "regions": len(regions),
                        "textured": sum(not r.flat for r in regions.values())},
              "bank_bytes": [len(bank), len(nb)], "texbank_bytes": [len(texbank), len(ntb)],
              "reversed_winding": bool(reverse), **info, "blob_stats": stats}
    return nb, ntb, report
