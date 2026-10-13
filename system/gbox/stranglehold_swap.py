"""Stranglehold (PS3) character writer: a library character as Tequila or as a multiplayer enemy / character skin.

The donor is retargeted onto the package's own SkeletalMesh skeleton (gbox.sm64_swap.retarget, with fit events),
textured through one 1024 atlas written over the mesh's body diffuse texture (DXT re-encoded in place, its normal /
specular / graypack maps flattened), split into SPU segments (gbox.stranglehold_models documents the layout) and
written back as a new SkeletalMesh export:

* the new export is APPENDED to the logical package (the old bytes stay, unreferenced), so every other export keeps
  its serial offset; only the mesh's export-table entry (SerialSize, SerialOffset) changes;
* the package's compressed chunks are rebuilt: the chunk holding the export table and any chunk whose bytes changed
  are recompressed, the last chunk is extended over the appended export; the uncompressed summary keeps its length
  (same chunk count), the file is padded to 32 KiB like the shipped ones and its size is updated in PS3TOC.txt;
* every LOD of the mesh carries the donor (LOD n decimated to the stock LOD's triangle count); RefSkeleton, sockets,
  physics asset and animations are the game's own, so the donor plays Tequila's / the enemy's animations.

Slots: player | tequila (all ten Tequila packages: the five outfits, single player + multiplayer) |
tequila:<default|suit|jacket|sweater|jack_swtr> | enemy:<gk_assault_1 ...> (a gang class's multiplayer skin) |
enemies (all 22 gang skins) | model:<package stem> (any roster package). Campaign enemies live inside the level
packages and share one texture atlas per class family; they are not written (docs/stranglehold.md).

Unverified in game: the SPU job's scratch-size words and command-buffer hole are reproduced from the shipped
segments' sizes (see segment_bytes); the packed tangent frame is copied from the nearest stock vertex.
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
import time
import zlib
from pathlib import Path

import numpy as np

from . import stranglehold_models as M
from . import stranglehold_inventory as SI

GAME_IDS = {M.GAME_ID}
WRITER = "gbox.stranglehold_swap"
COOKED = "PS3_GAME/USRDIR/StrangleholdGame/CookedPS3"
TOC = "PS3_GAME/USRDIR/StrangleholdGame/PS3TOC.txt"
PAD = 32768
ATLAS = (1024, 1024)
SEG_VERTS, SEG_TRIS, SEG_MATRICES = 700, 1100, 60
TEQUILA = {"default": "char_tequila", "suit": "char_tequila_suit", "jacket": "char_tequila_jacket",
           "sweater": "char_tequila_sweater", "jack_swtr": "char_tequila_jack_swtr"}
ENEMIES = {slug.replace("stranglehold_", ""): stem for stem, slug, _n, role in M.ROSTER if role == "enemy"}
REPLACEMENT_SPEC = {"skeleton": "Stranglehold medium_skeleton (87-94 bones, HumanIK names)", "roles": "all",
                    "influences": 1, "tex": 1024, "decimate": True,
                    "budget": "segments of <= 700 vertices / 1100 triangles; LODs decimated to the stock counts"}
JMAP_ROLES = ("hip", "chest", "head", "l_upper", "l_fore", "l_hand", "r_upper", "r_fore", "r_hand",
              "l_thigh", "l_shin", "l_foot", "r_thigh", "r_shin", "r_foot")


# ------------------------------------------------------------------------------------------------ slots
def is_slot(slot: str) -> bool:
    s = (slot or "player").strip().lower()
    return s in ("player", "tequila", "enemies", "cast") or s.startswith(("tequila:", "enemy:", "model:"))


def packages_for(slot: str) -> list[str]:
    """Package stems a slot writes (single player and multiplayer Tequila packages both)."""
    s = (slot or "player").strip().lower()
    if s in ("player", "tequila"):
        return [p for st in TEQUILA.values() for p in (st, st + "_MP")]
    if s.startswith("tequila:"):
        st = TEQUILA.get(s.split(":", 1)[1])
        if not st:
            raise ValueError(f"unknown Tequila outfit {s!r}: {', '.join(TEQUILA)}")
        return [st, st + "_MP"]
    if s == "enemies":
        return list(ENEMIES.values())
    if s.startswith("enemy:"):
        k = s.split(":", 1)[1].replace(" ", "_")
        st = ENEMIES.get(k) or next((v for kk, v in ENEMIES.items() if kk.startswith(k)), None)
        if not st:
            raise ValueError(f"unknown enemy {k!r}: {', '.join(ENEMIES)}")
        return [st]
    if s.startswith("model:"):
        k = s.split(":", 1)[1]
        stems = {st.lower(): st for st, *_ in M.ROSTER} | {st.lower() + "_mp": st + "_MP" for st in TEQUILA.values()}
        st = stems.get(k.lower()) or stems.get(("char_" + k).lower())
        if not st:
            raise ValueError(f"unknown package {k!r}")
        return [st]
    raise ValueError(f"not a Stranglehold slot: {slot!r}")


def cast_slots() -> list[dict]:
    out = [{"slot": "player", "name": "Inspector Tequila (every outfit, story + multiplayer)", "kind": "player",
            "writer": WRITER, "aggregate": True}]
    out += [{"slot": f"tequila:{k}", "name": f"Tequila, {k.replace('_', ' ')} outfit", "kind": "player",
             "writer": WRITER} for k in TEQUILA]
    out += [{"slot": f"enemy:{k}", "name": n.replace(" (Stranglehold)", "") + " (multiplayer skin)", "kind": "enemy",
             "writer": WRITER} for st, slug, n, role in M.ROSTER if role == "enemy"
            for k in [slug.replace("stranglehold_", "")]]
    out.append({"slot": "enemies", "name": "every gang enemy skin (multiplayer)", "kind": "enemy", "writer": WRITER,
                "aggregate": True})
    out += [{"slot": f"model:{st}", "name": n.replace(" (Stranglehold)", ""), "kind": role, "writer": WRITER}
            for st, slug, n, role in M.ROSTER if role in ("boss", "character")]
    return out


# ------------------------------------------------------------------------------------------------ DXT encode
def _565(c):
    c = np.clip(np.rint(c), 0, 255).astype(np.int64)
    return ((c[..., 0] * 31 + 127) // 255 << 11) | ((c[..., 1] * 63 + 127) // 255 << 5) | ((c[..., 2] * 31 + 127) // 255)


def _rgb(c):
    return np.stack([((c >> 11) & 31) * 255 / 31, ((c >> 5) & 63) * 255 / 63, (c & 31) * 255 / 31], -1)


def dxt_encode(rgba: np.ndarray, kind: int) -> bytes:
    """(h, w, 4) uint8 -> DXT1 (kind 1) or DXT5 (kind 5) blocks; bounding-box endpoints, nearest palette entries."""
    h, w = rgba.shape[:2]
    bh, bw = max(h // 4, 1), max(w // 4, 1)
    img = np.zeros((bh * 4, bw * 4, 4), np.uint8)
    img[:h, :w] = rgba[:bh * 4, :bw * 4]
    blk = img.reshape(bh, 4, bw, 4, 4).transpose(0, 2, 1, 3, 4).reshape(bh * bw, 16, 4).astype(np.float64)
    rgb = blk[..., :3]
    c0, c1 = _565(rgb.max(1)), _565(rgb.min(1))
    swap = c0 < c1
    c0, c1 = np.where(swap, c1, c0), np.where(swap, c0, c1)
    p0, p1 = _rgb(c0), _rgb(c1)
    pal = np.stack([p0, p1, (2 * p0 + p1) / 3, (p0 + 2 * p1) / 3], 1)
    idx = np.argmin(((rgb[:, :, None, :] - pal[:, None, :, :]) ** 2).sum(-1), 2)
    idx = np.where((c0 == c1)[:, None], 0, idx).astype(np.uint64)
    word = (idx << (np.uint64(2) * np.arange(16, dtype=np.uint64))).sum(1).astype(np.uint64)
    color = np.zeros((len(blk), 8), np.uint8)
    color[:, 0], color[:, 1] = c0 & 255, c0 >> 8
    color[:, 2], color[:, 3] = c1 & 255, c1 >> 8
    for k in range(4):
        color[:, 4 + k] = (word >> np.uint64(8 * k)) & np.uint64(255)
    if kind == 1:
        return color.tobytes()
    a = blk[..., 3]
    a0, a1 = a.max(1), a.min(1)
    k = np.arange(1, 7)[None, :]
    tab = np.concatenate([a0[:, None], a1[:, None], ((7 - k) * a0[:, None] + k * a1[:, None]) / 7], 1)
    ai = np.argmin(np.abs(a[:, :, None] - tab[:, None, :]), 2)
    ai = np.where((a0 == a1)[:, None], 0, ai).astype(np.uint64)
    bits = (ai << (np.uint64(3) * np.arange(16, dtype=np.uint64))).sum(1).astype(np.uint64)
    alpha = np.zeros((len(blk), 8), np.uint8)
    alpha[:, 0], alpha[:, 1] = a0.astype(np.uint8), a1.astype(np.uint8)
    for j in range(6):
        alpha[:, 2 + j] = (bits >> np.uint64(8 * j)) & np.uint64(255)
    return np.concatenate([alpha, color], 1).tobytes()


def texture_patches(pkg: M.Package, j: int, rgba: np.ndarray) -> list[tuple[int, bytes]]:
    """Every inline mip of Texture2D export j re-encoded from rgba -> [(logical offset, bytes)] (same sizes)."""
    from PIL import Image
    e = pkg.exports[j - 1]
    b = pkg.blob(j)
    props, o = M.properties(pkg, b, 4)
    fmt = props.get("Format", 0)
    if fmt not in (5, 7):
        raise ValueError(f"{e['name']}: texture format {fmt} is not DXT1/DXT5")
    o += 16
    n = struct.unpack_from(">i", b, o)[0]
    o += 4
    out = []
    src = Image.fromarray(np.ascontiguousarray(rgba))
    for _ in range(n):
        flags, count, size, _off = struct.unpack_from(">iiii", b, o)
        o += 16
        if size > 0 and not flags & 1:
            w, h = struct.unpack_from(">ii", b, o + size)
            mip = np.asarray(src.resize((max(w, 4), max(h, 4)), Image.LANCZOS if w >= 64 else Image.BOX).convert("RGBA"))
            data = dxt_encode(mip, 1 if fmt == 5 else 5)
            if len(data) != size:
                data = (data * (size // max(len(data), 1) + 1))[:size]   # 4x4 mips below a block repeat the block
            out.append((e["offset"] + o, data))
            o += size
        o += 8
    return out


# ------------------------------------------------------------------------------------------------ index + segment encode
def encode_indexes(tris: np.ndarray) -> tuple[bytes, dict]:
    """(m, 3) local indexes in first-use order -> the segment's index block body (every triangle coded 3: own
    indexes; explicit ones delta-coded on eight lanes) + header numbers. Inverse of models.decode_indexes."""
    tris = np.asarray(tris, np.int64)
    seq, exp, nxt = [], [], 0
    for t in tris:
        for i in t:
            if i == nxt:
                seq.append(0)
                nxt += 1
            elif i < nxt:
                seq.append(1)
                exp.append(int(i))
            else:
                raise ValueError("vertexes are not in first-use order")
    deltas = [e - (exp[k - 8] if k >= 8 else 0) for k, e in enumerate(exp)]
    bias = max([0] + [-d for d in deltas])
    vals = [d + bias for d in deltas]
    width = max(1, max(vals, default=0).bit_length())

    def pack(values, w):
        nb = (len(values) * w + 7) // 8
        acc = 0
        for v in values:
            acc = (acc << w) | v
        acc <<= nb * 8 - len(values) * w
        return acc.to_bytes(nb, "big") if nb else b""
    seq_b = pack(seq, 1)
    body = seq_b + pack([3] * len(tris), 2) + pack(vals, width)
    return body, {"nexp": len(exp), "bias": bias, "seq_bytes": len(seq_b), "width": width, "verts": nxt}


def palette_ranges(bones) -> tuple[tuple[int, int], tuple[int, int]]:
    """Sorted bone indexes -> two contiguous matrix ranges (start, count) covering them with the fewest matrices."""
    b = sorted(set(int(x) for x in bones))
    if len(b) == 1:
        return (b[0], 1), (b[0], 0)
    best = None
    for k in range(1, len(b)):
        r0, r1 = (b[0], b[k - 1] - b[0] + 1), (b[k], b[-1] - b[k] + 1)
        if best is None or r0[1] + r1[1] < best[0][1] + best[1][1]:
            best = (r0, r1)
    return best


def _ranges_size(bones) -> int:
    r0, r1 = palette_ranges(bones)
    return r0[1] + r1[1]


def scratch_words(nvp: int, ni: int, npal: int) -> tuple[int, int]:
    """The SPU job's two scratch words: [1] = 7 bytes per (padded) vertex exactly as shipped; [0] follows the
    shipped segments (~2 bytes per index + ~30 per vertex), kept generous and within the largest shipped value."""
    est = 2490 + 29.6 * nvp + 2.0 * ni + 5.0 * npal + 2944
    return int(min(32384, -(-int(est) // 128) * 128)), nvp * 7


def hole_size(ni: int) -> int:
    """Command-buffer hole (16-byte units) as the shipped segments size it: one step per 768 indexes."""
    return 0x0D + sum(1 for k in range(1, 8) if 768 * k + 50 <= ni)


def segment_bytes(pos_ms, frame, uv0, uv1, bones, tris) -> bytes:
    """One SPU segment from mesh-space positions (cm), packed frames (9 bytes), UVs, one bone per vertex and
    first-use-ordered triangles."""
    n, m = len(pos_ms), len(tris)
    body, h = encode_indexes(tris)
    if h["verts"] != n:
        raise ValueError(f"segment uses {h['verts']} of {n} vertexes")
    vbytes = -(-n * M.VERTEX_BYTES // 16) * 16
    A = -(-(len(body) + 8) // 16) * 16
    blk = body + b"\0" * (A - 8 - len(body)) + struct.pack(">HIH", A, 0, vbytes)
    nvp = -(-n // 8) * 8
    cfg = bytes([0x06, hole_size(3 * m), 0xFF, 0xFF, 0xFF, 0x31]) + struct.pack(">HH", nvp, 3 * m) + b"\xff" * 4 + b"\0\0"
    hdr = cfg + struct.pack(">HHHHBB", A, h["nexp"], h["bias"], h["seq_bytes"], h["width"], 0)
    va = np.zeros((n, M.VERTEX_BYTES), np.uint8)
    va[:, 0:6] = np.asarray(pos_ms, ">f2").view(np.uint8).reshape(n, 6)
    va[:, 6:15] = frame
    va[:, 15:19] = np.asarray(uv0, ">f2").view(np.uint8).reshape(n, 4)
    va[:, 19:23] = np.asarray(uv1, ">f2").view(np.uint8).reshape(n, 4)
    verts = va.tobytes() + b"\0" * (vbytes - n * M.VERTEX_BYTES)
    (s0, n0), (s1, n1) = palette_ranges(bones)
    pal = list(range(s0, s0 + n0)) + list(range(s1, s1 + n1))
    slot = {bn: k for k, bn in enumerate(pal)}
    wsize = -(-n * 8 // 16) * 16
    w = np.zeros((n, 8), np.uint8)
    sl = np.array([slot[int(x)] for x in bones], np.uint8)
    w[:, 0] = 255
    w[:, 1] = sl
    w[:, 3] = sl
    w[:, 5] = sl
    w[:, 7] = sl
    weights = w.tobytes() + b"\0" * (wsize - n * 8)
    dma0 = min(vbytes, 0x4000)
    skin = (struct.pack(">IHH", 0, dma0, vbytes - dma0) + b"\0" * 8 +
            struct.pack(">HHHHH", s0 * 48, s1 * 48, n0 * 48, n1 * 48, wsize) + b"\0" * 8 + struct.pack(">H", wsize))
    x, y = scratch_words(nvp, 3 * m, n0 + n1)
    return hdr + blk + verts + skin + weights + struct.pack(">II", x, y) + b"\0" * 30


def split_segments(F: np.ndarray, B: np.ndarray, P: np.ndarray) -> list[np.ndarray]:
    """Faces (global vertex ids) -> face-index groups within the segment limits, grouped by bone then height so
    each segment's bone palette stays small."""
    owner = B[F[:, 0]]
    order = np.lexsort((P[F, 1].mean(1), owner))
    segs, cur, verts, bones = [], [], set(), set()
    for fi in order:
        f = F[fi]
        nv = verts | set(int(v) for v in f)
        nb = bones | set(int(B[v]) for v in f)
        if cur and (len(nv) > SEG_VERTS or len(cur) + 1 > SEG_TRIS or _ranges_size(nb) > SEG_MATRICES):
            segs.append(np.array(cur))
            cur, nv, nb = [], set(int(v) for v in f), set(int(B[v]) for v in f)
        cur.append(fi)
        verts, bones = nv, nb
    if cur:
        segs.append(np.array(cur))
    return segs


