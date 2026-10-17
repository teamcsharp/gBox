"""Zelda: Ocarina of Time (N64): the ROM side of gBox's OoT model swaps (gbox.oot_swap) and world props (gbox.oot_place).

Reference: the zeldaret/oot decompilation (github.com/zeldaret/oot, CC0) - read as documentation only, nothing of it is
shipped or run: baseroms/<version>/config.yml + segments.csv (dmadata offset, file order), include/animation.h (skeletons,
Link's animation frames), src/code/z_player_lib.c (Link's hand / sheath / waist display-list tables), assets/xml (where
Link's objects keep their skeletons).

ROM model:
  * every file is Yaz0-compressed in the retail ROM and found through the DMA table (dmadata: {vromStart, vromEnd,
    romStart, romEnd} per file, romEnd 0 = stored uncompressed). DmaMgr searches the table linearly, so a changed file is
    simply stored UNCOMPRESSED past the end of the ROM data with romEnd 0; a file that grows gets a fresh VROM range past
    every other file and the tables that name its VROM (gObjectTable in `code`) are pointed at it. Nothing else moves.
  * `code` holds gObjectTable (object id -> VROM range), gActorOverlayTable and Link's display-list tables. Patched
    `code` keeps its size and VROM.
  * the CIC-6105 header CRC is recomputed (dmadata and code lie inside the checksummed first MB).
Display lists are F3DEX2 (32-vertex cache): G_VTX 0x01, G_TRI1 0x05, G_TRI2 0x06, G_DL 0xDE, G_ENDDL 0xDF.
"""
from __future__ import annotations

import struct

import numpy as np
from .formats.lz import yaz0_decompress  # noqa: F401  (shared codec, moved to gbox.formats)

# version -> dmadata offset + DMA indices (segments.csv line - 2) of the files gBox reads. N64 retail + GameCube ports.
VERSIONS = {
    "ntsc-1.0": {"dma": 0x7430, "code": 27, "link_anim": 7, "player": 34, "kaleido": 33, "code_vram": 0x800110A0},
    "ntsc-1.1": {"dma": 0x7430, "code": 27, "link_anim": 7, "player": 34, "kaleido": 33, "code_vram": 0x800110A0},
    "ntsc-1.2": {"dma": 0x7960, "code": 27, "link_anim": 7, "player": 34, "kaleido": 33, "code_vram": 0x800116E0},
    "pal-1.0": {"dma": 0x7950, "code": 28, "link_anim": 6, "player": 35, "kaleido": 34, "code_vram": 0x800116E0},
    "pal-1.1": {"dma": 0x7950, "code": 28, "link_anim": 6, "player": 35, "kaleido": 34, "code_vram": 0x800116E0},
    "gc-us": {"dma": 0x7170, "code": 27, "link_anim": 7, "player": 33, "kaleido": 32, "code_vram": 0x80010EE0},
    "gc-eu": {"dma": 0x7170, "code": 28, "link_anim": 6, "player": 34, "kaleido": 33, "code_vram": 0x80010F00},
    # Build identity: https://github.com/zeldaret/oot/blob/main/README.md (gc-eu-mq).
    # Master Quest retail ROM shipped on the PAL GameCube disc (NZLP): same dmadata/code layout as gc-eu, its own name.
    "gc-eu-mq": {"dma": 0x7170, "code": 28, "link_anim": 6, "player": 34, "kaleido": 33, "code_vram": 0x80010F00},
}
# md5 of the big-endian ROM -> exact version (the decomp's checksum files); others are told apart by layout
MD5 = {"5bd1fe107bf8106b2ab6650abecd54d6": "ntsc-1.0", "721fdcc6f5f34be55c43a807f2a16af4": "ntsc-1.1",
       "57a9719ad547c516342e1a15d5c28c3d": "ntsc-1.2", "e040de91a74b61e3201db0e2323f768a": "pal-1.0",
       "d714580dd74c2c033f5e1b6dc0aeac77": "pal-1.1",
       "1618403427e4344a57833043db5ce3c3": "gc-eu-mq"}
OBJECT_LINK_BOY, OBJECT_LINK_CHILD, OBJECT_GAMEPLAY_KEEP = 0x14, 0x15, 0x01


# ---------------------------------------------------------------- Yaz0



# ---------------------------------------------------------------- CRC (CIC-6105)

def crc6105(rom: bytes) -> tuple[int, int]:
    m = 0xFFFFFFFF
    t1 = t2 = t3 = t4 = t5 = t6 = 0xDF26F436
    words = struct.unpack_from(">262144I", rom, 0x1000)
    key = struct.unpack_from(">64I", rom, 0x750)
    for i, d in enumerate(words):
        t = (t6 + d) & m
        if t < t6:
            t4 = (t4 + 1) & m
        t6 = t
        t3 ^= d
        s = d & 0x1F
        r = ((d << s) | (d >> (32 - s))) & m if s else d
        t5 = (t5 + r) & m
        t2 = t2 ^ r if t2 > d else t2 ^ t6 ^ d
        t1 = (t1 + (key[i & 0x3F] ^ d)) & m
    return t6 ^ t4 ^ t3, t5 ^ t2 ^ t1


# ---------------------------------------------------------------- the ROM

