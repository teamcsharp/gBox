"""GTA (PS2) RenderWare assets: read/write DFF clumps and PS2 TXD rasters, the IMG/DIR archive and the disc's IMG copies,
so a character model can replace the player ped. No third-party tools; formats checked against the GTA III PS2 (USA)
disc and documented on the GTA modding wiki (RenderWare binary stream sections, PS2 native textures).

What the discs hold (GTA III PS2, SLUS_200.62):
  * MODELS/GTA3.DIR (32-byte entries: u32 offset in sectors, u32 size in sectors, char name[24]) + MODELS/GTA3.IMG,
    and 11 byte-identical copies GTA3_1.IMG .. GTA3_11.IMG spread over the DVD (the streamer reads the copy nearest
    the head). A replaced entry must be written into every copy. The IMG is packed (no gaps): a new file must fit
    its old sector count (the DIR size field is updated to the new count).
  * player.DFF / PLAYER.TXD = Claude. The DFF is NOT PS2-native: RW 3.1 (0x310) plain geometry (tristrip BinMesh,
    one morph target, positions+normals+UVs), instanced by the game at load. 17 frames (root 'player', Swaist, Smid,
    legs/feet, Storso, arms/hands, Shead), 16 rigid atomics (one geometry per body part frame); peds are animated by
    frame name. Rockstar's exporter wrote the clump header size 188 bytes short; RW never checks it (kept verbatim).
  * TXDs are PS2-native: TextureNative platform 'PS2\\0', raster Struct = 64-byte header (w, h, depth, raster format,
    TEX0, TEX1, MIPTBP1/2 GS registers, pixel bytes, palette bytes, GS memory size, sky mipmap value) + data Struct:
    when format & 0x20000 every image is preceded by a 0x50-byte GIF upload packet (GIF tag, TRXPOS, TRXREG @0x20, TRXDIR, image tag).
    8-bit textures are uploaded as PSMCT32 (TRXREG = w/2 x h/2), i.e. the pixels are stored PSMT8-swizzled; the 256-entry
    palette is RGBA with alpha 0x80 = opaque in CSM1 order (index bits 3 and 4 swapped).

Round trip: parse(bytes) -> Chunk tree -> to_bytes() is byte-identical for every DFF and TXD in GTA3.IMG (see
roundtrip_img()).
"""
from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

SECTOR = 2048
# chunk ids
STRUCT, STRING, EXTENSION, TEXTURE, MATERIAL, MATLIST, FRAMELIST, GEOMETRY, CLUMP, ATOMIC = 1, 2, 3, 6, 7, 8, 0xE, 0xF, 0x10, 0x14
TEXNATIVE, TEXDICT, GEOMLIST, BINMESH, NATIVEDATA, FRAMENAME = 0x15, 0x16, 0x1A, 0x50E, 0x510, 0x253F2FE
CONTAINERS = {EXTENSION, TEXTURE, MATERIAL, MATLIST, FRAMELIST, GEOMETRY, CLUMP, ATOMIC, TEXNATIVE, TEXDICT, GEOMLIST}


# ---------------------------------------------------------------------------------------------------------------- chunks
@dataclass
class Chunk:
    type: int
    version: int
    data: bytes = b""                       # leaf payload
    kids: list = field(default_factory=list)
    container: bool = False
    size_override: int | None = None        # header size as found on disc when it differs from the real one

    def find(self, t: int) -> list["Chunk"]:
        return [k for k in self.kids if k.type == t]

    def first(self, t: int) -> "Chunk":
        return next(k for k in self.kids if k.type == t)

    def body(self) -> bytes:
        return b"".join(k.to_bytes() for k in self.kids) if self.container else self.data

    def to_bytes(self) -> bytes:
        b = self.body()
        return struct.pack("<III", self.type, len(b) if self.size_override is None else self.size_override, self.version) + b