def lod_bytes(stock: dict, P_ms, frame, uv0, uv1, B, F) -> tuple[bytes, dict]:
    """One FStaticLODModel carrying the fitted mesh in a single section / chunk (material 0)."""
    segs = []
    used = sorted(set(int(x) for x in B))
    nverts = 0
    for fidx in split_segments(F, B, P_ms):
        faces = F[fidx]
        order, remap = [], {}
        for v in faces.reshape(-1):
            if int(v) not in remap:
                remap[int(v)] = len(order)
                order.append(int(v))
        order = np.array(order)
        local = np.vectorize(remap.get)(faces)
        segs.append(segment_bytes(P_ms[order], frame[order], uv0[order], uv1[order], B[order], local))
        nverts += len(order)
    ntri = len(F)
    if ntri > 0xFFFF:
        raise ValueError(f"{ntri} triangles do not fit one section")
    ch = stock["chunks"][0]
    out = struct.pack(">i", 1) + struct.pack(">HHIH", 0, 0, 0, ntri) + struct.pack(">i", 0)
    active = sorted(set(stock["active_bones"]) | set(used))
    out += struct.pack(">i", len(active)) + struct.pack(f">{len(active)}H", *active)
    out += struct.pack(">i", 0)
    out += struct.pack(">i", 1) + struct.pack(">iii", 0, 0, 0) + struct.pack(">i", len(used)) + \
        struct.pack(f">{len(used)}H", *used) + struct.pack(">iii", nverts, 0, ch["max_influences"])
    out += struct.pack(">iii", stock["size_field"], nverts, 0)
    out += struct.pack(">ii", 1, len(segs)) + b"".join(segs)
    rb = stock["required_bones"]
    out += struct.pack(">i", len(rb)) + rb
    return out, {"segments": len(segs), "vertices": nverts, "triangles": ntri, "bones": len(used)}


