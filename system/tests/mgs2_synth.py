"""Synthetic Metal Gear Solid 2 data for the tests (no game bytes): a two-layer DVD image (ISO9660 per layer), a
STAGE.DAT with encrypted TOC / stage headers / zlib pages, kms models on a made-up 21-bone humanoid with the game's
bone tree, and texture packs laid out in GS memory."""
import struct

import numpy as np

from gbox import mgs2_inventory as inv
from gbox.ps2_gs import GSMemory, alpha_to_gs, csm1

SECTOR = 2048
FAKE_ELF = b"\x7fELF" + b"MGS2-TEST-ELF" * 40

# bone: (offset from parent (mm), parent) - hip, spine, chest, r clav / upper / fore / hand, l clav / upper / fore /
# hand, neck, head, r thigh / shin / foot / toe, l thigh / shin / foot / toe (the game's tree)
BONES = [((0, 0, 0), -1), ((0, 20, 0), 0), ((0, 150, 0), 1),
         ((-30, 230, 0), 2), ((-135, 0, 0), 3), ((0, -290, 0), 4), ((-40, -220, 50), 5),
         ((30, 230, 0), 2), ((135, 0, 0), 7), ((0, -290, 0), 8), ((40, -220, 50), 9),
         ((0, 290, 0), 2), ((0, 115, 0), 11),
         ((-120, -60, 40), 0), ((0, -460, 5), 13), ((0, -420, -40), 14), ((0, -140, 95), 15),
         ((120, -60, 40), 0), ((0, -460, 5), 17), ((0, -420, -40), 18), ((0, -140, 95), 19)]


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


def _layer(files: dict, base: int, min_sectors: int = 0) -> tuple[bytes, int]:
    """{'NAME' or 'DIR/NAME': bytes} -> sectors from `base` (PVD at base+16, root at base+18, the MGS2 directory at
    base+19, files from base+20; extents relative to `base`)."""
    lba = 20
    root = [_dirrec(b"\0", 18, SECTOR, 2), _dirrec(b"\1", 18, SECTOR, 2)]
    sub = [_dirrec(b"\0", 19, SECTOR, 2), _dirrec(b"\1", 18, SECTOR, 2)]
    data = []
    has_dir = any("/" in n for n in files)
    if has_dir:
        root.append(_dirrec(b"MGS2", 19, SECTOR, 2))
    for name, blob in files.items():
        rec = _dirrec(f"{name.split('/')[-1]};1".encode(), lba, len(blob), 0)
        (sub if "/" in name else root).append(rec)
        data.append((lba, blob))
        lba += max(1, (len(blob) + SECTOR - 1) // SECTOR)
    lba = max(lba, min_sectors)
    img = bytearray(lba * SECTOR)
    pvd = bytearray(SECTOR)
    pvd[0], pvd[1:6], pvd[6] = 1, b"CD001", 1
    pvd[40:72] = b"PLAYSTATION".ljust(32)
    struct.pack_into("<I", pvd, 80, lba)
    struct.pack_into(">I", pvd, 84, lba)
    pvd[156:190] = _dirrec(b"\0", 18, SECTOR, 2)
    img[16 * SECTOR:17 * SECTOR] = pvd
    img[17 * SECTOR] = 255
    r = b"".join(root)
    img[18 * SECTOR:18 * SECTOR + len(r)] = r
    s = b"".join(sub)
    img[19 * SECTOR:19 * SECTOR + len(s)] = s
    for at, blob in data:
        img[at * SECTOR:at * SECTOR + len(blob)] = blob
    return bytes(img), lba


def make_dvd(layer0: dict, layer1: dict) -> bytes:
    """A two-layer DVD image like the owned one: layer 0's volume size = the layer break; layer 1 starts 16 sectors
    before it, its PVD sits at the break."""
    l0, n0 = _layer(layer0, 0, 64)
    start1 = n0 - 16
    l1, _n1 = _layer(layer1, start1)
    img = bytearray(l0[:start1 * SECTOR]) + bytearray(l1)
    return bytes(img)


# ---------------------------------------------------------------- kms
def _box(c, r):
    """12 counter-clockwise (outward) triangles of an axis-aligned box: (positions (8,3), triangles)."""
    x, y, z = c
    P = np.array([[x - r, y - r, z - r], [x + r, y - r, z - r], [x + r, y + r, z - r], [x - r, y + r, z - r],
                  [x - r, y - r, z + r], [x + r, y - r, z + r], [x + r, y + r, z + r], [x - r, y + r, z + r]], float)
    T = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (3, 7, 6), (3, 6, 2),
         (0, 4, 7), (0, 7, 3), (1, 2, 6), (1, 6, 5)]
    return P, T


