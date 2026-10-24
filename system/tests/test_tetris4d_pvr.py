"""Focused tests for the Tetris 4D (Japan) Dreamcast PVR reader/writer."""

import struct
from pathlib import Path

import pytest

from gbox import ninja
from gbox.tetris4d_pvr import (
    CHARACTER_SLOTS, decode_pvr, donor_swap, encode_pvr_like, parse_pvr,
    portrait_slots,
)

GDI_CANDIDATES = [
    Path.home() / "gbox-cache" / "dc" / "864538c6473a986e" / "disc.gdi",
    Path("/home/ehm_eckx/gBox_alt/gbox-cache/dc/864538c6473a986e/disc.gdi"),
]


def _gdi():
    for c in GDI_CANDIDATES:
        if c.exists():
            return c
    return None


def _disc():
    from gbox.gdrom import GDRom
    gdi = _gdi()
    if gdi is None:
        pytest.skip("cached split GDI not present")
    return GDRom(str(gdi))


def _synthetic(pixfmt, dfmt, w, h, body, gbix=5100):
    pvrt = (b"PVRT" + struct.pack("<I", 8 + len(body))
            + bytes([pixfmt, dfmt, 0, 0]) + struct.pack("<HH", w, h) + body)
    return (b"GBIX" + struct.pack("<I", 8) + struct.pack("<I", gbix) + pvrt)


# ---------------------------------------------------------------- synthetic

def test_parse_synthetic_vq_header():
    body = bytes(2048) + bytes(32 * 32)
    data = _synthetic(2, 0x03, 64, 64, body)
    hdr = parse_pvr(data)
    assert (hdr.width, hdr.height) == (64, 64)
    assert hdr.pixfmt == 2 and hdr.dfmt == 0x03
    assert hdr.gbix == 5100
    assert hdr.storage == "vq-2x2"
    assert "64x64 ARGB4444 vq-2x2" in hdr.describe()


def test_synthetic_vq_noop_roundtrip_is_byte_exact():
    body = bytearray(2048)
    for c in range(256):
        for k in range(4):
            struct.pack_into("<H", body, (c * 4 + k) * 2, (c * 7 + k * 13) & 0xFFFF)
    body += bytes((64 // 2) * (64 // 2))
    data = _synthetic(2, 0x03, 64, 64, bytes(body))
    w, h, rgba = decode_pvr(data)
    assert (w, h) == (64, 64) and len(rgba) == 64 * 64 * 4
    assert encode_pvr_like(data, rgba) == data


def test_synthetic_twiddled_noop_roundtrip_is_byte_exact():
    w = h = 16
    body = bytearray(w * h * 2)
    for y in range(h):
        for x in range(w):
            i = y * w + x
            v = ((i % 32) << 11) | (((i * 2) % 64) << 5) | (i % 32)  # RGB565-exact
            struct.pack_into("<H", body, 2 * ninja._twiddle(x, y), v)
    data = _synthetic(1, 0x01, w, h, bytes(body))
    w2, h2, rgba = decode_pvr(data)
    assert (w2, h2) == (w, h)
    assert encode_pvr_like(data, rgba) == data


def test_synthetic_linear_noop_roundtrip_is_byte_exact():
    w, h = 8, 4
    body = bytearray(w * h * 2)
    for i in range(w * h):
        n = i % 16
        v = (15 << 12) | (n << 8) | (n << 4) | n  # ARGB4444-exact
        struct.pack_into("<H", body, 2 * i, v)
    data = _synthetic(2, 0x09, w, h, bytes(body))
    w2, h2, rgba = decode_pvr(data)
    assert (w2, h2) == (w, h)
    assert encode_pvr_like(data, rgba) == data


def test_donor_swap_keeps_size_and_changes_pixels():
    src = _synthetic(1, 0x01, 16, 16,
                     b"".join(struct.pack("<H", (i * 257) & 0xFFFF)
                              for i in range(256)))
    dst = _synthetic(1, 0x01, 16, 16,
                     b"".join(struct.pack("<H", (i * 11) & 0xFFFF)
                              for i in range(256)))
    out = donor_swap(dst, src)
    assert len(out) == len(dst)
    assert out != dst
    assert parse_pvr(out).describe() == parse_pvr(dst).describe()
    assert decode_pvr(out)[2] == decode_pvr(src)[2]


def test_donor_swap_rejects_dimension_mismatch():
    a = _synthetic(1, 0x01, 16, 16, bytes(512))
    b = _synthetic(1, 0x01, 32, 32, bytes(2048))
    with pytest.raises(ValueError):
        donor_swap(a, b)


def test_portrait_slots_selection():
    names = ["MENU/MENUMODEL/05AKA.PVR", "MENU/MENUMODEL/05AO.PVR",
             "GAME/AO.PVR", "MENU/MENUMODEL/TEXTURE.NJT", "MENU/MENUMODEL/05X.PVR"]
    assert portrait_slots(names) == ["MENU/MENUMODEL/05AKA.PVR",
                                     "MENU/MENUMODEL/05AO.PVR",
                                     "MENU/MENUMODEL/05X.PVR"]


# ------------------------------------------------------------------- disc

@pytest.mark.parametrize("slot", CHARACTER_SLOTS)
def test_disc_character_portraits_have_expected_format(slot):
    disc = _disc()
    data = disc.read("MENU/MENUMODEL/%s.PVR" % slot)
    hdr = parse_pvr(data)
    assert (hdr.width, hdr.height) == (64, 64)
    assert hdr.dfmt == 0x03 and hdr.pixfmt == 2
    assert hdr.gbix == 5100 + CHARACTER_SLOTS.index(slot)
    assert len(data) == 3104


@pytest.mark.parametrize("slot", CHARACTER_SLOTS)
def test_disc_portrait_noop_roundtrip_is_byte_exact(slot):
    disc = _disc()
    data = disc.read("MENU/MENUMODEL/%s.PVR" % slot)
    w, h, rgba = decode_pvr(data)
    assert (w, h) == (64, 64)
    assert encode_pvr_like(data, rgba) == data


def test_disc_portrait_donor_swap_swaps_pixels_and_keeps_size():
    disc = _disc()
    target = disc.read("MENU/MENUMODEL/05AKA.PVR")
    donor = disc.read("MENU/MENUMODEL/05PINK.PVR")
    out = donor_swap(target, donor)
    assert len(out) == len(target)
    assert out != target
    assert parse_pvr(out).gbix == parse_pvr(target).gbix
    # the slot keeps its own codebook and index block: only pixels change
    q = parse_pvr(out).pvrt_offset
    assert out[q + 16:q + 16 + 2048] == target[q + 16:q + 16 + 2048]
    a = decode_pvr(out)[2]
    b = decode_pvr(donor)[2]
    err = sum(abs(x - y) for x, y in zip(a, b)) / len(a)
    assert err <= 32.0, err


def test_disc_gameplay_textures_roundtrip():
    disc = _disc()
    for name, dfmt in (("GAME/AO.PVR", 0x02), ("GAME/WAKU.PVR", 0x01),
                       ("GAME/TETRIS.PVR", 0x09)):
        data = disc.read(name)
        hdr = parse_pvr(data)
        assert hdr.dfmt == dfmt, name
        _w, _h, rgba = decode_pvr(data)
        assert encode_pvr_like(data, rgba) == data, name