def mesh_blob(pkg: M.Package, mesh: dict, lods: list[bytes]) -> bytes:
    b = pkg.blob(mesh["export"])
    return b[:mesh["lod"][0]["start"]] + b"".join(lods) + b[mesh["lods_end"]:]


# ------------------------------------------------------------------------------------------------ package rewrite
def export_entry_fields(d: bytes) -> list[tuple[int, int]]:
    """(SerialSize position, SerialOffset position or -1) of every export-table entry in the logical package."""
    o = d.index(b"\x00\x00\x00\x05None\x00") + 9
    _flags, _nc, _no, ec, eo = struct.unpack_from(">5I", d, o)
    p, out = eo, []
    for _ in range(ec):
        p += 24 + 8
        size = struct.unpack_from(">i", d, p)[0]
        sp = p
        p += 4
        op = -1
        if size > 0:
            op = p
            p += 4
        comps = struct.unpack_from(">i", d, p)[0]
        p += 4 + 12 * comps + 4
        nets = struct.unpack_from(">i", d, p)[0]
        p += 4 + 4 * nets + 16
        out.append((sp, op))
    return out


def compress_chunk(data: bytes, block: int = 0x10000, level: int = 9) -> bytes:
    """One UE3 compressed chunk: tag, block size, totals, block table, zlib blocks."""
    blocks = [zlib.compress(data[k:k + block], level) for k in range(0, len(data), block)] or [zlib.compress(b"")]
    sizes = [(len(c), min(block, len(data) - k * block)) for k, c in enumerate(blocks)]
    head = struct.pack(">IIII", SI.TAG, block, sum(c for c, _ in sizes), len(data))
    return head + b"".join(struct.pack(">II", c, u) for c, u in sizes) + b"".join(blocks)


