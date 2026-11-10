import os
import struct
import numpy as np
import pytest
from gbox.formats import bntx_nx as B


def _swizzle_ref(lin, bw, bh, bpb, bh_gobs):
    """Independent per-block forward Tegra block-linear swizzle (slow reference)."""
    pitch = bw * bpb
    gx = (pitch + 63) // 64
    rows = (bh + 8 * bh_gobs - 1) // (8 * bh_gobs) * bh_gobs
    out = bytearray(gx * rows * 512)
    for y in range(bh):
        for x in range(bw):
            xb = x * bpb
            o = (((y // 8) // bh_gobs) * gx * bh_gobs + (xb // 64) * bh_gobs + (y // 8) % bh_gobs) * 512
            xi, yi = xb % 64, y % 8
            o += (xi // 32) * 256 + (yi // 2) * 64 + ((xi % 32) // 16) * 32 + (yi % 2) * 16 + xi % 16
            out[o:o + bpb] = lin[(y * bw + x) * bpb:(y * bw + x + 1) * bpb]
    return bytes(out)


@pytest.mark.parametrize("bw,bh,bpb,lg", [(16, 16, 16, 1), (32, 64, 8, 2), (8, 32, 16, 3)])
def test_deswizzle_inverts_reference(bw, bh, bpb, lg):
    rng = np.random.default_rng(bw * bh)
    lin = rng.integers(0, 256, bw * bh * bpb, dtype=np.uint8).tobytes()
    bhg = 1 << lg
    while bhg > 1 and (bh + 7) // 8 <= bhg // 2:
        bhg //= 2
    sw = _swizzle_ref(lin, bw, bh, bpb, bhg)
    assert B.deswizzle(sw, bw * 4, bh * 4, bpb, lg) == lin


def test_bc1_and_bc3_solid():
    c565 = struct.pack("<HH", 0xF800, 0xF800)  # pure red
    blk = c565 + b"\0\0\0\0"
    img = B.decode_bcn(blk * 4, 8, 8, 0x1A)
    assert (img[..., 0] == 255).all() and (img[..., 1:3] == 0).all() and (img[..., 3] == 255).all()
    bc3 = bytes([128, 128]) + b"\0" * 6 + blk
    img = B.decode_bcn(bc3 * 4, 8, 8, 0x1C)
    assert (img[..., 3] == 128).all() and (img[..., 0] == 255).all()


def _bntx(w=8, h=8, fmt=0x1A01):
    size = 0x1000
    b = bytearray(size)
    b[:8] = b"BNTX\0\0\0\0"
    struct.pack_into("<I", b, 0x1C, size)
    struct.pack_into("<IQ", b, 0x24, 1, 0x100)  # count, table
    struct.pack_into("<Q", b, 0x100, 0x200)
    r = 0x200
    b[r:r + 4] = b"BRTI"
    struct.pack_into("<HH", b, r + 0x12, 0, 0)
    struct.pack_into("<H", b, r + 0x16, 1)
    struct.pack_into("<IIIIII", b, r + 0x1C, fmt, 0, w, h, 1, 1)
    struct.pack_into("<I", b, r + 0x34, 0)
    struct.pack_into("<Q", b, r + 0x60, 0x300)
    struct.pack_into("<Q", b, r + 0x70, 0x320)
    struct.pack_into("<H", b, 0x300, 3)
    b[0x302:0x305] = b"abc"
    struct.pack_into("<Q", b, 0x320, 0x800)
    red = struct.pack("<HH", 0xF800, 0xF800) + b"\0" * 4
    b[0x800:0x800 + 8] = red  # blocks of 2x2: first GOB row
    return bytes(b)


def test_parse_synthetic_and_split():
    buf = _bntx() + _bntx()
    offs = B.split_bntx(buf)
    assert offs == [0, 0x1000]
    t = B.parse_bntx(buf, 0x1000)[0]
    assert (t.name, t.width, t.height, t.mips, t.codec[0]) == ("abc", 8, 8, 1, "BC1")
    assert t.mip_offsets == [0x800] and t.offset == 0x1000
    with pytest.raises(ValueError):
        B.parse_bntx(b"BNTX\0\0\0\0" + b"\0" * 0x30)


WTP = os.environ.get("GBOX_B2_WTP", os.path.expanduser("~/.hermes/cache/scratch/b2/pl0000_pl0000.wtp"))


@pytest.mark.skipif(not os.path.exists(WTP), reason="real Bayonetta 2 pl0000.wtp not available")
def test_real_pl0000_wtp_all_textures_decode_coherently():
    d = open(WTP, "rb").read()
    texs = [t for o in B.split_bntx(d) for t in B.parse_bntx(d, o)]
    assert len(texs) == 32
    assert {t.fmt >> 8 for t in texs} == {0x1C, 0x20, 0x34}
    body = next(t for t in texs if t.name.endswith("pl0000_body_C2_rev"))
    assert (body.width, body.height, body.block_height_log2) == (1024, 2048, 4)
    img = B.decode_mip(d, body, 0)
    smooth = np.abs(np.diff(img[..., :3].astype(float), axis=1)).mean()
    shuf = np.random.default_rng(0).permutation(img.reshape(-1, 4)).reshape(img.shape)
    assert smooth < 0.2 * np.abs(np.diff(shuf[..., :3].astype(float), axis=1)).mean()
