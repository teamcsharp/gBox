"""SoulCalibur (Dreamcast, Namco 1999, T-1401N): native fighter, weapon and texture formats (docs/soulcalibur_dc.md).

Containers (HUMAN.DAT and the other *.DAT files on the GD-ROM):

* ``olnk``: ``u32 count, b"olnk", u32 header bytes, u32 total, u32 0`` then ``count`` x ``(u32 offset, u32 size)``
  with offsets relative to the end of the header. An empty entry has size 0. The game's loader (0x8c0ac1a0 /
  0x8c0ac666) opens up to 32 of these archives and reads one entry at a time.
* ``table``: ``u32 count, u32 header bytes, count x u32 end offset`` (the sub-entries of one archive entry; header
  padded to 32 bytes with the "32byte" filler string). ``0x8c01bde0`` returns sub-entry i.

HUMAN.DAT has 21 groups of 10 entries, one group per character id 1..21 (``FUN_8c02e37a`` loads entry
``(chara - 1) * 10 + costume``): entries 0..3 are costumes, 4 the motion pack, 5..9 the weapons ("buki"). A costume
is a table of 9: [0] a texture bank (table: LZ model + 256x256 YUV422 twiddled pages), [1] the character's voice
bank (AICA SOSB/SOSP/SOSD, the same in every costume), [2] LZ cloth/chain parameters, [3] an olnk of three small
tables, [4] face-shape data, [6] LZ data. A weapon is a table of a LZ model and one or two pages.

LZ (``0x8c0ee76c``): a flag byte read LSB first with a sentinel high bit (``0xff`` = seven literals, ``0x00`` = end);
bit 1 = a literal byte, bit 0 = a big-endian u16 ``v``: copy ``((v >> 11) - 1 & 31) + 1`` bytes from
``((v - 1) & 0x7ff) + 1`` back.

Model (after LZ): header 0x20 bytes (``u32 strips offset @0x18, u16 bones @0x1c``), then one 32-byte record per bone:
``u16 stores, u16 adds, u32 vertex offset, u32 extra offset, u16 positions, u16 normals, 4 x s16 rest angles
(65536 = 360 degrees, applied X then Y then Z), 3 x s16 translation (/16000), s16 parent``. A bone's vertex block is
``positions`` then ``normals`` 16-byte rows ``x, y, z, w`` in the bone's space; ``w`` is the skin weight whose low 12
mantissa bits are the output vertex (normal) index: the first ``stores`` rows store ``w * M @ p``, the rest add to it
(the game skins by accumulation, bone by bone). Strips follow: sections of ``u8 material, u8 flags, u8 0, u8 count``
headers with ``count`` x ``(u16 position, u16 normal | 0x8000 on the last, u16 u, u16 v)`` (u / v are the upper half of
a float), a u32 0 closing each section and an empty section closing the list. ``material & 3`` is the texture page
(bank entry 1 + page).
"""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import numpy as np

GAME_IDS = {"c747331797369f74": "SoulCalibur (USA) CHD", "e4ad4831b09591b6": "Soulcalibur (USA) 7z GDI",
            "32bdc48bc550f79b": "Soul Calibur v1.000 GDI"}
EXECUTABLE_SHA256 = "646fd82c5a8c65f2ae91f4a049984f8509387b0b2da5f6f511d1ac876781fa7f"
READER_VERSION = 1
HUMAN = "HUMAN.DAT"
GROUP = 10                                       # HUMAN.DAT entries per character id
COSTUMES, MOTION, WEAPONS = range(0, 4), 4, range(5, 10)
SCALE = 1.0 / 16000.0                            # bone translation units -> model units
LIB_SCALE = 1.0                                  # model units are about metres (Mitsurugi stands 1.83)