def rewrite_package(raw: bytes, replace: dict[int, bytes], patches: list[tuple[int, bytes]] = ()) -> bytes:
    """A chunked .xxx file -> new file bytes: exports in `replace` appended (export table updated), byte patches
    applied in place, changed chunks recompressed, the last chunk extended, padded to 32 KiB."""
    s = SI.read_summary(raw[:4096])
    if s["layout"] != "chunked":
        raise ValueError(f"only chunked packages are written (this one is {s['layout']})")
    _s, logical = M.load_package(raw)
    d = bytearray(logical)
    for off, data in patches:
        d[off:off + len(data)] = data
    fields = export_entry_fields(bytes(d))
    for idx, blob in sorted(replace.items()):
        sp, op = fields[idx - 1]
        if op < 0:
            raise ValueError(f"export {idx} has no serial offset")
        while len(d) % 16:
            d.append(0)
        struct.pack_into(">i", d, sp, len(blob))
        struct.pack_into(">i", d, op, len(d))
        d += blob
    chunks = [dict(c) for c in s["chunks"]]
    chunks[-1]["usize"] = len(d) - chunks[-1]["uoff"]
    first = struct.pack(">IIII", *(s["chunks"][0][k] for k in ("uoff", "usize", "coff", "csize")))
    tpos = raw.find(first, 0, s["chunks"][0]["coff"])
    if tpos < 0:
        raise ValueError("compressed-chunk table not found in the summary")
    head_len = s["chunks"][0]["coff"]
    out = bytearray(raw[:head_len])
    pos = head_len
    body = []
    for k, c in enumerate(chunks):
        old = s["chunks"][k]
        new = bytes(d[c["uoff"]:c["uoff"] + c["usize"]])
        same = (c["usize"] == old["usize"] and new == logical[old["uoff"]:old["uoff"] + old["usize"]])
        comp = raw[old["coff"]:old["coff"] + old["csize"]] if same else compress_chunk(new)
        c["coff"], c["csize"] = pos, len(comp)
        body.append(comp)
        pos += len(comp)
    # the chunk table in the uncompressed summary: patch its entries
    for k, c in enumerate(chunks):
        struct.pack_into(">IIII", out, tpos + 16 * k, c["uoff"], c["usize"], c["coff"], c["csize"])
    out += b"".join(body)
    out += b"\0" * (-len(out) % PAD)
    return bytes(out)


