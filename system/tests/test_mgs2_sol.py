"""Focused tests for the OWNED MGS2 Sons of Liberty build (SLUS-201.44).

These pin the facts read off the operator's own disc: the file map, the ISO geometry, the ELF identity
and the STAGE.DAT cipher that was verified to decrypt on this build. No other build's hash is reused.
"""
from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gbox import mgs2_inventory as inv
from gbox import mgs2_sol as sol


def test_manifest_is_the_owned_map():
    assert len(sol.MANIFEST) == 11
    assert sol.MANIFEST["SLUS_201.44"] == (284, 841648)
    assert sol.MANIFEST["MGS2/STAGE.DAT"] == (1325353, 624904192)
    assert sol.MANIFEST["SYSTEM.CNF"] == (283, 54)


def test_manifest_is_internally_sound():
    """The recorded map tiles the image consistently: no gaps in the contiguous run, nothing past the end."""
    assert sol.verify_manifest() == []


def test_dat_payloads_tile_the_image_back_to_back():
    """Measured on the owned ISO: the six .DAT payloads are contiguous, so the map can be used directly."""
    chain = ["MGS2/DEMO.DAT", "MGS2/MOVIE.DAT", "MGS2/STAGE.DAT", "MGS2/CODEC.DAT",
             "MGS2/FACE.DAT", "MGS2/VOX.DAT"]
    for a, b in zip(chain, chain[1:]):
        la, sa = sol.MANIFEST[a]
        lb, sb = sol.MANIFEST[b]
        assert la + sol._sectors(sa) == lb, f"{a} does not end where {b} starts"
    assert sol.payload_overlaps() == []


def test_every_manifest_entry_fits_inside_the_image():
    for name, (lba, size) in sol.MANIFEST.items():
        assert lba + sol._sectors(size) <= sol.TOTAL_SECTORS, name


def test_elf_identity_is_ours_not_substance():
    """The owned build must not be confused with the Substance build the shared reader was written for."""
    assert sol.ELF == "SLUS_201.44"
    assert sol.ELF_SIZE == 841648
    assert inv.ELF == "SLUS_205.54"
    assert inv.ELF_SIZE == 852772
    assert sol.ELF_SHA256 != inv.ELF_SHA256
    assert len(sol.ELF_SHA256) == 64 and len(sol.ISO_SHA256) == 64


def test_iso_geometry():
    assert sol.ISO_SIZE == 4620910592
    assert sol.ISO_SIZE // sol.SECTOR == sol.TOTAL_SECTORS == 2256304
    assert sol.LAYER0_SECTORS == sol.TOTAL_SECTORS          # single layer, unlike the Substance DVD
    assert sol.TOTAL_SECTORS < inv.TOTAL_SECTORS


def test_stage_toc_fixture_decrypts_on_this_build():
    """The recorded TOC header really is this disc's: it must round trip through the shared cipher."""
    plain = bytes.fromhex(sol.STAGE_TOC_HEADER_PLAIN)
    raw = inv.Cipher.for_toc(sol.STAGE_KEY).run(plain)
    assert inv.Cipher.for_toc(sol.STAGE_KEY).run(raw) == plain
    toc_sectors, count = struct.unpack_from("<hh", plain, 2)
    assert (toc_sectors, count) == (sol.STAGE_TOC_SECTORS, sol.STAGE_COUNT) == (1, 115)


def test_stage_header_fixture_decrypts_on_this_build():
    """The 'init' stage header must round trip through the per-stage cipher."""
    plain = bytes.fromhex(sol.STAGE_INIT_HEADER_PLAIN)
    raw = inv.Cipher.for_stage(sol.STAGE_KEY, "init").run(plain)
    assert inv.Cipher.for_stage(sol.STAGE_KEY, "init").run(raw) == plain
    rows = struct.unpack_from("<I", plain, 0)[0]
    assert rows == 10
    assert struct.unpack_from("<I", plain, 4)[0] == 0x7F010000     # the page marker row


def test_page0_evidence_is_consistent():
    assert sol.PAGE0_DSIZE == 1021952
    assert sol.PAGE0_CSIZE == 411960
    assert sol.PAGE0_CSIZE < sol.PAGE0_DSIZE
    assert len(sol.PAGE0_SHA256) == 64


def test_name_hash_is_24_bit_and_nonzero():
    for name in ("init", "select", "n_title", "r_tnk0"):
        h = inv.name_hash(name)
        assert 0 < h <= 0xFFFFFF
    assert inv.name_hash("init") != inv.name_hash("select")
    # an independent restatement of the rotate-5 rule
    h = 0
    for c in b"init":
        h = (((h << 5) | (h >> 19)) + c) & 0xFFFFFF
    assert (h or 1) == inv.name_hash("init")


def test_stage_toc_head_order():
    names = [n for n, _ in sol.STAGE_TOC_HEAD]
    assert names[:4] == ["init", "select", "n_title", "museum"]
    offs = [o for _, o in sol.STAGE_TOC_HEAD]
    assert offs == sorted(offs)


def test_owned_elf_string_table_is_self_consistent():
    """The owned ELF's measured string table must agree with its own LOAD segment delta."""
    import importlib
    sol = importlib.import_module('gbox.mgs2_sol')
    assert sol.ELF_SIZE == 841648
    assert sol.ELF_LOAD_DELTA == 0xFFF80
    for label, (off, va, lit) in sol.ELF_STRINGS.items():
        assert va == off + sol.ELF_LOAD_DELTA, label
    b = chr(92)
    assert sol.ELF_STRINGS['loader_container'][2] == 'cdrom0:' + b + 'MGS2' + b + '%s;1'
    assert sol.ELF_STRINGS['stage_decoder_tag'][2] == 'STGDEC'
    assert sol.ELF_STRINGS['elf_path'][2] == 'cdrom0:' + b + 'SLUS_201.44;1'
    assert {'stage.dat', 'demo.dat', 'vox.dat', 'movie.dat', 'face.dat', 'codec.dat'} <= {
        lit for _o, _v, lit in sol.ELF_STRINGS.values()}


def test_owned_stage_probe_noop_roundtrip():
    """Format probe on the owned disc: r_tnk0 has a kms (0x0a) and texture pack (0x13) and a no-op rebuild is lossless."""
    import pytest
    from gbox import mgs2_inventory as inv
    src = sol.source_path()
    if not src.exists():
        pytest.skip("owned ISO not mounted")
    d = inv.Disc(str(src))
    try:
        r = sol.probe_stage(d, "r_tnk0")
    finally:
        d.close()
    assert r["pages"] == 3 and r["span_sectors"] == 1350
    assert r["kms"]["size"] == 15184 and r["kms"]["hash"] == "0x31792f"
    assert r["kms"]["sha256"] == "112c2782773ebe645e30134079c3cf334b22bc8c51089f39adb42eca28012a85"
    assert r["texpack"]["size"] == 16640 and r["texpack"]["hash"] == "0x61165e"
    assert r["page_roundtrip"] and r["stage_rebuild_fits_span"] and r["rebuilt_pages_decode_equal"]