class Rom:
    """A retail OoT ROM (big-endian .z64 bytes): files by DMA index / object id, decompressed on demand; `put` stages a
    changed file, `build` writes them all into a new ROM."""

    def __init__(self, data: bytes):
        if data[:4] != b"\x80\x37\x12\x40":
            raise ValueError("need a big-endian .z64 ROM")
        self.data = bytes(data)
        self.version = self._version()
        self.v = VERSIONS[self.version]
        self.dma = []
        o = self.v["dma"]
        while True:
            e = struct.unpack_from(">4I", self.data, o)
            if e == (0, 0, 0, 0):
                break
            self.dma.append(list(e))
            o += 16
        self._cache: dict[int, bytes] = {}
        self.changed: dict[int, bytes] = {}
        code = self.file(self.v["code"])
        keep = self.dma[self._keep_index()]
        self.obj_table = code.find(struct.pack(">II", keep[0], keep[1])) - 8   # gObjectTable[0] is {0, 0}
        assert self.obj_table > 0 and code[self.obj_table:self.obj_table + 8] == bytes(8), "gObjectTable not found"

    def _version(self) -> str:
        import hashlib
        h = hashlib.md5(self.data).hexdigest()
        if h in MD5:
            return MD5[h]
        pal = self.data[0x3E:0x3F] in (b"P", b"D", b"F")
        for name, v in VERSIONS.items():
            o = v["dma"]
            if o + 48 <= len(self.data) and struct.unpack_from(">4I", self.data, o) == (0, 0x1060, 0, 0) and \
                    struct.unpack_from(">I", self.data, o + 32)[0] == o and (name.startswith(("pal", "gc-eu")) == pal):
                return name
        raise ValueError("not an Ocarina of Time ROM gBox knows (N64 NTSC 1.0/1.1/1.2, PAL 1.0/1.1, GameCube US/EU)")

    def _keep_index(self) -> int:
        """gameplay_keep: the first object file (DMA index = link_animetion's + a fixed distance in every version)."""
        return {"ntsc": 498, "pal": 499, "gc-us": 497, "gc-eu": 498}[next(k for k in ("ntsc", "pal", "gc-us", "gc-eu")
                                                                       if self.version.startswith(k))]

    def file(self, i: int) -> bytes:
        if i in self.changed:
            return self.changed[i]
        if i not in self._cache:
            vs, ve, rs, re_ = self.dma[i]
            raw = self.data[rs:rs + (ve - vs if re_ == 0 else re_ - rs)]
            self._cache[i] = yaz0_decompress(raw) if raw[:4] == b"Yaz0" else raw
        return self._cache[i]

    def index_of_vrom(self, vrom: int) -> int:
        return next(i for i, e in enumerate(self.dma) if e[0] == vrom)

    def object_index(self, obj_id: int) -> int:
        vs, _ve = struct.unpack_from(">II", self.file(self.v["code"]), self.obj_table + 8 * obj_id)
        return self.index_of_vrom(vs)

    def object(self, obj_id: int) -> bytes:
        return self.file(self.object_index(obj_id))

    def put(self, i: int, data: bytes) -> None:
        self.changed[i] = bytes(data)

    def put_object(self, obj_id: int, data: bytes) -> None:
        self.put(self.object_index(obj_id), data)

    def build(self) -> bytes:
        """-> the new ROM: changed files uncompressed after the last ROM data (16-byte aligned), DMA entries updated. A
        file that grew gets a fresh VROM range, and every table naming its old range is pointed at the new one:
        gObjectTable in `code`, plus the files listed in self.ref_files (a scene's room list), CRC fixed."""
        out = bytearray(self.data)
        end = max(e[3] or (e[2] + e[1] - e[0]) for e in self.dma)
        at = (end + 0xFFF) & ~0xFFF
        vnext = (max(e[1] for e in self.dma) + 0xFFFF) & ~0xFFFF
        code_i = self.v["code"]
        moved = {}
        for i, d in sorted(self.changed.items()):
            vs, ve = self.dma[i][:2]
            if len(d) > ve - vs:                         # grew: a fresh VROM range past every other file
                assert i != code_i, "code must keep its size"
                nvs, nve = vnext, vnext + ((len(d) + 0xF) & ~0xF)
                vnext = (nve + 0xFFFF) & ~0xFFFF
                moved[i] = ((vs, ve), (nvs, nve))
        for i in {code_i} | set(getattr(self, "ref_files", ())):
            d = bytearray(self.file(i))
            for (ovs, ove), (nvs, nve) in moved.values():
                o = 0
                while (o := d.find(struct.pack(">II", ovs, ove), o)) >= 0:
                    if o % 4 == 0 and (i != code_i or (o >= self.obj_table and (o - self.obj_table) % 8 == 0)):
                        struct.pack_into(">II", d, o, nvs, nve)
                    o += 4
            if bytes(d) != self.file(i):
                self.changed[i] = bytes(d)

        def place(d: bytes) -> int:
            nonlocal at
            o = at
            if len(out) < o + len(d):
                out.extend(b"\xff" * (o + len(d) - len(out)))
            out[o:o + len(d)] = d
            at = (o + len(d) + 0xF) & ~0xF
            return o
        for i, d in sorted(self.changed.items()):
            vs, ve = moved[i][1] if i in moved else self.dma[i][:2]
            self.dma[i] = [vs, ve, place(d + bytes(ve - vs - len(d))), 0]
        size = 1 << max(25, (at - 1).bit_length())       # 32 MB, else 64 MB
        if size > 0x4000000:
            raise ValueError(f"ROM would be {at / 2**20:.1f} MB (> 64 MB)")
        out.extend(b"\xff" * (size - len(out)))
        o = self.v["dma"]
        for k, e in enumerate(self.dma):
            struct.pack_into(">4I", out, o + 16 * k, *e)
        struct.pack_into(">II", out, 0x10, *crc6105(out))
        return bytes(out)