def update_toc(toc: str, sizes: dict[str, int]) -> str:
    """PS3TOC.txt lines 'size 0 0 ..\\StrangleholdGame\\CookedPS3\\<file> 0' -> new sizes for the rewritten files."""
    out = []
    for line in toc.splitlines(keepends=True):
        parts = line.split(" ")
        if len(parts) >= 5:
            name = parts[3].replace("\\", "/").rsplit("/", 1)[-1].lower()
            if name in sizes:
                parts[0] = str(sizes[name])
                line = " ".join(parts)
        out.append(line)
    return "".join(out)


# ------------------------------------------------------------------------------------------------ fit
def target_of(mesh: dict) -> dict:
    """The retarget target (sm64_swap frame: left +X, up +Y, front +Z; centimetres) of a stock mesh."""
    W = M.bind_pose(mesh["bones"])
    T = W[:, :3, 3] @ M.GL
    P = np.concatenate([sg["pos"] for g in mesh["groups"] for sg in g]) @ M.GL
    parents = [bn["parent"] if i else -1 for i, bn in enumerate(mesh["bones"])]
    names = [bn["name"].lower() for bn in mesh["bones"]]
    head = names.index("head")
    return {"T": T, "parent": parents, "ground": float(P[:, 1].min()), "joints": len(T),
            "head_h": float(P[:, 1].max() - T[head][1]) * 2, "height": float(np.ptp(P[:, 1]))}


def jmap_of(mesh: dict) -> dict:
    names = {bn["name"].lower(): i for i, bn in enumerate(mesh["bones"])}
    return {r: names[M.ROLE_BONES[r]] for r in JMAP_ROLES if M.ROLE_BONES[r] in names}