# character id - 1 -> (key, name, aliases); id 10 and id 21 hold no body (extra weapons only)
FIGHTERS = [
    (0, "MIT", "Mitsurugi", ["Heishiro Mitsurugi"]),
    (1, "SEU", "Seung Mina", ["Mina"]),
    (2, "TAK", "Taki", []),
    (3, "MAX", "Maxi", []),
    (4, "VOL", "Voldo", []),
    (5, "SOP", "Sophitia", ["Sophitia Alexandra"]),
    (6, "SIE", "Siegfried", ["Siegfried Schtauffen"]),
    (7, "ROC", "Rock", []),
    (8, "HWA", "Hwangseong", ["Hwang", "Hwang Seong-gyeong"]),
    (10, "IVY", "Ivy", ["Isabella Valentine"]),
    (11, "KIL", "Kilik", []),
    (12, "XIA", "Xianghua", ["Chai Xianghua"]),
    (13, "LIZ", "Lizardman", ["Aeon"]),
    (14, "YOS", "Yoshimitsu", []),
    (15, "EDG", "Edge Master", []),
    (16, "NIG", "Nightmare", []),
    (17, "AST", "Astaroth", []),
    (18, "INF", "Inferno", []),
    (19, "CER", "Cervantes", ["Cervantes de Leon"]),
]


# ---------------------------------------------------------------- containers

def olnk(data: bytes) -> list[bytes]:
    """The entries of an olnk archive (empty ones as b"")."""
    n, tag, hdr, _total = struct.unpack_from("<I4sII", data, 0)
    if tag != b"olnk":
        raise ValueError("not an olnk archive")
    out = []
    for i in range(n):
        off, size = struct.unpack_from("<II", data, 0x10 + 8 * i)
        out.append(data[hdr + off:hdr + off + size])
    return out


def olnk_layout(data: bytes) -> list[tuple[int, int]]:
    """[(absolute offset, size)] of every entry."""
    n, tag, hdr, _total = struct.unpack_from("<I4sII", data, 0)
    if tag != b"olnk":
        raise ValueError("not an olnk archive")
    return [(hdr + struct.unpack_from("<I", data, 0x10 + 8 * i)[0], struct.unpack_from("<I", data, 0x14 + 8 * i)[0])
            for i in range(n)]


def table(data: bytes) -> list[bytes]:
    """The sub-entries of a counted table (u32 n, u32 header bytes, n end offsets)."""
    n, hdr = struct.unpack_from("<II", data, 0)
    if not 0 < n < 64 or hdr < 8 + 4 * n or hdr > len(data):
        raise ValueError(f"not a table (n={n}, header={hdr})")
    ends = struct.unpack_from(f"<{n}I", data, 8)
    out, start = [], hdr
    for e in ends:
        if e < start or e > len(data):
            raise ValueError("table entry out of range")
        out.append(data[start:e])
        start = e
    return out


FILLER = bytes.fromhex("ccb5c2cc") * 2 + b"32byte" + bytes.fromhex("b6adb3a6a4cb")


