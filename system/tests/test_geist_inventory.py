import struct

import pytest

from gbox.geist_inventory import (
    ASSET_ROLES,
    GAME_ID,
    TITLE,
    disc_header,
    dol_entry,
    tpl_images,
)

GC_MAGIC = 0xC2339F3D
TPL_MAGIC = 0x0020AF30


def _gc_header(disc_id=b"GITE01", region=1):
    head = bytearray(0x440)
    head[:6] = disc_id
    struct.pack_into(">I", head, 0x1C, GC_MAGIC)
    head[0x20:0x20 + 5] = b"Geist"
    struct.pack_into(">III", head, 0x420, 0x2000, 0x4000, 0x100)  # dol_off, fst_off, fst_size
    bi2 = bytearray(0x20)
    struct.pack_into(">I", bi2, 0x18, region)
    return bytes(head), bytes(bi2)


def test_disc_header_identity():
    head, bi2 = _gc_header()
    h = disc_header(head, bi2)
    assert h["disc_id"] == "GITE01"
    assert h["region"] == "NTSC-U"
    assert h["dol_offset"] == 0x2000
    assert h["title"] == "Geist"


def test_disc_header_rejects_non_gc():
    head, bi2 = _gc_header()
    head = bytearray(head)
    struct.pack_into(">I", head, 0x1C, 0xDEADBEEF)
    with pytest.raises(ValueError):
        disc_header(bytes(head), bi2)


def test_tpl_images():
    # TPL: magic, count=1, image-table at 0x0C; image header at 0x14: h,w,fmt,data(0x20)
    b = bytearray(0x20 + 4)
    struct.pack_into(">I", b, 0, TPL_MAGIC)
    struct.pack_into(">II", b, 4, 1, 0x0C)
    struct.pack_into(">I", b, 0x0C, 0x14)
    struct.pack_into(">HHII", b, 0x14, 16, 32, 6, 0x20)  # 16x32 RGBA8
    imgs = tpl_images(bytes(b))
    assert imgs == [{"w": 32, "h": 16, "fmt": "RGBA8"}]


def test_tpl_images_rejects_bad_magic():
    with pytest.raises(ValueError):
        tpl_images(b"\x00" * 16)


def test_dol_entry():
    dol = bytearray(0xE4)
    struct.pack_into(">I", dol, 0xE0, 0x80003100)
    assert dol_entry(bytes(dol)) == 0x80003100


def test_asset_roles_grounded():
    # Every extension the assimilate fingerprint observed must map to a role here.
    observed = {".gsf", ".olc", ".spt", ".spd", ".song", ".sdf_gc", ".bin", ".tpl",
                ".adp", ".m3d", ".mmf", ".samp", ".$$$", ".acky", ".txt"}
    assert observed <= set(ASSET_ROLES)
    assert GAME_ID == "34dd475ee86a0b74" and TITLE == "Geist (USA)"