def corners(prims: list[dict], layout: dict) -> dict:
    """Retargeted prims -> one welded corner mesh {P, UV (atlas), B, F} (gbox.twin_snakes_swap.corners)."""
    from .auf_swap import _material_key, atlas_uvs
    P, UV, B, F = [], [], [], []
    index: dict = {}
    for p in prims:
        page, tile, size = layout.get(_material_key(p), (0, (0, 0, 1, 1), (1, 1)))
        for tri in np.asarray(p["tris"], int).reshape(-1, 3):
            uv3 = atlas_uvs(p["uv"][tri], tile, size)
            face = []
            for c, v in enumerate(tri):
                key = (tuple(np.round(p["pos"][v], 2)), tuple(np.round(uv3[c], 4)), int(p["J"][v, 0]))
                i = index.get(key)
                if i is None:
                    i = index[key] = len(P)
                    P.append(p["pos"][v])
                    UV.append(uv3[c])
                    B.append(int(p["J"][v, 0]))
                face.append(i)
            if len(set(face)) == 3:
                F.append(face)
    return {"P": np.array(P, float).reshape(-1, 3), "UV": np.array(UV, float).reshape(-1, 2),
            "B": np.array(B, int), "F": np.array(F, int).reshape(-1, 3)}


def nearest(src: np.ndarray, q: np.ndarray, block: int = 2048) -> np.ndarray:
    out = np.zeros(len(q), np.int64)
    for k in range(0, len(q), block):
        d = ((q[k:k + block, None, :] - src[None, :, :]) ** 2).sum(-1)
        out[k:k + block] = d.argmin(1)
    return out


def fit(donor_rig: dict, mesh: dict, scale: dict | None = None, label: str = "", progress=None) -> dict:
    """Donor rig -> per-LOD encoded geometry for one stock mesh + the atlas page."""
    from . import fit_events as FE
    from .auf_swap import build_pages, decimate, donor_materials
    from .sm64_swap import retarget
    tgt = target_of(mesh)
    jm = jmap_of(mesh)
    prims, rep = retarget(donor_rig, tgt, scale, jm)
    FE.weights(prims, jm, "rigid per bone (one RefSkeleton bone per vertex)", len(mesh["bones"]),
               names=[bn["name"] for bn in mesh["bones"]])
    pages, layout = build_pages(donor_materials(prims), [ATLAS])
    cm = corners(prims, layout)
    stock_seg = [sg for g in mesh["groups"] for sg in g]
    sP = np.concatenate([sg["pos"] for sg in stock_seg])
    sF = np.concatenate([sg["frame"] for sg in stock_seg])
    sU1 = np.concatenate([sg["uv1"] for sg in stock_seg])
    lods, reports = [], []
    for k, lod in enumerate(mesh["lod"]):
        target = int(lod["triangles"] * (1.25 if k == 0 else 1.0))
        P, F = (decimate(cm["P"], cm["F"], target) if len(cm["F"]) > target else (cm["P"], cm["F"]))
        used = np.unique(F)
        remap = -np.ones(len(P), np.int64)
        remap[used] = np.arange(len(used))
        P2, F2 = P[used], remap[F]
        P_ms = P2 @ M.GL                                   # back to mesh space (-Y up)
        F_ms = F2[:, [0, 2, 1]]                            # and the game's winding
        nn = nearest(sP, P_ms)
        data, r = lod_bytes(lod, P_ms, sF[nn], cm["UV"][used], sU1[nn], cm["B"][used], F_ms)
        lods.append(data)
        reports.append(r | {"lod": k, "stock_triangles": lod["triangles"]})
        if k == 0:
            FE.stage("decimate", data={"from": int(len(cm["F"])), "to": int(len(F2)), "stock": lod["triangles"],
                                       "lods": len(mesh["lod"])}, prims=[{"pos": P2 * M.SCALE, "tris": F2}])
        if progress:
            progress(None, f"{label}: LOD {k} {r['triangles']} triangles in {r['segments']} segments")
    FE.stage("encode", data={"segments": sum(r["segments"] for r in reports), "lods": len(reports),
                             "bones": reports[0]["bones"], "atlas": f"{ATLAS[0]}x{ATLAS[1]}",
                             "where": "a new SkeletalMesh export appended to the package"})
    return {"lods": lods, "atlas": pages[0], "report": rep | {"lods": reports}}


def flat(size, rgba) -> np.ndarray:
    w, h = size
    return np.broadcast_to(np.array(rgba, np.uint8), (h, w, 4)).copy()