# ---------------------------------------------------------------- skeletons, animations, poses

def u32(b: bytes, o: int) -> int:
    return struct.unpack_from(">I", b, o)[0]


def skeleton(obj: bytes, off: int, lod: bool | None = None) -> dict:
    """SkeletonHeader / FlexSkeletonHeader at `off` (segment-6 offset) -> {limbs: [{pos, child, sibling, dls: [segaddr..],
    at: offset of the limb}], count, dlcount (flex only), table: offset of the limb pointer table}."""
    tbl, cnt = u32(obj, off) & 0xFFFFFF, obj[off + 4]
    ptrs = [u32(obj, tbl + 4 * i) & 0xFFFFFF for i in range(cnt)]
    if lod is None:                                      # LOD limbs are 16 bytes, standard 12: look at the spacing
        gaps = {b - a for a, b in zip(ptrs, ptrs[1:])}
        lod = 16 in gaps and 12 not in gaps
    limbs = []
    for p in ptrs:
        x, y, z, ch, sb = struct.unpack_from(">hhhBB", obj, p)
        dls = list(struct.unpack_from(">II" if lod else ">I", obj, p + 8))
        limbs.append({"pos": (x, y, z), "child": ch, "sibling": sb, "dls": dls, "at": p})
    dlc = obj[off + 8] if off + 8 < len(obj) else None
    return {"limbs": limbs, "count": cnt, "dlcount": dlc, "table": tbl, "lod": lod, "header": off}


def dfs(limbs: list[dict]) -> list[int]:
    order, stack = [], [0]
    while stack:
        i = stack.pop()
        order.append(i)
        lb = limbs[i]
        if lb["sibling"] != 0xFF:
            stack.append(lb["sibling"])
        if lb["child"] != 0xFF:
            stack.append(lb["child"])
    return order


def rot_zyx(r) -> np.ndarray:
    """OoT Matrix_TranslateRotateZYX rotation part (column vectors): Rz @ Ry @ Rx, binary angles."""
    x, y, z = (np.pi * float(a) / 32768 for a in r)
    cx, sx, cy, sy, cz, sz = np.cos(x), np.sin(x), np.cos(y), np.sin(y), np.cos(z), np.sin(z)
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return Rz @ Ry @ Rx


def pose(skel: dict, frame: list | None = None) -> list[np.ndarray]:
    """World 4x4 (column-vector) matrix per limb. frame: [root translation, rot limb0, rot limb1, ...] (Vec3s); None =
    every rotation 0 (the skeleton's bind layout)."""
    limbs = skel["limbs"]
    W = [None] * len(limbs)

    def go(i, parent):
        lb = limbs[i]
        m = np.eye(4)
        t = frame[0] if (frame is not None and i == 0) else lb["pos"]
        m[:3, 3] = t
        m[:3, :3] = rot_zyx(frame[i + 1]) if frame is not None else np.eye(3)
        W[i] = parent @ m
        if lb["child"] != 0xFF:
            go(lb["child"], W[i])
        if lb["sibling"] != 0xFF:
            go(lb["sibling"], parent)
    go(0, np.eye(4))
    return W


def link_frame(rom: "Rom", header_off: int, frame: int = 0, limbs: int = 21) -> list:
    """A Link animation frame (LinkAnimationHeader in gameplay_keep -> link_animetion): root translation, then one
    rotation per limb (Vec3s each; the face index after them is ignored)."""
    keep = rom.object(OBJECT_GAMEPLAY_KEEP)
    seg = u32(keep, header_off + 4) & 0xFFFFFF
    data = rom.file(rom.v["link_anim"])
    o = seg + frame * ((limbs + 1) * 6 + 2)
    v = struct.unpack_from(f">{(limbs + 1) * 3}h", data, o)
    return [v[k:k + 3] for k in range(0, len(v), 3)]


# ---------------------------------------------------------------- F3DEX2 display lists (reading)