def build_table(parts: list[bytes]) -> bytes:
    """A counted table with the game's 32-byte header padding (byte-exact for the shipped tables)."""
    n = len(parts)
    hdr = (8 + 4 * n + 31) & ~31
    ends, pos = [], hdr
    for p in parts:
        pos += len(p)
        ends.append(pos)
    head = struct.pack(f"<II{n}I", n, hdr, *ends)
    head += (FILLER * (1 + hdr // len(FILLER)))[:hdr - len(head)]
    return head + b"".join(parts)


def build_olnk(entries: list[bytes], header: int | None = None) -> bytes:
    """An olnk archive; entry data are laid out back to back in order (as the shipped archives are)."""
    n = len(entries)
    hdr = header if header is not None else 0x10 + 8 * n
    out = bytearray(struct.pack("<I4sII", n, b"olnk", hdr, 0))
    pos = 0
    for e in entries:
        out += struct.pack("<II", pos, len(e))
        pos += len(e)
    out += b"\0" * (hdr - len(out))
    for e in entries:
        out += e
    struct.pack_into("<I", out, 12, 0)
    return bytes(out)


# ---------------------------------------------------------------- LZ (0x8c0ee76c)

def lz_decompress(src: bytes) -> bytes:
    out = bytearray()
    i, n = 0, len(src)
    while i < n:
        flag = src[i]
        i += 1
        if flag == 0xFF:
            out += src[i:i + 7]
            i += 7
            continue
        if flag == 0:
            return bytes(out)
        while flag != 1:
            bit, flag = flag & 1, flag >> 1
            if bit:
                out.append(src[i])
                i += 1
            else:
                v = (src[i] << 8) | src[i + 1]
                i += 2
                count = (((v >> 11) - 1) & 0x1F) + 1
                back = ((v - 1) & 0x7FF) + 1
                if back > len(out):
                    raise ValueError("LZ reference before the start of the output")
                for _ in range(count):
                    out.append(out[-back])
    raise ValueError("LZ stream has no end marker")


def lz_compress(data: bytes) -> bytes:
    """Greedy encoder for lz_decompress (matches of 2..32 bytes up to 2048 back; 0xff seven-literal runs)."""
    data = bytes(data)
    n = len(data)
    out = bytearray()
    heads: dict[bytes, list[int]] = {}
    i = 0
    tokens: list[tuple] = []
    while i < n:
        best_len, best_back = 0, 0
        if i + 2 <= n:
            key = data[i:i + 2]
            cands = heads.get(key, [])
            for p in reversed(cands[-64:]):
                back = i - p
                if back > 2048:
                    break
                k = 2
                while k < 32 and i + k < n and data[p + k] == data[i + k]:
                    k += 1
                if k > best_len:
                    best_len, best_back = k, back
                    if k == 32:
                        break
        step = best_len if best_len >= 2 else 1
        for j in range(i, min(i + step, n - 1)):
            heads.setdefault(data[j:j + 2], []).append(j)
        if best_len >= 2:
            tokens.append(("m", best_len, best_back))
        else:
            tokens.append(("l", data[i]))
        i += step
    for t in range(0, len(tokens), 7):                     # up to 7 tokens per flag byte (bit 7 = sentinel)
        group = tokens[t:t + 7]
        flag, body = 1 << len(group), bytearray()          # seven literals give 0xff: the decoder's fast path
        for b, tok in enumerate(group):
            if tok[0] == "l":
                flag |= 1 << b
                body.append(tok[1])
            else:
                count, back = tok[1], tok[2]
                v = ((count & 31) << 11) | (back & 0x7FF)  # count 32 -> 0, back 2048 -> 0
                body += bytes((v >> 8, v & 0xFF))
        out.append(flag)
        out += body
    out.append(0)
    return bytes(out)


def pad32(data: bytes) -> bytes:
    return data + b"\0" * (-len(data) % 32)


# ---------------------------------------------------------------- textures: 256x256 YUV422, twiddled

PAGE = 256
_TW: np.ndarray | None = None


def _tw() -> np.ndarray:
    """Linear texel -> twiddled word index of a 256x256 page."""
    global _TW
    if _TW is None:
        from .formats.texture import morton
        ys, xs = np.divmod(np.arange(PAGE * PAGE), PAGE)
        _TW = np.array([morton(int(x), int(y)) for x, y in zip(xs, ys)], np.int64)
    return _TW


def page_rgb(data: bytes) -> np.ndarray:
    """A 256x256 page (twiddled YUV422 words: Y high byte, U / V low byte of the even / odd texel) -> RGB uint8."""
    if len(data) != PAGE * PAGE * 2:
        raise ValueError(f"page is {len(data)} bytes, expected {PAGE * PAGE * 2}")
    words = np.frombuffer(data, "<u2")[_tw()].reshape(PAGE, PAGE).astype(np.int32)
    y = (words >> 8).astype(np.float32)
    c = (words & 0xFF).astype(np.float32)
    u = np.repeat(c[:, 0::2], 2, axis=1) - 128.0
    v = np.repeat(c[:, 1::2], 2, axis=1) - 128.0
    rgb = np.stack([y + 1.375 * v, y - 0.34375 * u - 0.6875 * v, y + 1.71875 * u], -1)
    return np.clip(np.rint(rgb), 0, 255).astype(np.uint8)


def page_encode(rgb: np.ndarray) -> bytes:
    """RGB (256x256x3) -> twiddled YUV422 page (the inverse of page_rgb; chroma averaged over each texel pair)."""
    a = np.asarray(rgb, np.float32)[..., :3]
    if a.shape != (PAGE, PAGE, 3):
        raise ValueError("a page is 256x256 RGB")
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    y = 0.299 * r + 0.587 * g + 0.114 * b
    u = (b - y) / 1.71875 + 128.0
    v = (r - y) / 1.375 + 128.0
    c = np.empty_like(y)
    c[:, 0::2] = (u[:, 0::2] + u[:, 1::2]) / 2
    c[:, 1::2] = (v[:, 0::2] + v[:, 1::2]) / 2
    words = (np.clip(np.rint(y), 0, 255).astype(np.uint16) << 8) | np.clip(np.rint(c), 0, 255).astype(np.uint16)
    out = np.empty(PAGE * PAGE, np.uint16)
    out[_tw()] = words.reshape(-1)
    return out.astype("<u2").tobytes()


# ---------------------------------------------------------------- model

def _f(bits: int) -> float:
    return struct.unpack("<f", struct.pack("<I", bits & 0xFFFFFFFF))[0]


def parse_model(m: bytes) -> dict:
    """A decompressed fighter / weapon model -> bones (records), skin rows and strip sections."""
    if len(m) < 0x20:
        raise ValueError("model too short")
    strips_at, nb = struct.unpack_from("<IH", m, 0x18)
    bones = []
    for i in range(nb):
        o = 0x20 + 32 * i
        stores, adds, voff, xoff, npos, nnrm = struct.unpack_from("<HHIIHH", m, o)
        ang = struct.unpack_from("<4h", m, o + 16)
        tr = struct.unpack_from("<3h", m, o + 24)
        parent = struct.unpack_from("<h", m, o + 30)[0]
        if parent >= i or parent < -1:
            raise ValueError(f"bone {i}: parent {parent} is not an earlier bone")
        if stores + adds != npos or voff + 16 * (npos + nnrm) > len(m):
            raise ValueError(f"bone {i}: vertex block out of range")
        rows = np.frombuffer(m, "<f4", (npos + nnrm) * 4, voff).reshape(-1, 4).astype(np.float64)
        wbits = np.frombuffer(m, "<u4", (npos + nnrm) * 4, voff).reshape(-1, 4)[:, 3].astype(np.int64)
        weight = np.frombuffer((wbits & ~0xFFF).astype("<u4").tobytes(), "<f4").astype(np.float64)
        bones.append({"index": i, "stores": stores, "adds": adds, "vertex_offset": voff, "extra_offset": xoff,
                      "positions": npos, "normals": nnrm, "angles": ang, "translation": tr, "parent": parent,
                      "rows": rows[:, :3], "slot": wbits & 0xFFF, "weight": weight})
    sections, o = [], strips_at
    while True:
        strips = []
        while True:
            if o + 4 > len(m):
                raise ValueError("strip list runs past the model")
            h = m[o:o + 4]
            o += 4
            if h == b"\0\0\0\0":
                break
            n = h[3]
            if n < 3 or o + 8 * n > len(m):
                raise ValueError(f"bad strip header {h.hex()} at 0x{o - 4:x}")
            rec = np.frombuffer(m, "<u2", 4 * n, o).reshape(n, 4).astype(np.int64)
            o += 8 * n
            if not rec[-1, 1] & 0x8000 or (rec[:-1, 1] & 0x8000).any():
                raise ValueError(f"strip end flag misplaced before 0x{o:x}")
            uv = np.frombuffer((rec[:, 2:] << 16).astype("<u4").tobytes(), "<f4").reshape(n, 2).astype(np.float64)
            strips.append({"material": h[0], "flags": h[1], "pad": h[2], "pos": rec[:, 0] & 0x7FFF,
                           "nrm": rec[:, 1] & 0x7FFF, "uv": uv, "raw_uv": rec[:, 2:]})
        if not strips:
            break
        sections.append(strips)
    return {"header": m[:0x18], "strips_offset": strips_at, "strips_end": o, "bones": bones, "sections": sections,
            "tail": m[o:], "size": len(m)}


def _rot(axis: int, a: float) -> np.ndarray:
    c, s = np.cos(a), np.sin(a)
    r = np.eye(3)
    i, j = [(1, 2), (2, 0), (0, 1)][axis]
    r[i, i], r[i, j], r[j, i], r[j, j] = c, -s, s, c
    return r


def bone_local(b: dict) -> np.ndarray:
    """Rest transform of a bone relative to its parent: R = Rz @ Ry @ Rx (angles in 1/65536 turns), T / 16000."""
    a = [x * 2 * np.pi / 65536.0 for x in b["angles"][:3]]
    m = np.eye(4)
    m[:3, :3] = _rot(2, a[2]) @ _rot(1, a[1]) @ _rot(0, a[0])
    m[:3, 3] = np.array(b["translation"], float) * SCALE
    return m


def bone_world(bones: list[dict]) -> list[np.ndarray]:
    out: list[np.ndarray] = []
    for b in bones:
        loc = bone_local(b)
        out.append(out[b["parent"]] @ loc if b["parent"] >= 0 else loc)
    return out


def skin(model: dict, world: list[np.ndarray] | None = None) -> dict:
    """Accumulate every bone's rows like the game: positions, normals and per-vertex influences {bone: weight}."""
    bones = model["bones"]
    world = world or bone_world(bones)
    npos = 1 + max((int(b["slot"][:b["positions"]].max()) for b in bones if b["positions"]), default=-1)
    nnrm = 1 + max((int(b["slot"][b["positions"]:].max()) for b in bones if b["normals"]), default=-1)
    P, N = np.zeros((npos, 3)), np.zeros((max(nnrm, 1), 3))
    infl: list[dict] = [dict() for _ in range(npos)]
    for b, W in zip(bones, world):
        k = b["positions"]
        rows, slot, w = b["rows"], b["slot"], b["weight"]
        q = rows[:k] @ W[:3, :3].T + W[:3, 3]
        for r in range(k):
            s = int(slot[r])
            if r < b["stores"]:
                P[s] = w[r] * q[r]
            else:
                P[s] += w[r] * q[r]
            infl[s][b["index"]] = infl[s].get(b["index"], 0.0) + float(w[r])
        n = rows[k:] @ W[:3, :3].T
        for r in range(len(n)):
            N[int(slot[k + r])] += w[k + r] * n[r]
    N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-9)
    return {"positions": P, "normals": N, "influences": infl, "world": world}


def strip_triangles(n: int):
    """Corner triples of an n-vertex strip, alternating winding."""
    return [(k, k + 1, k + 2) if k % 2 == 0 else (k + 1, k, k + 2) for k in range(n - 2)]


# ---------------------------------------------------------------- GLB export

# game model space -> library frame (+Y up, facing +Z, left at +X). Fighters face +Z (the face strips sit in front
# of the head bone) but the game's space is left-handed (texture text reads mirrored in a right-handed reading), so
# X is mirrored (det -1; mesh_arrays flips the winding): the game's -X side is the fighter's left.
FRAME = np.diag([-1.0, 1.0, 1.0])


def _quat(R: np.ndarray) -> list[float]:
    from .doapp_chars import _quat as q
    return q(R)


def _png(rgba: np.ndarray) -> bytes:
    from .doapp_chars import _png as p
    return p(np.ascontiguousarray(rgba, np.uint8))


def mesh_arrays(model: dict, sk: dict, frame: np.ndarray = FRAME) -> dict:
    """Unique corners per material: {material: {pos, nrm, uv, joints, weights, tris}} in the library frame."""
    P = sk["positions"] @ frame.T
    N = -sk["normals"] @ frame.T                     # stored normals point inward (lit as -N); outward here
    flip = np.linalg.det(frame) < 0
    out: dict[int, dict] = {}
    for sec in model["sections"]:
        for s in sec:
            mat = int(s["material"])
            d = out.setdefault(mat, {"key": {}, "pos": [], "nrm": [], "uv": [], "src": [], "tris": []})
            ids = []
            for p, n, uv in zip(s["pos"], s["nrm"], s["uv"]):
                key = (int(p), int(n), float(uv[0]), float(uv[1]))
                if key not in d["key"]:
                    d["key"][key] = len(d["pos"])
                    d["pos"].append(P[p])
                    d["nrm"].append(N[n] if n < len(N) else np.array([0.0, 1.0, 0.0]))
                    d["uv"].append(uv)
                    d["src"].append(int(p))
                ids.append(d["key"][key])
            for a, b, c in strip_triangles(len(ids)):
                if len({ids[a], ids[b], ids[c]}) == 3:
                    d["tris"].append((ids[a], ids[c], ids[b]) if flip else (ids[a], ids[b], ids[c]))
    for d in out.values():
        J = np.zeros((len(d["src"]), 4), np.uint16)
        W = np.zeros((len(d["src"]), 4), np.float32)
        for v, src in enumerate(d["src"]):
            top = sorted(sk["influences"][src].items(), key=lambda kv: -kv[1])[:4]
            tot = sum(w for _, w in top) or 1.0
            for c, (j, w) in enumerate(top):
                J[v, c], W[v, c] = j, w / tot
            if not top:
                W[v, 0] = 1.0
        d.update(pos=np.array(d["pos"], np.float32).reshape(-1, 3), nrm=np.array(d["nrm"], np.float32).reshape(-1, 3),
                 uv=np.array(d["uv"], np.float32).reshape(-1, 2), joints=J, weights=W,
                 tris=np.array(d["tris"], np.uint32).reshape(-1, 3))
        d.pop("key")
    return out


def write_glb(path: Path, parts: list[dict], bones: list[dict], world: list[np.ndarray], pages: list[np.ndarray],
              name: str, extras: dict | None = None, frame: np.ndarray = FRAME,
              bone_names: list[str] | None = None, parents: list[int] | None = None) -> Path:
    """Skinned GLB: joint nodes from the rest pose, one primitive per (part, material), pages as PNG textures.
    parts: [{"arrays": mesh_arrays(...), "pages": [page index -> texture index]}]; parents overrides the hierarchy
    (world matrices are kept, so a re-parented joint keeps its place)."""
    parents = list(parents) if parents is not None else [b["parent"] for b in bones]
    bin_, views, accs = bytearray(), [], []

    def view(data: bytes, target=None):
        while len(bin_) % 4:
            bin_.append(0)
        views.append({"buffer": 0, "byteOffset": len(bin_), "byteLength": len(data), **({"target": target} if target else {})})
        bin_.extend(data)
        return len(views) - 1

    def acc(arr, typ, ctype=5126, target=34962, minmax=False):
        arr = np.ascontiguousarray(arr)
        x = {"bufferView": view(arr.tobytes(), target), "componentType": ctype, "count": len(arr), "type": typ}
        if minmax:
            x["min"], x["max"] = arr.reshape(len(arr), -1).min(0).tolist(), arr.reshape(len(arr), -1).max(0).tolist()
        accs.append(x)
        return len(accs) - 1

    C = np.eye(4)
    C[:3, :3] = frame
    Ci = np.linalg.inv(C)
    Wl = [C @ W @ Ci for W in world]                     # joint world matrices in the library frame
    nodes = []
    names = bone_names or [f"b{i:02d}" for i in range(len(bones))]
    for i in range(len(bones)):
        L = Wl[i] if parents[i] < 0 else np.linalg.inv(Wl[parents[i]]) @ Wl[i]
        nodes.append({"name": names[i], "translation": L[:3, 3].tolist(), "rotation": _quat(L[:3, :3])})
    for i, p in enumerate(parents):
        if p >= 0:
            nodes[p].setdefault("children", []).append(i)
    roots = [i for i, p in enumerate(parents) if p < 0]
    images, textures, materials, prims = [], [], [], []
    for k, rgb in enumerate(pages):
        rgba = np.concatenate([rgb, np.full(rgb.shape[:2] + (1,), 255, np.uint8)], -1)
        images.append({"bufferView": view(_png(rgba)), "mimeType": "image/png", "name": f"{name}_page{k}"})
        textures.append({"source": k, "sampler": 0})
    mat_index: dict[tuple, int] = {}
    for pi, part in enumerate(parts):
        for mat, d in sorted(part["arrays"].items()):
            if not len(d["tris"]):
                continue
            tex = part["pages"][mat & 3] if (mat & 3) < len(part["pages"]) else None
            key = (tex, mat & 0xFC)
            if key not in mat_index:
                m = {"name": f"{name}_m{len(materials)}_{mat:02x}", "doubleSided": bool(mat & 0x40) or not (mat & 0x10),
                     "pbrMetallicRoughness": {"metallicFactor": 0.0, "roughnessFactor": 0.9,
                                              **({"baseColorTexture": {"index": tex}} if tex is not None else {})}}
                mat_index[key] = len(materials)
                materials.append(m)
            prims.append({"attributes": {"POSITION": acc(d["pos"], "VEC3", minmax=True), "NORMAL": acc(d["nrm"], "VEC3"),
                                         "TEXCOORD_0": acc(d["uv"], "VEC2"), "JOINTS_0": acc(d["joints"], "VEC4", 5123),
                                         "WEIGHTS_0": acc(d["weights"], "VEC4")},
                          "indices": acc(d["tris"].reshape(-1), "SCALAR", 5125, 34963), "material": mat_index[key]})
    ibm = np.array([np.linalg.inv(W).T.reshape(16) for W in Wl], np.float32)
    skin_ = {"name": f"{name}_rig", "joints": list(range(len(bones))), "skeleton": roots[0],
             "inverseBindMatrices": acc(ibm, "MAT4", target=None)}
    nodes.append({"name": name, "mesh": 0, "skin": 0})
    gl = {"asset": {"version": "2.0", "generator": "gbox.soulcalibur_dc", **({"extras": extras} if extras else {})},
          "scene": 0, "scenes": [{"name": name, "nodes": roots + [len(nodes) - 1]}], "nodes": nodes,
          "meshes": [{"name": name, "primitives": prims}], "skins": [skin_], "materials": materials,
          "images": images, "textures": textures,
          "samplers": [{"magFilter": 9729, "minFilter": 9729, "wrapS": 10497, "wrapT": 10497}],
          "accessors": accs, "bufferViews": views, "buffers": [{"byteLength": 0}]}
    while len(bin_) % 4:
        bin_.append(0)
    gl["buffers"][0]["byteLength"] = len(bin_)
    js = json.dumps(gl, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    out = struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(bin_))
    out += struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(bin_), 0x004E4942) + bytes(bin_)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(out)
    return path