def swap_package(raw: bytes, donor_rig: dict, scale: dict | None = None, label: str = "", progress=None) -> tuple[bytes, dict]:
    """One character package + donor -> new package bytes + report."""
    _s, data = M.load_package(raw)
    pkg = M.Package(data)
    mi = pkg.find("SkeletalMesh")
    if len(mi) != 1:
        raise ValueError(f"expected one SkeletalMesh, found {len(mi)}")
    mesh = M.parse_mesh(pkg, mi[0])
    f = fit(donor_rig, mesh, scale, label, progress)
    new_blob = mesh_blob(pkg, mesh, f["lods"])
    patches = []
    ref = mesh["materials"][0] if mesh["materials"] else 0
    dj = M.pick_diffuse(pkg, mesh, ref)
    textures = {}
    if dj:
        atlas = f["atlas"]
        if atlas.shape[2] == 3:
            atlas = np.concatenate([atlas, np.full(atlas.shape[:2] + (1,), 255, np.uint8)], 2)
        patches += texture_patches(pkg, dj, atlas)
        textures["diffuse"] = pkg.exports[dj - 1]["name"]
        dname = pkg.exports[dj - 1]["name"]
        tex = {pkg.exports[j - 1]["name"]: j for j in pkg.find("Texture2D")}
        for kind, col in (("normal", (128, 128, 255, 255)), ("specular", (20, 20, 20, 255)), ("graypack", (0, 0, 0, 255))):
            n = re.sub("diffuse", kind, dname, flags=re.I)
            if n in tex and n != dname:
                sz = M.texture_mips(pkg, tex[n])["size"]
                patches += texture_patches(pkg, tex[n], flat((min(sz[0], 64), min(sz[1], 64)), col))
                textures[kind] = n
    out = rewrite_package(raw, {mi[0]: new_blob}, patches)
    # proof: the written package reads back with the donor
    _s2, d2 = M.load_package(out)
    p2 = M.Package(d2)
    m2 = M.parse_mesh(p2, mi[0])
    report = f["report"] | {"mesh": mesh["name"], "textures": textures, "bytes": len(out), "stock_bytes": len(raw),
                            "readback_triangles": [l["triangles"] for l in m2["lod"]]}
    return out, report


# ------------------------------------------------------------------------------------------------ mod build / use
def mod_name(slot: str, slugs: list[str]) -> str:
    tag = re.sub(r"[^a-z0-9]+", "_", (slot or "player").lower()).strip("_")
    return f"sh_{tag}_{hashlib.sha256(json.dumps(sorted(slugs)).encode()).hexdigest()[:8]}"


def build_changes(root: Path, toc_text: str, plan: dict[str, tuple], progress=None) -> tuple[dict, dict]:
    """plan {package stem: (donor rig, scale, label)} -> filemods changes {rel path: {bytes}} + report."""
    from . import fit_events as FE
    changes, report, sizes = {}, {}, {}
    for stem, (rig, scale, label, slug) in plan.items():
        FE.model(stem, label, slug)
        try:
            raw = (Path(root) / f"{stem}.xxx").read_bytes()
            out, rep = swap_package(raw, rig, scale, f"{label} as {stem}", progress)
            changes[f"{COOKED}/{stem}.xxx"] = {"bytes": out}
            sizes[f"{stem}.xxx".lower()] = len(out)
            report[stem] = {"status": "built", **rep}
            FE.stage("write", data={"file": f"{stem}.xxx", "bytes": len(out), "stock": len(raw)})
        except Exception as e:                             # noqa: BLE001 - one package must not sink the rest
            report[stem] = {"status": "failed", "reason": f"{type(e).__name__}: {e}"[:400]}
    if sizes:
        changes[TOC] = {"bytes": update_toc(toc_text, sizes).encode("latin1")}
    return changes, report


def _rom_root(ctx, game) -> tuple[Path, Path]:
    from . import characters as C
    rom = C._rom(ctx, game)
    return rom, rom.parent / "StrangleholdGame" / "CookedPS3"


def _donor(ctx, meta: dict) -> tuple[dict, dict | None]:
    from . import characters as C
    from .sm64_swap import load_rig
    rig = meta.get("rig") or {}
    roles = dict(rig.get("roles") or {})
    if not {"hip", "head"} <= roles.keys():
        raise ValueError(f"{meta['slug']}: the collection entry has no hip/head body roles; not retargetable")
    return load_rig(Path(C._local_or_fetch(ctx, meta, meta["model"])), roles), rig.get("scale")


def build_mod(cfg, game: dict, rom: Path, name: str, plan: dict, progress=None) -> dict:
    from . import filemods
    root = rom.parent / "StrangleholdGame" / "CookedPS3"
    toc = (rom.parent / "StrangleholdGame" / "PS3TOC.txt").read_bytes().decode("latin1")
    changes, report = build_changes(root, toc, plan, progress)
    if not any(r["status"] == "built" for r in report.values()):
        raise ValueError("; ".join(f"{k}: {r.get('reason')}" for k, r in report.items())[:800])
    b = filemods.build(cfg, game["game_id"], rom, name, changes, progress)
    return b | {"report": report}


