import struct
import pytest

from gbox import madden2005_mmap as mm, madden2005_terf as terf
from gbox.gcdisc import GCDisc

DISC = None


def _disc():
    global DISC
    if DISC is None:
        DISC = GCDisc("/mnt/gbox/hyperspin/Arcade/collections/Nintendo GameCube/roms/"
                      "Madden NFL 2005 (USA).gcz")
    return DISC


def _first_member(archive: str) -> bytes:
    buf = _disc().read(archive)
    idx = terf.parse_terf(buf)
    m = next(m for m in idx.members if m.size)
    return terf.member_bytes(buf, idx, m.index)


def test_plyface_member_is_mmap():
    data = _first_member("PLYRFACE.DAT")
    assert data[:4] == mm.MMAP


def test_rgb5a3_word_decodes_skin_tone():
    # 0x5986 = 0b0101_1001_1000_0110 = RGB4444 A=5,R=9,G=8,B=6 -> (153,136,102) alpha 182
    assert mm.rgb5a3_word(0x5986) == (153, 136, 102, 182)


def test_parse_mmap_regions_and_palette():
    data = _first_member("PLYRFACE.DAT")
    tex = mm.parse_mmap(data)
    assert tex.num_maps == 2
    assert len(tex.regions) == 2
    # region 0 is 128x128, region 1 is 64x64 (observed header)
    assert (tex.regions[0].w, tex.regions[0].h) == (128, 128)
    assert (tex.regions[1].w, tex.regions[1].h) == (64, 64)
    # 14 palette entries for region 0 (0x000e0000)
    assert tex.regions[0].pal_entries == 14
    # region 0 data_off points at the RGB5A3 palette (confirmed skin tones there)
    assert tex.regions[0].data_off == 0x0060
    assert tex.palette_off == 0x0060
    expected_words = tex.regions[0].pal_entries * 4
    assert len(tex.raw_palette_bytes) == expected_words * 2
    assert len(tex.palette) == expected_words
    # decoded palette contains the observed skin tones (present, not fabricated)
    rgbs = {c[:3] for c in tex.palette}
    assert (119, 170, 170) in rgbs and (82, 148, 189) in rgbs


def test_member_contains_face_geometry_block():
    data = _first_member("PLYRFACE.DAT")
    offs = mm.face_block_offsets(data)
    assert data[:4] == mm.MMAP
    assert any(data[o:o + 4] in (mm.FACE, mm.FAC) for o in offs)


def test_no_refpack_wrapper_on_members():
    for archive in ("PLYRFACE.DAT", "FACEGEOM.DAT"):
        data = _first_member(archive)
        assert not data[:4] == bytes.fromhex("10fb" + struct.pack(">H", len(data))[:2].hex())
