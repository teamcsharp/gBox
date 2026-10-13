"""Yuke's PS1 wrestling engine (WWF SmackDown! 2: Know Your Role; SmackDown! 1 shares the containers): identify and
extract the wrestlers into the character collection, and write any rigged collection character in a wrestler's
place as a modded disc image (characters op=use / op=match / op=extract route here).

Formats (worked out from the operator's disc and the running game; see docs/model_swaps.md section 10):
  * DPAC (ED1H.PAC heads, ED1B.PAC bodies, ED1L.PAC legs, EXE.PAC overlays ...): "DPAC", u32 table bytes + 8, u32 data
    bytes (file size - 0x4000), u32 7; at 0x800 the table {tag, u16 count, u16 flags, ...} then {u16 id, u16 size in
    0x100-byte units}; entries start at 0x4000, each 0x800-aligned. ED1* ids = BCD(roster id) << 4 | costume.
  * PAC (one DPAC entry): "PAC ", u32 n, n x {u16 type, u24 offset, u24 size} (offsets from the end of the table,
    4-aligned). A body-part entry = type 0 EMD model + type 0x0A texture PAC (n x BPE-packed TIM).
  * BPE: "BPE ", u32 0x100, u32 packed size, u32 size; then Philip Gage's byte-pair blocks (pair table, u16 LE block
    size, data). Writer here: the same algorithm (gbox.yukes_sd.bpe_encode).
  * TIM: standard PS1 TIM, 8 bpp with a 256-colour CLUT. One CLUT row per part file (heads 256, legs 257, bodies 258,
    x 768); head TIMs fill VRAM x 320..383, legs 384..447, bodies 448..511 (the game relocates them per slot).
  * EMD: "EMD ", u16 0x10, u16 32 (bones), u16 0x110, u16 words after 0x110, u16 slots (8), u16 descriptors; 32 bone
    records {s16 offset x, y, z (in the parent's frame), u8 axis mask, u8 depth}; 8 slots {u16 first descriptor, u16
    variants} (head expressions, hand poses: the game picks one variant per slot); descriptors {u16 word offset, u16
    words, u16 1 (rigid), u16 3 * vertices + groups + 1}; then the chunks: {u16 clut, u16 tpage}, vertex groups
    {u8 n, u8 bone, u8 last, u8 0} + n x {s16 x, y, z, nx, ny, nz (4.12)} in the bone's frame, then primitive blocks
    {u8 n, u8 last, u8 0, u8 code (0x34 GT3 / 0x3C GT4)} + n x 12 bytes (GT3: 3 u8 indices, pad, 3 u8 uv pairs, pad;
    GT4: u32 of four 7-bit indices, 4 uv pairs). A chunk holds at most 128 vertices (the scratchpad transform buffer).
    Triangles are culled with NCLIP: (v0, v1, v2) runs clockwise seen from outside (game space: +Y down, front = -Z).
  * The skeleton (31 bones, the same for every wrestler): parent = PARENT; the game composes each bone's world matrix
    by FK (offsets above) and draws every vertex group with its bone's camera matrix (GTE). REST = the world matrices
    of a standing wrestler, read from the game's skeleton array during a match (Ghidra on a RAM image: 0x80062c80
    builds the camera matrices from the world ones, 0x80061868 draws a rigid chunk).
"""
from __future__ import annotations

import json
import re
import shutil
import struct
import time
from collections import Counter
from pathlib import Path

import numpy as np
from .formats.texture import tim_build, tim_parse  # noqa: F401  (shared, moved to gbox.formats)

GAME_IDS = {"276334ad218ffb46": "WWF SmackDown! 2 - Know Your Role (USA)"}
SD1_IDS = {"4e59d0d55cc190cb": "WWF SmackDown! (USA)"}      # same containers (D/C/EH/EB/EL.PAC); reader only, see docs
PART_FILES = ("ED1H.PAC", "ED1B.PAC", "ED1L.PAC")

PARENT = [-1, 0, 1, 2, 3, 2, 5, 5, 6, 6, 6, 8, 2, 12, 12, 13, 13, 13, 15, 0, 0, 19, 19, 21, 23, 0, 0, 25, 25, 27, 29]
# bone -> body role (collection rig roles); 0 pelvis, 1 waist, 2 chest, 3 neck, 4 head, 5/12 clavicles, 6.. left arm
# (upper 6, fore 8, hand 11; 7/9/10 twist helpers), 13.. right arm, 19.. left leg (thigh 19, shin 21, foot 23, toe 24)
ROLE_BONE = {"hip": 0, "chest": 2, "neck": 3, "head": 4, "l_upper": 6, "l_fore": 8, "l_hand": 11, "r_upper": 13,
             "r_fore": 15, "r_hand": 18, "l_thigh": 19, "l_shin": 21, "l_foot": 23, "r_thigh": 25, "r_shin": 27,
             "r_foot": 29}
# world matrices of a standing wrestler (The Rock, scale 1): 9 x s16 (4.12) rows, then TRZ, TRX, TRY (game units)
REST = [
    (100, -4084, -317, 4044, 147, -635, 643, -297, 4034, 0, -5, -940),
    (-161, 4094, -66, -4074, -165, -408, -407, 49, 4073, -29, -10, -1120),
    (-121, 4084, -269, -4072, -145, -438, -445, 252, 4059, -48, -18, -1302),
    (-162, 4082, -272, -4067, -188, -476, -486, 247, 4054, -47, -27, -1543),
    (216, 3206, 2533, -4049, -193, 598, 586, -2538, 3153, -58, -31, -1634),
    (4055, 21, -568, -78, 4074, -434, 559, 438, 4028, -74, -26, -1540),
    (2057, -3188, 1536, 3414, 1310, -1846, 937, 2206, 3309, -43, 199, -1545),
    (3516, -2099, -19, 1916, 3218, -1657, 859, 1412, 3740, -43, 199, -1545),
    (294, -2281, 3386, 3685, 1613, 768, -1764, 2987, 2157, 19, 336, -1318),
    (1281, -3013, 2457, 3865, 1279, -443, -449, 2455, 3233, 19, 336, -1318),
    (294, -2767, 3002, 3685, 1478, 1003, -1764, 2626, 2583, 19, 336, -1318),
    (526, -2297, 3347, 3989, 923, 7, -766, 3255, 2345, -104, 356, -1062),
    (-4088, -183, 174, 158, -4069, -458, 196, -449, 4061, -74, -26, -1540),
    (-1442, -3166, -2155, 3777, -787, -1378, 652, -2471, 3192, -64, -254, -1532),
    (-3312, -2346, -550, 2353, -2962, -1575, 506, -1586, 3735, -64, -254, -1532),
    (224, -3488, -2129, 3807, -605, 1384, -1490, -2055, 3206, -21, -351, -1281),
    (-648, -3249, -2403, 4020, -789, -24, -442, -2362, 3309, -21, -351, -1281),
    (224, -3333, -2364, 3807, -699, 1339, -1490, -2271, 3056, -21, -351, -1281),
    (512, -3344, -2304, 4056, 283, 483, -233, -2342, 3344, -125, -336, -1017),
    (816, -3729, -1486, 3980, 553, 787, -518, -1602, 3733, 7, 96, -944),
    (465, -3960, -949, 4069, 464, 42, 65, -945, 3983, 7, 96, -944),
    (316, -3729, -1666, 4027, 553, -482, 661, -1602, 3709, -44, 175, -557),
    (572, -3729, -1596, 4053, 553, 152, 74, -1602, 3767, -44, 175, -557),
    (13, -3742, -1667, 4076, 156, -327, 358, -1659, 3725, 25, 208, -132),
    (13, -3742, -1667, 4076, 156, -327, 358, -1659, 3725, -100, 265, -67),
    (-323, -4083, 66, 4029, -312, 661, -658, 115, 4038, -8, -107, -937),
    (-112, -4095, -112, 4094, -115, 0, -6, -111, 4094, -8, -107, -937),
    (-293, -4083, 151, 4056, -312, -462, 467, 115, 4064, -73, -139, -545),
    (-311, -4083, 109, 4081, -312, 100, -97, 115, 4089, -73, -139, -545),
    (-396, -4075, 145, 4053, -412, -407, 413, 103, 4070, -24, -170, -117),
    (-396, -4075, 145, 4053, -412, -407, 413, 103, 4070, -160, -181, -50),
]
G = np.diag([1.0, -1.0, -1.0])      # game space (+Y down, front -Z) <-> glTF space (+Y up, front +Z, left = +X)
GLTF_SCALE = 0.001                  # game units -> metres in the collection (a wrestler is ~1.9 m)

# chunk slots by the bones their original chunk uses -> the new model's bones that go there
SLOT_BONES = {"head": [3, 4], "torso": [1, 2], "larm": [6, 8], "lhand": [11], "rarm": [13, 15], "rhand": [18],
              "lleg": [19, 21, 23], "rleg": [0, 25, 27, 29]}
