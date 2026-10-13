"""Synthetic Enter the Matrix / Path of Neo data for the tests: a flat ISO9660 image, a CD-type CHD v5 around it,
a WAD1.DFU archive (both name hashes), and DC patch models (.dcn) on a made-up 89-joint humanoid skeleton with the
game's joint tree (no game bytes)."""
import lzma
import struct
import zlib

import numpy as np

from gbox import shiny_dfu

# ---------------------------------------------------------------- ISO9660 (flat root, enough for gbox's readers)


def _dirrec(name: bytes, lba: int, size: int, flags: int) -> bytes:
    r = bytearray(33 + len(name) + (1 - len(name) % 2))
    r[0] = len(r)
    struct.pack_into("<I", r, 2, lba)
    struct.pack_into(">I", r, 6, lba)
    struct.pack_into("<I", r, 10, size)
    struct.pack_into(">I", r, 14, size)
    r[25] = flags
    r[32] = len(name)
    r[33:33 + len(name)] = name
    return bytes(r)


def make_iso(files: dict, volume: str = "TESTDISC") -> bytes:
    """{NAME: bytes} -> a 2048-byte-sector ISO9660 image: PVD at 16, root directory at 18, files from 20."""
    lba, recs, data = 20, [_dirrec(b"\0", 18, 2048, 2), _dirrec(b"\1", 18, 2048, 2)], []
    for name, blob in files.items():
        recs.append(_dirrec(f"{name};1".encode(), lba, len(blob), 0))
        data.append((lba, blob))
        lba += max(1, (len(blob) + 2047) // 2048)
    root = b"".join(recs)
    assert len(root) <= 2048
    img = bytearray(lba * 2048)
    pvd = bytearray(2048)
    pvd[0], pvd[1:6], pvd[6] = 1, b"CD001", 1
    pvd[40:72] = volume.encode().ljust(32)
    pvd[156:190] = _dirrec(b"\0", 18, 2048, 2)
    img[16 * 2048:17 * 2048] = pvd
    img[17 * 2048] = 255
    img[18 * 2048:18 * 2048 + len(root)] = root
    for at, blob in data:
        img[at * 2048:at * 2048 + len(blob)] = blob
    return bytes(img)


# ---------------------------------------------------------------- CHD v5, CD type (cdlz / cdzl / self / none hunks)
class _BitWriter:
    def __init__(self):
        self.bits = []

    def put(self, v: int, n: int):
        self.bits += [(v >> (n - 1 - i)) & 1 for i in range(n)]

    def bytes(self) -> bytes:
        b = self.bits + [0] * (-len(self.bits) % 8)
        return bytes(int("".join(map(str, b[i:i + 8])), 2) for i in range(0, len(b), 8))


def make_chd(iso: bytes, frames_per_hunk: int = 8) -> bytes:
    """A MODE1 (cooked) single-track CHD v5: hunk 0 cdzl, other hunks cdlz, repeats as self references, the last
    hunk stored uncompressed."""
    frame, sector, sub = 2448, 2352, 96
    nfr = len(iso) // 2048
    hb = frames_per_hunk * frame
    nh = -(-nfr // frames_per_hunk)
    raw = []
    for h in range(nh):
        buf = bytearray(hb)
        for k in range(frames_per_hunk):
            n = h * frames_per_hunk + k
            if n < nfr:
                buf[k * frame:k * frame + 2048] = iso[n * 2048:(n + 1) * 2048]
        raw.append(bytes(buf))
    meta = (f"TRACK:1 TYPE:MODE1 SUBTYPE:NONE FRAMES:{nfr} PREGAP:0 PGTYPE:MODE1 PGSUB:NONE POSTGAP:0").encode() + b"\0"
    meta_blob = b"CHT2" + bytes([1]) + len(meta).to_bytes(3, "big") + struct.pack(">Q", 0) + meta
    first = 124 + len(meta_blob)
    payload, types, lengths, selfs = bytearray(), [], [], []
    seen = {}
    for h, hunk in enumerate(raw):
        if hunk in seen:
            types.append(5)
            selfs.append(seen[hunk])
            lengths.append(0)
            continue
        seen[hunk] = h
        if h == nh - 1 and nh > 2:
            types.append(4)
            lengths.append(hb)
            payload += hunk
            continue
        secs = b"".join(hunk[k * frame:k * frame + sector] for k in range(frames_per_hunk))
        subs = b"".join(hunk[k * frame + sector:(k + 1) * frame] for k in range(frames_per_hunk))
        if h == 0:
            c = zlib.compressobj(9, zlib.DEFLATED, -15)
            base = c.compress(secs) + c.flush()
            types.append(1)
        else:
            c = lzma.LZMACompressor(lzma.FORMAT_RAW, filters=[{"id": lzma.FILTER_LZMA1, "dict_size": 1 << 20,
                                                               "lc": 3, "lp": 0, "pb": 2}])
            base = c.compress(secs) + c.flush()
            types.append(0)
        z = zlib.compressobj(9, zlib.DEFLATED, -15)
        blob = bytes((frames_per_hunk + 7) // 8) + len(base).to_bytes(2, "big") + base + z.compress(subs) + z.flush()
        lengths.append(len(blob))
        payload += blob
    lbits = max(lengths).bit_length()
    sbits = max(1, (nh - 1).bit_length())
    bw = _BitWriter()
    for _ in range(16):
        bw.put(4, 4)                                       # every code 4 bits long: code == symbol
    for t in types:
        bw.put(t, 4)
    si = iter(selfs)
    for t, ln in zip(types, lengths):
        if t <= 3:
            bw.put(ln, lbits)
            bw.put(0, 16)
        elif t == 4:
            bw.put(0, 16)
        else:
            bw.put(next(si), sbits)
    mbits = bw.bytes()
    map_off = first + len(payload)
    mh = struct.pack(">I", len(mbits)) + first.to_bytes(6, "big") + struct.pack(">H", 0) + bytes([lbits, sbits, 0, 0])
    hdr = bytearray(124)
    hdr[:8] = b"MComprHD"
    struct.pack_into(">II", hdr, 8, 124, 5)
    hdr[16:32] = b"cdlzcdzlcdfl\0\0\0\0"
    struct.pack_into(">QQQII", hdr, 32, nh * hb, map_off, 124, hb, frame)
    return bytes(hdr) + meta_blob + bytes(payload) + mh + mbits


# ---------------------------------------------------------------- WAD1.DFU
def make_dfu(files: dict, variant: str = "etm", packed=(), split: int | None = None,
             seeds=(22313, 2067, 674)) -> tuple[bytes, bytes]:
    """{name: bytes} -> (WAD1.DFU, WAD1_B.DFU); names in `packed` are zlib streams; `split` cuts the data space."""
    rows, blobs = [], []
    for name, data in files.items():
        stored = zlib.compress(data, 9) if name in packed else data
        rows.append([shiny_dfu.name_hash(name, seeds, variant), len(stored), 0, len(data)])
        blobs.append(stored)
    order = sorted(range(len(rows)), key=lambda i: rows[i][0])
    base = (0x18 + 16 * len(rows) + 0x7FF) & ~0x7FF
    data, off = bytearray(), 0
    for i in order:
        rows[i][2] = off
        data += blobs[i]
        off += len(blobs[i])
        while off % 4:
            data += b"\0"
            off += 1
    head = struct.pack("<6I", len(rows), *seeds, 2112, 32) + b"".join(struct.pack("<4I", *rows[i]) for i in order)
    whole = head.ljust(base, b"\0") + bytes(data)
    cut = len(whole) if split is None else base + split
    return whole[:cut], whole[cut:]


# ---------------------------------------------------------------- .dcn
PARENTS = ([-1, 0, 0, 0, 1, 3, 2, 6, 4, 5, 8, 7, 7, 9, 7, 12, 10, 11, 13, 14, 17, 19, 20, 21, 22, 23, 24, 25, 27, 26]
           + [28] * 5 + list(range(30, 40)) + [29] * 5 + list(range(45, 55)) + [15] * 29)
_BODY = {0: (0, 90, 0), 1: (9, 88, 0), 2: (0, 95, 0), 3: (-9, 88, 0), 4: (9.5, 70, 0), 5: (-9.5, 70, 0),
         6: (0, 105, 0), 7: (0, 125, 0), 8: (10, 48, 0.4), 9: (-10, 48, 0.4), 10: (11, 10, 1.2), 11: (3, 127, 0),
         12: (0, 133, -0.3), 13: (-11, 10, 1.2), 14: (-3, 127, 0), 15: (0, 141.5, -1.1), 16: (11.5, 2.5, -10),
         17: (14, 126, -0.1), 18: (-11.5, 2.5, -10), 19: (-14, 126, -0.1), 20: (19.5, 115, -2), 21: (-19.5, 115, -2),
         22: (26.5, 103, -4.3), 23: (-26.5, 103, -4.3), 24: (30.3, 98.8, -14.4), 25: (-30.3, 98.8, -14.4),
         26: (32.8, 96, -21.1), 27: (-32.8, 96, -21.1)}


def skeleton() -> np.ndarray:
    """89 rest positions (model space: cm, +Y up, facing -Z, left at +X) on the game's joint tree."""
    P = np.zeros((89, 3))
    for i, p in _BODY.items():
        P[i] = p
    P[28], P[29] = P[27], P[26]
    for i in range(30, 60):
        par = PARENTS[i]
        side = -1 if i < 45 else 1
        k = (i - 30) % 15
        P[i] = P[par] + np.array([side * (0.9 + 0.13 * k), -1.1 - 0.07 * k, -2.3 - 0.11 * k])
    rng = np.random.default_rng(7)
    for i in range(60, 89):
        d = rng.normal(size=3)
        P[i] = P[15] + d / np.linalg.norm(d) * (8.0 + 0.137 * (i - 60))
    return P


def offsets(P: np.ndarray) -> np.ndarray:
    return np.array([P[i] - (P[PARENTS[i]] if PARENTS[i] >= 0 else 0) for i in range(len(P))])


def _vert(pos, nrm, joint, weights=None) -> bytes:
    b = struct.pack("<3fI", *pos, joint * 4) + struct.pack("<3fI", *nrm, 1 if weights else 0)
    if weights:
        (j0, w0), (j1, w1) = weights
        b += struct.pack("<IfIf", j0 * 4, w0, j1 * 4, w1)
    return b


def quad_packet(slot, uv4, cps, joint, weights=None) -> bytes:
    """uv4: corner UVs of control points 0, 12, 15, 3; cps: 16 positions row-major."""
    body = b"".join(_vert(p, (0, 0, -1), joint, weights) for p in cps)
    size = 4 + len(body) // 16
    hdr = b"".join(struct.pack("<2f2I", u, v, (slot if k == 0 else size if k == 1 else 0), 0)
                   for k, (u, v) in enumerate(uv4))
    return hdr + body


def tri_patch_packet(slot, uv3, cps, joint) -> bytes:
    body = b"".join(_vert(p, (0, 0, -1), joint) for p in cps)
    size = 3 + len(body) // 16
    hdr = b"".join(struct.pack("<2f2I", u, v, (slot if k == 0 else size if k == 1 else 0), 0)
                   for k, (u, v) in enumerate(uv3))
    return hdr + body


def tri3_packet(slot, uvs, pos, joint) -> bytes:
    b = struct.pack("<4I", slot, 10, 3, 0)
    for uv, p in zip(uvs, pos):
        b += struct.pack("<2f2I", *uv, 0, 0) + _vert(p, (0, 0, -1), joint)
    return b


def flat_quad(center, size, joint):
    """A flat 4 x 4 control grid (a planar Bezier patch) facing -Z (the character's front)."""
    cx, cy, cz = center
    return [(cx + size * (j / 3 - 0.5), cy - size * (i / 3 - 0.5), cz) for i in range(4) for j in range(4)], joint


def mesh(packets: dict, flags=64, group=-1, group_joints=()) -> bytes:
    """packets: {0: [quad packets], 1: [triangle patches], 2: [triangles]} -> 0x50 header + joint list + blocks."""
    blocks = [b"".join(packets.get(k, [])) for k in range(4)]
    hdr = bytearray(0x50)
    hdr[:0x14] = b"synthetic\0".ljust(0x14, b"\0")
    struct.pack_into("<4I", hdr, 0x14, 0xFFFFFFFF, flags, 0x78001045, 0)
    struct.pack_into("<4I", hdr, 0x24, *[len(packets.get(k, [])) for k in range(4)])
    struct.pack_into("<iI", hdr, 0x34, group, len(group_joints))
    struct.pack_into("<4I", hdr, 0x3C, *[len(b) for b in blocks])
    gj = struct.pack(f"<{len(group_joints)}i", *group_joints) if group_joints else b""
    pad = ((len(group_joints) + 3) & ~3) - len(group_joints) if group_joints else 0
    return bytes(hdr) + gj + b"\0" * (4 * pad) + b"".join(blocks)


def texture(name: str, w: int, h: int, bpp: int, rgba_fn=None) -> tuple[bytes, bytes]:
    """(0x40 header, pixels + palette) for a 4 / 8-bit CLUT or 16-bit direct texture."""
    hdr = bytearray(0x40)
    hdr[:0x20] = name.encode().ljust(0x20, b"\0")
    if bpp == 16:
        px = np.zeros((h, w), "<u2")
        px[:] = 31 | (1 << 15)                              # red
        data, pal = px.tobytes(), b""
    else:
        n = 16 if bpp == 4 else 256
        pal = np.zeros((n, 4), np.uint8)
        pal[:, 0] = np.arange(n) * (255 // (n - 1))
        pal[:, 3] = 255
        idx = (np.arange(w * h) % n).astype(np.uint8)
        data = (idx[0::2] | (idx[1::2] << 4)).astype(np.uint8).tobytes() if bpp == 4 else idx.tobytes()
        pal = pal.tobytes()
    struct.pack_into("<6I", hdr, 0x20, w, h, 0, len(data), 0, len(pal))
    return bytes(hdr), data + pal


def material(name: str, tex: int, env: int = -1, flag: float = 0.0) -> bytes:
    r = bytearray(0x48)
    r[:0x20] = name.encode().ljust(0x20, b"\0")
    struct.pack_into("<3i", r, 0x20, tex, -1, env)
    struct.pack_into("<7f", r, 0x2C, flag, 1, 1, 1, 1, 1, 0.3)
    return bytes(r)


def make_dcn(meshes: list[bytes], textures: list[tuple[bytes, bytes]], materials: list[bytes],
             configs: list[tuple[list[int], list[int]]], checksum: int = 0x002E5EA3, name: str = "Synthetic",
             P: np.ndarray | None = None) -> bytes:
    P = skeleton() if P is None else P
    h = bytearray(0x48)
    struct.pack_into("<I", h, 0, checksum)
    h[4:0x14] = name.encode()[:15].ljust(16, b"\0")
    struct.pack_into("<2f", h, 0x14, 1.0, 1.0)
    struct.pack_into("<I", h, 0x1C, len(P))
    struct.pack_into("<I", h, 0x24, len(materials))
    struct.pack_into("<I", h, 0x2C, len(textures))
    struct.pack_into("<I", h, 0x34, len(configs))
    struct.pack_into("<I", h, 0x40, len(meshes))
    out = bytes(h) + b"\0" * (4 * len(meshes))
    out += offsets(P).astype("<f4").tobytes() + P.astype("<f4").tobytes()
    out += b"".join(meshes)
    out += b"".join(t[0] for t in textures) + b"".join(t[1] for t in textures)
    out += b"".join(materials)
    out += b"".join(struct.pack("<5I", 0, len(ms), 0, 0, 0) for ms, _sm in configs)
    for ms, sm in configs:
        out += struct.pack(f"<{len(ms)}i", *ms) + struct.pack(f"<{len(sm)}i", *sm)
    return out


def humanoid_dcn(name: str = "Synthetic") -> bytes:
    """A small but complete character: flat quad patches on torso, head, both arms and legs, one triangle patch and
    two plain triangles, two textures (4- and 8-bit), two materials, a full config and a LOD config."""
    P = skeleton()
    quads = []
    for joint, center, size in ((7, (0, 118, -10), 20), (0, (0, 92, -10), 18), (15, (0, 145, -11), 12),
                                (8, (10, 30, -6), 8), (9, (-10, 30, -6), 8), (17, (20, 115, -4), 6),
                                (19, (-20, 115, -4), 6), (26, (33, 95, -22), 4), (27, (-33, 95, -22), 4),
                                (10, (11, 5, -6), 5), (13, (-11, 5, -6), 5)):
        cps, j = flat_quad(center, size, joint)
        slot = 1 if joint == 15 else 0
        w = ((joint, 0.8), (0, 0.2)) if joint in (8, 9) else None
        quads.append(quad_packet(slot, [(0, 0), (0, 1), (1, 1), (1, 0)], cps, j, w))
    tri = tri_patch_packet(0, [(0, 0), (1, 0), (0, 1)],
                           [(0, 100, -12), (3, 100, -12), (6, 100, -12), (9, 100, -12), (6, 103, -12), (3, 106, -12),
                            (0, 109, -12), (0, 106, -12), (0, 103, -12), (3, 103, -12)], 2)
    t3 = [tri3_packet(0, [(0, 0), (1, 0), (0, 1)], [(0, 60, -9), (4, 60, -9), (0, 64, -9)], 0),
          tri3_packet(1, [(0, 0), (1, 0), (0, 1)], [(0, 150, -9), (3, 150, -9), (0, 153, -9)], 15)]
    full = mesh({0: quads, 1: [tri]})
    lod = mesh({2: t3})
    texs = [texture("body.tga", 32, 32, 4), texture("head.tga", 64, 64, 8)]
    mats = [material("body", 0), material("head", 1)]
    return make_dcn([full, lod], texs, mats, [([0], [0, 1]), ([1], [0, 1])], name=name, P=P)
