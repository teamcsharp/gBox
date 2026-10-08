"""GTA Liberty City Stories (PS2) character models: read the player's .mdl/.chk from the disc, export glTF, write a
new player .mdl/.chk for a library character and repack the disc image. No third-party tools at run time.

Formats (checked against the LCS USA disc SLUS_214.23; struct layouts from aap's open-source librwgta
tools/storiesconv, rsl.h / rslconv.cpp / leedsgta.h, verified byte by byte here):

  * Relocatable chunk (".mdl" ident 'ldm\\0' 0x006D646C, ".chk" texture list 'xet\\0' 0x00746578, GAME.DTZ 'GTAG'):
    0x20-byte header {ident, shrink, fileSize, dataSize, relocTab, numRelocs, globalTab, u16 numClasses, u16 numFuncs};
    every pointer in the file is an offset from the file start; relocTab lists numRelocs file offsets of those pointer
    slots (the loader adds the load address to each). Our writer emits the same: a blob + its pointer-slot table.
  * GAME.DTZ = zlib(GTAG). ResourceImage at 0x20: +0x18 numModelInfos, +0x1C modelInfoPtrs, +0x40 TXD pool,
    +0x5C CStreaming (ms_aInfoForModel[6175] x 20 bytes from +4: posn/size in 2 KB sectors of MODELS/GTA3PS2.IMG at
    +12/+16; TXD slot k = info 4900+k). Model 0 = the player (TXD slot 56 'player' at IMG sector 0); its streaming
    size is 0: the player is a *special* model, loaded by name from the special-model directory (game.dat, 32-byte
    entries {u32 sector, u32 sectors, char name[24] 'player\\0mdl'}): player.mdl (Toni, sector 23, 41 sectors),
    plr..plr16 (outfits; a new story starts in plr3), player2..12, csplr*/csplayer* (cutscene variants), plus
    the story characters. Live addresses (Ghidra, FindPlayerPed etc.): see LIVE below and docs/model_swaps.md.
  * Ped .mdl: data @0x20 = {CColModel*, RslElementGroup*}. ElementGroup(8+list) -> RslNode tree (0xAC bytes each:
    object, objectList, modelling 4x4, ltm 4x4, child, next, root, nodeId, RslTAnimTree*, name*, hierId) and one
    RslElement (0x30) -> RslGeometry (0x20: object, refCount, matList{mats*, n, space}, RslSkin*, pad) followed by
    sPs2Geometry (0x40: bound, size = numStrips<<20 | bytes, flags 1 pos/2 nrm/4 uv/8 prelit/0x10 skin, numVerts,
    dmaOffset, u16 bbox[6], scale[3], pos[3]) + numStrips sPs2GeometryMesh (0x30: bound, uvScale[2], unk, dmaPacket,
    numTriangles, matID, f16 min/max) + per strip a DMA chain: DMA tag (qwc), then batches of VIF codes:
      UNPACK V4-32 (GIF tag, nloop = vertex count), STMASK/STROW + UNPACK V3-16 positions
      (x = s16/32767.5*scale + pos), STMASK/STROW + UNPACK V2-8 UVs (u8/127.5*uvScale), [V4-5 prelit],
      UNPACK V3-8 normals (s8/128), UNPACK V4-32 skin (float weight with the low byte = bone index * 4), MSCAL.
    Batches of one strip overlap by 2 vertices (one triangle strip per mesh).
    RslSkin {numBones, numUsedBones, usedBones*, invMatrices* (numBones x 4x4), ...}; RslTAnimTree (LCS, 92 bytes)
    {flags, numNodes, ..., pNodeInfo* (8 bytes: s8 id, s8 index, s8 flags PUSH=2/POP=1, RslNode*)} - the animation
    hierarchy; skin bone i = hierarchy node i. Material {char *texname, RGBA, refCount, matfx*}.
  * Texture list .chk: RslTexList (24 bytes) + RslTexture {RslRasterPS2*, dict*, link, name[32], mask[32]},
    RslRasterPS2 {u8 *data, u32 flags = logw | logh<<6 | depth<<12 | mips<<20 | swizzle-mask<<24}; data = the mip
    levels (8-bit levels with swizzle bit set are stored PSMT8-swizzled, 4-bit as nibbles) then the palette
    (RGBA, alpha 0x80 = opaque; 256-colour palettes in CSM1 order).
"""
from __future__ import annotations

import json
import struct
import time
import zlib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

SECTOR = 2048
MDL_IDENT, TEX_IDENT, GTAG_IDENT = 0x006D646C, 0x00746578, 0x47544147
LCS_GAME_IDS = {"002b9dca58a18ea1"}                 # Grand Theft Auto - Liberty City Stories (USA) (PS2)
# LCS peds bind in a T-pose, Z up, facing +X, left arm along +Y -> glTF Y up, facing +Z, left = +X
LCS_TO_GLTF = np.array([[0, 1, 0, 0], [0, 0, 1, 0], [1, 0, 0, 0], [0, 0, 0, 1]], float)
# LCS ped skeleton (24 hierarchy nodes; bone index = hierarchy order) -> the body roles gbox retargeting uses
LCS_ROLES = {"pelvis": "Pelvis", "hip": "Spine", "chest": "Spine1", "neck": "Neck", "head": "Head",
             "r_clav": "Bip01 R Clavicle", "r_upper": "R UpperArm", "r_fore": "R Forearm", "r_hand": "R Hand",
             "r_hand_end": "R Finger", "l_clav": "Bip01 L Clavicle", "l_upper": "L UpperArm", "l_fore": "L Forearm",
             "l_hand": "L Hand", "l_hand_end": "L Finger", "r_thigh": "R Thigh", "r_shin": "R Calf", "r_foot": "R Foot",
             "r_toe": "R Toe0", "l_thigh": "L Thigh", "l_shin": "L Calf", "l_foot": "L Foot", "l_toe": "L Toe0"}


def gta_key(name: str) -> int:
    """The Stories model-name hash (CRC32 of the upper-cased name without the final xor)."""
    return zlib.crc32(name.upper().encode()) ^ 0xFFFFFFFF


# ------------------------------------------------------------------------------------------------ relocatable chunks
class Reloc:
    """A relocatable chunk as found on disc (pointers = file offsets)."""

    def __init__(self, b: bytes):
        self.b = bytes(b)
        (self.ident, self.shrink, self.file_size, self.data_size, self.reloc_tab, self.num_relocs, self.global_tab,
         self.num_classes, self.num_funcs) = struct.unpack_from("<IIIIIIIHH", self.b, 0)

    def u8(self, o): return self.b[o]
    def u16(self, o): return struct.unpack_from("<H", self.b, o)[0]
    def i16(self, o): return struct.unpack_from("<h", self.b, o)[0]
    def u32(self, o): return struct.unpack_from("<I", self.b, o)[0]
    def i32(self, o): return struct.unpack_from("<i", self.b, o)[0]
    def f32(self, o, n=1):
        v = struct.unpack_from(f"<{n}f", self.b, o)
        return v[0] if n == 1 else v

    def cstr(self, o, n=64):
        return self.b[o:o + n].split(b"\0")[0].decode("latin-1") if o else ""


class Blob:
    """Builder for a relocatable chunk: allocate structs, write pointers (recorded in the reloc table)."""

    def __init__(self):
        self.b = bytearray(0x20)
        self.ptrs: list[int] = []

    def alloc(self, n: int, align: int = 4) -> int:
        self.b += bytes(-len(self.b) % align)
        o = len(self.b)
        self.b += bytes(n)
        return o

    def put(self, o, fmt, *v):
        struct.pack_into(fmt, self.b, o, *v)

    def ptr(self, slot: int, target: int):
        self.put(slot, "<I", target)
        if target:
            self.ptrs.append(slot)

    def finish(self, ident: int, num_funcs: int = 0, global_tab: int | None = None, pad: int = 0xAA) -> bytes:
        self.b += bytes([pad]) * (-len(self.b) % 4)
        data_size = len(self.b)
        tab = b"".join(struct.pack("<I", p) for p in sorted(set(self.ptrs)))
        out = bytes(self.b) + tab
        struct.pack_into("<IIIIIIIHH", (hdr := bytearray(out[:0x20])), 0, ident, 0, len(out), data_size, data_size,
                         len(set(self.ptrs)), data_size if global_tab is None else global_tab, 0, num_funcs)
        return bytes(hdr) + out[0x20:]


# ------------------------------------------------------------------------------------------------------- the disc
def iso_files(f) -> dict[str, tuple[int, int]]:
    from .gta_rw import iso_files as _iso
    return _iso(f)