# (vertices, faces) per bone part: the faces weigh each slot's share of its part file's EMD room (slot_budgets)
CAPS = {4: (84, 120), 3: (12, 12), 2: (48, 64), 1: (22, 24), 6: (24, 30), 8: (24, 30), 11: (36, 36), 13: (24, 30),
        15: (24, 30), 18: (36, 36), 0: (30, 40), 19: (26, 32), 21: (24, 28), 23: (24, 28), 25: (26, 32), 27: (24, 28),
        29: (24, 28)}
FILE_SLOTS = {"ED1H.PAC": ("head",), "ED1B.PAC": ("torso", "larm", "lhand", "rarm", "rhand"), "ED1L.PAC": ("lleg", "rleg")}
SLOT_OF = {b: s for s, bs in SLOT_BONES.items() for b in bs}
VERTS_PER_FACE = 0.62      # welded slot meshes (no seam copies: uvs live on the primitives): ~0.5 closed, ~0.7 open
FIT_VERSION = 2            # bump when the writer's output changes: older mods (.gbox-mod.json "fit") are rebuilt


# ---------------------------------------------------------------- BPE (Yuke's: Gage's byte-pair encoding, LE sizes)

def bpe_decode(d: bytes) -> bytes:
    if d[:4] != b"BPE ":
        raise ValueError("not BPE")
    _v, csz, usz = struct.unpack_from("<III", d, 4)
    src, p, out = d[16:16 + csz], 0, bytearray()
    while p < len(src) and len(out) < usz:
        left, right, c = list(range(256)), [0] * 256, 0
        while True:
            count = src[p]; p += 1
            if count > 127:
                c += count - 127
                count = 0
            if c == 256:
                break
            for _ in range(count + 1):
                left[c] = src[p]; p += 1
                if left[c] != c:
                    right[c] = src[p]; p += 1
                c += 1
            if c == 256:
                break
        size = src[p] | src[p + 1] << 8
        p += 2
        stack, n = [], 0
        while n < size or stack:
            if stack:
                x = stack.pop()
            else:
                x = src[p]; p += 1; n += 1
            if x == left[x]:
                out.append(x)
            else:
                stack.append(right[x]); stack.append(left[x])
    return bytes(out[:usz])


BPE_DEPTH = 8          # max pair nesting: the game's decoder expands pairs on a small stack (deeper corrupts RAM)


def _bpe_block(buf: bytes) -> bytes:
    left, right, depth = list(range(256)), [0] * 256, [0] * 256
    taken = set(buf)                                       # codes that occur in the data (or are pairs) stay taken
    while True:
        free = [c for c in range(256) if c not in taken]
        if not free or len(buf) < 4:
            break
        best = None
        for (a, b), n in Counter(zip(buf, buf[1:])).most_common(64):
            if n < 4:
                break
            if max(depth[a], depth[b]) + 1 <= BPE_DEPTH:
                best = (a, b)
                break
        if best is None:
            break
        a, b = best
        c = free[0]
        buf = buf.replace(bytes((a, b)), bytes((c,)))
        left[c], right[c] = a, b
        depth[c] = max(depth[a], depth[b]) + 1
        taken.add(c)
    out = bytearray()
    c = 0
    while c < 256:                                         # Gage's pair-table writer
        if c == left[c]:
            ln = 1
            c += 1
            while ln < 127 and c < 256 and c == left[c]:
                ln += 1
                c += 1
            out.append(ln + 127)
            ln = 0
            if c == 256:
                break
        else:
            ln = 0
            c += 1
            while (ln < 127 and c < 256 and c != left[c]) or (ln < 125 and c < 254 and c + 1 != left[c + 1]):
                ln += 1
                c += 1
            out.append(ln)
            c -= ln + 1
        for _ in range(ln + 1):
            out.append(left[c])
            if c != left[c]:
                out.append(right[c])
            c += 1
    out += struct.pack("<H", len(buf)) + buf
    return bytes(out)


def bpe_encode(data: bytes, block: int = 5000, max_chars: int = 200) -> bytes:
    """Gage's blocking: a block ends at `block` bytes or before its `max_chars + 1`th distinct byte value (so enough
    codes stay free for pairs)."""
    blocks, i = [], 0
    while i < len(data):
        seen, j = set(), i
        while j < len(data) and j - i < block:
            if data[j] not in seen and len(seen) >= max_chars:
                break
            seen.add(data[j])
            j += 1
        blocks.append(data[i:j])
        i = j
    body = b"".join(_bpe_block(b) for b in blocks)
    return b"BPE " + struct.pack("<III", 0x100, len(body), len(data)) + body


# ---------------------------------------------------------------- containers

def dpac_entries(b: bytes) -> list[tuple[int, int, int]]:
    """-> [(id, size in 0x100-byte units, offset)] for the used entries."""
    if b[:4] != b"DPAC":
        raise ValueError("not a DPAC")
    n, flags = struct.unpack_from("<HH", b, 0x804)
    first = 0x808 if flags & 0x80 else 0x810
    out, o = [], 0x4000
    for i in range(n):
        eid, units = struct.unpack_from("<HH", b, first + 4 * i)
        if not units:
            continue
        out.append((eid, units, o))
        o = (o + units * 0x100 + 0x7FF) & ~0x7FF
    return out


def pac_parse(b: bytes, o: int = 0) -> list[tuple[int, bytes]]:
    if b[o:o + 4] != b"PAC ":
        raise ValueError("not a PAC")
    n = struct.unpack_from("<I", b, o + 4)[0]
    base = o + 8 + 8 * n
    out = []
    for i in range(n):
        e = b[o + 8 + 8 * i:o + 16 + 8 * i]
        t, off, sz = e[0] | e[1] << 8, int.from_bytes(e[2:5], "little"), int.from_bytes(e[5:8], "little")
        out.append((t, b[base + off:base + off + sz]))
    return out


def pac_build(items: list[tuple[int, bytes]]) -> bytes:
    head, body = bytearray(b"PAC " + struct.pack("<I", len(items))), bytearray()
    for t, d in items:
        body += bytes((-len(body)) % 4)
        head += struct.pack("<H", t) + len(body).to_bytes(3, "little") + len(d).to_bytes(3, "little")
        body += d
    return bytes(head + body)


def repaintable(tim: dict) -> bool:
    """True for an 8-bpp TIM with one 256-colour CLUT, which build_entry repaints. It keeps every other TIM as it is:
    4-bpp detail pages (16-colour CLUTs on rows 253-255/257 of 30 wrestlers' legs) and CLUT-less 16-bpp pages."""
    c = tim.get("clut_xy")
    return tim.get("bpp") == 1 and c is not None and c[2] * c[3] == 256


def rgba5551(c: np.ndarray) -> np.ndarray:
    c = np.asarray(c, np.uint16)
    rgb = np.stack([(c & 31), (c >> 5) & 31, (c >> 10) & 31], -1).astype(np.uint16) * 255 // 31
    a = np.where(c == 0, 0, 255)
    return np.concatenate([rgb, a[..., None]], -1).astype(np.uint8)


def to5551(rgb: np.ndarray) -> np.ndarray:
    c = np.asarray(rgb, np.uint16)[..., :3] >> 3
    v = c[..., 0] | (c[..., 1] << 5) | (c[..., 2] << 10)
    return np.where(v == 0, 0x0421, v).astype(np.uint16)  # 0 is the transparent colour


# ---------------------------------------------------------------- EMD

def emd_parse(e: bytes) -> dict:
    if e[:4] != b"EMD ":
        raise ValueError("not an EMD")
    hs, nb, aoff, words, na, nd = struct.unpack_from("<6H", e, 4)
    bones = [struct.unpack_from("<hhhBB", e, hs + 8 * i) for i in range(nb)]
    slots = [struct.unpack_from("<HH", e, aoff + 4 * i) for i in range(na)]
    doff = aoff + 4 * na
    desc = [struct.unpack_from("<4H", e, doff + 8 * i) for i in range(nd)]
    data = doff + 8 * nd
    chunks = [chunk_parse(e[data + 4 * d[0]:data + 4 * (d[0] + d[1])]) if d[1] else None for d in desc]
    return {"bones": bones, "slots": slots, "desc": desc, "chunks": chunks, "raw": e, "hs": hs, "aoff": aoff}


