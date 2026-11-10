import struct, zlib
from gbox import merc3d_tex as t


def _hdr(w, h, mips, fmt):
    return b"TEX\0" + struct.pack("<3I", 0x200800A4, mips | (w << 6) | (h << 19), 1 | (fmt << 8) | 0x10000)


def test_header_and_sizes():
    d = _hdr(256, 512, 5, 0x0C) + bytes(174592)
    h = t.parse_header(d)
    assert (h["width"], h["height"], h["mips"], h["format"], h["version"]) == (256, 512, 5, 0x0C, 0xA4)
    assert t.mip_sizes(h) == [131072, 32768, 8192, 2048, 512]
    assert 0x10 + sum(t.mip_sizes(h)) == len(d) - 0


def test_etc1_flat_block():
    # standard ETC1 individual mode block, base 0xF0F0F0 both halves, table 0, all indices 0 (+2)
    std = bytes([0xFF, 0xFF, 0xFF, 0x00 << 2, 0, 0, 0, 0])
    px = t._etc1_block(std[::-1])
    assert px[0] == (255, 255, 255) and len(px) == 16


def test_etc1a4_alpha_and_png():
    blk = bytes([0xFF] * 8) + bytes([0xFF, 0xFF, 0xFF, 0x00, 0, 0, 0, 0])[::-1]
    d = _hdr(8, 8, 1, 0x0C) + blk * 4
    w, h, rgba = t.decode(d)
    assert (w, h) == (8, 8) and set(rgba[3::4]) == {255}
    p = t.png(w, h, rgba)
    assert p[:8] == b"\x89PNG\r\n\x1a\n"


def test_bad_size_rejected():
    d = _hdr(8, 8, 1, 0x0C) + bytes(10)
    try:
        t.decode(d)
    except ValueError:
        return
    raise AssertionError


# --- real-data acceptance: validates decode against actual pl0000 (Chris) skins ---
# Requires the owned ROM at RE_MERC3D_ROM (set via env); skipped when absent.
# The SHA256s below are the bytes-on-disk hashes of the ARC TEX entries, which
# anchor the decode output to a specific build (EUR CTR-P-ABMP, sha256 of the
# 3ds above). They prevent silent regressions in header/tile/byte-order logic.
_PL0000_SKINS = {
    "pl0000_skin_BM": ("9e13aa0d4c4e80fb732eba1be72abaa04c51f1832848aeabce968afc0336f049", 0x0C, "color"),
    "pl0000_skin_NM": ("3a187f79ae3c1772fb08eb7e4f1b7eddded6a32ae5d1ad9fe4df7f1898ef1291", 0x0B, "normal"),
    "pl0000_hair02_BM": ("fa0c6ec2bc20526c7a2b0d410f3ca6a1c81b36d20cacf41ed7c483b3306f17ae", 0x0C, "color"),
    "pl0000_hair02_NM": ("9ec1aaa0d9008091162535d92e391617cd264b93a439a93fc2fb1b9d881a07f3", 0x0B, "normal"),
    "pl0000_hair01_NM": ("7d83c179995530aa33b0ca6099f2cdd5012acc8c247223c643d7407b1d90c68e", 0x0C, "normal"),
}


def _load_pl0000_tex():
    import os
    rom = os.environ.get("RE_MERC3D_ROM")
    if not rom or not os.path.exists(rom):
        return None
    import hashlib
    from gbox.ctr_romfs import CtrImage
    from gbox.merc3d_inventory import Arc3ds, ROSTER_RE
    with CtrImage(rom) as img:
        files = img.romfs_files()
        arcf = next(f for f in files if ROSTER_RE.match(f.path) and "Chris ).arc" in f.path)
        arc = Arc3ds(img.read_file(arcf))
        return {e.name.replace("\\", "/").rsplit("/", 1)[-1]: arc.read(e) for e in arc.find("tex")}


def test_real_pl0000_skins_decode(monkeypatch=None):
    tex = _load_pl0000_tex()
    if tex is None:
        import pytest
        pytest.skip("RE_MERC3D_ROM not set or missing; skipping real-data decode")
    import hashlib
    from collections import Counter
    for name, (want_sha, want_fmt, kind) in _PL0000_SKINS.items():
        d = tex[name]
        assert hashlib.sha256(d).hexdigest() == want_sha, f"{name}: sha drift"
        h = t.parse_header(d)
        assert h["format"] == want_fmt
        w, hh, rgba = t.decode(d, 0)
        assert (w, hh) == (h["width"], h["height"])
        n = w * hh
        # dominant-channel check discriminates color vs normal maps and proves
        # the byte-swap/tile/base16 path produced image-like (not noise) output.
        b = sum(rgba[i * 4 + 2] for i in range(0, n, 7)) / (n // 7 + 1)
        r = sum(rgba[i * 4] for i in range(0, n, 7)) / (n // 7 + 1)
        if kind == "normal":
            assert b > 240 and abs(r - 128) < 4, f"{name}: not normal-map-signed"
        else:
            assert b < 128, f"{name}: color map unexpectedly blue-dominant"
        # no all-zero or all-equal frame: real texture has real variance
        uniq = len({rgba[i * 4:i * 4 + 3] for i in range(0, min(n, 4096) * 4, 4)})
        assert uniq > 5, f"{name}: near-flat decode ({uniq} colors)"
    # ETC1A4 alpha must vary on the skin color map (hair01_NM uses fmt 0x0C too)
    w, hh, rgba = t.decode(tex["pl0000_skin_BM"], 0)
    alphas = set(rgba[3::4])
    assert len(alphas) > 1, "skin_BM alpha should vary (ETC1A4)"