# ---------------------------------------------------------------- the fighter skeleton: body roles

# bones 0..17 are the motion skeleton every fighter shares (two roots: 0 = waist / upper body, 11 = pelvis / legs);
# on the game's -X side (the fighter's left, see FRAME) bones 3..6 are the left arm and 12..14 the left leg; 7..10 and
# 15..17 are the right
CORE_ROLES = {"hip": 11, "chest": 1, "neck": 2, "l_clav": 3, "l_upper": 4, "l_fore": 5, "l_hand": 6,
              "r_clav": 7, "r_upper": 8, "r_fore": 9, "r_hand": 10, "l_thigh": 12, "l_shin": 13, "l_foot": 14,
              "r_thigh": 15, "r_shin": 16, "r_foot": 17}
CORE_PARENTS = [-1, 0, 1, 1, 3, 4, 5, 1, 7, 8, 9, -1, 11, 12, 13, 11, 15, 16]
BONE_NAMES = {0: "waist", 1: "spine", 2: "neck", 3: "l_clavicle", 4: "l_upper_arm", 5: "l_forearm", 6: "l_hand",
              7: "r_clavicle", 8: "r_upper_arm", 9: "r_forearm", 10: "r_hand", 11: "pelvis", 12: "l_thigh",
              13: "l_shin", 14: "l_foot", 15: "r_thigh", 16: "r_shin", 17: "r_foot"}