def humanoid_kms(tex_pack: int, tex: int, radius: int = 40, extra: int = 0) -> bytes:
    """A kms on the synthetic 21-bone humanoid: one textured box per bone (each triangle its own 3-vertex strip with
    the restart flags), the second half of the arm / leg vertices blended with the parent (weight word < 4096)."""
    nb = len(BONES)
    parts = []                                          # (bone, pos (n,4) s16, nrm (n,4), uv (n,2))
    for b, (off, par) in enumerate(BONES):
        P, T = _box((0, 0, 0), radius)
        v = []
        for t in T:
            a, bb, c = P[list(t)]
            n = np.cross(bb - a, c - a)
            n = n / np.linalg.norm(n)
            for k, corner in enumerate((a, bb, c)):
                v.append((corner, n, k < 2))
        for i in range(0, len(v), 30):                  # parts of 30 vertices (10 triangles)
            chunk = v[i:i + 30]
            pos = np.array([[*c, 4096 if (par < 0 or b % 2) else 2048] for c, _n, _r in chunk], np.int16)
            # stored the way the game stores them: pointing into the body (gbox.mgs2_models negates on read, #2367)
            nrm = np.array([[*np.round(-n * 4095), (0x8FFF if r else 0x0FFF)] for _c, n, r in chunk]).astype(np.int64)
            nrm = nrm.astype(np.uint16).view(np.int16).reshape(-1, 4)
            uv = np.array([[int(4096 * ((j % 3) / 2)), int(4096 * ((j // 3) % 2))] for j in range(len(chunk))], np.int16)
            parts.append((b, pos, nrm, uv))
    hdr = 0x40 + 0x40 * nb
    ptab = hdr
    arrays = ptab + 0x30 * len(parts)
    blob, offs = bytearray(), []
    for b, pos, nrm, uv in parts:
        op = arrays + len(blob)
        blob += pos.tobytes()
        blob += b"\0" * (-len(blob) % 16)
        on = arrays + len(blob)
        blob += nrm.tobytes()
        blob += b"\0" * (-len(blob) % 16)
        ou = arrays + len(blob)
        blob += uv.tobytes()
        blob += b"\0" * (-len(blob) % 16)
        offs.append((op, on, ou))
    out = bytearray(arrays)
    struct.pack_into("<4I", out, 0, 0xB253A3, nb, nb, tex_pack)
    struct.pack_into("<3I", out, 0x10, 3, 4, 5)
    struct.pack_into("<6f", out, 0x1C, -1294, -1294, -1294, 1294, 1294, 1294)
    q = ptab
    for b, (off, par) in enumerate(BONES):
        mine = [i for i, p in enumerate(parts) if p[0] == b]
        o = 0x40 + 0x40 * b
        struct.pack_into("<2I", out, o, 1, len(mine))
        struct.pack_into("<6f", out, o + 8, -radius, -radius, -radius, radius, radius, radius)
        struct.pack_into("<3f", out, o + 32, *off)
        struct.pack_into("<iI", out, o + 44, par, ptab + 0x30 * mine[0])
    for i, (b, pos, nrm, uv) in enumerate(parts):
        op, on, ou = offs[i]
        flags = 0x49 if BONES[b][1] >= 0 and b % 2 == 0 else 0x48
        struct.pack_into("<12I", out, ptab + 0x30 * i, flags, len(pos), tex, 0, 0, op, on, ou, 0, 0, 0, 0)
    return bytes(out + blob) + b"\0" * extra


# ---------------------------------------------------------------- texture pack
def tex0(tbp, tbw, psm, tw, th, cbp, csa=0):
    lg = lambda v: int(v).bit_length() - 1              # noqa: E731
    return tbp | (tbw << 14) | (psm << 20) | (lg(tw) << 26) | (lg(th) << 30) | (cbp << 37) | (csa << 56)


def texture_pack(entries: list[dict], pix_blocks: int = 0x220, clut_blocks: int = 16) -> bytes:
    """entries [{hash, rect (x0, y0, x1, y1) texels, index (h, w) u8, palette (256, 4), tbp, tbw, cbp}] (PSMT8,
    TW 512 / TH 1024) -> a pack: header, 0xa0 records, page-linear PSMCT32 pixel and CLUT regions."""
    n = len(entries)
    pix_off = (0x20 + 0xA0 * n + 0x7F) & ~0x7F
    clut_off = pix_off + 256 * pix_blocks
    pix, clut = GSMemory(1 << 20), GSMemory(1 << 18)
    recs = bytearray()
    for e in entries:
        x0, y0, x1, y1 = e["rect"]
        full = pix.read8(e["tbp"], e["tbw"], e["tbw"] * 64, y1)
        full[y0:y1, x0:x1] = e["index"]
        pix.write8(full, e["tbp"], e["tbw"])
        stored = csm1(alpha_to_gs(np.asarray(e["palette"], np.uint8)))
        clut.write32(stored.reshape(16, 16, 4).tobytes(), e["cbp"], 1, 16, 16)
        r = bytearray(0xA0)
        tw, th = 512, 1024
        struct.pack_into("<4f", r, 0, (x0 + 0.5) / tw, (y0 + 0.5) / th, (x1 - x0 - 1) / tw, (y1 - y0 - 1) / th)
        struct.pack_into("<I", r, 16, e["hash"])
        struct.pack_into("<QQ", r, 0x20, 0x7000000000008001, 0x0FFFEEEE)
        regs = [(2 | 8 | (x0 << 4) | ((x1 - 1) << 14) | (y0 << 24) | ((y1 - 1) << 34), 0x08),
                ((0x13 << 20) | (e["cbp"] << 37) | (4 << 61), 0x16),
                (tex0(e["tbp"], e["tbw"], 0x13, tw, th, e["cbp"]), 0x06), (0x44, 0x42), (0, 0x7F)]
        for k, (d, a) in enumerate(regs):
            struct.pack_into("<QQ", r, 0x30 + 16 * k, d, a)
        recs += r
    hdr = struct.pack("<8I", 0, pix_blocks, pix_blocks, clut_blocks, n, 0, pix_off, clut_off)
    out = bytearray(hdr + recs)
    out += b"\0" * (pix_off - len(out))
    out += pix.dump_linear(0, pix_blocks)
    out += clut.dump_linear(0, clut_blocks)
    return bytes(out)


def checker(h=64, w=64, a=3, b=200):
    y, x = np.mgrid[0:h, 0:w]
    return np.where(((x // 8) + (y // 8)) % 2 == 0, a, b).astype(np.uint8)


def palette(seed=0):
    rng = np.random.default_rng(seed)
    p = rng.integers(0, 256, (256, 4)).astype(np.uint8)
    p[:, 3] = 255
    return p


# ---------------------------------------------------------------- STAGE.DAT
def stage_blob(name: str, key: int, pages: list[tuple[int, list[tuple[int, int, bytes]]]], seed: int = 0x1234) -> bytes:
    """pages [(marker, [(type, hash, bytes), ...])] -> an encrypted stage (header + pages)."""
    rows, blobs, coff = [], [], 0
    for marker, files in pages:
        data, frows = bytearray(), []
        for t, h, b in files:
            frows.append(((t << 24) | h, len(data)))
            data += b
            data += b"\0" * (-len(data) % 16)
        raw = inv.encode_page(bytes(data), seed)
        rows.append((marker, len(data)))
        rows.append(((0x7E << 24) | len(raw), coff))
        rows += frows
        blobs.append((coff, raw))
        coff += (len(raw) + SECTOR - 1) // SECTOR * SECTOR
    head = inv.encode_stage_header(rows, key, name)
    body = bytearray(coff)
    for o, raw in blobs:
        body[o:o + len(raw)] = raw
    return head + bytes(body)


def stage_dat(stages: list[tuple[str, bytes]], key: int = 0x3DB7B4DA, slack: int = 4) -> bytes:
    """[(name, stage blob)] -> STAGE.DAT: clear key + encrypted TOC (1 sector), each stage padded with `slack`
    spare sectors."""
    toc_rows, body, sec = b"", bytearray(), 1
    for name, blob in stages:
        toc_rows += name.encode().ljust(8, b"\0") + struct.pack("<I", sec)
        n = (len(blob) + SECTOR - 1) // SECTOR + slack
        body += blob + b"\0" * (n * SECTOR - len(blob))
        sec += n
    c = inv.Cipher.for_toc(key)
    hdr = c.run(struct.pack("<6H", 1, 1, len(stages), 0x4010, 0, 0))
    toc = struct.pack("<I", key) + hdr + c.run(toc_rows + b"\0" * (-len(toc_rows) % 4))
    toc += b"\0" * (SECTOR - len(toc))
    return bytes(toc) + bytes(body)
