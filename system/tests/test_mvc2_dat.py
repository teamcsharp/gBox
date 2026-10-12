"""MVC2 DC DAT container decoder (#1315): GFX1 LZSS + twiddle, GFX2 assembly,
palette banks and animation groups.  Real-disc checks decode one Ryu (PL00)
frame; they run when the unpacked disc cache is present, and are skipped in CI.
"""

import hashlib
import struct
from pathlib import Path

import pytest

from gbox import mvc2_dat as M

DAT = Path.home() / "gbox-cache/dc/02db6d37c0e20375/an/PL00_DAT.BIN"
EXE = Path.home() / "gbox-cache/dc/02db6d37c0e20375/an/1ST_READ.BIN"


# ---------------------------------------------------------------- GFX1 codec

def test_decodeA_literals():
    # one flag byte (all-literal) + 8 literal bytes
    assert M.decodeA(b"\x00ABCDEFGH", 8) == b"ABCDEFGH"


def test_decodeA_backref_rle():
    # flags 0x01: 7 literals then one back-ref b=0x00 -> dist 0, count 2,
    # overlapping copy of the previous output bytes (RLE semantics)
    assert M.decodeA(b"\x01ABCDEFG\x00", 9) == b"ABCDEFGGG"


def test_decodeA_backref_from_empty_is_zero():
    # bootstrapping a run from an empty window yields zeros (ROM's dist=0 trick)
    assert M.decodeA(b"\x80A\x00", 4) == b"\x00\x00\x00\x00"


def test_decodeA_short_stream_pads():
    assert M.decodeA(b"\x00AB\x02", 6) == b"AB\x02\x00\x00\x00"