def roles(model: dict) -> dict[str, int]:
    """The 18 body roles of a fighter model (bone indices). The head is the child of the neck (bone 2) that carries
    the most skin rows; fighters whose bone 19 hangs off the waist (Voldo, Rock, Yoshimitsu, Inferno) still have
    their head under the neck."""
    bones = model["bones"]
    if len(bones) < 18 or [b["parent"] for b in bones[:18]] != CORE_PARENTS:
        raise ValueError("not a fighter skeleton (bones 0..17 differ from the shared motion skeleton)")
    out = dict(CORE_ROLES)
    kids = [b for b in bones if b["parent"] == 2 and b["positions"]]
    out["head"] = max(kids, key=lambda b: b["positions"])["index"] if kids else 2
    return out


def glb_parents(bones: list[dict]) -> list[int]:
    """The hierarchy written to GLBs: the waist (0) under the pelvis (11), so hip -> chest -> neck -> head is one
    chain (both roots sit at the origin, so no joint moves)."""
    par = [b["parent"] for b in bones]
    if len(par) > 11 and par[0] == -1 and par[11] == -1:
        par[0] = 11
    return par


def bone_names(model: dict) -> list[str]:
    head = roles(model)["head"] if len(model["bones"]) >= 18 else None
    return [("head" if i == head else BONE_NAMES.get(i, f"b{i:02d}")) for i in range(len(model["bones"]))]