def chunk_parse(c: bytes) -> dict:
    clut, tpage = struct.unpack_from("<HH", c, 0)
    p, groups, prims = 4, [], []
    while True:
        n, bone, last, _z = c[p:p + 4]
        p += 4
        groups.append((bone, [struct.unpack_from("<6h", c, p + 12 * i) for i in range(n)]))
        p += 12 * n
        if last:
            break
    while p < len(c):
        n, last, _z, code = c[p:p + 4]
        p += 4
        for _ in range(n):
            r = c[p:p + 12]
            p += 12
            if code & 0x08:
                w = struct.unpack_from("<I", r)[0]
                prims.append(([(w >> s) & 0x7F for s in (0, 7, 14, 21)], [(r[4 + 2 * k], r[5 + 2 * k]) for k in range(4)]))
            else:
                prims.append((list(r[:3]), [(r[4 + 2 * k], r[5 + 2 * k]) for k in range(3)]))
        if last:
            break
    return {"clut": clut, "tpage": tpage, "groups": groups, "prims": prims}


def chunk_build(clut: int, tpage: int, groups: list, tris: list, keep_empty: bool = False) -> tuple[bytes, int]:
    """groups [(bone, [(x, y, z, nx, ny, nz)])] (vertex index = position across groups), tris [((i0, i1, i2),
    ((u, v) x 3))] already in the game's winding. -> (chunk bytes, descriptor work size)."""
    out = bytearray(struct.pack("<HH", clut, tpage))
    groups = [g for g in groups if g[1] or keep_empty]
    nv = sum(len(v) for _b, v in groups)
    if nv > 128:
        raise ValueError(f"chunk has {nv} vertices (max 128)")
    for k, (bone, vs) in enumerate(groups):
        out += bytes((len(vs), bone, int(k == len(groups) - 1), 0))
        for v in vs:
            out += struct.pack("<6h", *[int(np.clip(round(x), -32768, 32767)) for x in v])
    blocks = [tris[i:i + 255] for i in range(0, len(tris), 255)] or [[]]
    for k, blk in enumerate(blocks):
        out += bytes((len(blk), int(k == len(blocks) - 1), 0, 0x34))
        for idx, uv in blk:
            out += bytes((idx[0], idx[1], idx[2], 0)) + bytes(int(np.clip(round(x), 0, 255)) for u in uv for x in u) + b"\0\0"
    return bytes(out), 3 * nv + len(groups) + 1