def test_decodeA_roundtrip_twiddle():
    lin = bytes([(x // 4 + y) % 16 for y in range(8) for x in range(8)])
    sto = M.vflip(lin, 8, 8)
    tw = M.twiddle_pal4(sto, 8, 8)
    enc = b"".join(b"\x00" + tw[i:i + 8] for i in range(0, len(tw), 8))
    assert M.decodeA(enc, 32) == tw
    assert M.detwiddle_pal4(tw, 8, 8) == sto
    assert M.vflip(M.detwiddle_pal4(tw, 8, 8), 8, 8) == lin


def test_twiddle_rejects_non_pow2():
    with pytest.raises(ValueError):
        M.twiddle_pal4(b"\x00" * 50, 10, 10)


# ------------------------------------------------------- synthetic DAT fixture

def _make_dat() -> bytes:
    """One 8x8 part (palette idx 1 everywhere), one sprite, one animation cell.

    Layout quirk shared by GFX1/GFX2: the leading u32 is BOTH the table byte
    count (4*n) and the offset of entry 0, because entry 0 sits right after
    the table (real PL00: count 0x17f4 == part-0 offset 0x17f4).
    """
    lin = bytes([1] * 64)  # display order: every pixel is index 1
    sto = M.vflip(lin, 8, 8)
    tw = M.twiddle_pal4(sto, 8, 8)
    enc = b"".join(b"\x00" + tw[i:i + 8] for i in range(0, len(tw), 8))
    part = b"\x00\x00\x01\x01" + enc  # header [lw][lh][sw][sh], 8x8

    gfx1 = 0x40
    gfx2 = gfx1 + 4 + len(part)          # count u32 + part blob
    pal = gfx2 + 4 + 2 + 8               # count u32 + u16 cnt + 1 rec
    anim = pal + 32                      # one palette bank
    end = anim + 0x100 + 8 + 8 + 20      # pre-table + grp tab(2) + sub tab(2) + cell
    tab = [gfx1, gfx2, pal, 0, 0, anim, end] + [0] * 9

    out = bytearray(struct.pack("<16I", *tab))
    out += struct.pack("<I", 4)                    # GFX1 count (== part-0 offset)
    out += part
    out += struct.pack("<I", 4)                    # GFX2 count (== sprite-0 offset)
    out += struct.pack("<H", 1) + struct.pack("<hhHH", 0, 0, 0, 0)  # 1 rec, part 0
    out += b"\x00\x00" * 16                       # palette bank 0 (idx 0 transparent)
    out[pal + 2:pal + 4] = b"\x00\xff"            # idx 1 = ARGB4444 0xFF00 = red
    out += b"\x00" * 0x100                        # animation pre-table
    out += struct.pack("<I", 0x108)               # group 0 -> sub table
    out += struct.pack("<I", 0)                   # next group slot: end
    out += struct.pack("<I", 0x110)               # sub 0 -> cell
    out += struct.pack("<I", 0)                   # next sub slot: end
    cell = bytearray(20)
    cell[2] = 3                                    # duration
    cell[3] = 0x80                                 # ender: last cell
    struct.pack_into("<H", cell, 4, 0)             # sprite 0
    cell[0x11] = 0
    cell[0x12] = 1
    out += cell
    return bytes(out)


def test_synthetic_dat_roundtrip():
    dat = _make_dat()
    assert M.part_count(dat) == 1
    idx, w, h = M.part_indices(dat, 0)
    assert (w, h) == (8, 8)
    assert idx == bytes([1] * 64)
    assert M.palette_bank(dat, 0)[1] == (255, 0, 0, 255)
    assert M.palette_bank(dat, 0)[0] == (0, 0, 0, 0)
    assert M.sprite_records(dat, 0) == [
        {"dx": 0, "dy": 0, "part": 0, "flip": False, "flipy": False}]
    anim = M.animation_groups(dat, 0)
    assert anim[0][0] == [{"sprite_id": 0, "duration": 3,
                           "render_extra": 0, "hitbox_group": 1}]
    w, h, rgba = M.render_cell(dat, 0)
    assert (w, h) == (8, 8)
    assert rgba == bytes((255, 0, 0, 255)) * 64


# ------------------------------------------------- real-disc checks (PL00 = Ryu)

@pytest.mark.skipif(not DAT.exists(), reason="unpacked MVC2 disc cache not present")
class TestRealPL00:
    def test_file_identity(self):
        assert hashlib.sha256(DAT.read_bytes()).hexdigest() == (
            "751165ed1fc9f001961a8ed02ec437c5171c7712bf9718694e6a09b97667597b")

    def test_sections_and_part_count(self):
        dat = DAT.read_bytes()
        tab = M.dat_sections(dat)
        assert tab[0] == 0x40 and tab[1] == 0x67F40 and tab[2] == 0x6E440
        assert tab[3] == 0x6EB60 and tab[5] == 0x7EB60 and tab[6] == 0x83D40
        assert M.part_count(dat) == 1533

    def test_part_geometry(self):
        dat = DAT.read_bytes()
        for sel, wh in ((0, (8, 32)), (1, (32, 128)), (2, (16, 32)), (3, (8, 8))):
            _, _, _, w, h = M.part_geom(dat, sel)
            assert (w, h) == wh

    def test_part_decode_checksums(self):
        dat = DAT.read_bytes()
        for sel, want in ((0, "ca9c29af1a2c1461efd44b444a756196"),
                          (1, "9e42fe3ca5cd0da515feb1adb1da0d3b"),
                          (2, "8ac10af2d1a5f98dea695b2dd86ebc85"),
                          (3, "bc79f5c6b20b79830cc20529ecc27b4d")):
            idx, _, _ = M.part_indices(dat, sel)
            assert hashlib.md5(idx).hexdigest() == want

    def test_palette_bank0_ryu(self):
        pal = M.palette_bank(DAT.read_bytes(), 0)
        assert pal[0] == (0, 0, 0, 0)
        assert pal[1] == (17, 17, 17, 255)
        assert pal[2] == (255, 204, 153, 255)   # Ryu skin tone
        assert pal[3] == (255, 170, 119, 255)

    def test_sprites_and_assembly(self):
        dat = DAT.read_bytes()
        assert struct.unpack_from("<I", dat, 0x67F40)[0] // 4 == 441
        assert M.sprite_records(dat, 0) == [
            {"dx": 120, "dy": -70, "part": 0, "flip": False, "flipy": False}]

    def test_animation_groups_match_catalog(self):
        anim = M.animation_groups(DAT.read_bytes(), 0)
        assert len(anim) == 26
        assert len(anim[0]) == 8
        assert [c["sprite_id"] for c in anim[0][0][:3]] == [61, 62, 63]
        assert all(c["duration"] == 3 and c["hitbox_group"] == 1
                   for c in anim[0][0])

    def test_render_first_frame(self):
        w, h, rgba = M.render_cell(DAT.read_bytes(), 0, group=0, sub=0, cell=0)
        assert (w, h) == (79, 128)
        assert hashlib.md5(rgba).hexdigest() == "219a8b0d1499b5134c1ddf92bac00fdc"
        assert sum(1 for i in range(3, len(rgba), 4) if rgba[i]) == 2947


@pytest.mark.skipif(not EXE.exists(), reason="unpacked MVC2 disc cache not present")
class TestRealExe:
    def test_decoder_is_in_rom(self):
        boot = EXE.read_bytes()
        # loc_8c0354c0 = file offset 0x254c0: the GFX1 LZSS decompressor
        assert boot[0x254C0:0x254C0 + 20].hex() == "e62f00e7c62f0fecb62fa62f962f5369669a6c39"

    def test_asset_name_table(self):
        boot = EXE.read_bytes()
        vals = struct.unpack_from("<401I", boot, M.NAME_TABLE_OFF)
        names = [boot[v - M.EXE_BASE:v - M.EXE_BASE + 12].split(b"\0")[0].decode()
                 for v in vals]
        assert names[0] == "AICADRV.BIN"
        assert names.index("PL00_DAT.BIN") == 209
        assert names.index("PL00_FAC.BIN") == 3
        assert names.index("PL00_VOI.BIN") == 63
        assert names.index("PL00_WIN.BIN") == 153
        assert names.index("S_PL00A.BIN") == 268