# ---------------------------------------------------------------- reading the disc

def human_entries(human: bytes) -> list[bytes]:
    return olnk(human)


def costume_parts(entry: bytes) -> dict:
    """A costume entry -> {model (decompressed), pages (raw), table, bank}."""
    t = table(entry)
    bank = table(t[0])
    return {"table": t, "bank": bank, "model": lz_decompress(bank[0]), "pages": bank[1:]}


def weapon_parts(entry: bytes) -> dict:
    t = table(entry)
    return {"table": t, "model": lz_decompress(t[0]), "pages": t[1:]}


def fighter(key: str):
    q = key.strip().casefold()
    for g, k, name, aliases in FIGHTERS:
        if q in {k.casefold(), name.casefold(), *(a.casefold() for a in aliases)} or q == f"fighter:{k}".casefold():
            return g, k, name
    raise ValueError(f"Unknown SoulCalibur fighter {key!r}")


def costumes_of(entries: list[bytes], group: int) -> list[int]:
    return [c for c in COSTUMES if entries[group * GROUP + c]]


def weapons_of(entries: list[bytes], group: int) -> list[int]:
    return [w for w in WEAPONS if entries[group * GROUP + w]]


def export(human: bytes, group: int, costume: int, out: Path, name: str, weapon: int | None = None,
           extras: dict | None = None) -> dict:
    """One fighter costume (+ its first weapon, attached to the right hand) -> rigged, textured GLB."""
    entries = olnk(human)
    cp = costume_parts(entries[group * GROUP + costume])
    body = parse_model(cp["model"])
    sk = skin(body)
    rl = roles(body)
    pages = [page_rgb(p) for p in cp["pages"]]
    bones = [dict(b) for b in body["bones"]]
    world = list(sk["world"])
    parents = glb_parents(body["bones"])
    names = bone_names(body)
    parts = [{"arrays": mesh_arrays(body, sk), "pages": list(range(len(pages)))}]
    weapon_info = None
    wlist = weapons_of(entries, group)
    if weapon is None and wlist:
        weapon = wlist[0]
    if weapon is not None and entries[group * GROUP + weapon]:
        wp = weapon_parts(entries[group * GROUP + weapon])
        wm = parse_model(wp["model"])
        base = len(bones)
        # the first weapon root (the blade) goes to the right hand, further roots (sheath, shield, second blade) to
        # the left hand; their in-game placement comes from the motion, this is the rest attachment
        holder = []
        for b in wm["bones"]:
            if b["parent"] < 0:
                holder.append(rl["r_hand"] if not any(h is not None for h in holder) else rl["l_hand"])
            else:
                holder.append(None)
        wlocal = bone_world(wm["bones"])
        wworld = []
        for i, b in enumerate(wm["bones"]):
            root = i
            while wm["bones"][root]["parent"] >= 0:
                root = wm["bones"][root]["parent"]
            wworld.append(world[holder[root]] @ wlocal[i])
        wsk = skin(wm, wworld)
        hand = rl["r_hand"]
        for i, b in enumerate(wm["bones"]):
            nb = dict(b)
            nb["index"] = base + i
            bones.append(nb)
            parents.append(holder[i] if b["parent"] < 0 else base + b["parent"])
            names.append(f"weapon_{i}")
        world += wworld
        wsk["influences"] = [{base + j: w for j, w in d.items()} for d in wsk["influences"]]
        first = len(pages)
        pages += [page_rgb(p) for p in wp["pages"]]
        parts.append({"arrays": mesh_arrays(wm, wsk), "pages": list(range(first, len(pages)))})
        weapon_info = {"entry": group * GROUP + weapon, "slot": weapon, "bones": len(wm["bones"]),
                       "attached_to": sorted({names[h] for h in holder if h is not None}),
                       "placement": "first weapon root at the right hand's rest frame, other roots at the left hand "
                                    "(in game the motion places the weapon)"}
    glb = write_glb(Path(out), parts, bones, world, pages, name, extras=extras, bone_names=names, parents=parents)
    tris = sum(len(d["tris"]) for p in parts for d in p["arrays"].values())
    return {"glb": glb, "roles": {r: names[j] for r, j in rl.items()}, "role_bones": rl, "bones": len(body["bones"]),
            "triangles": tris, "positions": len(sk["positions"]), "pages": len(cp["pages"]), "weapon": weapon_info,
            "model_bytes": len(cp["model"])}