class LcsDisc:
    """MODELS/GTA3PS2.IMG + CHK/PS2/GAME.DTZ of an LCS PS2 disc image (.iso, 2048-byte sectors)."""

    def __init__(self, iso: Path):
        self.iso = Path(iso)
        with open(iso, "rb") as f:
            self.files = iso_files(f)
            lba, size = self.files["CHK/PS2/GAME.DTZ"]
            f.seek(lba * SECTOR)
            self.dtz = f.read(size)
        self.img_lba, self.img_size = self.files["MODELS/GTA3PS2.IMG"]
        self.game = Reloc(zlib.decompress(self.dtz))
        if self.game.ident != GTAG_IDENT:
            raise ValueError("GAME.DTZ is not a GTAG chunk")

    def img_read(self, sector: int, sectors: int) -> bytes:
        with open(self.iso, "rb") as f:
            f.seek((self.img_lba + sector) * SECTOR)
            return f.read(sectors * SECTOR)

    def file_at(self, sector: int) -> bytes:
        """The relocatable chunk starting at an IMG sector (trimmed to its fileSize)."""
        head = self.img_read(sector, 1)
        n = struct.unpack_from("<I", head, 8)[0]
        return self.img_read(sector, (n + SECTOR - 1) // SECTOR)[:n]

    # GAME.DTZ tables
    def streaming(self, k: int) -> tuple[int, int]:
        st = self.game.u32(0x20 + 0x5C)
        o = st + 4 + 20 * k
        return self.game.u32(o + 12), self.game.u32(o + 16)

    def model_info(self, i: int) -> dict | None:
        g = self.game
        base = g.u32(0x20 + 0x1C)
        if not 0 <= i < g.u32(0x20 + 0x18):
            return None
        p = g.u32(base + 4 * i)
        if not p:
            return None
        txd = g.i16(p + 0x1E)
        return {"index": i, "hash": g.u32(p + 8), "type": g.u8(p + 0x10), "txd_slot": txd,
                "txd": self.txd_name(txd) if txd >= 0 else "", "ped_type": g.u32(p + 0x30) if g.u8(p + 0x10) == 7 else None}

    def txd_name(self, slot: int) -> str:
        pool = self.game.u32(0x20 + 0x40)
        items = self.game.u32(pool)
        return self.game.cstr(items + slot * 28 + 8, 20)

    def special_dir(self) -> list[dict]:
        """The special-model directory (player, outfits, story characters): [{name, sector, sectors}]."""
        if hasattr(self, "_sdir"):
            return self._sdir
        d = self.game.b
        k = d.find(b"player\0mdl\0")
        if k < 0:
            raise ValueError("special-model directory not found in GAME.DTZ")
        k -= 8

        def ok(o):
            return 0 <= o and o + 32 <= len(d) and 32 < d[o + 8] < 127 and b"\0mdl\0" in d[o + 8:o + 32]
        while ok(k - 32):
            k -= 32
        out = []
        while ok(k):
            s, n = struct.unpack_from("<II", d, k)
            nm = d[k + 8:k + 32].split(b"\0")
            out.append({"name": nm[0].decode("latin-1"), "sector": s, "sectors": n, "dir_offset": k})
            k += 32
        self._sdir = out
        return out

    def special(self, name: str) -> dict:
        for e in self.special_dir():
            if e["name"].lower() == name.lower():
                return e
        raise KeyError(name)

    def player_txd(self) -> tuple[int, int]:
        """(sector, sectors) of the player TXD ('player', slot 56)."""
        mi = self.model_info(0)
        return self.streaming(4900 + mi["txd_slot"])


# --------------------------------------------------------------------------------------------------- ped .mdl reader
@dataclass
class Node:
    name: str
    node_id: int
    parent: int
    local: np.ndarray                      # 4x4 (column vectors), modelling matrix
    offset: int = 0


@dataclass
class Strip:
    mat: int
    uv_scale: tuple
    unknown: int
    pos: np.ndarray                        # (n,3) model space
    uv: np.ndarray                         # (n,2)
    nrm: np.ndarray | None
    J: np.ndarray | None                   # (n,4) bone indices
    W: np.ndarray | None                   # (n,4)
    batches: list = field(default_factory=list)    # vertex count per batch (before overlap removal)


@dataclass
class PedModel:
    nodes: list[Node]
    hier: list[tuple[int, int]]            # (node id, flags) per animation node = skin bone order
    bone_nodes: list[int]                  # hierarchy node i -> index into nodes
    inv_bind: np.ndarray                   # (nb,4,4) column-vector matrices
    materials: list[dict]                  # {texture, color}
    geo_flags: int
    scale: tuple
    pos: tuple
    strips: list[Strip]
    raw: Reloc

    def bone_world(self) -> np.ndarray:
        return np.stack([np.linalg.inv(m) for m in self.inv_bind])

    def bone_names(self) -> list[str]:
        return [self.nodes[i].name for i in self.bone_nodes]


def _mat44(r: Reloc, o: int) -> np.ndarray:
    m = np.array(r.f32(o, 16), float).reshape(4, 4).T     # rows right/up/at/pos -> column vectors
    m[3] = [0, 0, 0, 1]
    return m


def _unpack_bytes(code: int) -> int:
    num = (code >> 16) & 0xFF
    vn, vl = (code >> 26) & 3, (code >> 24) & 3
    if (code & 0x6F000000) == 0x6F000000:
        per = 2
    else:
        per = (vn + 1) * (32, 16, 8, 16)[vl] // 8
    return (num * per + 3) & ~3


def _strip_decode(r: Reloc, p: int, flags: int, scale, pos, uvs) -> Strip:
    qwc = r.u32(p) & 0xFFFF
    end = p + (qwc + 1) * 16
    w = p + 16
    P, UV, N, J, W, batches = [], [], [], [], [], []
    first = True
    while w < end:
        if r.u32(w) != 0x6C018000:
            break
        nv = r.u32(w + 16) & 0x7FFF
        batches.append(nv)
        w += 20
        skip = 0 if first else 2
        data = {}
        while True:
            c = r.u32(w)
            op = c >> 24
            if op == 0x20:                                   # STMASK
                w += 8
            elif op == 0x30:                                 # STROW
                w += 20
            elif op == 0x14 or op == 0x15:                   # MSCAL
                w += 4
                while w < end and r.u32(w) == 0:
                    w += 4
                break
            elif (op & 0x60) == 0x60:
                n = (c >> 16) & 0xFF
                data[op & 0x6F] = (w + 4, n)
                w += 4 + _unpack_bytes(c)
            else:
                w += 4
        o, n = data[0x69]                                    # V3-16 positions
        a = np.frombuffer(r.b, "<i2", n * 3, o).reshape(n, 3).astype(float) / 32767.5 * np.array(scale) + np.array(pos)
        P.append(a[skip:])
        o, n = data[0x66]                                    # V2-8 uvs
        a = np.frombuffer(r.b, np.uint8, n * 2, o).reshape(n, 2).astype(float) / 127.5 * np.array(uvs)
        UV.append(a[skip:])
        if 0x6A in data:
            o, n = data[0x6A]
            N.append((np.frombuffer(r.b, np.int8, n * 3, o).reshape(n, 3).astype(float) / 128.0)[skip:])
        if 0x6C in data:
            o, n = data[0x6C]
            raw = np.frombuffer(r.b, "<u4", n * 4, o).reshape(n, 4)
            wt = (raw & ~np.uint32(0xFF)).view("<f4").astype(float)
            idx = ((raw >> 2) & 0x3F).astype(int)
            idx[wt == 0] = 0
            J.append(idx[skip:])
            W.append(wt[skip:])
        first = False
    cat = lambda L: np.concatenate(L) if L else None   # noqa: E731
    return Strip(0, tuple(uvs), 0, cat(P), cat(UV), cat(N), cat(J), cat(W), batches)


def read_ped(b: bytes) -> PedModel:
    r = Reloc(b)
    if r.ident != MDL_IDENT:
        raise ValueError("not a .mdl chunk")
    eg = r.u32(0x24)
    if r.u8(eg) != 2:
        raise ValueError("not a ped model (no element group at +4)")
    nodes: list[Node] = []
    index = {}

    def walk(o, parent):
        while o:
            i = len(nodes)
            index[o] = i
            nodes.append(Node(r.cstr(r.u32(o + 0xA4), 24), r.i32(o + 0x9C), parent, _mat44(r, o + 0x10), o))
            if r.u32(o + 0x90):
                walk(r.u32(o + 0x90), i)
            o = r.u32(o + 0x94)
    walk(r.u32(eg + 4), -1)
    # first element (peds have one)
    a = r.u32(eg + 8) - 0x1C
    g = r.u32(a + 0x14)
    hier_p = r.u32(a + 0x2C) or next(r.u32(n.offset + 0xA0) for n in nodes if r.u32(n.offset + 0xA0))
    nn, ni = r.u32(hier_p + 4), r.u32(hier_p + 0x30)
    hier = [(r.u8(ni + 8 * k), r.u8(ni + 8 * k + 2)) for k in range(nn)]
    by_id = {}
    for k, n in enumerate(nodes):
        by_id.setdefault(n.node_id & 0xFF, k)
    bone_nodes = [by_id[h[0]] for h in hier]
    mats_p, nmat, skin = r.u32(g + 12), r.u32(g + 16), r.u32(g + 24)
    materials = []
    for k in range(nmat):
        m = r.u32(mats_p + 4 * k)
        materials.append({"texture": r.cstr(r.u32(m), 32), "color": tuple(r.b[m + 4:m + 8])})
    nb, inv = r.u32(skin), r.u32(skin + 12)
    inv_bind = np.stack([_mat44(r, inv + 64 * k) for k in range(nb)])
    G = g + 0x20
    size, flags = r.u32(G + 16), r.i32(G + 20)
    scale, pos = r.f32(G + 0x28, 3), r.f32(G + 0x34, 3)
    ns = size >> 20
    dbase = G + 0x40 + 0x30 * ns
    strips = []
    for k in range(ns):
        sm = G + 0x40 + 0x30 * k
        s = _strip_decode(r, dbase + r.u32(sm + 0x1C), flags, scale, pos, r.f32(sm + 0x10, 2))
        s.mat, s.unknown = r.i16(sm + 0x22), r.i32(sm + 0x18)
        strips.append(s)
    return PedModel(nodes, hier, bone_nodes, inv_bind, materials, flags, scale, pos, strips, r)


def strip_triangles(n: int) -> np.ndarray:
    """Triangle-strip vertex count -> (t,3) index triangles (alternating winding, degenerates dropped later)."""
    i = np.arange(max(n - 2, 0))
    t = np.stack([i, i + 1, i + 2], 1)
    t[1::2] = t[1::2][:, [1, 0, 2]]
    return t


# ---------------------------------------------------------------------------------------------- texture list (.chk)
@dataclass
class Tex:
    name: str
    width: int
    height: int
    depth: int
    flags: int
    rgba: np.ndarray


def _swz8(w, h):
    from .gta_rw import _swz8_map
    return _swz8_map(w, h)


def _csm1(n):
    from .gta_rw import _csm1 as c
    return c(n)


def read_chk(b: bytes) -> list[Tex]:
    r = Reloc(b)
    if r.ident != TEX_IDENT:
        raise ValueError("not a texture list chunk")
    out = []
    head = 0x20 + 8                                   # texturesInDict link
    l = r.u32(head)
    seen = set()
    while l and l != head and l not in seen:
        seen.add(l)
        t = l - 8
        ras = r.u32(t)
        name = r.cstr(t + 16, 32)
        data, fl = r.u32(ras), r.u32(ras + 4)
        w, h, d, mips = 1 << (fl & 0x3F), 1 << ((fl >> 6) & 0x3F), (fl >> 12) & 0x3F, (fl >> 20) & 0xF
        swz = (fl >> 24) & 1
        o = data
        sizes = []
        ww, hh = w, h
        for _ in range(max(mips, 1)):
            sizes.append(ww * hh * d // 8)
            ww, hh = max(ww // 2, 1), max(hh // 2, 1)
        pal_o = data + sum(sizes)
        if d == 8:
            idx = np.frombuffer(r.b, np.uint8, w * h, o)
            if swz:
                idx = idx[_swz8(w, h)]
            pal = np.frombuffer(r.b, np.uint8, 1024, pal_o).reshape(256, 4)[_csm1(256)]
        elif d == 4:
            raw = np.frombuffer(r.b, np.uint8, w * h // 2, o)
            idx = np.stack([raw & 0xF, raw >> 4], 1).reshape(-1)
            if swz:
                idx = idx[_swz8(w, h)]
            pal = np.frombuffer(r.b, np.uint8, 64, pal_o).reshape(16, 4)
        elif d == 32:
            px = np.frombuffer(r.b, np.uint8, w * h * 4, o).reshape(h, w, 4).astype(np.uint16)
            px[..., 3] = np.minimum(255, px[..., 3] * 255 // 128)
            out.append(Tex(name, w, h, d, fl, px.astype(np.uint8)))
            l = r.u32(l)
            continue
        else:
            raise NotImplementedError(f"{name}: depth {d}")
        p = pal.astype(np.uint16)
        p[:, 3] = np.minimum(255, p[:, 3] * 255 // 128)
        out.append(Tex(name, w, h, d, fl, p.astype(np.uint8)[idx].reshape(h, w, 4)))
        l = r.u32(l)
    return out


def write_chk(texs: list[tuple[str, np.ndarray]], depth: int = 8) -> bytes:
    """[(name, RGBA (h,w,4) power-of-two)] -> a texture list .chk (one mip, 8-bit swizzled or 4-bit linear)."""
    from .gta_rw import quantize
    bl = Blob()
    head = bl.alloc(24)
    bl.put(head, "<BBBB", 6, 0, 0, 0)
    prev = head + 8
    tex_offs = []
    for name, rgba in texs:
        h, w = rgba.shape[:2]
        t = bl.alloc(80)
        ras = bl.alloc(8)
        tex_offs.append((t, ras, name, rgba))
    # link list: head.next -> t0.link -> t1.link ... -> head
    links = [t + 8 for t, *_ in tex_offs]
    chain = [head + 8] + links + [head + 8]
    for k in range(len(chain) - 1):
        bl.ptr(chain[k], chain[k + 1])                                   # next
        bl.ptr(chain[k + 1] + 4, chain[k])                              # prev
    for t, ras, name, rgba in tex_offs:
        h, w = rgba.shape[:2]
        bl.ptr(t, ras)
        bl.ptr(t + 4, head)
        nm = name.encode()[:31]
        bl.b[t + 16:t + 16 + len(nm)] = nm
        logw, logh = w.bit_length() - 1, h.bit_length() - 1
        if depth == 8:
            idx, pal = quantize(rgba, 256)
            swz = 1 if (w >= 16 and h >= 16 and not (w < 128 and h > w) and w <= 256 and h <= 256) else 0
            flat = idx.reshape(-1)
            if swz:
                buf = np.empty_like(flat)
                buf[_swz8(w, h)] = flat
                flat = buf
            p = pal.astype(np.uint16)
            p[:, 3] = (p[:, 3] * 128 + 127) // 255
            p2 = np.empty((256, 4), np.uint8)
            p2[_csm1(256)] = p.astype(np.uint8)
            payload = flat.tobytes() + p2.tobytes()
        else:
            idx, pal = quantize(rgba, 16)
            idx = np.minimum(idx, 15).reshape(-1)
            payload = (idx[0::2] | (idx[1::2] << 4)).astype(np.uint8).tobytes()
            p = pal[:16].astype(np.uint16)
            p[:, 3] = (p[:, 3] * 128 + 127) // 255
            payload += p.astype(np.uint8).tobytes()
            swz = 0
        d = bl.alloc(len(payload), 64)
        bl.b[d:d + len(payload)] = payload
        bl.ptr(ras, d)
        bl.put(ras + 4, "<I", logw | logh << 6 | depth << 12 | 1 << 20 | swz << 24)
    return bl.finish(TEX_IDENT)


# ------------------------------------------------------------------------------------------------------ glTF export
def ped_to_gltf(m: PedModel, texs: list[Tex], out: Path, name: str = "lcs_ped") -> Path:
    """Skinned .glb (Y-up, facing +Z): joints = the 24 hierarchy bones at their bind pose, 4 weights per vertex,
    one primitive per material with its texture."""
    import io
    from PIL import Image
    C = LCS_TO_GLTF
    bw = np.stack([C @ w for w in m.bone_world()])
    names = m.bone_names()
    nb = len(names)
    # parents from the PUSH/POP flags of the hierarchy
    parents, stack, prev = [], [], -1
    for k, (_id, fl) in enumerate(m.hier):
        parents.append(prev)
        if fl & 2:
            stack.append(prev)
        prev = k
        if fl & 1:
            prev = stack.pop() if stack else -1
    tex_by = {t.name.lower(): t for t in texs}
    blob, views, accs = bytearray(), [], []

    def view(b, target=None):
        while len(blob) % 4:
            blob.append(0)
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(b), **({"target": target} if target else {})})
        blob.extend(b)
        return len(views) - 1

    def acc(a, ct, typ, target=None, mm=False):
        d = {"bufferView": view(np.ascontiguousarray(a).tobytes(), target), "componentType": ct, "count": len(a), "type": typ}
        if mm:
            d["min"], d["max"] = a.min(0).tolist(), a.max(0).tolist()
        accs.append(d)
        return len(accs) - 1
    prims, materials, images, textures = [], [], [], []
    for mi, mat in enumerate(m.materials):
        P, UV, N, J, W, T = [], [], [], [], [], []
        base = 0
        for s in m.strips:
            if s.mat != mi:
                continue
            n = len(s.pos)
            t = strip_triangles(n)
            pp = s.pos
            t = t[(np.linalg.norm(np.cross(pp[t[:, 1]] - pp[t[:, 0]], pp[t[:, 2]] - pp[t[:, 0]]), axis=1) > 1e-12)]
            P.append(pp); UV.append(s.uv); N.append(s.nrm if s.nrm is not None else np.zeros((n, 3)))
            J.append(s.J if s.J is not None else np.zeros((n, 4), int)); W.append(s.W if s.W is not None else np.c_[np.ones(n), np.zeros((n, 3))])
            T.append(t + base)
            base += n
        if not P:
            continue
        P = (np.c_[np.concatenate(P), np.ones(base)] @ C.T)[:, :3]
        N = np.concatenate(N) @ C[:3, :3].T
        Wt = np.concatenate(W)
        Wt = Wt / np.maximum(Wt.sum(1, keepdims=True), 1e-9)
        Jt = np.minimum(np.concatenate(J), nb - 1)
        attrs = {"POSITION": acc(P.astype(np.float32), 5126, "VEC3", 34962, True),
                 "NORMAL": acc(N.astype(np.float32), 5126, "VEC3", 34962),
                 "TEXCOORD_0": acc(np.concatenate(UV).astype(np.float32), 5126, "VEC2", 34962),
                 "JOINTS_0": acc(Jt.astype(np.uint16), 5123, "VEC4", 34962),
                 "WEIGHTS_0": acc(Wt.astype(np.float32), 5126, "VEC4", 34962)}
        pbr = {"metallicFactor": 0, "roughnessFactor": 1, "baseColorFactor": [c / 255 for c in mat["color"]]}
        t = tex_by.get(mat["texture"].lower())
        if t is None and not mat["texture"]:                # nameless material: its texture is set at run time
            named = {x["texture"].lower() for x in m.materials}  # (Toni's head) -> the TXD's unreferenced texture
            t = next((x for x in texs if x.name.lower() not in named), None)
        if t is not None:
            bio = io.BytesIO()
            Image.fromarray(t.rgba).save(bio, "PNG")
            images.append({"bufferView": view(bio.getvalue()), "mimeType": "image/png", "name": t.name})
            textures.append({"source": len(images) - 1, "sampler": 0})
            pbr["baseColorTexture"] = {"index": len(textures) - 1}
        materials.append({"name": mat["texture"] or f"mat{mi}", "pbrMetallicRoughness": pbr, "doubleSided": True,
                          **({"alphaMode": "MASK"} if t is not None and (t.rgba[..., 3] < 128).any() else {})})
        prims.append({"attributes": attrs, "indices": acc(np.concatenate(T).reshape(-1).astype(np.uint32), 5125, "SCALAR", 34963),
                      "material": len(materials) - 1})
    nodes = []
    for i in range(nb):
        lm = bw[i] if parents[i] < 0 else np.linalg.inv(bw[parents[i]]) @ bw[i]
        nodes.append({"name": names[i], "matrix": lm.T.reshape(-1).tolist()})
    for i in range(nb):
        ch = [j for j in range(nb) if parents[j] == i]
        if ch:
            nodes[i]["children"] = ch
    ibm = np.stack([np.linalg.inv(w).T for w in bw]).astype(np.float32).reshape(nb, 16)
    gl = {"asset": {"version": "2.0", "generator": "gbox.gta_stories_models"}, "scene": 0,
          "nodes": nodes + [{"name": name, "mesh": 0, "skin": 0}],
          "scenes": [{"nodes": [i for i in range(nb) if parents[i] < 0] + [nb]}],
          "meshes": [{"name": name, "primitives": prims}],
          "skins": [{"joints": list(range(nb)), "inverseBindMatrices": acc(ibm, 5126, "MAT4")}],
          "materials": materials}
    if images:
        gl.update(images=images, textures=textures, samplers=[{"magFilter": 9729, "minFilter": 9729}])
    while len(blob) % 4:
        blob.append(0)
    gl["accessors"], gl["bufferViews"], gl["buffers"] = accs, views, [{"byteLength": len(blob)}]
    js = json.dumps(gl, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    Path(out).write_bytes(struct.pack("<III", 0x46546C67, 2, 28 + len(js) + len(blob)) + struct.pack("<II", len(js), 0x4E4F534A)
                          + js + struct.pack("<II", len(blob), 0x004E4942) + bytes(blob))
    return Path(out)


# ------------------------------------------------------------------------------------------------------- the writer
def bone_parents(m: PedModel) -> list[int]:
    """Skin bone parents from the hierarchy's PUSH (2) / POP (1) flags."""
    parents, stack, prev = [], [], -1
    for _id, fl in m.hier:
        parents.append(prev)
        if fl & 2:
            stack.append(prev)
        prev = len(parents) - 1
        if fl & 1:
            prev = stack.pop() if stack else -1
    return parents


class _Template:
    """Duck-typed stand-in for re4gc_models.Bin so re4gc_enemies.retarget() fits a rig onto the LCS skeleton:
    bones = (index, parent) in hierarchy order, positions in millimetres in glTF axes (Y up, facing +Z, left +X)."""

    def __init__(self, m: PedModel):
        par = bone_parents(m)
        self.bones = [(k, par[k] if par[k] >= 0 else 0xFF) for k in range(len(par))]
        self._w = {k: (LCS_TO_GLTF @ w)[:3, 3] * 1000.0 for k, w in enumerate(m.bone_world())}

    def bone_world(self):
        return self._w


def lcs_roles(m: PedModel) -> dict[str, int]:
    names = m.bone_names()
    return {r: names.index(n) for r, n in LCS_ROLES.items() if n in names}


def retarget_onto(m: PedModel, src_model: Path, src_roles: dict) -> list[dict]:
    """A library character (glTF + {role: joint name}) -> prims on the LCS skeleton: pos/nrm in the .mdl's model
    space (metres, Z up), J[:,0] = skin bone (hierarchy index), uv, tris, tex (RGBA or None), color."""
    from .characters import rig_from_gltf
    from .re4gc_enemies import retarget
    rig = rig_from_gltf(Path(src_model), src_roles)
    prims = retarget(rig, _Template(m), roles=lcs_roles(m), height_range=(1600.0, 1950.0))
    inv = np.linalg.inv(LCS_TO_GLTF)[:3, :3]
    for p in prims:
        p["pos"] = (np.asarray(p["pos"], float) / 1000.0) @ inv.T
        p["nrm"] = np.asarray(p["nrm"], float) @ inv.T
    return prims


def _resize(img: np.ndarray, side: int) -> np.ndarray:
    from PIL import Image
    return np.array(Image.fromarray(np.ascontiguousarray(img)).convert("RGBA").resize((side, side), Image.LANCZOS))


def pack_atlases(prims: list[dict], sizes: list[tuple[int, int]], fill: float = 0.85):
    """Every source image (texture or flat colour) gets a power-of-two square cell, sized by how much surface uses
    it, packed (buddy allocation) into the atlases [(w, h)]. Returns (atlases RGBA, per prim (atlas index,
    per-triangle corner uvs (t,3,2) in atlas space))."""
    items, prim_item = {}, []
    for p in prims:
        tex = p.get("tex")
        col = tuple(int(c) for c in (p.get("color") or (200, 200, 200, 255))[:4])
        mode = p.get("alpha_mode", "OPAQUE")
        key = ("tex", id(tex), mode) if tex is not None else ("col", col)
        P, T = np.asarray(p["pos"], float), np.asarray(p["tris"], int).reshape(-1, 3)
        area = float(np.linalg.norm(np.cross(P[T[:, 1]] - P[T[:, 0]], P[T[:, 2]] - P[T[:, 0]]), axis=1).sum()) / 2
        it = items.setdefault(key, {"img": tex, "color": col, "area": 0.0})
        if tex is not None and mode == "OPAQUE" and it["img"] is tex:
            # glTF OPAQUE ignores texture alpha. Carry that rule into the PS2
            # atlas instead of cutting holes in opaque FF7 body materials.
            it["img"] = np.asarray(tex).copy()
            it["img"][..., 3] = 255
        it["area"] += area + 1e-6
        prim_item.append(key)
    total_px = sum(w * h for w, h in sizes)
    total_area = sum(i["area"] for i in items.values())
    regions = []                                       # square regions: (atlas, x, y, side)
    for a, (w, h) in enumerate(sizes):
        s = min(w, h)
        for y in range(0, h, s):
            for x in range(0, w, s):
                regions.append((a, x, y, s))
    biggest = max(r[3] for r in regions)
    order = sorted(items, key=lambda k: -items[k]["area"])
    for shrink in range(8):
        for k in order:
            it = items[k]
            if it["img"] is None:
                it["side"] = 4
            else:
                side = 1 << max(2, int(np.floor(np.log2(max(np.sqrt(it["area"] / total_area * total_px * fill), 1)))))
                it["side"] = max(4, min(side >> shrink, biggest))
        free = {}                                      # side -> free blocks (atlas, x, y)
        for a, x, y, s in regions:
            free.setdefault(s, []).append((a, x, y))
        ok = True
        for k in sorted(order, key=lambda k: -items[k]["side"]):
            want = s = items[k]["side"]
            while not free.get(s):
                s *= 2
                if s > biggest:
                    ok = False
                    break
            if not ok:
                break
            a, x, y = free[s].pop(0)
            while s > want:                             # split the buddy block
                s //= 2
                free.setdefault(s, []).extend([(a, x + s, y), (a, x, y + s), (a, x + s, y + s)])
            items[k]["cell"] = (a, x, y)
        if ok:
            break
    else:
        raise ValueError("the textures don't fit the atlases")
    atlases = [np.zeros((h, w, 4), np.uint8) for w, h in sizes]
    for a in atlases:
        a[..., 3] = 255
    for it in items.values():
        a, x, y = it["cell"]
        s = it["side"]
        if it["img"] is None:
            atlases[a][y:y + s, x:x + s] = np.array(it["color"][:3] + (255,), np.uint8)
        else:
            atlases[a][y:y + s, x:x + s] = _resize(it["img"], s)
    out = []
    for p, key in zip(prims, prim_item):
        it = items[key]
        a, x, y = it["cell"]
        s = it["side"]
        w, h = sizes[a]
        T = np.asarray(p["tris"], int).reshape(-1, 3)
        uv = np.asarray(p["uv"], float)[T]                     # (t,3,2)
        uv = np.clip(uv - np.floor(uv.min(1, keepdims=True)), 0, 1)   # wrap each triangle into the first tile
        au = (x + 0.5 + uv[..., 0] * (s - 1)) / w
        av = (y + 0.5 + uv[..., 1] * (s - 1)) / h
        out.append((a, np.stack([au, av], -1)))
    return atlases, out


def stripify(tris: list[tuple]) -> list[list[int]]:
    """Greedy strips preserving every source triangle's winding, with the fewest-neighbour start and best of
    three cyclic rotations. A 3-vertex list is a lone triangle."""
    und: dict = {}
    for t, (a, b, c) in enumerate(tris):
        for e in ((a, b), (b, c), (c, a)):
            und.setdefault(frozenset(e), []).append(t)
    nb = [sum(len(und[frozenset(e)]) - 1 for e in ((a, b), (b, c), (c, a))) for a, b, c in tris]
    used = [False] * len(tris)

    def take(u, v):
        for t in und.get(frozenset((u, v)), ()):
            tri = tris[t]
            if not used[t] and any(tri[k] == u and tri[(k + 1) % 3] == v for k in range(3)):
                return t
        return None

    def grow(s0):
        st, tk = list(s0), []
        while True:
            u, v = st[-2:]
            t = take(v, u) if len(st) % 2 else take(u, v)
            if t is None:
                return st, tk
            used[t] = True
            tk.append(t)
            st.append(next(v for v in tris[t] if v != st[-1] and v != st[-2]))
    out = []
    for t0 in sorted(range(len(tris)), key=lambda t: nb[t]):
        if used[t0]:
            continue
        used[t0] = True
        a, b, c = tris[t0]
        best = None
        for s0 in ((a, b, c), (b, c, a), (c, a, b)):
            st, tk = grow(s0)
            for t in tk:
                used[t] = False
            if best is None or len(tk) > len(best[1]) or (len(tk) == len(best[1]) and len(st) < len(best[0])):
                best = (st, tk)
        for t in best[1]:
            used[t] = True
        out.append(best[0])
    return out


def _mesh_strips(tris: list[tuple], max_len: int = 300) -> list[list[int]]:
    """Triangles -> strips joined by degenerate vertices, keeping each new strip's parity even."""
    pieces = stripify(tris)
    meshes, cur = [], []
    for s in pieces:
        if cur and len(cur) + len(s) + 3 > max_len:
            meshes.append(cur)
            cur = []
        if cur:
            if len(cur) % 2:
                cur.append(cur[-1])
            cur += [cur[-1], s[0]]
        cur += s
    if cur:
        meshes.append(cur)
    return meshes


def _batch(nv: int, q: np.ndarray, uvb: np.ndarray, nb: np.ndarray, sk: np.ndarray) -> bytes:
    """One VU batch exactly as the game's own: GIF tag, positions V3-16 @1, uvs V2-8 unsigned @0x55, normals V3-8
    @0x2B, skin V4-32 @0x7F (double-buffered: +TOPS), MSCAL 6."""
    def pad(b):
        return b + bytes(-len(b) % 4)
    out = struct.pack("<5I", 0x6C018000, 0, 0, nv, 0x8000 | nv)
    out += struct.pack("<2I", 0x20000000, 0x40404040) + struct.pack("<5I", 0x30000000, 0, 0, 0, 0)
    out += struct.pack("<I", 0x79000000 | nv << 16 | 0x8001) + pad(q.astype("<i2").tobytes())
    out += struct.pack("<2I", 0x20000000, 0x50505050) + struct.pack("<5I", 0x30000000, 0, 0, 0xFF, 0)
    out += struct.pack("<I", 0x76000000 | nv << 16 | 0xC055) + pad(uvb.astype(np.uint8).tobytes())
    out += struct.pack("<I", 0x6A000000 | nv << 16 | 0x802B) + pad(nb.astype(np.int8).tobytes())
    out += struct.pack("<I", 0x6C000000 | nv << 16 | 0x807F) + sk.astype("<u4").tobytes()
    return out + struct.pack("<I", 0x14000006)


def build_geometry(m: PedModel, groups: dict[int, dict]) -> tuple[bytes, dict]:
    """groups {material index: {pos (n,3), nrm, uv, J (n,) bone, tris (t,3)}} -> the sPs2Geometry block (header,
    mesh headers, DMA packets) in the original's encoding, plus stats. Vertices are rigid (one bone, weight 1)."""
    allp = np.concatenate([g["pos"] for g in groups.values()])
    lo, hi = allp.min(0), allp.max(0)
    pos = (lo + hi) / 2
    ext = np.maximum((hi - lo) / 2, 1e-3)
    scale = 2.0 ** np.ceil(np.log2(ext * 1.0001))               # powers of two like the originals (0.25, 1, 1)
    unk = {s.mat: s.unknown for s in m.strips}
    meshes = []
    for mi, g in sorted(groups.items()):
        q = np.clip(np.round((g["pos"] - pos) / scale * 32767.5), -32767, 32767).astype(np.int64)
        uvb = np.clip(np.round(g["uv"] * 127.5), 0, 255).astype(np.int64)
        nb = np.clip(np.round(g["nrm"] * 127), -127, 127).astype(np.int64)
        J = np.asarray(g["J"]).astype(np.int64)
        # one vertex per (position, uv, bone): corners that differ only in their normal (flat-shaded or decimated
        # sources) share an averaged normal, so the strips stay long
        k0, inv = np.unique(np.concatenate([q, uvb, J[:, None]], 1), axis=0, return_inverse=True)
        inv = inv.reshape(-1)
        nsum = np.zeros((len(k0), 3))
        np.add.at(nsum, inv, np.asarray(g["nrm"], float))
        nsum /= np.maximum(np.linalg.norm(nsum, axis=1, keepdims=True), 1e-9)
        nb = np.clip(np.round(nsum * 127), -127, 127).astype(np.int64)
        uniq = np.concatenate([k0[:, :5], nb, k0[:, 5:6]], 1)
        tris = [tuple(int(inv[v]) for v in t) for t in g["tris"]]
        tris = [t for t in tris if len(set(t)) == 3]
        sph_c = (g["pos"].min(0) + g["pos"].max(0)) / 2
        sph_r = float(np.linalg.norm(g["pos"] - sph_c, axis=1).max())
        for st in _mesh_strips(tris):
            meshes.append((mi, uniq[np.array(st)], sph_c, sph_r))
    ns = len(meshes)
    head = 0x40 + 0x30 * ns
    dma, hdrs, nverts = bytearray(), bytearray(), 0
    for mi, v, c, r in meshes:
        n = len(v)
        nverts += n
        body = bytearray()
        k = 0
        while True:
            b = v[k:k + 42]
            sk = np.zeros((len(b), 4), np.uint32)
            sk[:, 0] = 0x3F800000 | (b[:, 8].astype(np.uint32) << 2)
            body += _batch(len(b), b[:, 0:3], b[:, 3:5], b[:, 5:8], sk)
            if k + 42 >= n:
                break
            k += 40
        body += bytes(-len(body) % 16)
        off = len(dma)
        dma += struct.pack("<4I", 0x60000000 | len(body) // 16, 0, 0, 0) + body
        mn, mx = v[:, :3].min(0), v[:, :3].max(0)
        hdrs += struct.pack("<4f2fiIHh3h3h", *c, r, 1.0, 1.0, unk.get(mi, -8), off, n - 2, mi, *mn, *mx)
    gc = (lo + hi) / 2
    gr = float(np.linalg.norm(allp - gc, axis=1).max())
    qmax = np.abs(np.round((allp - pos) / scale * 32767.5)).max(0).astype(int)
    size = head + len(dma)
    hdr = struct.pack("<4fIiHH3h3h3f3f", *gc, gr, ns << 20 | size, m.geo_flags & ~8, nverts, head,
                      *(-qmax), *qmax, *scale, *pos)
    return bytes(hdr + hdrs + dma), {"meshes": ns, "vertices": int(nverts), "bytes": size,
                                     "triangles": int(sum(len(g["tris"]) for g in groups.values()))}


def replace_geometry(orig: bytes, block: bytes) -> bytes:
    """The original .mdl with its sPs2Geometry block swapped: everything after it moves by a multiple of 64 bytes,
    every relocated pointer / reloc entry past it is shifted."""
    r = Reloc(orig)
    a = r.u32(r.u32(0x24) + 8) - 0x1C
    G = r.u32(a + 0x14) + 0x20
    old_end = G + (r.u32(G + 16) & 0xFFFFF)
    blk = block + bytes(-len(block) % 64)
    while (G + len(blk) - old_end) % 64:
        blk += bytes(16)
    delta = G + len(blk) - old_end
    out = bytearray(orig[:G] + blk + orig[old_end:])

    def sh(x):
        return x + delta if x >= old_end else x
    slots = [r.u32(r.reloc_tab + 4 * i) for i in range(r.num_relocs)]
    for s in slots:
        v = r.u32(s)
        if G <= v < old_end or G <= s < old_end:
            raise ValueError("a pointer points into the geometry block")
        struct.pack_into("<I", out, sh(s), sh(v))
    rt = sh(r.reloc_tab)
    for i, s in enumerate(slots):
        struct.pack_into("<I", out, rt + 4 * i, sh(s))
    struct.pack_into("<IIIII", out, 8, r.file_size + delta, sh(r.data_size), rt, r.num_relocs, sh(r.global_tab))
    return bytes(out)


def replace_chk(orig: bytes, images: dict[str, np.ndarray]) -> bytes:
    """The original texture list with new pixels for the named textures: same size, depth, mip count and swizzle
    flags (so the file and every pointer stay as they were). One palette per texture for all its mips."""
    from PIL import Image
    from .gta_rw import quantize
    r = Reloc(orig)
    out = bytearray(orig)
    want = {k.lower(): v for k, v in images.items()}
    head = 0x28
    l, seen, done = r.u32(head), set(), []
    while l and l != head and l not in seen:
        seen.add(l)
        t = l - 8
        name = r.cstr(t + 16, 32)
        rgba = want.get(name.lower())
        if rgba is not None:
            ras = r.u32(t)
            data, fl = r.u32(ras), r.u32(ras + 4)
            w, h, d = 1 << (fl & 0x3F), 1 << ((fl >> 6) & 0x3F), (fl >> 12) & 0x3F
            mips, swz = max((fl >> 20) & 0xF, 1), fl >> 24
            if d not in (4, 8):
                raise NotImplementedError(f"{name}: depth {d}")
            top = np.array(Image.fromarray(np.ascontiguousarray(rgba)).convert("RGBA").resize((w, h), Image.LANCZOS))
            idx0, pal = quantize(top, 256 if d == 8 else 16)
            pal_img = Image.new("P", (1, 1))
            pal_img.putpalette([int(x) for x in pal[:, :3].reshape(-1)] + [0] * (768 - pal[:, :3].size))
            o, ww, hh = data, w, h
            for lv in range(mips):
                if lv == 0:
                    idx = idx0
                else:
                    small = Image.fromarray(top).resize((ww, hh), Image.LANCZOS)
                    idx = np.array(small.convert("RGB").quantize(palette=pal_img, dither=Image.Dither.NONE), np.uint8)
                    if (pal[:, 3] == 0).any():
                        idx[np.array(small)[..., 3] < 128] = int(np.argmax(pal[:, 3] == 0))
                flat = idx.reshape(-1).astype(np.uint8)
                if d == 4:
                    flat = np.minimum(flat, 15)
                if (swz >> lv) & 1:
                    buf = np.empty_like(flat)
                    buf[_swz8(ww, hh)] = flat
                    flat = buf
                b = (flat[0::2] | (flat[1::2] << 4)).astype(np.uint8).tobytes() if d == 4 else flat.tobytes()
                out[o:o + len(b)] = b
                o += ww * hh * d // 8
                ww, hh = max(ww // 2, 1), max(hh // 2, 1)
            p = pal.astype(np.uint16)
            p[:, 3] = (p[:, 3] * 128 + 127) // 255
            if d == 8:
                p2 = np.empty((256, 4), np.uint8)
                p2[_csm1(256)] = p.astype(np.uint8)
                out[o:o + 1024] = p2.tobytes()
            else:
                out[o:o + 64] = p[:16].astype(np.uint8).tobytes()
            done.append(name.lower())
        l = r.u32(l)
    missing = [k for k in want if k not in done]
    if missing:
        raise ValueError(f"textures not in the list: {missing}")
    return bytes(out)


# ------------------------------------------------------------------------------------------------- swap / extract
def txd_for(disc: LcsDisc, name: str) -> tuple[int, int]:
    """(sector, sectors) of a special model's TXD: the TXD slot with the model's name ('player' = slot 56)."""
    pool = disc.game.u32(0x20 + 0x40)
    for slot in range(disc.game.u32(pool + 8)):
        if disc.txd_name(slot).lower() == name.lower():
            s, n = disc.streaming(4900 + slot)
            if n:
                return s, n
    raise KeyError(f"no TXD named {name}")


def texture_slots(m: PedModel, texs: list[Tex]) -> list[dict]:
    """The atlases a swap can paint: one per distinct texture the model's materials use (a nameless material =
    the TXD texture no material names, set by the game at run time - Toni's head), with its size and the first
    material that draws with it."""
    named = {x["texture"].lower() for x in m.materials if x["texture"]}
    spare = [t for t in texs if t.name.lower() not in named]
    by = {t.name.lower(): t for t in texs}
    out, seen = [], {}
    for mi, mat in enumerate(m.materials):
        t = by.get(mat["texture"].lower()) if mat["texture"] else (spare[0] if spare else None)
        if t is None or t.name.lower() in seen:
            continue
        seen[t.name.lower()] = mi
        out.append({"texture": t.name, "material": mi, "size": (t.width, t.height), "depth": t.depth})
    return out


def swap_files(disc: LcsDisc, src_model: Path, src_roles: dict, entry: str = "player", work: Path | None = None,
               blender: str | None = None, progress=None) -> dict:
    """Build the replacement .mdl + .chk for one special model (default 'player' = Toni): the library character
    retargeted onto the model's own 24-bone skeleton (bone count/order/hierarchy, collision and skin matrices kept,
    so every animation still drives it), textures packed into the model's own texture slots (same sizes, depths,
    mips). Decimates (Blender) until the .mdl fits the model's sectors in the IMG."""
    progress = progress or (lambda p, m: None)
    e = disc.special(entry)
    orig = disc.file_at(e["sector"])
    m = read_ped(orig)
    ts, tn = txd_for(disc, entry)
    chk = disc.file_at(ts)
    texs = read_chk(chk)
    slots = texture_slots(m, texs)
    budget = e["sectors"] * SECTOR
    src, tried = Path(src_model), []
    work = Path(work or Path(src_model).parent)
    for attempt in range(5):
        progress(20 + attempt * 12, f"Retargeting onto {entry}'s skeleton ({len(m.bone_names())} bones)")
        prims = retarget_onto(m, src, src_roles)
        atlases, maps = pack_atlases(prims, [s["size"] for s in slots])
        groups: dict = {}
        for p, (a, uv) in zip(prims, maps):
            T = np.asarray(p["tris"], int).reshape(-1, 3)
            g = groups.setdefault(slots[a]["material"], {"pos": [], "nrm": [], "uv": [], "J": [], "tris": []})
            base = sum(len(x) for x in g["pos"])
            g["pos"].append(p["pos"][T].reshape(-1, 3))
            g["nrm"].append(p["nrm"][T].reshape(-1, 3))
            g["uv"].append(uv.reshape(-1, 2))
            g["J"].append(np.asarray(p["J"])[:, 0][T].reshape(-1))
            g["tris"].append(np.arange(len(T) * 3).reshape(-1, 3) + base)
        for g in groups.values():
            for k in g:
                g[k] = np.concatenate(g[k])
        block, stats = build_geometry(m, groups)
        mdl = replace_geometry(orig, block)
        tried.append({"triangles": stats["triangles"], "bytes": len(mdl)})
        if len(mdl) <= budget:
            break
        if not blender:
            raise ValueError(f"{len(mdl)} bytes > the {budget} the IMG slot holds and no Blender here to decimate")
        target = int(stats["triangles"] * (budget / len(mdl)) * 0.93)
        progress(25 + attempt * 12, f"Too big ({len(mdl)} > {budget} bytes): decimating to ~{target} triangles")
        from .re4gc_enemies import decimate
        src = decimate(Path(src_model), work / f"_lcs_dec_{entry}_{attempt}.glb", target, blender)
    else:
        raise ValueError(f"doesn't fit {entry}.mdl's {e['sectors']} sectors: {tried}")
    new_chk = replace_chk(chk, {s["texture"]: a for s, a in zip(slots, atlases)})
    if len(new_chk) > tn * SECTOR:
        raise ValueError("texture list grew")
    return {"entry": entry, "mdl": mdl, "chk": new_chk, "mdl_sector": e["sector"], "mdl_sectors": e["sectors"],
            "chk_sector": ts, "chk_sectors": tn, "stats": stats, "tried": tried, "atlases": atlases,
            "slots": slots, "model": read_ped(mdl), "source": str(src)}


def patch_iso(iso: Path, disc: LcsDisc, files: list[tuple[int, int, bytes]]) -> list[dict]:
    """Write files into GTA3PS2.IMG inside a (copied) disc image: (IMG sector, slot sectors, bytes), zero padded."""
    out = []
    with open(iso, "r+b") as f:
        for sector, sectors, data in files:
            if len(data) > sectors * SECTOR:
                raise ValueError(f"{len(data)} bytes > {sectors} sectors at IMG sector {sector}")
            f.seek((disc.img_lba + sector) * SECTOR)
            f.write(data + bytes(sectors * SECTOR - len(data)))
            out.append({"img_sector": sector, "sectors": sectors, "bytes": len(data)})
    return out


def extract_player(disc: LcsDisc, out: Path, entry: str = "player") -> dict:
    """A special model (default Toni) -> skinned .glb with its textures; returns names/stats."""
    e = disc.special(entry)
    m = read_ped(disc.file_at(e["sector"]))
    ts, _tn = txd_for(disc, entry)
    texs = read_chk(disc.file_at(ts))
    ped_to_gltf(m, texs, Path(out), entry)
    return {"entry": entry, "bones": m.bone_names(), "materials": m.materials, "textures": [t.name for t in texs],
            "vertices": int(sum(len(s.pos) for s in m.strips)), "glb": str(out)}


def lcs_iso_from_rom(rom: Path, dst: Path, progress=None) -> Path:
    """The vanilla disc image for patching: a CHD is extracted with chdman (MODE1/2048 track -> plain .iso)."""
    import shutil
    import subprocess
    dst = Path(dst)
    if dst.exists():
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    part = dst.with_suffix(".part")
    if Path(rom).suffix.lower() == ".chd":
        exe = shutil.which("chdman")
        if not exe:
            raise ValueError("chdman is needed to unpack the CHD (apt install mame-tools)")
        if progress:
            progress(5, f"Unpacking {Path(rom).name} (chdman)")
        cue = dst.with_suffix(".cue")
        r = subprocess.run([exe, "extractcd", "-i", str(rom), "-o", str(cue), "-ob", str(part), "-f"],
                           capture_output=True, text=True, timeout=3600)
        if r.returncode or not part.exists():
            raise RuntimeError(f"chdman failed: {(r.stdout + r.stderr)[-800:]}")
        cue.unlink(missing_ok=True)
    else:
        shutil.copy2(rom, part)
    part.replace(dst)
    return dst


# ------------------------------------------------------------------------------------- live game (SLUS_214.23, NTSC-U)
# EE RAM addresses from Ghidra (gBox ghidra_script DecompileAll, MIPS:LE:64:64-32addr, gp = 0x3D6EF0), checked live:
#   FindPlayerPed      0x107368: return *(CWorld::Players + PlayerInFocus*sizeof(CPlayerInfo)), 162 callers
#   CWorld::Players    0x408E40 (CPlayerInfo +0 = CPlayerPed*), PlayerInFocus (pre-scaled byte offset) 0x3D9BC8
#   CStreaming::RequestSpecialModel 0x18FF80 (model id, name, flags): hash = GetUppercaseKey(name) (0x1838D8);
#     CBaseModelInfo::SetModelName 0x1B7C80 (hash at +8), CDirectory::FindItem 0x1450D8 on the special-model
#     directory (*(CStreaming*)0x3D0CC8 + 0x1E328), SetTexDictionary 0x1B7B18 (TXD = the model's name, else "generic")
#   CModelInfo::ms_modelInfoPtrs 0x3D8720 (pointer to the array), numModelInfos 0x3D9BA0
#   CPed: +0x30 position, +0x58 s16 modelIndex (CEntity), +0x534 CVehicle* (m_pMyVehicle), +0x538 in-vehicle flag
LIVE = {"players": 0x408E40, "focus": 0x3D9BC8, "mi_ptrs": 0x3D8720, "mi_count": 0x3D9BA0, "streaming": 0x3D0CC8,
        "ped_model": 0x58, "ped_pos": 0x30, "ped_vehicle": 0x534, "ped_in_vehicle": 0x538, "movies": (0x1F3744, 0x1F3758, 0x1F376C, 0x1F3780)}
# Toni's outfits = special models loaded into model slot 0 (+ the TXD of the same name). The story starts in plr3.
OUTFITS = {"player": "mafia suit (player.mdl, unused by the story)", "plr": "mafia suit", "plr2": "lawyer",
           "plr3": "traveller (the story's starting outfit)", "plr4": "chauffeur", "plr5": "mask", "plr6": "tuxedo",
           "plr7": "Guardian Angels", "plr8": "Elvis", "plr9": "mascot", "plr10": "boxer shorts", "plr11": "Avenging Angels",
           "plr12": "dragon", "plr13": "T-shirt and jeans", "plr14": "tracksuit", "plr15": "short-sleeved shirt",
           "plr16": "long-sleeved shirt"}
GAME_IDS = {"002b9dca58a18ea1": "Grand Theft Auto - Liberty City Stories (USA)"}


def _read(ctx, sid: str, addr: int, n: int) -> bytes:
    from .characters import _api
    return bytes.fromhex(_api(ctx, "POST", f"/api/sessions/{sid}/rpc", json={"op": "read_memory",
                                                                              "args": {"address": addr, "length": n}}))


def identify(ctx, sid: str) -> dict:
    """Who the player is in a running LCS session: FindPlayerPed() -> its model index -> that model's name hash ->
    the special-model name (Toni's outfit .mdl in GTA3PS2.IMG), plus whether he's driving."""
    u32 = lambda a: struct.unpack("<I", _read(ctx, sid, a, 4))[0]     # noqa: E731
    if not u32(LIVE["mi_count"]):
        return {"status": "not_loaded", "message": "the game hasn't loaded its world yet (no model table in RAM)"}
    ped = u32(LIVE["players"] + u32(LIVE["focus"]))
    if not ped:
        return {"status": "no_player", "message": "no player ped yet (title screen or loading)"}
    hdr = _read(ctx, sid, ped, 0x60)
    idx = struct.unpack_from("<h", hdr, LIVE["ped_model"])[0]
    mi = u32(u32(LIVE["mi_ptrs"]) + 4 * idx)
    h = u32(mi + 8)
    names = {gta_key(n): n for n in OUTFITS} | {gta_key(n): n for n in ("csplr", "csplayer")}
    name = names.get(h)
    veh = struct.unpack("<I", _read(ctx, sid, ped + LIVE["ped_vehicle"], 4))[0]
    inv = _read(ctx, sid, ped + LIVE["ped_in_vehicle"], 1)[0]
    who = (f"Toni Cipriani, outfit {name} ({OUTFITS[name]})" if name in OUTFITS else
           f"model #{idx} ({name or f'hash {h:08x}'})")
    return {"status": "ok", "ped": ped, "model_index": idx, "model_hash": h, "model": name, "outfit": OUTFITS.get(name),
            "position": [round(x, 2) for x in struct.unpack_from("<3f", hdr, LIVE["ped_pos"])],
            "driving": bool(inv and veh), "message": f"You are playing as {who}" + (", driving." if inv and veh else ".")}


def build_mod(cfg, game: dict, rom: Path, src_model: Path, roles: dict, name: str, entries: list[str] | None = None,
              skip_movies: bool = False, progress=None) -> dict:
    """The disc-image mod: every Toni outfit (or `entries`) replaced by the library character. Unpacks the CHD once
    per node (cache/modbase/<game>/<stem>.iso), builds every .mdl/.chk first (all must fit their IMG slots), then
    copies the image and writes them in."""
    import shutil
    from . import filemods
    progress = progress or (lambda p, m: None)
    gid = game["game_id"]
    base = lcs_iso_from_rom(rom, filemods.base_dir(cfg, gid) / (Path(rom).stem + ".iso"), progress)
    disc = LcsDisc(base)
    work = Path(cfg.cache) / "characters_build" / name
    work.mkdir(parents=True, exist_ok=True)
    try:
        from .characters import _blender
        bl = _blender(cfg)
    except Exception:
        bl = None
    entries = entries or list(OUTFITS)
    # biggest IMG slot first: a model decimated to fit one outfit is carried on to the (smaller) next ones, so every
    # outfit gets the most triangles its slot holds and Blender runs only when a slot is smaller than the last
    entries = sorted(entries, key=lambda n: -disc.special(n)["sectors"])
    files, report, src = [], [], Path(src_model)
    for k, entry in enumerate(entries):
        progress(10 + 60 * k / len(entries), f"Writing {entry}.mdl ({OUTFITS.get(entry, '')})")
        r = swap_files(disc, src, roles, entry, work, bl)
        e = disc.special(entry)
        files += [(e["sector"], e["sectors"], r["mdl"]), (r["chk_sector"], r["chk_sectors"], r["chk"])]
        report.append({"entry": entry, "outfit": OUTFITS.get(entry), "mdl_bytes": len(r["mdl"]), "slot_bytes": e["sectors"] * SECTOR,
                       "chk_bytes": len(r["chk"]), **r["stats"], "decimated": len(r["tried"]) > 1})
        src = Path(r["source"])                      # later outfits start from the (decimated) model that fit
        if k == 0:
            ped_to_gltf(r["model"], read_chk(r["chk"]), work / "preview.glb", name)
    out = filemods.mod_dir(cfg, gid, name)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    image = f"LCS {name}.iso"
    progress(75, f"Copying the disc image ({base.stat().st_size >> 20} MB)")
    shutil.copyfile(base, out / image)
    patch_iso(out / image, disc, files)
    if skip_movies:                                  # test builds: the intro movies hang some emulator builds
        lba, _ = disc.files["SLUS_214.23"]
        with open(out / image, "r+b") as f:
            for va in LIVE["movies"]:
                f.seek(lba * SECTOR + va - 0xFF000)
                if f.read(4) == struct.pack("<I", 0x0C0D6808):
                    f.seek(-4, 1)
                    f.write(bytes(4))
    (out / ".gbox-mod.json").write_text(json.dumps({"name": name, "game_id": gid, "image": image, "built": time.time(),
                                                    "files": ["MODELS/GTA3PS2.IMG"], "entries": entries}))
    try:
        from .characters import render_preview
        render_preview(work / "preview.glb", work / "preview.png")
        shutil.copy2(work / "preview.png", out / "preview.png")
    except Exception:
        pass
    return {"mod": name, "image": image, "dir": str(out), "outfits": report}


def use(ctx, meta: dict, game: dict, inp) -> dict:
    """characters op=use for LCS: identify who the player is (if a session is given), build lcs_<slug> (every Toni
    outfit replaced, on the control plane where the collection is) unless it exists, record it, launch it on the
    requesting session's node."""
    from . import characters as C
    gid, name = game["game_id"], f"lcs_{meta['slug']}"
    who = None
    if inp.session_id:
        try:
            who = identify(ctx, inp.session_id)
        except Exception as e:                       # noqa: BLE001 - identification is informational
            who = {"status": "error", "message": f"couldn't read the session: {e}"}
    sess = C._session(ctx, inp.session_id) if inp.session_id else None
    node = sess["session_id"].split("-")[0] if sess else C.HOST_OS
    from . import filemods
    have = name in {m["name"] for m in filemods.list_mods(ctx.config, gid)}
    built = None
    if inp.rebuild or not have:
        if C.library_root(ctx.config).is_dir():
            roles = meta.get("rig", {}).get("roles")
            if not roles:
                raise ValueError(f"{meta['name']} has no body roles (rig.roles): can't fit it to Toni's skeleton")
            built = build_mod(ctx.config, game, C._rom(ctx, game), C._local_or_fetch(ctx, meta, meta["model"]), roles,
                              name, progress=ctx.progress)
            C._api(ctx, "POST", f"/api/characters/{meta['slug']}/targets",
                   json={"game_id": gid, "slot": "player", "mod": name, "nodes": [C.HOST_OS],
                         "notes": f"replaces Toni in all {len(built['outfits'])} outfits (his 24-bone skeleton and "
                                  "animations stay); cutscenes still show Toni (csplr*.mdl)"})
        else:
            cp = next((w["id"] for w in C._api(ctx, "GET", "/api/workers") if w.get("os") == "linux"), None)
            ctx.progress(10, "Building the LCS mod on the control-plane node (the collection lives there)")
            j = C._job(ctx, "characters", {"op": "use", "character": meta["slug"], "game_id": gid, "rebuild": inp.rebuild,
                                           "launch": False}, cp, 3600)
            r = (j.get("output") or {}).get("result") or {}
            if j.get("state") != "succeeded" or r.get("status") not in ("built", "ready"):
                return {"status": "failed", "mod": name, "identified": who, "error": r.get("error") or j.get("error") or r}
            built = r.get("build")
    res = {"mod": name, "build": built, "identified": who,
           "replaces": "Toni Cipriani in every outfit (player, plr..plr16; his skeleton and animations stay)"}
    if not inp.launch:
        return res | {"status": "built" if built else "ready"}
    ctx.progress(90, f"Launching Liberty City Stories with {meta['name']} (mod {name})")
    lj = C._api(ctx, "POST", "/api/jobs", json={"tool": "@launch", "input": {"game_id": gid, "mod": name, "node": node}})
    t0 = time.time()
    while lj.get("state") in ("queued", "running") and time.time() - t0 < 1800:
        time.sleep(2)
        lj = C._api(ctx, "GET", f"/api/jobs/{lj['id']}")
    ok = lj.get("state") == "succeeded"
    launch = {"job": lj.get("id"), "state": lj.get("state"), "node": node,
              "session_id": (lj.get("output") or {}).get("session_id"), "error": lj.get("error")}
    msg = ((who or {}).get("message", "") + " " if who and who.get("status") == "ok" else "") + (
        f"Liberty City Stories is running with {meta['name']} in Toni's place (mod {name})." if ok
        else f"Mod {name} is {'built' if built else 'ready'} but the launch {lj.get('state')}: {lj.get('error')}")
    return res | {"status": ("built+launched" if built else "launched") if ok else "launch " + str(lj.get("state")),
                  "launch": launch, "message": msg}


def extract_run(ctx, game: dict, e: dict, work: Path) -> dict:
    """characters op=extract (DEDICATED route): Toni (or one outfit, e['key']) straight from the disc -> .glb."""
    from . import characters as C
    from . import filemods
    rom = C._rom(ctx, game)
    iso = lcs_iso_from_rom(rom, filemods.base_dir(ctx.config, game["game_id"]) / (Path(rom).stem + ".iso"), ctx.progress)
    entry = e.get("key") or "plr3"
    out = Path(work) / f"lcs_{entry}.glb"
    info = extract_player(LcsDisc(iso), out, entry)
    disc = LcsDisc(iso)
    ts, _ = txd_for(disc, entry)
    return {"files": [out], "tool": "gbox.gta_stories_models", "roles": dict(LCS_ROLES),
            "source_files": [f"MODELS/GTA3PS2.IMG: {entry}.mdl (sector {disc.special(entry)['sector']}), "
                             f"TXD {entry} (sector {ts})"],
            "notes": f"LCS {entry}.mdl ({OUTFITS.get(entry, '')}): 24-bone skinned ped, {info['vertices']} strip vertices, "
                     f"textures {', '.join(info['textures'])}"}


def roster() -> list[dict]:
    return [{"key": "plr3", "slug": "lcs_toni", "name": "Toni Cipriani",
             "aliases": ["Toni", "Toni Cipriani", "LCS Toni", "LCS player", "Liberty City Stories player"], "kind": "character"}] + [
        {"key": k, "slug": f"toni_{k}", "name": f"Toni Cipriani ({v.split(' (')[0]})", "aliases": [f"Toni {v.split(' (')[0]}"],
         "kind": "character"} for k, v in OUTFITS.items() if k != "plr3"]