def use(ctx, meta: dict, game: dict, inp) -> dict:
    """characters op=use for Stranglehold (PS3): slot player | tequila[:outfit] | enemy:<class> | enemies |
    model:<package>. Built where the collection is; launched through the session swap."""
    from . import characters as C
    slot = (getattr(inp, "slot", "") or "player").strip().lower()
    stems = packages_for(slot)
    name = mod_name(slot, [meta["slug"]])
    from . import filemods
    have = name in {m["name"] for m in filemods.list_mods(ctx.config, game["game_id"])}
    built = None
    if getattr(inp, "rebuild", False) or not have:
        rig, scale = _donor(ctx, meta)
        rom, _root = _rom_root(ctx, game)
        plan = {st: (rig, scale, meta.get("name", meta["slug"]), meta["slug"]) for st in stems}
        b = build_mod(ctx.config, game, rom, name, plan, ctx.progress)
        built = {k: v for k, v in b.items() if k != "report"} | {
            "packages": {k: v["status"] for k, v in b["report"].items()}}
        C._api(ctx, "POST", f"/api/characters/{meta['slug']}/targets",
               json={"game_id": game["game_id"], "slot": slot, "mod": name, "nodes": [C.HOST_OS],
                     "notes": f"Stranglehold {slot}: {', '.join(stems)}; the game's skeleton and animations kept; "
                              "gameplay verification required"})
    res = {"mod": name, "slot": slot, "build": built, "status": "built_unverified" if built else "ready",
           "replaces": stems, "gameplay_verified": False, "replacement_kind": "native_disc"}
    if getattr(inp, "launch", False):
        sess = C._session(ctx, inp.session_id) if getattr(inp, "session_id", "") else None
        node = sess["session_id"].split("-")[0] if sess else "idle"
        res["launch"] = C._launch(ctx, game["game_id"], name, node)
        res["message"] = (f"Stranglehold is running with {meta['name']} in place of {', '.join(stems)} (mod {name}); "
                          "the new body loads with the next level / multiplayer match.")
    return res


def build_cast(cfg, game: dict, pairs, name: str, progress=None) -> dict:
    """cast_swap's pairs path: [(slot, meta)] -> one mod. -> {mod, slots: {slot: {status, reason?}}}."""
    from . import characters as C
    from .models import CatalogEntry
    from .sm64_swap import load_rig
    from .tools import rom_path
    root = C.library_root(cfg)
    plan, per, owner = {}, {}, {}
    for slot, meta in pairs:
        try:
            rig = meta.get("rig") or {}
            roles = dict(rig.get("roles") or {})
            if not {"hip", "head"} <= roles.keys():
                raise ValueError(f"{meta['slug']}: no hip/head body roles")
            r = load_rig(root / meta["slug"] / meta["model"], roles)
            for st in packages_for(slot):
                plan[st] = (r, rig.get("scale"), meta.get("name", meta["slug"]), meta["slug"])
                owner[st] = slot
        except Exception as e:                             # noqa: BLE001
            per[slot] = {"status": "failed", "reason": str(e)[:400]}
    if not plan:
        return {"mod": None, "slots": per}
    rom = rom_path(CatalogEntry.model_validate(game), cfg)
    try:
        b = build_mod(cfg, game, rom, name, plan, progress)
    except Exception as e:                                 # noqa: BLE001
        return {"mod": None, "slots": per | {s: {"status": "failed", "reason": str(e)[:400]} for s, _m in pairs
                                             if s not in per}}
    for slot, _m in pairs:
        if slot in per:
            continue
        st = [b["report"].get(p, {}) for p, s in owner.items() if s == slot]
        ok = [x for x in st if x.get("status") == "built"]
        per[slot] = {"status": "built"} if ok and len(ok) == len(st) else \
            {"status": "partial" if ok else "failed", "reason": "; ".join(str(x.get("reason")) for x in st
                                                                       if x.get("status") != "built")[:400]}
    return {"mod": name, "slots": per}


def main(argv=None) -> int:
    """python -m gbox.stranglehold_swap <donor.glb> <roles.json> <CookedPS3 dir> <out dir> [slot]: write the packages
    (and PS3TOC.txt) a slot needs into out dir, without a mod folder (offline check)."""
    import sys
    from .sm64_swap import load_rig
    a = list(sys.argv[1:] if argv is None else argv)
    glb, roles, root, out = Path(a[0]), json.loads(Path(a[1]).read_text()), Path(a[2]), Path(a[3])
    slot = a[4] if len(a) > 4 else "tequila:default"
    rig = load_rig(glb, roles)
    out.mkdir(parents=True, exist_ok=True)
    toc_path = root.parent / "PS3TOC.txt"
    toc = toc_path.read_bytes().decode("latin1") if toc_path.is_file() else ""  # keep CRLF
    t0 = time.time()
    changes, report = build_changes(root, toc, {st: (rig, None, glb.stem, glb.stem) for st in packages_for(slot)},
                                    lambda p, m: print(m))
    for rel, ch in changes.items():
        (out / Path(rel).name).write_bytes(ch["bytes"])
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk in ("status", "reason", "bytes", "stock_bytes",
                                                                    "readback_triangles", "textures")}
                      for k, v in report.items()}, indent=1), f"{time.time() - t0:.1f} s")
    return 0 if all(v["status"] == "built" for v in report.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