def _parse_at(d: bytes, o: int, greedy: bool = False) -> tuple[Chunk, int]:
    t, s, v = struct.unpack_from("<III", d, o)
    o += 12
    if t not in CONTAINERS:
        return Chunk(t, v, d[o:o + s]), o + s
    c, end, p = Chunk(t, v, container=True), o + s, o
    while p < end or (greedy and p + 12 <= len(d) and _looks_like(d, p, v)):
        k, p = _parse_at(d, p)
        c.kids.append(k)
    if p != end:
        c.size_override = s
    return c, p


def _looks_like(d: bytes, p: int, version: int) -> bool:
    t, s, v = struct.unpack_from("<III", d, p)
    return v == version and t in CONTAINERS | {STRUCT, STRING} and p + 12 + s <= len(d)


def parse(d: bytes) -> tuple[Chunk, bytes]:
    """The root chunk (its children read past a too-small header size, as RW's stream reader does) + trailing bytes."""
    root, end = _parse_at(d, 0, greedy=True)
    return root, d[end:]


def string_chunk(s: str, version: int = 0x310) -> Chunk:
    b = s.encode() + b"\0"
    return Chunk(STRING, version, b + b"\0" * (-len(b) % 4))


# ------------------------------------------------------------------------------------------------------- disc + IMG
def iso_files(f) -> dict[str, tuple[int, int]]:
    """ISO9660 path (upper case, '/') -> (lba, size) of every file on a 2048-byte-sector image."""
    def sec(lba, n):
        f.seek(lba * SECTOR)
        return f.read(n * SECTOR)
    out = {}

    def walk(lba, size, pre):
        buf, o = sec(lba, (size + SECTOR - 1) // SECTOR)[:size], 0
        while o < len(buf):
            ln = buf[o]
            if ln == 0:
                o = (o // SECTOR + 1) * SECTOR
                continue
            l, s = struct.unpack_from("<I", buf, o + 2)[0], struct.unpack_from("<I", buf, o + 10)[0]
            nm = buf[o + 33:o + 33 + buf[o + 32]]
            if nm not in (b"\0", b"\1"):
                n = nm.decode("ascii", "replace").split(";")[0].upper()
                if buf[o + 25] & 2:
                    walk(l, s, pre + n + "/")
                else:
                    out[pre + n] = (l, s)
            o += ln
    pvd = sec(16, 1)
    walk(struct.unpack_from("<I", pvd, 158)[0], struct.unpack_from("<I", pvd, 166)[0], "")
    return out


def dir_read(d: bytes) -> list[list]:
    """GTA III/VC .DIR: [offset sectors, size sectors, name] per entry, in file order."""
    return [[*struct.unpack_from("<II", d, i), d[i + 8:i + 32].split(b"\0")[0].decode("ascii")] for i in range(0, len(d), 32)]


def dir_write(ents: list[list], template: bytes) -> bytes:
    """Write sizes/offsets back into the original DIR bytes (names and their padding bytes are kept)."""
    out = bytearray(template)
    for i, (o, s, _n) in enumerate(ents):
        struct.pack_into("<II", out, i * 32, o, s)
    return bytes(out)


class GtaDisc:
    """A GTA III / VC PS2 disc image (plain 2048-byte sectors, e.g. `chdman extractcd` output), opened read-only or for
    in-place patching of a COPY."""
    def __init__(self, iso: Path, writable: bool = False, img: str = "MODELS/GTA3.IMG"):
        self.f = open(iso, "r+b" if writable else "rb")
        self.files = iso_files(self.f)
        stem = img.rsplit(".", 1)[0]
        self.dir_name = stem + ".DIR"
        self.imgs = [img] + sorted((k for k in self.files if k.startswith(stem + "_") and k.endswith(".IMG")),
                                   key=lambda k: int(k[len(stem) + 1:-4]))
        self.dir_raw = self.read_file(self.dir_name)
        self.ents = dir_read(self.dir_raw)
        self.index = {e[2].lower(): i for i, e in enumerate(self.ents)}

    def read_file(self, path: str) -> bytes:
        lba, size = self.files[path]
        self.f.seek(lba * SECTOR)
        return self.f.read(size)

    def entry(self, name: str, copy: int = 0) -> bytes:
        o, s, _ = self.ents[self.index[name.lower()]]
        self.f.seek((self.files[self.imgs[copy]][0] + o) * SECTOR)
        return self.f.read(s * SECTOR)

    def slot_sectors(self, name: str) -> int:
        """Sectors this entry may use without moving others: up to the next entry's offset (IMG is packed)."""
        o, s, _ = self.ents[self.index[name.lower()]]
        nxt = min((e[0] for e in self.ents if e[0] > o), default=self.files[self.imgs[0]][1] // SECTOR)
        return nxt - o

    def replace(self, name: str, data: bytes) -> dict:
        """Write `data` into the entry's slot in every IMG copy (zero padded to whole sectors) and fix the DIR size."""
        i = self.index[name.lower()]
        o, s, n = self.ents[i]
        need = (len(data) + SECTOR - 1) // SECTOR
        if need > self.slot_sectors(name):
            raise ValueError(f"{name}: {need} sectors > its {self.slot_sectors(name)}-sector slot")
        pad = data + b"\0" * (need * SECTOR - len(data))
        for img in self.imgs:
            self.f.seek((self.files[img][0] + o) * SECTOR)
            self.f.write(pad)
        self.ents[i][1] = need
        self.dir_raw = dir_write(self.ents, self.dir_raw)
        lba, _ = self.files[self.dir_name]
        self.f.seek(lba * SECTOR)
        self.f.write(self.dir_raw)
        return {"entry": n, "sectors": need, "was": s, "copies": len(self.imgs)}

    def close(self):
        self.f.close()


def roundtrip_img(disc: GtaDisc, limit: int | None = None) -> dict:
    """parse -> to_bytes on every DFF/TXD of the IMG; returns counts and the failures (must be none)."""
    ok, bad, quirks = 0, [], 0
    for o, s, n in disc.ents[:limit]:
        if not n.lower().endswith((".dff", ".txd")):
            continue
        d = disc.entry(n)
        root, tail = parse(d)
        out = root.to_bytes() + tail
        if out == d:
            ok += 1
            quirks += root.size_override is not None
        else:
            bad.append(n)
    return {"identical": ok, "failed": bad, "root_size_quirks": quirks}


# ------------------------------------------------------------------------------------------------------------- frames
GTA_TO_GLTF = np.array([[-1, 0, 0, 0], [0, 0, 1, 0], [0, 1, 0, 0], [0, 0, 0, 1]], float)   # peds face +Y, left = -X
FRAME_FMT = "<9f3fiI"                       # rotation 3x3 (rows = right, up, at), position, parent, flags


def frames_read(framelist: Chunk) -> list[dict]:
    st = framelist.first(STRUCT).data
    n = struct.unpack_from("<I", st)[0]
    names = []
    for ext in framelist.find(EXTENSION):
        nm = [k for k in ext.kids if k.type == FRAMENAME]
        names.append(nm[0].data.decode("ascii", "replace") if nm else "")
    out = []
    for i in range(n):
        v = struct.unpack_from(FRAME_FMT, st, 4 + 56 * i)
        m = np.eye(4)
        m[:3, :3] = np.array(v[:9]).reshape(3, 3).T                 # columns = right, up, at
        m[:3, 3] = v[9:12]
        out.append({"name": names[i] if i < len(names) else "", "local": m, "parent": v[12], "flags": v[13]})
    for f in out:
        f["world"] = f["local"] if f["parent"] < 0 else out[f["parent"]]["world"] @ f["local"]
    return out


# ------------------------------------------------------------------------------------------------------------- geometry
@dataclass
class Geom:
    """Plain (non-native) RW 3.1 geometry: one morph target, triangle list."""
    pos: np.ndarray                         # (n, 3) float32
    nrm: np.ndarray | None
    uv: np.ndarray | None                   # (n, 2)
    tris: np.ndarray                        # (m, 3) vertex indices
    mat: np.ndarray | None = None           # (m,) material index
    prelit: np.ndarray | None = None        # (n, 4) uint8


def geometry_read(g: Chunk) -> Geom:
    st = g.first(STRUCT).data
    fmt, nt, nv, nm = struct.unpack_from("<IIII", st)
    o = 16 + (12 if g.version < 0x34000 else 0)
    prelit = uv = nrm = None
    if fmt & 8:
        prelit = np.frombuffer(st, np.uint8, nv * 4, o).reshape(nv, 4)
        o += nv * 4
    nts = (fmt >> 16) & 0xFF or (1 if fmt & 4 else 0) + (1 if fmt & 0x80 else 0)
    for t in range(nts):
        a = np.frombuffer(st, np.float32, nv * 2, o).reshape(nv, 2)
        uv = a if t == 0 else uv
        o += nv * 8
    tr = np.frombuffer(st, np.uint16, nt * 4, o).reshape(nt, 4)
    o += nt * 8
    o += 16                                                        # bounding sphere
    hasv, hasn = struct.unpack_from("<II", st, o)
    o += 8
    pos = np.frombuffer(st, np.float32, nv * 3, o).reshape(nv, 3) if hasv else None
    o += nv * 12 if hasv else 0
    if hasn:
        nrm = np.frombuffer(st, np.float32, nv * 3, o).reshape(nv, 3)
    return Geom(pos, nrm, uv, tr[:, [1, 0, 3]].astype(np.int64), tr[:, 2].astype(np.int64), prelit)


def _binmesh(tris: np.ndarray, mats: np.ndarray, nmat: int, version: int) -> Chunk:
    body, total, meshes = b"", 0, 0
    for m in range(nmat):
        idx = tris[mats == m].reshape(-1)
        if not len(idx):
            continue
        body += struct.pack("<II", len(idx), m) + idx.astype("<u4").tobytes()
        total += len(idx)
        meshes += 1
    return Chunk(BINMESH, version, struct.pack("<III", 0, meshes, total) + body)   # flags 0 = triangle list


def geometry_build(g: Geom, template: Chunk) -> Chunk:
    """A new Geometry chunk with the template's material list and extension plugins (BinMesh rebuilt as a triangle
    list; other plugins copied)."""
    v = template.version
    nv, nt = len(g.pos), len(g.tris)
    fmt = 0x2 | 0x4 | 0x20 | (0x10 if g.nrm is not None else 0) | (0x8 if g.prelit is not None else 0)
    st = struct.pack("<IIII", fmt, nt, nv, 1)
    if v < 0x34000:
        st += struct.pack("<3f", 1.0, 1.0, 1.0)
    if g.prelit is not None:
        st += np.asarray(g.prelit, np.uint8).tobytes()
    st += np.asarray(g.uv, "<f4").tobytes()
    mats = np.zeros(nt, np.int64) if g.mat is None else np.asarray(g.mat)
    t = np.asarray(g.tris)
    st += np.stack([t[:, 1], t[:, 0], mats, t[:, 2]], 1).astype("<u2").tobytes()
    c = g.pos.mean(0) if nv else np.zeros(3)
    r = float(np.linalg.norm(g.pos - c, axis=1).max()) if nv else 0.0
    st += struct.pack("<4fII", *c, r, 1, 1 if g.nrm is not None else 0)
    st += np.asarray(g.pos, "<f4").tobytes()
    if g.nrm is not None:
        st += np.asarray(g.nrm, "<f4").tobytes()
    out = Chunk(GEOMETRY, v, container=True)
    out.kids.append(Chunk(STRUCT, v, st))
    ml = template.first(MATLIST)
    out.kids.append(ml)
    ext = Chunk(EXTENSION, v, container=True)
    nmat = struct.unpack_from("<I", ml.first(STRUCT).data)[0]
    for k in template.first(EXTENSION).kids:
        ext.kids.append(_binmesh(t, mats, nmat, v) if k.type == BINMESH else k)
    out.kids.append(ext)
    return out


# ------------------------------------------------------------------------------------------------------- PS2 rasters
def _swz8_map(w: int, h: int) -> np.ndarray:
    """For each linear PSMT8 pixel (y*w+x), its byte index in the PSMCT32-uploaded (w/2 x h/2 words) buffer."""
    y, x = np.mgrid[0:h, 0:w]
    block = (y & ~0xF) * w + (x & ~0xF) * 2
    swap = (((y + 2) >> 2) & 1) * 4
    ypos = (((y & ~3) >> 1) + (y & 1)) & 7
    column = ypos * w * 2 + ((x + swap) & 7) * 4
    byte = ((y >> 1) & 1) + ((x >> 2) & 2)
    return (block + column + byte).reshape(-1)


def _csm1(n: int) -> np.ndarray:
    i = np.arange(n)
    return (i & ~0x18) | ((i & 0x08) << 1) | ((i & 0x10) >> 1) if n == 256 else i


@dataclass
class Ps2Raster:
    name: str
    mask: str
    width: int
    height: int
    depth: int
    fmt: int
    header: bytes                   # 64-byte raster header (GS registers etc.), kept as found
    data: bytes                     # pixel + palette section


def texnative_read(tn: Chunk) -> Ps2Raster:
    plat = tn.kids[0].data
    if plat[:4] != b"PS2\0":
        raise ValueError(f"not a PS2 texture (platform {plat[:4]!r})")
    strs = tn.find(STRING)
    hdr, data = _raster_parts([k for k in tn.kids if k.type == STRUCT][1].data)
    w, h, depth, fmt = struct.unpack_from("<IIII", hdr)
    return Ps2Raster(strs[0].data.split(b"\0")[0].decode(), strs[1].data.split(b"\0")[0].decode(), w, h, depth, fmt,
                     hdr, data)


def _raster_parts(b: bytes) -> tuple[bytes, bytes]:
    """The raster Struct holds two Structs: the 64-byte header and the pixel/palette data."""
    _, s1, _ = struct.unpack_from("<III", b, 0)
    _, s2, _ = struct.unpack_from("<III", b, 12 + s1)
    return b[12:12 + s1], b[24 + s1:24 + s1 + s2]


def raster_indexed(r: Ps2Raster) -> tuple[np.ndarray, np.ndarray]:
    """Top mip level of an 8-bit raster: (h, w) indices + 256 x RGBA palette (alpha 0x80 -> 255)."""
    if r.depth != 8:
        raise NotImplementedError(f"depth {r.depth}")
    hdrs = bool(r.fmt & 0x20000)
    pix_bytes, _pal_bytes = struct.unpack_from("<II", r.header, 48)
    o = 0x50 if hdrs else 0
    rw, rh = struct.unpack_from("<II", r.data, 0x20) if hdrs else (r.width, r.height)
    raw = np.frombuffer(r.data, np.uint8, r.width * r.height, o)
    idx = raw[_swz8_map(r.width, r.height)] if rw * rh * 4 == r.width * r.height else raw
    pal = np.frombuffer(r.data, np.uint8, 1024, pix_bytes + o).reshape(256, 4)[_csm1(256)].astype(np.uint16)
    pal[:, 3] = np.minimum(255, pal[:, 3] * 255 // 128)
    return idx.reshape(r.height, r.width), pal.astype(np.uint8)


def raster_rgba(r: Ps2Raster) -> np.ndarray:
    """Top mip level as (h, w, 4) uint8 RGBA."""
    idx, pal = raster_indexed(r)
    return pal[idx]


def raster_set_indexed(r: Ps2Raster, idx: np.ndarray, pal_rgba: np.ndarray) -> Ps2Raster:
    """Same size/format raster with new 8-bit indices (h, w) and a 256 x RGBA palette (alpha 255 = opaque). Only the
    top level is replaced; GIF headers and GS registers are kept."""
    if r.depth != 8 or idx.shape != (r.height, r.width):
        raise ValueError("needs an 8-bit raster of the same size")
    hdrs = bool(r.fmt & 0x20000)
    pix_bytes, _ = struct.unpack_from("<II", r.header, 48)
    o = 0x50 if hdrs else 0
    rw, rh = struct.unpack_from("<II", r.data, 0x20) if hdrs else (r.width, r.height)
    flat = idx.astype(np.uint8).reshape(-1)
    if rw * rh * 4 == r.width * r.height:
        buf = np.empty_like(flat)
        buf[_swz8_map(r.width, r.height)] = flat
        flat = buf
    out = bytearray(r.data)
    out[o:o + flat.size] = flat.tobytes()
    pal = np.zeros((256, 4), np.uint16)
    pal[:len(pal_rgba)] = pal_rgba
    pal[:, 3] = (pal[:, 3] * 128 + 127) // 255
    po = pix_bytes + o
    p2 = np.empty((256, 4), np.uint8)
    p2[_csm1(256)] = pal.astype(np.uint8)
    out[po:po + 1024] = p2.tobytes()
    return Ps2Raster(r.name, r.mask, r.width, r.height, r.depth, r.fmt, r.header, bytes(out))


def texnative_replace_data(tn: Chunk, r: Ps2Raster):
    """Put a same-size data section back (header Struct bytes kept)."""
    ras = [k for k in tn.kids if k.type == STRUCT][1]
    _, s1, _ = struct.unpack_from("<III", ras.data, 0)
    old = ras.data
    if len(r.data) != struct.unpack_from("<I", old, 16 + s1)[0]:
        raise ValueError("raster data size changed")
    ras.data = old[:24 + s1] + r.data + old[24 + s1 + len(r.data):]


def quantize(rgba: np.ndarray, colors: int = 256) -> tuple[np.ndarray, np.ndarray]:
    """RGBA image -> (indices, palette RGBA) with PIL's median cut (alpha kept binary: < 128 -> transparent)."""
    from PIL import Image
    a = rgba[..., 3] >= 128
    rgb = Image.fromarray(np.ascontiguousarray(rgba[..., :3]))
    q = rgb.quantize(colors - 1 if not a.all() else colors, method=Image.Quantize.MEDIANCUT)
    idx = np.array(q, np.uint8)
    pal = np.array(q.getpalette()[:3 * 256], np.uint8).reshape(-1, 3)
    out = np.zeros((256, 4), np.uint8)
    out[:len(pal), :3] = pal
    out[:, 3] = 255
    if not a.all():
        out[255] = 0
        idx[~a] = 255
    return idx, out


# ---------------------------------------------------------------------------------------------------- glTF export
def clump_to_gltf(dff: bytes, out: Path, rgba: np.ndarray | None = None, name: str = "ped") -> Path:
    """A rigid-part ped clump -> .glb: one mesh skinned 100% per vertex to its atomic's frame (joints = frame names),
    GTA Z-up -> glTF Y-up facing +Z with the ped's left at +X (x, y, z) -> (-x, z, y) (the
    Parasite Eve / PSO / RE4 exports face that way too). For retargeting (scripts/retarget_rigid.py) and looking at the model."""
    root, _ = parse(dff)
    frames = frames_read(root.first(FRAMELIST))
    geoms = root.first(GEOMLIST).find(GEOMETRY)
    C = GTA_TO_GLTF
    P, N, UV, J, T = [], [], [], [], []
    for at in root.find(ATOMIC):
        fi, gi = struct.unpack_from("<II", at.first(STRUCT).data)
        g = geometry_read(geoms[gi])
        m = C @ frames[fi]["world"]
        base = sum(len(p) for p in P)
        P.append((np.c_[g.pos, np.ones(len(g.pos))] @ m.T)[:, :3])
        N.append(g.nrm @ m[:3, :3].T if g.nrm is not None else np.zeros_like(g.pos))
        UV.append(g.uv if g.uv is not None else np.zeros((len(g.pos), 2)))
        J.append(np.full(len(g.pos), fi))
        T.append(g.tris + base)
    world = [C @ f["world"] for f in frames]
    return write_skinned_glb(out, np.concatenate(P), np.concatenate(N), np.concatenate(UV), np.concatenate(J),
                             np.concatenate(T), [f["name"] for f in frames], [f["parent"] for f in frames], world, rgba, name)


def write_skinned_glb(out: Path, pos, nrm, uv, joint, tris, names, parents, world, rgba=None, name="model") -> Path:
    """Minimal skinned glTF binary (1 primitive, 1 joint per vertex); joints placed at world matrices (translation +
    rotation kept, so the node hierarchy is the source skeleton)."""
    import io
    blob = bytearray()

    def view(arr, target=None):
        b = np.ascontiguousarray(arr).tobytes()
        while len(blob) % 4:
            blob.append(0)
        off = len(blob)
        blob.extend(b)
        v = {"buffer": 0, "byteOffset": off, "byteLength": len(b)}
        if target:
            v["target"] = target
        views.append(v)
        return len(views) - 1

    views, accs = [], []

    def acc(arr, ctype, typ, target=None, minmax=False):
        a = {"bufferView": view(arr, target), "componentType": ctype, "count": len(arr), "type": typ}
        if minmax:
            a["min"], a["max"] = arr.min(0).tolist(), arr.max(0).tolist()
        accs.append(a)
        return len(accs) - 1
    n = len(names)
    nodes = []
    for i in range(n):
        lm = world[i] if parents[i] < 0 else np.linalg.inv(world[parents[i]]) @ world[i]
        nodes.append({"name": names[i], "matrix": lm.T.reshape(-1).tolist()})
    for i in range(n):
        ch = [j for j in range(n) if parents[j] == i]
        if ch:
            nodes[i]["children"] = ch
    roots = [i for i in range(n) if parents[i] < 0]
    ibm = np.stack([np.linalg.inv(w).T for w in world]).astype(np.float32)
    attrs = {"POSITION": acc(pos.astype(np.float32), 5126, "VEC3", 34962, True),
             "NORMAL": acc(nrm.astype(np.float32), 5126, "VEC3", 34962),
             "TEXCOORD_0": acc(uv.astype(np.float32), 5126, "VEC2", 34962),
             "JOINTS_0": acc(np.c_[joint, np.zeros((len(joint), 3))].astype(np.uint16), 5123, "VEC4", 34962),
             "WEIGHTS_0": acc(np.c_[np.ones(len(joint)), np.zeros((len(joint), 3))].astype(np.float32), 5126, "VEC4", 34962)}
    ind = acc(tris.reshape(-1).astype(np.uint32), 5125, "SCALAR", 34963)
    gl = {"asset": {"version": "2.0", "generator": "gbox.gta_rw"}, "scene": 0,
          "nodes": nodes + [{"name": name, "mesh": 0, "skin": 0}],
          "scenes": [{"nodes": roots + [n]}],
          "meshes": [{"name": name, "primitives": [{"attributes": attrs, "indices": ind, "material": 0}]}],
          "skins": [{"joints": list(range(n)), "inverseBindMatrices": acc(ibm.reshape(n, 16), 5126, "MAT4")}],
          "materials": [{"name": name, "pbrMetallicRoughness": {"metallicFactor": 0, "roughnessFactor": 1}, "doubleSided": True}]}
    if rgba is not None:
        from PIL import Image
        bio = io.BytesIO()
        Image.fromarray(rgba).save(bio, "PNG")
        gl["images"] = [{"bufferView": view(np.frombuffer(bio.getvalue(), np.uint8)), "mimeType": "image/png"}]
        gl["samplers"] = [{"magFilter": 9728, "minFilter": 9728}]
        gl["textures"] = [{"source": 0, "sampler": 0}]
        gl["materials"][0]["pbrMetallicRoughness"]["baseColorTexture"] = {"index": 0}
    while len(blob) % 4:
        blob.append(0)
    gl["accessors"], gl["bufferViews"], gl["buffers"] = accs, views, [{"byteLength": len(blob)}]
    js = json.dumps(gl, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    Path(out).write_bytes(struct.pack("<III", 0x46546C67, 2, 28 + len(js) + len(blob)) + struct.pack("<II", len(js), 0x4E4F534A)
                          + js + struct.pack("<II", len(blob), 0x004E4942) + bytes(blob))
    return Path(out)