def emd_build(src: dict, new_chunks: dict[int, tuple[bytes, int]]) -> bytes:
    """The original EMD's header, bones and slots; descriptors -> the new chunks (same index; others empty)."""
    e = src["raw"]
    head = bytearray(e[:src["aoff"] + 4 * len(src["slots"])])
    desc, data = bytearray(), bytearray()
    for i in range(len(src["desc"])):
        if i in new_chunks:
            c, work = new_chunks[i]
            c = c + bytes((-len(c)) % 4)
            desc += struct.pack("<4H", len(data) // 4, len(c) // 4, 1, work)
            data += c
        else:
            desc += bytes(8)
    out = head + desc + data
    struct.pack_into("<H", out, 10, (len(out) - src["aoff"]) // 4)
    return bytes(out)


def chunk_slot(ch: dict) -> str:
    bones = {b for b, v in ch["groups"] if v}
    for slot, key in (("head", 4), ("lhand", 11), ("rhand", 18), ("larm", 6), ("rarm", 13), ("rleg", 25), ("lleg", 21)):
        if key in bones:
            return slot
    if 19 in bones:
        return "lleg"
    return "torso"


# ---------------------------------------------------------------- skeleton

def _rest_mats():
    W = []
    for r in REST:
        m = np.array(r[:9], float).reshape(3, 3) / 4096
        u, _s, vt = np.linalg.svd(m)                       # orthonormalize (4.12 rounding)
        W.append((u @ vt, np.array([r[10], r[11], r[9]], float)))
    return W


def rest_world(bones: list | None = None) -> list[tuple[np.ndarray, np.ndarray]]:
    """World (rotation, position) per bone in game space for a bone table (offsets), with the standing pose's
    local rotations (REST); default = REST itself (The Rock's table)."""
    W0 = _rest_mats()
    if bones is None:
        return W0
    out = [W0[0]]
    for k in range(1, 31):
        p = PARENT[k]
        L = W0[p][0].T @ W0[k][0]
        R = out[p][0] @ L
        t = out[p][1] + out[p][0] @ np.array(bones[k][:3], float)
        out.append((R, t))
    return out


# ---------------------------------------------------------------- disc

def base_bin(cfg, game: dict, progress=lambda p, m: None) -> Path:
    """One vanilla raw image per game on this node (cache/modbase/<game_id>/<rom stem>.bin)."""
    from . import filemods, psxdisc
    from .models import CatalogEntry
    from .tools import rom_path
    rom = rom_path(CatalogEntry.model_validate(game), cfg)
    out = filemods.base_dir(cfg, game["game_id"]) / (rom.stem + ".bin")
    if not out.exists():
        progress(3, f"Unpacking {rom.name} to a raw image (once per game)")
        tmp = out.with_name(out.stem + ".part.bin")
        psxdisc.chd_to_bin(rom, tmp) if rom.suffix.lower() == ".chd" else shutil.copyfile(rom, tmp)
        tmp.replace(out)
        tmp.with_suffix(".cue").unlink(missing_ok=True)
    return out


def read_files(bin_path: Path, names=PART_FILES) -> dict[str, bytes]:
    from .psxdisc import RawBin
    rb = RawBin(bin_path, writable=False)
    try:
        return {n: rb.read(n) for n in names}
    finally:
        rb.close()


def roster(bin_path: Path | None = None, exe: bytes | None = None) -> list[dict]:
    """The game's roster {id, name, special} from the first EXE.PAC overlay (12-byte records: u32 id, name pointer,
    special-move pointer); id = the ED1* model group."""
    if exe is None:
        exe = read_files(bin_path, ("EXE.PAC",))["EXE.PAC"]
    eid, units, o = dpac_entries(exe)[0]
    ov = bpe_decode(exe[o:o + units * 0x100])
    t_addr = struct.unpack_from("<I", ov, 0x18)[0]

    def s(a):
        k = a - t_addr + 0x800
        return ov[k:ov.index(b"\0", k)].decode("latin-1").strip() if 0x800 <= k < len(ov) else ""
    ok = lambda i, n, m: i < 256 and t_addr <= n < t_addr + len(ov) and t_addr <= m < t_addr + len(ov)
    key = struct.pack("<I", t_addr + ov.index(b"The Rock\0") - 0x800)
    o = ov.index(key) - 4
    while ok(*struct.unpack_from("<III", ov, o - 12)):
        o -= 12
    out = []
    while ok(*struct.unpack_from("<III", ov, o)):
        i, n, m = struct.unpack_from("<III", ov, o)
        if i < 200 and s(n):
            out.append({"id": i, "name": s(n), "special": s(m)})
        o += 12
    return out


SD_ALIASES = {"Stone Cold": ["Steve Austin", "Stone Cold Steve Austin", "Austin"], "The Rock": ["Rock", "Dwayne Johnson"],
              "The Undertaker": ["Undertaker", "Taker"], "Triple H": ["HHH"], "Scotty Too Hotty": ["Scotty 2 Hotty"],
              "Rikishi": ["Rikishi Fatu"]}


def slug_of(name: str) -> str:
    return "sd2_" + re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def find_wrestler(ros: list[dict], query: str) -> dict:
    from .characters import best_match
    q = str(query).strip()
    if q.isdigit():
        hit = next((w for w in ros if w["id"] == int(q)), None)
        if hit:
            return hit
    cands = [{"name": w["name"], "aliases": SD_ALIASES.get(w["name"], []), "slug": slug_of(w["name"]), "id": w["id"]} for w in ros]
    hit = best_match(cands, q)
    if not hit:
        raise LookupError(f"no SmackDown! 2 wrestler matches {query!r}")
    return next(w for w in ros if w["id"] == hit["id"])


# ---------------------------------------------------------------- extraction (original wrestler -> rigged glTF)

def _vram(entries: list[list[dict]]) -> np.ndarray:
    v = np.zeros((512, 1024), np.uint16)
    for tims in entries:
        for t in tims:
            px, py, pw, ph = t["rect"]
            v[py:py + ph, px:px + pw] = t["pix"].reshape(ph, pw * 2).view("<u2").reshape(ph, pw)
            cx, cy, cw, ch = t["clut_xy"]
            v[cy:cy + ch, cx:cx + cw] = t["clut"].reshape(ch, cw)
    return v


def _page(v: np.ndarray, tpage: int, clut: int) -> np.ndarray:
    tx, ty = (tpage & 0xF) * 64, ((tpage >> 4) & 1) * 256
    units = v[ty:ty + 256, tx:tx + 128]
    idx = np.stack([units & 0xFF, units >> 8], -1).reshape(256, 256)
    cx, cy = (clut & 0x3F) * 16, clut >> 6
    return rgba5551(v[cy, cx:cx + 256])[idx]


def bcd(roster_id: int) -> int:
    """ED1* entry ids are BCD: roster id 46 -> group 0x46 (entry ids 0x460..0x463)."""
    return int(str(int(roster_id)), 16)


def entry_parts(files: dict[str, bytes], group: int, costume: int = 0) -> dict:
    """{file: {"emd": parsed, "tims": [...], "id": id}} for one wrestler costume (falls back to costume 0 / any)."""
    out = {}
    for f in PART_FILES:
        ents = [e for e in dpac_entries(files[f]) if e[0] >> 4 == bcd(group)]
        if not ents:
            raise LookupError(f"{f}: no model group {group}")
        eid, units, o = next((e for e in ents if e[0] & 15 == costume), ents[0])
        items = pac_parse(files[f], o)
        emd = emd_parse(next(d for t, d in items if t == 0))
        tims = [tim_parse(bpe_decode(d) if d[:4] == b"BPE " else d) for t, d in pac_parse(next(d for t, d in items if t == 0x0A))]
        out[f] = {"emd": emd, "tims": tims, "id": eid}
    return out


def assemble(parts: dict) -> dict:
    """A costume's three part files in the standing pose -> {prims for melee write_gltf, joints, ground, head_h}."""
    emd0 = parts["ED1B.PAC"]["emd"]
    W = rest_world(emd0["bones"])
    v = _vram([p["tims"] for p in parts.values()])
    prims, pages = [], {}
    for f, p in parts.items():
        emd = p["emd"]
        for (st, cnt) in emd["slots"]:
            if not cnt or st >= len(emd["chunks"]):
                continue
            ch = emd["chunks"][st]                         # the first variant of each slot (neutral face, open hand)
            if ch is None:
                continue
            P, N, J = [], [], []
            for bone, vs in ch["groups"]:
                R, t = W[bone]
                for x in vs:
                    P.append(R @ np.array(x[:3], float) + t)
                    N.append(R @ (np.array(x[3:], float) / 4096))
                    J.append(bone)
            P, N, J = np.array(P), np.array(N), np.array(J)
            key = (ch["tpage"], ch["clut"])
            if key not in pages:
                pages[key] = _page(v, *key)
            tris, uvs, pos, nrm, jj = [], [], [], [], []
            for idx, uv in ch["prims"]:
                faces = [(0, 1, 2)] if len(idx) == 3 else [(0, 1, 2), (1, 3, 2)]
                for a, b, c in faces:
                    for k in (a, c, b):                    # game winding -> glTF counter-clockwise
                        pos.append(P[idx[k]]); nrm.append(N[idx[k]]); jj.append(J[idx[k]])
                        uvs.append(((uv[k][0] + 0.5) / 256, (uv[k][1] + 0.5) / 256))
            if not pos:
                continue
            n = len(pos)
            Jm = np.zeros((n, 4), np.uint16)
            Jm[:, 0] = jj
            Wm = np.zeros((n, 4), np.float32)
            Wm[:, 0] = 1
            nr = np.array(nrm) @ G.T
            nr /= np.maximum(np.linalg.norm(nr, axis=1, keepdims=True), 1e-9)
            prims.append({"pos": (np.array(pos) @ G.T) * GLTF_SCALE, "nrm": nr, "uv": np.array(uvs),
                          "tris": np.arange(n).reshape(-1, 3), "J": Jm, "W": Wm, "tex": pages[key],
                          "color": (255, 255, 255, 255), "wrap": (0, 0)})
    joints = []
    for k in range(31):
        w = np.eye(4)
        w[:3, 3] = (G @ W[k][1]) * GLTF_SCALE
        joints.append({"parent": PARENT[k], "world": w})
    return {"prims": prims, "joints": joints}


JOINT_NAMES = [f"b{k:02d}" for k in range(31)]


def extract(files: dict[str, bytes], group: int, out: Path, name: str, costume: int = 0) -> dict:
    from .melee_models import write_gltf
    a = assemble(entry_parts(files, group, costume))
    write_gltf(Path(out), a["joints"], a["prims"], 1.0, name, JOINT_NAMES)
    return {"roles": {r: JOINT_NAMES[b] for r, b in ROLE_BONE.items()}, "triangles": sum(len(p["tris"]) for p in a["prims"])}


# ---------------------------------------------------------------- writer (collection character -> wrestler)

def _cover_rect(tims: list[dict], tpage: int) -> tuple[int, int, int, int]:
    """Largest rectangle (page texels: u0, v0, w, h) fully covered by a part file's TIMs."""
    tx = (tpage & 0xF) * 64
    cov = np.zeros((256, 256), bool)
    for t in tims:
        px, py, pw, ph = t["rect"]
        u0 = (px - tx) * 2
        if 0 <= u0 < 256:
            cov[py % 256:py % 256 + ph, u0:u0 + pw * 2] = True
    xs = sorted({0, 256} | {(t["rect"][0] - tx) * 2 for t in tims} | {(t["rect"][0] - tx + t["rect"][2]) * 2 for t in tims})
    ys = sorted({0, 256} | {t["rect"][1] % 256 for t in tims} | {t["rect"][1] % 256 + t["rect"][3] for t in tims})
    best = (0, 0, 0, 0)
    for i, x0 in enumerate(xs):
        for x1 in xs[i + 1:]:
            for j, y0 in enumerate(ys):
                for y1 in ys[j + 1:]:
                    a = (x1 - x0) * (y1 - y0)
                    if a > best[2] * best[3] and 0 <= x0 and x1 <= 256 and cov[y0:y1, x0:x1].all():
                        best = (x0, y0, x1 - x0, y1 - y0)
    return best


def target_skeleton(bones: list) -> dict:
    """tgt for sm64_swap.retarget: the standing pose's joint positions in glTF space (game units)."""
    W = rest_world(bones)
    T = np.array([G @ w[1] for w in W])
    Ws = []
    for t in T:
        m = np.eye(4)
        m[3, :3] = t
        Ws.append(m)
    return {"T": T, "W": Ws, "parent": PARENT, "ground": float(min(T[24][1], T[30][1]) - 70), "head_h": 270.0,
            "joints": 31}


def _first_chunks(emd: dict):
    firsts = {st for st, cnt in emd["slots"] if cnt}
    for i, ch in enumerate(emd["chunks"]):
        if ch is not None and i in firsts:
            yield i, ch


def slot_allowed(tmpl: dict) -> dict[str, set]:
    """Bones each slot's chunk may bind vertices to: the template chunk's own vertex groups (the stock arm chunk also
    carries the chest/clavicle groups, the right leg chunk the pelvis and the left thigh: that is how the game stitches
    the parts) plus the slot's own bones."""
    allowed = {s: set(bs) for s, bs in SLOT_BONES.items()}
    for f in PART_FILES:
        for _i, ch in _first_chunks(tmpl[f]["emd"]):
            allowed[chunk_slot(ch)].update(b for b, _v in ch["groups"])
    return allowed


def slot_budgets(tmpl: dict, shrink: dict | None = None) -> dict[str, tuple[int, int]]:
    """(vertices, faces) per slot chunk: each part file's EMD room (the replaced wrestler's own EMD size, less the
    headers and the ghost groups) shared between its slots by CAPS weight, 12 bytes per vertex and per primitive;
    a chunk also stays within 128 vertices with its ghosts. shrink {slot: k} scales a slot down (a retry)."""
    out = {}
    for f in PART_FILES:
        emd = tmpl[f]["emd"]
        fixed = emd["aoff"] + 4 * len(emd["slots"]) + 8 * len(emd["desc"])
        ghosts = {}
        for _i, ch in _first_chunks(emd):
            s = chunk_slot(ch)
            fixed += 4 + 4 * len(ch["groups"]) + 8 + 4      # chunk header, group headers, prim block headers, pad
            ghosts[s] = ghosts.get(s, 0) + sum(len(v) for b, v in ch["groups"] if b not in SLOT_BONES.get(s, []))
        room = (len(emd["raw"]) - fixed - 12 * sum(ghosts.values())) / 12
        w = {s: sum(CAPS[b][1] for b in SLOT_BONES[s]) for s in FILE_SLOTS[f]}
        for s in FILE_SLOTS[f]:
            rec = room * w[s] / sum(w.values()) * (shrink or {}).get(s, 1.0)
            fc = int(rec / (1 + VERTS_PER_FACE))
            vc = int(min(128 - ghosts.get(s, 0), rec - fc))
            out[s] = (max(6, vc), max(6, fc))
    return out


def vertex_bones(P: np.ndarray, J: np.ndarray, T: np.ndarray) -> np.ndarray:
    """The game bone of every vertex (retargeted world positions P, glTF space, game units; J = the retarget's joint):
    the torso by height like the game's own parts (pelvis 0, waist 1, chest 2, neck 3), the head's base on the neck.
    Per vertex, not per face, so a face can span two bones and stretch like the stock models do."""
    y = P[:, 1]
    vb = np.asarray(J).copy()
    band = np.where(y >= T[3][1], 3, np.where(y >= T[2][1] - 40, 2, np.where(y >= T[1][1] - 60, 1, 0)))
    tor = np.isin(vb, (0, 2))
    vb[tor] = band[tor]
    vb[(vb == 4) & (y < T[3][1] + 25)] = 3
    vb[~np.isin(vb, list(CAPS))] = 2
    return vb


def _ancestors(b: int) -> list[int]:
    out = []
    while PARENT[b] >= 0:
        b = PARENT[b]
        out.append(b)
    return out


def resolve_bones(F: np.ndarray, vb: np.ndarray, allowed: dict[str, set], rounds: int = 4) -> np.ndarray:
    """No chunk can bind some faces' bones together (a waist vertex and a thigh vertex: only the right leg chunk holds
    the pelvis + thighs, only the torso chunk the waist). Move one corner of each such face up its bone's parent chain
    until a chunk can (the waist corner onto the pelvis), the fewest steps first, then the minority corner. Per vertex,
    once for the whole model: every chunk that copies the vertex then binds it to the same bone (no cracks)."""
    vb = vb.copy()
    sets = [frozenset(a) for a in allowed.values()]
    ok = lambda bs: any(set(bs) <= a for a in sets)         # noqa: E731
    for _ in range(rounds):
        bad = [i for i, f in enumerate(F) if not ok(vb[f].tolist())]
        if not bad:
            break
        for i in bad:
            bs = vb[F[i]].tolist()
            if ok(bs):
                continue
            cnt = Counter(bs)
            best = None
            for k in range(3):
                for step, a in enumerate(_ancestors(bs[k])):
                    if ok(bs[:k] + [a] + bs[k + 1:]):
                        key = (step, cnt[bs[k]])
                        if best is None or key < best[0]:
                            best = (key, k, a)
                        break
            if best is not None:
                k, a = best[1], best[2]
                b0 = bs[k]
                for v in F[i]:                             # every corner of this face on that bone moves together
                    if vb[v] == b0:
                        vb[v] = a
    return vb


def face_slots(FB: np.ndarray, allowed: dict[str, set]) -> np.ndarray:
    """Each face (its three vertex bones) -> the slot chunk that draws it: the majority bone's slot if that chunk may
    bind all three bones, else another slot that can (an armpit face goes to the arm chunk, which carries the chest
    group), else the majority bone's slot (its stray corners are rebound there)."""
    cache, out = {}, []
    for bs in map(tuple, np.asarray(FB).tolist()):
        if bs not in cache:
            maj = Counter(bs).most_common(1)[0][0]        # (a helper bone, e.g. a clavicle, has no slot of its own)
            pref = [s for s in [SLOT_OF.get(maj)] + [SLOT_OF.get(b) for b in bs] + list(SLOT_BONES) if s]
            cache[bs] = next((s for s in pref if set(bs) <= allowed[s]),
                             SLOT_OF.get(maj) or next((s for s in SLOT_BONES if maj in allowed[s]), "torso"))
        out.append(cache[bs])
    return np.array(out, dtype=object)


def _nearest(src: np.ndarray, pts: np.ndarray) -> np.ndarray:
    out = np.empty(len(pts), int)
    for k in range(0, len(pts), 512):
        out[k:k + 512] = ((pts[k:k + 512, None] - src[None]) ** 2).sum(2).argmin(1)
    return out


def emd_size(emd: dict, counts: dict[str, tuple[dict, int]]) -> int:
    """Bytes emd_build + _like will write for {slot: ({bone: new vertices}, faces)} on this template EMD."""
    size = emd["aoff"] + 4 * len(emd["slots"]) + 8 * len(emd["desc"])
    for _i, ch in _first_chunks(emd):
        s = chunk_slot(ch)
        if s not in counts:
            continue
        new, nf = counts[s]
        order = [b for b, _v in ch["groups"]]
        nv = sum(new[b] if new.get(b) else max(1, len(v)) for b, v in ch["groups"])
        nv += sum(n for b, n in new.items() if b not in order and n)
        ng = len(order) + sum(1 for b, n in new.items() if b not in order and n)
        c = 4 + 4 * ng + 12 * min(nv, 128) + 4 * max(1, -(-nf // 255)) + 12 * nf
        size += c + (-c) % 4
    return size


def cut_slots(P, N, UV, F, FM, JV, T, tmpl: dict, mats: list, work: Path, blender, progress) -> tuple[dict, dict]:
    """The retargeted model (world positions, glTF space, game units) -> one welded mesh per slot chunk, every vertex
    on its own game bone: {slot: {P, N, F, bone (per vertex), part (bake tile bone per face), src}}, report.

    The stock wrestlers are built this way: a chunk's triangles index vertices of several bone groups, so elbows,
    knees, the waist and the neck stretch as the bones turn. Cutting the model into one closed-off shell per bone
    instead (the first writer) leaves every joint open: the shells pull apart and overlap as soon as the wrestler
    moves, and their duplicated boundary rings (plus the uv seam copies an N64-style bake makes; here the uvs live on
    the primitives) spend half the vertex budget, so the parts came out with ~45% of the stock triangle count."""
    from .aki_wrestling import _decimate_parts
    allowed = slot_allowed(tmpl)
    _u, first, wid = np.unique(np.round(P, 2), axis=0, return_index=True, return_inverse=True)
    wid = wid.reshape(-1)                                  # split copies of one point (uv seams) share one bone
    vb = resolve_bones(wid[F], vertex_bones(P, JV, T)[first], allowed)[wid]
    fs = face_slots(vb[F], allowed)
    sid = {s: i for i, s in enumerate(SLOT_BONES)}
    part = np.array([sid[s] for s in fs])
    slots = [s for s in SLOT_BONES if (fs == s).any()]
    shrink = {}
    for attempt in range(4):
        caps = slot_budgets(tmpl, shrink)
        dcaps = {sid[s]: (int(caps[s][0] * 1.12) + 2, caps[s][1] + 2) for s in SLOT_BONES}   # its seam allowance off
        dec = _decimate_parts(P, N, UV, F, FM, part, mats, dcaps, Path(work), blender, progress)
        geo, report = {}, {}
        for s in slots:
            g = dec[sid[s]]
            used = np.unique(F[fs == s])
            sb = vb[used].copy()
            own = np.array(SLOT_BONES[s])
            bad = ~np.isin(sb, list(allowed[s]))
            if bad.any():                                  # a corner on a bone this chunk can't bind: its own nearest
                sb[bad] = own[_nearest(T[own], P[used][bad])]
            Pv, Nv, Fv = np.asarray(g["P"], float), np.asarray(g["N"], float), np.asarray(g["F"], int).reshape(-1, 3)
            vc, fc = caps[s]
            nf0 = len(Fv)
            if len(np.unique(Fv)) > vc or len(Fv) > fc:    # still over (no Blender): keep the largest faces that fit
                area = np.linalg.norm(np.cross(Pv[Fv[:, 1]] - Pv[Fv[:, 0]], Pv[Fv[:, 2]] - Pv[Fv[:, 0]]), axis=1)
                seen, keep = set(), []
                for i in np.argsort(-area):
                    new = set(Fv[i].tolist()) - seen
                    if len(keep) < fc and len(seen) + len(new) <= vc:
                        keep.append(i)
                        seen |= new
                Fv = Fv[np.sort(keep)]
            used2, Fl = np.unique(Fv, return_inverse=True)
            Pv, Nv, Fv = Pv[used2], Nv[used2], Fl.reshape(-1, 3)
            bone = sb[_nearest(P[used], Pv)] if len(Pv) else np.zeros(0, int)
            tile = np.empty(len(Fv), int)
            for i, q in enumerate(bone[Fv] if len(Fv) else []):
                maj = Counter(q.tolist()).most_common(1)[0][0]
                tile[i] = maj if maj in own else own[np.argmin(np.linalg.norm(T[own] - T[maj], axis=1))]
            geo[s] = {"P": Pv, "N": Nv, "F": Fv, "bone": bone, "part": tile, "src": g["src"]}
            report[f"slot_{s}"] = {"verts": len(Pv), "faces": len(Fv), "budget": [vc, fc], "dropped": nf0 - len(Fv),
                                   "bones": {int(b): int(n) for b, n in zip(*np.unique(bone, return_counts=True))}}
        over = {}
        for f in PART_FILES:                               # the exact EMD size against the wrestler's own
            emd = tmpl[f]["emd"]
            cnt = {s: ({int(b): int(n) for b, n in zip(*np.unique(geo[s]["bone"], return_counts=True))}, len(geo[s]["F"]))
                   for s in FILE_SLOTS[f] if s in geo}
            need = emd_size(emd, cnt)
            if need > len(emd["raw"]):
                over[f] = need / len(emd["raw"])
        if not over:
            break
        for f, r in over.items():
            for s in FILE_SLOTS[f]:
                shrink[s] = shrink.get(s, 1.0) / r * 0.97
        progress(55, f"Model over the wrestler's size in {', '.join(over)}: refitting smaller")
    else:
        raise ValueError(f"model still over the wrestler's EMD size in {', '.join(over)}")
    return geo, report


def slot_chunk(g: dict | None, corners: list, W: list, speck_bone: int, uv0=(0, 0)) -> tuple[list, list]:
    """One slot's mesh (cut_slots geometry; corners = [(slot vertex triple, uv triple)], glTF winding) -> chunk_build
    input: a vertex group per bone (positions and 4.12 normals in the bone's rest frame), triangles in the game's
    winding indexing across the groups."""
    groups, tris = [], []
    if g is not None and corners:
        used = sorted({x for q, _uv in corners for x in q})
        ci, k0 = {}, 0
        for b in sorted({int(g["bone"][x]) for x in used}):
            R, t = W[b]
            vs = []
            for x in used:
                if g["bone"][x] != b:
                    continue
                n = R.T @ (G @ np.asarray(g["N"][x], float))
                vs.append(tuple(R.T @ (G @ np.asarray(g["P"][x], float) - t)) + tuple(n / (np.linalg.norm(n) or 1) * 4096))
                ci[x] = k0
                k0 += 1
            groups.append((b, vs))
        for q, uv in corners:                              # glTF counter-clockwise -> the game's winding
            tris.append(((ci[q[0]], ci[q[2]], ci[q[1]]), (uv[0], uv[2], uv[1])))
    if not groups:                                         # every slot draws something: a hidden speck
        groups = [(speck_bone, [(0, 0, 0, 0, 0, 4096), (1, 0, 0, 0, 0, 4096), (0, 1, 0, 0, 0, 4096)])]
        tris = [((0, 1, 2), (tuple(uv0), tuple(uv0), tuple(uv0)))]
    return groups, tris


def fit_character(files: dict, group: int, model: Path, roles: dict, work: Path, name: str, props=(), scale=None,
                  blender: str | None = None, progress=lambda p, m: None) -> dict:
    """-> {file: {"emd": parsed original (template), "chunks": {slot: (groups, tris)}, "atlas": (img, rect, tpage,
    clut)}, "rigged", "report"} for the replaced wrestler (costume 0's layout)."""
    from .sm64_swap import load_rig, retarget, write_rigged, read_rigged
    from .aki_wrestling import _bake_parts
    from .re4gc_enemies import decimate
    tmpl = entry_parts(files, group, 0)
    bones = tmpl["ED1B.PAC"]["emd"]["bones"]
    tgt = target_skeleton(bones)
    W = rest_world(bones)
    progress(15, f"Retargeting {name} onto the SmackDown! 2 skeleton")
    rig = load_rig(Path(model), roles, props)
    jm = {r: b for r, b in ROLE_BONE.items() if r != "neck"}
    prims, rep = retarget(rig, tgt, scale, jm)
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    rigged = write_rigged(prims, tgt, work / "sd2_rigged.gltf", name)
    src = rigged
    tris_src = sum(len(p["tris"]) for p in rig["prims"])
    from . import fit_events as FE
    if tris_src > 8000 and blender:
        FE.stage("decimate", "running", {"from": tris_src, "to": 8000})
        src = decimate(rigged, work / "sd2_dec.glb", 8000.0, blender)
    rp = read_rigged(src)
    FE.stage("decimate", "done" if src is not rigged else "skipped",
             {"from": tris_src, "triangles": int(sum(len(p["tris"]) for p in rp))}, prims=rp if src is not rigged else None)
    progress(30, "Cutting the model into the wrestler's part meshes")
    mats, mkey = [], {}
    allP, allN, allUV, allJ, F, FM = [], [], [], [], [], []
    base = 0
    for p in rp:
        key = (id(p["tex"]) if p["tex"] is not None else None, tuple(p["color"][:3]))
        if key not in mkey:
            mkey[key] = len(mats)
            mats.append({"tex": p["tex"], "color": p["color"]})
        allP.append(p["pos"]); allN.append(p["nrm"]); allUV.append(p["uv"]); allJ.append(p["jid"])
        F.append(p["tris"] + base)
        FM.append(np.full(len(p["tris"]), mkey[key]))
        base += len(p["pos"])
    P, N, UV, JV = np.concatenate(allP), np.concatenate(allN), np.concatenate(allUV), np.concatenate(allJ)
    F, FM = np.concatenate(F), np.concatenate(FM)
    T = tgt["T"]
    geo, report = cut_slots(P, N, UV, F, FM, JV, T, tmpl, mats, work, blender, progress)
    out = {}
    for f in PART_FILES:
        p0 = tmpl[f]
        ch0 = next(c for c in p0["emd"]["chunks"] if c is not None)
        tpage, clut = ch0["tpage"], ch0["clut"]
        u0, v0, rw, rh = _cover_rect(p0["tims"], tpage)
        tiles = []                                         # (slot, face indices): one texture tile per bone part
        for s in FILE_SLOTS[f]:
            g = geo.get(s)
            if g is None:
                continue
            for b in SLOT_BONES[s]:
                sel = np.where(g["part"] == b)[0]
                if len(sel):
                    tiles.append((s, sel))
        parts = []
        for s, sel in tiles:
            g = geo[s]
            used, Fl = np.unique(g["F"][sel], return_inverse=True)
            parts.append({"P": g["P"][used], "N": g["N"][used], "F": Fl.reshape(-1, 3), "src": g["src"], "used": used})
        img, parts_v = _bake_parts(parts, mats, rw, rh, [None] * len(parts))
        corners = {s: [] for s in FILE_SLOTS[f]}           # (slot vertex triple, uv triple) per face
        for (s, _sel), part, (vp, _vn, vu, faces) in zip(tiles, parts, parts_v):
            at = {tuple(x): int(i) for x, i in zip(part["P"], part["used"])}
            for q in faces:                                # the bake's corners are copies of the part's vertices
                corners[s].append(([at[tuple(vp[k])] for k in q], [(u0 + vu[k][0], v0 + vu[k][1]) for k in q]))
        chunks = {s: slot_chunk(geo.get(s), corners[s], W, SLOT_BONES[s][0], (u0, v0)) for s in FILE_SLOTS[f]}
        out[f] = {"tmpl": p0, "chunks": chunks, "atlas": (img, (u0, v0, rw, rh), tpage, clut)}
    report["triangles"] = sum(v["faces"] for k, v in report.items() if k.startswith("slot_"))
    report["retarget"] = rep
    report["source_triangles"] = tris_src
    FE.stage("encode", data={"triangles": report["triangles"], "files": len(out), "source_triangles": tris_src})
    return {"files": out, "rigged": rigged, "report": report}


def _like(orig: dict, groups: list, tris: list) -> tuple[list, list]:
    """The new vertex groups in the original chunk's bone order (the loader expects the chunk's bone list); an original
    bone the new model doesn't use there keeps its original vertices (unreferenced, never drawn); new-only bones
    after them."""
    order = [b for b, _v in orig["groups"]]
    ghost = {b: list(v) for b, v in orig["groups"]}
    mine = {b: v for b, v in groups}
    start, k = {}, 0
    for b, v in groups:
        start[b] = k
        k += len(v)
    out, remap, k = [], {}, 0
    for b in order + [b for b, _v in groups if b not in order]:
        vs = mine.get(b, [])
        for j in range(len(vs)):
            remap[start[b] + j] = k + j
        if not vs:                                         # the loader reads every group's vertices (an empty or
            vs = ghost.get(b) or [(0, 0, 0, 0, 0, 4096)]   # one-point torso group hangs it): the original ones stay,
        out.append((b, vs))                                # unreferenced
        k += len(vs)
    over = sum(len(v) for _b, v in out) - 128
    if over > 0:                                           # the 128-vertex chunk limit: shrink the ghost groups
        for k, (b, vs) in enumerate(out):
            if b not in mine and over > 0 and len(vs) > 3:
                cut = min(over, len(vs) - 3)
                out[k] = (b, vs[:len(vs) - cut])
                over -= cut
        # ghost vertices are never referenced, so the remap (built for the new model's vertices) needs a rebuild
        remap, k = {}, 0
        for b, vs in out:
            if b in mine:
                for j in range(len(mine[b])):
                    remap[start[b] + j] = k + j
            k += len(vs)
    return out, [(tuple(remap[x] for x in idx), uv) for idx, uv in tris]


def build_entry(fit_file: dict) -> bytes:
    """One part file's new DPAC entry: the template EMD with the new chunks (every variant of a slot), and the
    template's TIMs that the atlas covers, repainted with one new 256-colour CLUT."""
    tmpl = fit_file["tmpl"]
    emd = tmpl["emd"]
    new = {}
    firsts = {st for st, cnt in emd["slots"] if cnt}       # only each slot's first variant: the game falls back to it
    for i, ch in enumerate(emd["chunks"]):                 # when the picked one is empty, and the wrestler's model
        if ch is None or i not in firsts:                  # arena only holds about the original EMD's size
            continue
        s = chunk_slot(ch)
        if s not in fit_file["chunks"]:
            continue
        groups, tris = _like(ch, *fit_file["chunks"][s])
        new[i] = chunk_build(ch["clut"], ch["tpage"], groups, tris, keep_empty=True)
    emd_bytes = emd_build(emd, new)
    if len(emd_bytes) > len(emd["raw"]):
        raise ValueError(f"model is {len(emd_bytes)} bytes, the wrestler's arena takes {len(emd['raw'])}")
    img, (u0, v0, rw, rh), tpage, _clut = fit_file["atlas"]
    pix = img[..., :3]
    from .aki_wrestling import quantize
    _i, pal = quantize(np.concatenate([pix.reshape(-1, 3), np.full((rw * rh, 1), 255, np.uint8)], 1)[None], 256)
    pal = np.asarray(pal)[:, :3].astype(int)
    if len(pal) < 256:                                     # few-colour textures: the CLUT must still hold 256 entries
        pal = np.concatenate([pal, np.repeat(pal[-1:], 256 - len(pal), 0)])
    pal = pal[:256]
    flat = pix.reshape(-1, 3).astype(int)
    idx = np.empty(len(flat), np.uint8)
    for k in range(0, len(flat), 4096):                    # nearest palette entry
        idx[k:k + 4096] = ((flat[k:k + 4096, None] - pal[None]) ** 2).sum(2).argmin(1)
    idx = idx.reshape(rh, rw)
    clut = to5551(pal)
    tx = (tpage & 0xF) * 64
    tims = []
    for t in tmpl["tims"]:
        if not repaintable(t):                             # 4-bpp detail / CLUT-less TIMs: as they are
            tims.append(t)
            continue
        px, py, pw, ph = t["rect"]
        a0, b0 = (px - tx) * 2, py % 256
        a1, b1 = a0 + pw * 2, b0 + ph
        t2 = dict(t)                                       # every TIM stays (the game places a slot's TIMs by the
        t2["pix"] = t["pix"].copy()                        # set's layout: dropping some corrupts VRAM in slot 2)
        if not (a1 <= u0 or a0 >= u0 + rw or b1 <= v0 or b0 >= v0 + rh):
            ia0, ib0, ia1, ib1 = max(a0, u0), max(b0, v0), min(a1, u0 + rw), min(b1, v0 + rh)
            t2["pix"][ib0 - b0:ib1 - b0, ia0 - a0:ia1 - a0] = idx[ib0 - v0:ib1 - v0, ia0 - u0:ia1 - u0]
        t2["clut"] = clut
        tims.append(t2)
    texpac = pac_build([(i, bpe_encode(tim_build(t))) for i, t in enumerate(tims)])
    # ids must ascend (80027aa4 binary-searches them). Head ids 2/3 (attachment EMD + ASCII placement) are left out on
    # purpose: 8003e0c4 null-checks both, so the replaced head carries no leftover attachment of the target wrestler.
    return pac_build([(0, emd_bytes), (0x0A, texpac)])


def build_disc(base: Path, out_bin: Path, jobs: list[dict], work: Path, blender=None, progress=lambda p, m: None) -> dict:
    """jobs [{group, model, roles, name, props, scale}] -> modded raw image (+ .cue): every costume entry of each
    replaced wrestler in ED1H/ED1B/ED1L rewritten in place (same offsets and sizes)."""
    from .psxdisc import RawBin
    files = read_files(base)
    newf = {f: bytearray(files[f]) for f in PART_FILES}
    reports = []
    for k, jb in enumerate(jobs):
        fit = fit_character(files, jb["group"], jb["model"], jb["roles"], Path(work) / f"g{jb['group']}", jb["name"],
                            jb.get("props", ()), jb.get("scale"), blender,
                            progress=lambda p, m, k=k: progress(5 + (k * 80 + p * 0.8) / max(1, len(jobs)), m))
        sizes = {}
        for f in PART_FILES:
            ents = [e for e in dpac_entries(files[f]) if e[0] >> 4 == bcd(jb["group"])]
            data = build_entry(fit["files"][f])
            for eid, units, o in ents:
                room = units * 0x100
                if len(data) > room:
                    raise ValueError(f"{jb['name']}: {f} entry {eid:#x} needs {len(data)} bytes, has {room}")
                newf[f][o:o + room] = data + bytes(room - len(data))
            sizes[f] = [len(data), min(u * 0x100 for _e, u, _o in ents)]
        reports.append({"group": jb["group"], "character": jb["name"], "rigged": str(fit["rigged"]), "sizes": sizes,
                        **fit["report"]})
    progress(90, "Writing the disc image")
    out_bin = Path(out_bin)
    out_bin.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(base, out_bin)
    rb = RawBin(out_bin)
    try:
        for f in PART_FILES:
            if newf[f] != files[f]:
                rb.write_file(f, 0, bytes(newf[f]))
    finally:
        rb.close()
    out_bin.with_suffix(".cue").write_text(f'FILE "{out_bin.name}" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n')
    return {"bin": str(out_bin), "cue": str(out_bin.with_suffix(".cue")), "reports": reports}


# ---------------------------------------------------------------- gBox: collection, characters op=use / match / extract

def roster_entries() -> list[dict]:
    """characters.DEDICATED roster (fixed list; ids are the game's model groups)."""
    return [{"key": i, "slug": slug_of(n), "name": n, "aliases": SD_ALIASES.get(n, []) + [f"SmackDown 2 {n}"],
             "kind": "character"} for i, n in ROSTER_NAMES]


ROSTER_NAMES = [(0, "The Rock"), (1, "Stone Cold"), (2, "The Undertaker"), (3, "Triple H"), (4, "X-Pac"), (5, "Road Dogg"),
                (6, "Billy Gunn"), (8, "Kane"), (9, "Chris Jericho"), (10, "Kurt Angle"), (11, "Chris Benoit"),
                (12, "Eddie Guerrero"), (13, "Dean Malenko"), (14, "Perry Saturn"), (15, "Tazz"), (16, "The Goodfather"),
                (17, "D'Lo Brown"), (18, "Rikishi"), (19, "Grand Master Sexay"), (20, "Scotty Too Hotty"), (21, "Edge"),
                (22, "Christian"), (23, "Faarooq"), (24, "Bradshaw"), (25, "Buh Buh Ray Dudley"), (26, "D-Von Dudley"),
                (27, "Matt Hardy"), (28, "Jeff Hardy"), (29, "Hardcore Holly"), (30, "Crash"), (31, "Test"), (32, "Albert"),
                (33, "Big Boss Man"), (35, "Val Venis"), (36, "Al Snow"), (37, "Mark Henry"), (38, "Viscera"),
                (39, "Gangrel"), (40, "Steve Blackman"), (41, "Essa Rios"), (42, "Chyna"), (43, "Tori"), (44, "Ivory"),
                (45, "Jacqueline"), (46, "Trish Stratus"), (47, "The Kat"), (48, "Lita"), (49, "Vince McMahon"),
                (50, "Shane McMahon"), (51, "Stephanie McMahon"), (52, "Paul Bearer"), (53, "Michael Cole"), (54, "Mankind"),
                (55, "Bull Buchanan"), (56, "TAKA Michinoku"), (57, "Funaki"), (58, "Pat Patterson"), (59, "Gerald Brisco"),
                (60, "Pete Gas"), (61, "Rodney"), (62, "Joey Abs"), (63, "Shawn Michaels"), (64, "Mick Foley"),
                (65, "Cactus Jack"), (66, "Steven Richards"), (67, "Debra")]


def cast_slots() -> list[dict]:
    """The cast menu / whole-cast swap: one slot per wrestler (every costume), the names op=match resolves."""
    return [{"slot": n, "name": n, "kind": "wrestler", "group": i, "writer": "gbox.yukes_sd"} for i, n in ROSTER_NAMES]


def extract_run(ctx, game, e, work):
    """characters.DEDICATED run: the wrestler's costume 0 (head + body + legs, standing pose, one rigid joint per
    vertex) with its own TIM textures."""
    out = Path(work) / f"{e['slug']}.gltf"
    files = read_files(base_bin(ctx.config, game, ctx.progress))
    r = extract(files, e["key"], out, e["name"])
    return {"files": [out], "tool": "gbox.yukes_sd (extract)", "roles": r["roles"],
            "source_files": [f"ED1H/ED1B/ED1L.PAC model group {e['key']} (costume 0)"],
            "notes": "SmackDown! 2 wrestler in the game's standing pose; 31 joints, rigid skinning, first variant of "
                     "each slot (neutral face, open hands)"}


def mod_name(pairs: list[tuple[dict, dict]], title: str | None = None) -> str:
    if title and len(pairs) > 2:
        t = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
        return "sd2_" + re.sub(r"^(wwf_)?smackdown_2_|^(wwf_)?smackdown_", "", t)[:48].strip("_")
    if len(pairs) == 1:
        return f"sd2_{pairs[0][0]['slug']}_as_{slug_of(pairs[0][1]['name'])[4:]}"
    return "sd2_" + "_vs_".join(m["slug"] for m, _w in pairs)


def build_mod(cfg, game: dict, pairs: list[tuple[dict, dict]], progress=lambda p, m: None, root: Path | None = None,
              title: str | None = None) -> dict:
    from . import characters as C, filemods
    from .sm64_swap import _blender
    root = root or C.library_root(cfg)
    gid = game["game_id"]
    base = base_bin(cfg, game, progress)
    jobs = []
    for meta, w in pairs:
        roles = (meta.get("rig") or {}).get("roles") or {}
        if "hip" not in roles:
            raise ValueError(f"{meta['name']} has no body roles (rig.roles): can't map it onto a wrestler")
        jobs.append({"group": w["id"], "model": root / meta["slug"] / meta["model"], "roles": roles, "name": meta["name"],
                     "props": [p["node"] for p in meta.get("props") or []], "scale": (meta.get("rig") or {}).get("scale")})
    name = mod_name(pairs, title)
    work = Path(cfg.cache) / "characters_build" / name
    shutil.rmtree(work, ignore_errors=True)
    d = filemods.mod_dir(cfg, gid, name)
    if d.exists():
        shutil.rmtree(d)
    t = title or " vs ".join(m["name"] for m, _w in pairs)
    img = "WWF SmackDown! 2 - " + re.sub(r"[^\w .()'-]+", "", t).strip() + " (USA).bin"
    b = build_disc(base, d / img, jobs, work, _blender(cfg), progress)
    previews = []
    for (meta, w), rep in zip(pairs, b["reports"]):
        tdir = root / meta["slug"] / "targets"
        tdir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(rep["rigged"], tdir / "sd2_wrestler.gltf")
        try:
            previews.append(str(C.render_preview(tdir / "sd2_wrestler.gltf", tdir / "sd2_preview.png")))
        except Exception:                                  # noqa: BLE001
            pass
    cue = Path(b["cue"]).name
    mj = {"name": name, "game_id": gid, "image": cue, "title": t, "built": time.time(),
          "files": ["ED1H.PAC / ED1B.PAC / ED1L.PAC: wrestler model entries (gbox.yukes_sd)"],
          "characters": [m["slug"] for m, _w in pairs], "replaces": [w["name"] for _m, w in pairs],
          "triangles": [r["triangles"] for r in b["reports"]], "fit": FIT_VERSION}
    (d / ".gbox-mod.json").write_text(json.dumps(mj))
    shutil.rmtree(work, ignore_errors=True)
    return {"mod": name, "image": cue, "previews": previews,
            "reports": [{k: v for k, v in r.items() if k != "rigged"} for r in b["reports"]]}


def built_current(mod_dir: Path) -> bool:
    """A mod built by this writer version (an older fit, e.g. the per-bone shells before FIT_VERSION 2, is rebuilt)."""
    try:
        return json.loads((Path(mod_dir) / ".gbox-mod.json").read_text()).get("fit", 1) == FIT_VERSION
    except (OSError, ValueError):
        return False


def _roster_for(ctx, game) -> list[dict]:
    try:
        return roster(base_bin(ctx.config, game))
    except Exception:                                      # noqa: BLE001
        return [{"id": i, "name": n, "special": ""} for i, n in ROSTER_NAMES]


def use(ctx, meta: dict, game: dict, inp, pairs: list | None = None, title: str | None = None) -> dict:
    """characters op=use / op=match for SmackDown! 2: slot = a wrestler's name (default The Rock), build on the
    control plane, launch."""
    from . import characters as C, filemods
    gid = game["game_id"]
    if gid not in GAME_IDS:
        return {"status": "missing", "missing": needs(game), "message": needs(game)["have"]}
    sess = C._session(ctx, inp.session_id) if inp.session_id else None
    node = sess["session_id"].split("-")[0] if sess else C.HOST_OS
    if not C.library_root(ctx.config).is_dir():           # not the control plane: build there, launch here
        cp = next((w["id"] for w in C._api(ctx, "GET", "/api/workers") if w.get("os") == "linux"), None)
        args = {"op": inp.op, "character": inp.character, "game_id": gid, "slot": inp.slot, "rebuild": inp.rebuild,
                "launch": False, "pairs": inp.pairs, "title": inp.title}
        j = C._job(ctx, "characters", args, cp, 3600)
        r = (j.get("output") or {}).get("result") or {}
        if j.get("state") != "succeeded" or r.get("status") not in ("built", "ready"):
            return {"status": "failed", "error": r.get("error") or j.get("error") or r}
        name, built = r["mod"], r.get("build")
    else:
        ros = _roster_for(ctx, game)
        if pairs is None:
            w = find_wrestler(ros, inp.slot if inp.slot and inp.slot != "player" else "The Rock")
            pairs = [(meta, w)]
        name = mod_name(pairs, title)
        have = built_current(filemods.mod_dir(ctx.config, gid, name))
        built = None
        if inp.rebuild or not have:
            built = build_mod(ctx.config, game, pairs, ctx.progress, title=title)
            for m, w in pairs:
                C._api(ctx, "POST", f"/api/characters/{m['slug']}/targets",
                       json={"game_id": gid, "slot": w["name"], "mod": name, "nodes": [C.HOST_OS],
                             "notes": f"replaces {w['name']} (every costume; the game's skeleton, moves and animations); "
                                      "preview targets/sd2_preview.png"})
    res = {"mod": name, "build": built, "replaces": ", ".join(f"{w['name']} -> {m['name']}" for m, w in (pairs or []))}
    if not inp.launch:
        return res | {"status": "built" if built else "ready"}
    ctx.progress(92, f"Launching SmackDown! 2 (mod {name})")
    from .sm64_swap import _wait
    lj = _wait(ctx, C._api(ctx, "POST", "/api/jobs", json={"tool": "@launch", "input": {"game_id": gid, "mod": name,
                                                                                         "node": node}}), 600)
    ok = lj.get("state") == "succeeded"
    launch = {"job": lj.get("id"), "state": lj.get("state"), "node": node,
              "session_id": (lj.get("output") or {}).get("session_id"), "error": lj.get("error")}
    msg = (f"SmackDown! 2 is running with {res['replaces']} (mod {name}). Pick the replaced wrestler(s) on the select "
           "screen (the list and portraits keep the old names)." if ok else
           f"Mod {name} built but the launch {lj.get('state')}: {lj.get('error')}")
    return res | {"status": ("built+launched" if built else "launched") if ok else "built, launch failed", "launch": launch,
                  "message": msg}


def match(ctx, chars: list, game: dict, inp, pairs_in: list[tuple[str, str]], title: str | None = None) -> dict:
    from .characters import best_match
    ros = _roster_for(ctx, game)
    pairs, used = [], set()
    for cq, wq in pairs_in:
        meta = best_match(chars, cq)
        if not meta:
            raise LookupError(f"{cq!r} isn't in the collection")
        w = find_wrestler(ros, wq) if wq else next(x for x in ros if x["id"] not in used)
        if w["id"] in used:
            raise ValueError(f"{w['name']} is already replaced in this match")
        used.add(w["id"])
        pairs.append((meta, w))
    return use(ctx, pairs[0][0], game, inp, pairs, title)


def needs(game: dict) -> dict:
    t = (game.get("title") or "").lower()
    if "smackdown" in t and game.get("game_id") in SD1_IDS:
        return {"target": "a wrestler (EH/EB/EL.PAC head/body/leg models)", "format": "DPAC v1 (different table header) + "
                "the same PAC/EMD/TIM family as SmackDown! 2", "steps": ["port gbox.yukes_sd's DPAC reader to SD1's header",
                "capture SD1's standing skeleton (REST) the same way"], "have": "SmackDown! 2 writer (gbox/yukes_sd.py)"}
    return {"target": "a wrestler", "format": "Yuke's DPAC/EMD", "steps": [],
            "have": "WWF SmackDown! 2 - Know Your Role (USA) only (gbox/yukes_sd.py)"}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("roster")
    r.add_argument("bin")
    x = sub.add_parser("extract")
    x.add_argument("bin")
    x.add_argument("group", type=int)
    x.add_argument("out")
    a = ap.parse_args()
    if a.cmd == "roster":
        for w in roster(Path(a.bin)):
            print(w["id"], w["name"], "/", w["special"])
    else:
        print(extract(read_files(Path(a.bin)), a.group, Path(a.out), Path(a.out).stem))