def run_dl(segs: dict, addr: int, on_tri=None, st=None, depth=0, init: dict | None = None) -> dict:
    """Walk an F3DEX2 display list. segs {segment: bytes}. Calls on_tri(state, (i0, i1, i2), cmd address, which) per
    triangle (which: 0 / 1 = first / second triangle of a G_TRI2). state: vertex buffer [(pos, st, rgba-or-normal,
    matrix slot or None, vertex address)], the material state (texture source, tile 0, TLUT, combiner, prim / env colour,
    geometry mode, othermode H) and 'cmds' [(address, w0, w1)] of every command run."""
    if st is None:
        st = {"vb": [None] * 32, "timg": None, "tex_src": None, "tlut": None, "combine": None, "prim": 0xFFFFFFFF,
              "env": 0xFFFFFFFF, "geo": 0x00230405, "mtx": None, "cmds": [], "dls": set(), "tex_on": False,
              "tile0": None, "size0": None, "omh": 0, "tscale": (0xFFFF, 0xFFFF), **(init or {})}
    seg_of = lambda a: (a >> 24) & 0xF
    data = segs.get(seg_of(addr))
    if data is None or depth > 16:
        return st
    o = addr & 0xFFFFFF
    st["dls"].add(addr)
    while o + 8 <= len(data):
        w0, w1 = struct.unpack_from(">II", data, o)
        cmd = w0 >> 24
        here = (addr & 0xFF000000) | o
        st["cmds"].append((here, w0, w1))
        if cmd == 0x01:
            n, end = (w0 >> 12) & 0xFF, (w0 >> 1) & 0x7F
            st.setdefault("vtx", []).append((w1, 16 * n))
            src = segs.get(seg_of(w1))
            if src is not None:
                vo = w1 & 0xFFFFFF
                for k in range(n):
                    if vo + 16 * k + 16 <= len(src) and 0 <= end - n + k < 32:
                        x, y, z, _f, s, t, a, b, c, d = struct.unpack_from(">hhhHhh4B", src, vo + 16 * k)
                        st["vb"][end - n + k] = ((x, y, z), (s, t), (a, b, c, d), st["mtx"], w1 + 16 * k)
        elif cmd == 0x05 and on_tri:
            on_tri(st, tuple(((w0 >> s) & 0xFF) // 2 for s in (16, 8, 0)), here, 0)
        elif cmd == 0x06 and on_tri:
            on_tri(st, tuple(((w0 >> s) & 0xFF) // 2 for s in (16, 8, 0)), here, 0)
            on_tri(st, tuple(((w1 >> s) & 0xFF) // 2 for s in (16, 8, 0)), here, 1)
        elif cmd == 0xDA:
            st["mtx"] = (w1 - 0x0D000000) // 0x40 if seg_of(w1) == 0xD else None
        elif cmd == 0xDE:
            run_dl(segs, w1, on_tri, st, depth + 1)
            if (w0 >> 16) & 0xFF == 1:                   # branch: no return
                return st
        elif cmd == 0xDF:
            return st
        elif cmd == 0xFD:
            st["timg"] = w1
        elif cmd in (0xF3, 0xF4):
            st["tex_src"] = st["timg"]
        elif cmd == 0xF0:
            st["tlut"] = st["timg"]
        elif cmd == 0xFC:
            st["combine"] = (w0, w1)
        elif cmd == 0xFA:
            st["prim"] = w1
        elif cmd == 0xFB:
            st["env"] = w1
        elif cmd == 0xD9:
            st["geo"] = (st["geo"] & (w0 & 0xFFFFFF | 0xFF000000)) | w1
        elif cmd == 0xD7:
            st["tex_on"] = bool(w0 & 0xFE)
            st["tscale"] = (w1 >> 16, w1 & 0xFFFF)
        elif cmd == 0xE3:
            ln = (w0 & 0xFF) + 1
            sh = 32 - ((w0 >> 8) & 0xFF) - ln
            if sh >= 0:                                  # (a data word that only looks like a list: ignored)
                mask = ((1 << ln) - 1) << sh
                st["omh"] = (st["omh"] & ~mask) | (w1 & mask)
        elif cmd == 0xF5 and (w1 >> 24) & 7 == 0:
            st["tile0"] = (w0, w1)
        elif cmd == 0xF2 and (w1 >> 24) & 7 == 0:
            st["size0"] = (w0, w1)
        o += 8
    return st


def material(st) -> tuple:
    """The material a triangle is drawn with: (texture key or None, prim, env, combiner, lighting). Texture key:
    (source address, fmt, siz, w, h, tlut address, tlut type, cms, cmt)."""
    tex = None
    if st["tex_on"] and st["tex_src"] is not None and st["tile0"] is not None:
        t0, t1 = st["tile0"]
        s0, s1 = st["size0"] or (0, 0)
        fmt, siz = (t0 >> 21) & 7, (t0 >> 19) & 3
        masks, maskt = (t1 >> 4) & 0xF, (t1 >> 14) & 0xF
        w = 1 << masks if masks else ((s1 >> 12) & 0xFFF) // 4 - ((s0 >> 12) & 0xFFF) // 4 + 1
        h = 1 << maskt if maskt else (s1 & 0xFFF) // 4 - (s0 & 0xFFF) // 4 + 1
        tlut = st["tlut"] if fmt == 2 else None
        tex = (st["tex_src"], fmt, siz, max(1, w), max(1, h), tlut, (st["omh"] >> 14) & 3, (t1 >> 8) & 3, (t1 >> 18) & 3)
    return (tex, st["prim"], st["env"], st["combine"], bool(st["geo"] & 0x20000))


def _rgba16(v):
    v = np.asarray(v, np.uint32)
    return np.stack([(v >> 11 & 31) * 255 // 31, (v >> 6 & 31) * 255 // 31, (v >> 1 & 31) * 255 // 31,
                     (v & 1) * 255], -1).astype(np.uint8)


def decode_tex(segs: dict, tex: tuple, hints: dict | None = None) -> np.ndarray | None:
    """N64 texture -> (h, w, 4) uint8. tex = material()[0]. hints {segment number: bytes} for textures the game sets per
    frame (Link's eyes / mouth on segments 8 / 9)."""
    addr, fmt, siz, w, h, tlut, tt = tex[:7]

    def read(a, n):
        seg = (a >> 24) & 0xF
        d = (hints or {}).get(seg, segs.get(seg))
        o = a & 0xFFFFFF
        if d is None or o + n > len(d):
            return None
        return d[o:o + n]
    bits = (4, 8, 16, 32)[siz]
    raw = read(addr, w * h * bits // 8)
    if raw is None:
        return None
    if bits == 4:
        a = np.frombuffer(raw, np.uint8)
        v = np.stack([a >> 4, a & 15], -1).reshape(-1)
    elif bits == 8:
        v = np.frombuffer(raw, np.uint8)
    elif bits == 16:
        v = np.frombuffer(raw, ">u2")
    else:
        return np.frombuffer(raw, np.uint8).reshape(h, w, 4).copy()
    if fmt == 2:                                         # CI: palette of 16 / 256 RGBA16 (or IA16) entries
        pal_raw = read(tlut, (16 if bits == 4 else 256) * 2) if tlut is not None else None
        if pal_raw is None:
            return None
        pal = np.frombuffer(pal_raw, ">u2")
        if tt == 3:
            pi = pal.astype(np.uint32)
            pal_c = np.stack([pi >> 8, pi >> 8, pi >> 8, pi & 255], -1).astype(np.uint8)
        else:
            pal_c = _rgba16(pal)
        out = pal_c[np.minimum(v, len(pal) - 1)]
    elif fmt == 0:
        out = _rgba16(v)
    elif fmt == 3:                                       # IA
        v = v.astype(np.uint32)
        if bits == 4:
            i, al = (v >> 1) * 255 // 7, (v & 1) * 255
        elif bits == 8:
            i, al = (v >> 4) * 17, (v & 15) * 17
        else:
            i, al = v >> 8, v & 255
        out = np.stack([i, i, i, al], -1).astype(np.uint8)
    else:                                                # I
        v = v.astype(np.uint32)
        i = v * 17 if bits == 4 else v
        out = np.stack([i, i, i, np.full_like(i, 255)], -1).astype(np.uint8)
    return out.reshape(h, w, 4)


# ---------------------------------------------------------------- object -> mesh (extraction)

def parents(skel: dict) -> list[int]:
    par = [-1] * len(skel["limbs"])
    for i, lb in enumerate(skel["limbs"]):
        c = lb["child"]
        while c != 0xFF:
            par[c] = i
            c = skel["limbs"][c]["sibling"]
    return par


def object_mesh(obj: bytes, skel: dict, W: list, segs: dict | None = None, hints: dict | None = None,
                dl_of=None, init: dict | None = None) -> dict:
    """Every limb's display list drawn in the pose W (world 4x4 per limb) -> {prims: [{pos, nrm, uv, tris, J, tex,
    color, wrap}], joints: limb world positions}. dl_of(limb index) -> the list to draw (default: the near LOD)."""
    segs = {6: obj, **(segs or {})}
    limbs = skel["limbs"]
    slots = [i for i in dfs(limbs) if limbs[i]["dls"][0]]
    groups, texcache = {}, {}
    for i, lb in enumerate(limbs):
        dl = dl_of(i) if dl_of else lb["dls"][0]
        if not dl:
            continue

        def on(st, ix, here, which, i=i):
            vs = [st["vb"][k] for k in ix]
            if None in vs:
                return
            mat = material(st)
            g = groups.setdefault(mat, {"pos": [], "nrm": [], "uv": [], "J": []})
            for p, (s, t), c, m, _va in vs:
                j = i if m is None or m >= len(slots) else slots[m]
                M = W[j]
                g["pos"].append((M @ np.r_[p, 1.0])[:3])
                g["nrm"].append(M[:3, :3] @ np.array(c[:3], np.uint8).view(np.int8).astype(float) if mat[4] else np.zeros(3))
                tx = mat[0]
                sc = st["tscale"]
                g["uv"].append((s * sc[0] / 65536 / 32 / tx[3], t * sc[1] / 65536 / 32 / tx[4]) if tx else (0.0, 0.0))
                g["J"].append(j)
        run_dl(segs, dl, on, init=init)
    prims = []
    for mat, g in groups.items():
        P, N = np.array(g["pos"]), np.array(g["nrm"])
        T = np.arange(len(P)).reshape(-1, 3)
        fn = np.cross(P[T[:, 1]] - P[T[:, 0]], P[T[:, 2]] - P[T[:, 0]])
        flat = np.repeat(fn, 3, 0)
        bad = np.linalg.norm(N, axis=1) < 1e-6
        N[bad] = flat[bad]
        N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-9)
        tex, wrap = None, (10497, 10497)
        uv = np.array(g["uv"], float)
        if mat[0]:
            key = mat[0]
            if key not in texcache:
                t = decode_tex(segs, key, hints)
                cms, cmt = key[7], key[8]
                if t is not None and cms & 1:            # mirrored: unfold into the image, then plain repeat
                    t = np.concatenate([t, t[:, ::-1]], 1)
                if t is not None and cmt & 1:
                    t = np.concatenate([t, t[::-1]], 0)
                texcache[key] = t
            tex = texcache[key]
            if tex is not None:
                cms, cmt = key[7], key[8]
                if cms & 1:
                    uv[:, 0] /= 2
                if cmt & 1:
                    uv[:, 1] /= 2
                wrap = (33071 if cms == 2 else 10497, 33071 if cmt == 2 else 10497)
        col = np.array([255, 255, 255, 255], float)
        if mat[3]:                                       # PRIM / ENV in the colour combiner: multiply them in
            w0, w1 = mat[3]
            used = [(w0 >> 20) & 0xF, (w0 >> 15) & 0x1F, (w0 >> 5) & 0xF, w0 & 0x1F,
                    (w1 >> 28) & 0xF, (w1 >> 24) & 0xF, (w1 >> 15) & 7, (w1 >> 6) & 7]
            for code, c in ((3, mat[1]), (5, mat[2])):
                if code in used:
                    col[:3] *= np.array([(c >> 24) & 255, (c >> 16) & 255, (c >> 8) & 255]) / 255
        prims.append({"pos": P, "nrm": N, "uv": uv, "tris": T, "J": np.array(g["J"]), "tex": tex,
                      "color": tuple(int(v) for v in col), "wrap": wrap})
    return {"prims": prims, "joints": np.array([w[:3, 3] for w in W])}


def write_gltf(mesh: dict, skel: dict, W: list, path, name: str, scale: float = 0.01):
    """object_mesh() output -> a skinned glTF (one joint per limb, named l00..; world units x scale)."""
    from pathlib import Path
    from .melee_models import write_gltf as wg
    par = parents(skel)
    joints = []
    for i in range(len(W)):
        m = np.eye(4)
        m[:3, 3] = W[i][:3, 3]
        joints.append({"parent": par[i], "world": m})
    prims = []
    for p in mesh["prims"]:
        Jv = np.zeros((len(p["pos"]), 4), np.int64)
        Jv[:, 0] = p["J"]
        Wv = np.zeros((len(p["pos"]), 4))
        Wv[:, 0] = 1
        prims.append({**p, "J": Jv, "W": Wv, "name": f"m{len(prims)}"})
    return wg(Path(path), joints, prims, scale, name, [f"l{i:02d}" for i in range(len(W))])


# ---------------------------------------------------------------- F3DEX2 display lists (writing)

def _w(*ws) -> bytes:
    return struct.pack(f">{len(ws)}I", *ws)


def combine(c0, a0, c1, a1) -> bytes:
    """gsDPSetCombineLERP: c0 / c1 = (a, b, c, d) colour codes, a0 / a1 = (a, b, c, d) alpha codes, per cycle."""
    (a, b, c, d), (aa, ab, ac, ad) = c0, a0
    (e, f, g, h), (ea, eb, ec, ed) = c1, a1
    w0 = 0xFC000000 | (a & 15) << 20 | (c & 31) << 15 | (aa & 7) << 12 | (ac & 7) << 9 | (e & 15) << 5 | (g & 31)
    w1 = (b & 15) << 28 | (f & 15) << 24 | (ea & 7) << 21 | (ec & 7) << 18 | (d & 7) << 15 | (ab & 7) << 12 | \
        (ad & 7) << 9 | (h & 7) << 6 | (eb & 7) << 3 | (ed & 7)
    return _w(w0, w1)


# colour codes: a 1 TEXEL0, 3 PRIM, 15 zero; c 0 COMBINED, 4 SHADE, 31 zero; d 0 COMBINED, 4 SHADE, 7 zero; alpha 6 = 1
CC_TEX = combine((1, 15, 4, 7), (7, 7, 7, 6), (3, 15, 0, 7), (7, 7, 7, 0))      # TEXEL0*SHADE, then PRIM*COMBINED
CC_FLAT = combine((15, 15, 31, 4), (7, 7, 7, 6), (3, 15, 0, 7), (7, 7, 7, 0))    # SHADE, then PRIM*COMBINED
GEO_DRAW, GEO_STD = 0x00230005, 0x00230405              # zbuffer shade fog lighting smooth (+ cull back = SetupDL 25)
RENDER_OPA = _w(0xE200001C, 0xC8112078)                 # G_RM_FOG_SHADE_A, G_RM_AA_ZB_OPA_SURF2 (Link's own)
GEO_UNLIT = 0x00210005                                  # zbuffer shade fog smooth: vertex colours, no lights, no culling
LIGHT = np.array([0.35, 0.85, 0.4]) / np.linalg.norm([0.35, 0.85, 0.4])
OTHERMODE_25 = _w(0xEF182C00, 0xC8112078)               # Gfx_SetupDL_25's othermode (2-cycle, bilerp, persp, fog + opa)
CC_SETUP_25 = None                                      # set below: G_CC_MODULATEIDECALA, G_CC_MODULATEIA_PRIM2
ENDDL, PIPESYNC = _w(0xDF000000, 0), _w(0xE7000000, 0)
CC_SETUP_25 = combine((1, 15, 4, 7), (7, 7, 7, 1), (0, 15, 3, 7), (0, 7, 3, 7))


def mtx(m: np.ndarray) -> bytes:
    """A column-vector 4x4 float matrix -> N64 Mtx (S15.16, row-vector layout: integer halves then fractions)."""
    f = np.asarray(m, float).T                           # row-vector convention: translation in row 3
    fx = [[int(round(f[i][j] * 65536)) & 0xFFFFFFFF for j in range(4)] for i in range(4)]
    ai, af = [], []
    for i in range(4):
        for j in range(2):
            e1, e2 = fx[i][2 * j], fx[i][2 * j + 1]
            ai.append((e1 & 0xFFFF0000) | ((e2 >> 16) & 0xFFFF))
            af.append(((e1 << 16) & 0xFFFF0000) | (e2 & 0xFFFF))
    return struct.pack(">16I", *ai, *af)


def encode(parts: dict, materials: list, base: int, lit: bool = True, regions=None) -> tuple:
    """parts {limb: [(material, ((pos, nrm, uv) x3))]} limb-local -> (blob placed at segmented address `base`,
    {limb: address of its display list}). materials: [{"color": (r, g, b), "tex": (h, w, 4) uint8 or None}].
    Textures RGBA16 (<= 2048 texels, power-of-two sides), lit by the scene's lights (vertex normals), double-sided.
    lit=False: no scene lights (room geometry, where no actor lights are set): the shading is baked into vertex colours
    from a fixed light, and the lists leave the geometry mode as Gfx_SetupDL_25 has it.
    regions: [(start, end)] segment addresses of free bytes inside the object to fill first (first fit); then the
    result is (tail blob at base, dls, {region start: bytes}) - the tail only holds what didn't fit."""
    from .sm64_writer import fit_tmem, rgba16, tex_load
    blob = bytearray()
    pieces = {a: bytearray() for a, _e in (regions or [])}

    def put(b: bytes, align=8) -> int:
        for a, e in regions or []:
            pc = pieces[a]
            pad = (-(a + len(pc))) % align
            if a + len(pc) + pad + len(b) <= e:
                pc.extend(bytes(pad))
                o = a + len(pc)
                pc.extend(b)
                return o
        blob.extend(bytes((-len(blob)) % align))
        o = len(blob)
        blob.extend(b)
        return base + o
    mats = []
    for m in materials:
        t = None
        if m.get("tex") is not None:
            img = fit_tmem(m["tex"])
            t = (put(rgba16(img)), img.shape[1], img.shape[0])
        mats.append(t)
    dls = {}
    for j, tris in sorted(parts.items()):
        out = [PIPESYNC, _w(0xD9000000, GEO_DRAW if lit else GEO_UNLIT), RENDER_OPA, _w(0xE3001001, 0)]
        by_mat = {}
        for mi, tri in tris:
            by_mat.setdefault(mi, []).append(tri)
        for mi, mtris in by_mat.items():
            tex = mats[mi]
            c = materials[mi].get("color", (255, 255, 255))
            out.append(PIPESYNC)
            if tex:
                out += [CC_TEX, _w(0xD7000002, 0xFFFFFFFF), tex_load(*tex)]
                tw, th = tex[1], tex[2]
            else:
                out += [CC_FLAT, _w(0xD7000000, 0)]
                tw = th = 32
            out.append(_w(0xFA000080, (int(c[0]) << 24) | (int(c[1]) << 16) | (int(c[2]) << 8) | 0xFF))
            batch, cache, pend = [], {}, []

            def flush():
                if not batch:
                    return
                va = put(b"".join(batch), 16)
                n = len(batch)
                out.append(_w(0x01000000 | (n << 12) | (n << 1), va))
                for k in range(0, len(pend) - 1, 2):
                    out.append(_w(0x06000000 | pend[k], pend[k + 1]))
                if len(pend) % 2:
                    out.append(_w(0x05000000 | pend[-1], 0))
                batch.clear(), cache.clear(), pend.clear()
            for tri in mtris:
                uv = np.array([v[2] for v in tri], float) if tex else np.zeros((3, 2))
                # keep s/t in S10.5 range; shift only triangles that need it, so neighbours share vertices
                off = np.floor(uv.min(0)) if np.abs(uv).max() * max(tw, th) > 900 else np.zeros(2)
                vs = []
                for (p, n, _), (u, v) in zip(tri, uv - off):
                    s = int(np.clip(round(u * tw * 32), -32768, 32767))
                    t = int(np.clip(round(v * th * 32), -32768, 32767))
                    if lit:
                        nn = np.clip(np.round(np.asarray(n, float) * 127), -128, 127).astype(np.int8).view(np.uint8)
                    else:
                        k = 0.5 + 0.5 * max(0.0, float(np.dot(n, LIGHT)))
                        nn = np.full(3, int(round(255 * min(1.0, k))), np.uint8)
                    pp = np.clip(np.round(p), -32768, 32767).astype(int)
                    vs.append(struct.pack(">hhhHhh4B", *pp, 0, s, t, *nn, 255))
                new = [v for v in dict.fromkeys(vs) if v not in cache]
                if len(cache) + len(new) > 32:
                    flush()
                for v in vs:
                    if v not in cache:
                        cache[v] = len(batch)
                        batch.append(v)
                i0, i1, i2 = (cache[v] * 2 for v in vs)
                pend.append((i0 << 16) | (i1 << 8) | i2)
            flush()
        out += [PIPESYNC, _w(0xD9000000, GEO_STD), _w(0xD7000000, 0) if lit else _w(0xD7000002, 0xFFFFFFFF), ENDDL]
        dls[j] = put(b"".join(out), 8)
    blob.extend(bytes((-len(blob)) % 16))
    if regions is not None:
        return bytes(blob), dls, {a: bytes(pc) for a, pc in pieces.items() if pc}
    return bytes(blob), dls


def patch_skeleton(obj: bytes, skel: dict, blob_fn, regions=None) -> tuple[bytes, dict, int]:
    """Put new model data into an object and point its limbs at it. blob_fn(base segment address, regions) ->
    (tail blob, {limb: dl}[, {region start: bytes}]): pieces go into the given free regions of the object first
    (oot_writer.reclaimable: the old model's own bytes), the rest is appended. Limbs that had a display list keep one
    (an empty list when the model has nothing there), so a flex skeleton's matrix count and the actor's body-part
    count stay the same; limbs without one stay without. -> (new object, {limb: dl}, address of the empty list)."""
    out = bytearray(obj)
    out.extend(bytes((-len(out)) % 16))
    r = blob_fn(0x06000000 + len(out), [(0x06000000 + x, 0x06000000 + y) for x, y in regions] if regions else None)
    blob, dls = r[0], r[1]
    for at, pc in (r[2] if len(r) > 2 else {}).items():
        o = at & 0xFFFFFF
        out[o:o + len(pc)] = pc
    out.extend(blob)
    empty = 0x06000000 + len(out)
    out.extend(ENDDL + bytes(8))
    final = {}
    for i, lb in enumerate(skel["limbs"]):
        if not any(lb["dls"]):
            continue
        d = dls.get(i, empty)
        final[i] = d
        for k in range(len(lb["dls"])):
            struct.pack_into(">I", out, lb["at"] + 8 + 4 * k, d)
    return bytes(out), final, empty


def strip_body(obj: bytearray, dl: int, body: set, segs: dict | None = None) -> tuple[int, int]:
    """In place: every triangle drawn with a body material (material() key in `body`) inside display list `dl` (and its
    sub-lists in the object) becomes a no-op. -> (body triangles removed, other triangles kept)."""
    hit, kept = {}, [0]

    def on(st, ix, here, which):
        if material(st) in body:
            hit.setdefault(here, set()).add(which)
        else:
            kept[0] += 1
    run_dl({**(segs or {}), 6: bytes(obj)}, dl, on)
    for here, which in hit.items():
        if here >> 24 != 6:
            continue
        o = here & 0xFFFFFF
        w0, w1 = struct.unpack_from(">II", obj, o)
        if w0 >> 24 == 0x05 or which == {0, 1}:
            struct.pack_into(">II", obj, o, 0, 0)
        elif which == {0}:                               # keep the second triangle as a G_TRI1
            struct.pack_into(">II", obj, o, 0x05000000 | (w1 & 0xFFFFFF), 0)
        else:
            struct.pack_into(">II", obj, o, 0x05000000 | (w0 & 0xFFFFFF), 0)
    return sum(len(w) for w in hit.values()), kept[0]


# ---------------------------------------------------------------- reusing the replaced model's own bytes

def _ranges(obj: bytes, dls, segs: dict | None = None) -> list[tuple[int, int]]:
    """Object offsets [start, end) of the commands and vertex arrays the given display lists use."""
    out = []
    for d in dls:
        if not d or d >> 24 != 6:
            continue
        st = run_dl({**(segs or {}), 6: obj}, d)
        out += [(a & 0xFFFFFF, (a & 0xFFFFFF) + 8) for a, _w0, _w1 in st["cmds"] if a >> 24 == 6]
        out += [(a & 0xFFFFFF, (a & 0xFFFFFF) + n) for a, n in st.get("vtx", []) if a >> 24 == 6]
    return out


def _merge(rs):
    out = []
    for a, b in sorted(rs):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def reclaimable(obj: bytes, body_dls, kept_dls, refs=(), segs: dict | None = None) -> list[tuple[int, int]]:
    """Byte ranges of an object that only the replaced body used: the body lists' commands + vertex arrays, minus
    anything a kept list (equipment, lists the actor's code names) uses, minus any range a code word points into.
    Textures are never reclaimed. -> [(start, end)], largest first, 16-byte aligned."""
    body = _merge(_ranges(obj, body_dls, segs))
    kept = _merge(_ranges(obj, kept_dls, segs))
    free = []
    for a, b in body:
        cur = [(a, b)]
        for ka, kb in kept:
            nxt = []
            for x, y in cur:
                if kb <= x or ka >= y:
                    nxt.append((x, y))
                else:
                    if ka > x:
                        nxt.append((x, ka))
                    if kb < y:
                        nxt.append((kb, y))
            cur = nxt
        free += cur
    refs = sorted(r & 0xFFFFFF for r in refs if r >> 24 == 6)
    out = []
    for a, b in _merge(free):
        a, b = (a + 15) & ~15, b & ~15
        if b - a >= 0x100 and not any(a <= r < b for r in refs):
            out.append((a, b))
    return sorted(out, key=lambda r: r[0] - r[1])


def seg6_words(data: bytes) -> set[int]:
    """Every aligned word of a file that looks like a segment-6 address (code / overlay references into an object)."""
    a = np.frombuffer(data[:len(data) // 4 * 4], ">u4")
    return set(int(x) for x in a[(a >> 24) == 6])


def _selftest(path: str) -> None:
    from .sm64_swap import rom_bytes
    rom = Rom(rom_bytes(path))
    print(rom.version, len(rom.dma), "files; gObjectTable at code+" + hex(rom.obj_table))
    assert crc6105(rom.data) == struct.unpack_from(">II", rom.data, 0x10), "CRC algorithm"
    boy = rom.object(OBJECT_LINK_BOY)
    print("object_link_boy", hex(len(boy)), "child", hex(len(rom.object(OBJECT_LINK_CHILD))))


if __name__ == "__main__":
    import sys
    _selftest(sys.argv[1])
