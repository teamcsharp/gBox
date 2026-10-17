"""Focused tests for gbox.burnout2_inventory (Burnout 2 GC owned-disc inventory).

The full-disc integration test runs only when GBOX_BURNOUT2_ISO points at the owned image; the
synthetic tests validate the header/chunk parsers and the roster without the disc.
"""
import os
import struct

import pytest

from gbox.burnout2_inventory import (DISC_ID, DOL_ENTRY, DOL_OFFSET, ISO_SHA256, RACECARS, disc_header,
                                     dol_header, inventory, rw_chunks)


def make_head(game_id=b"GB4E51", title=b"Burnout 2", dol=0x1EC00, fst=0x20A700, fst_size=0x3F8D):
    head = bytearray(0x440)
    head[0:6] = game_id
    struct.pack_into(">I", head, 0x1C, 0xC2339F3D)
    head[0x20:0x20 + len(title)] = title
    struct.pack_into(">III", head, 0x420, dol, fst, fst_size)
    return bytes(head)


def test_disc_header_identity():
    hdr = disc_header(make_head())
    assert hdr["game_id"] == "GB4E51"
    assert hdr["title"] == "Burnout 2"
    assert hdr["magic"] == 0xC2339F3D
    assert hdr["dol_offset"] == DOL_OFFSET
    assert hdr["fst_offset"] == 0x20A700
    assert hdr["fst_size"] == 0x3F8D


def test_disc_header_rejects_non_gc():
    head = bytearray(0x440)
    head[0:6] = b"GB4E51"
    with pytest.raises(ValueError):
        disc_header(bytes(head))


def test_dol_header_sections():
    # two text sections, one data section, entry 0x80003140
    dol = bytearray(0x20000)
    struct.pack_into(">I", dol, 0x00, 0x100)   # text_off[0]
    struct.pack_into(">I", dol, 0x04, 0x2620)  # text_off[1]
    struct.pack_into(">I", dol, 0x1C, 0x18AFA0)  # data_off[0]
    struct.pack_into(">I", dol, 0x48, 0x80003100)  # text_addr[0]
    struct.pack_into(">I", dol, 0x4C, 0x80005800)  # text_addr[1]
    struct.pack_into(">I", dol, 0x64, 0x80005620)  # data_addr[0]
    struct.pack_into(">I", dol, 0x90, 0x2520)   # text_size[0]
    struct.pack_into(">I", dol, 0x94, 0x188980)  # text_size[1]
    struct.pack_into(">I", dol, 0xAC, 0x100)    # data_size[0]
    struct.pack_into(">I", dol, 0xE0, DOL_ENTRY)
    dh = dol_header(bytes(dol))
    assert dh["entry"] == DOL_ENTRY
    assert dh["text_sections"] == [(0x80003100, 0x2520), (0x80005800, 0x188980)]
    assert dh["data_sections"] == [(0x80005620, 0x100)]
    assert dh["size"] == 0x18AFA0 + 0x100


def test_rw_chunks_top_level():
    # little-endian {type,size,version}; size excludes the 12-byte header, version 0x1003ffff
    b = struct.pack("<III", 0x0809, 68, 0x1003FFFF) + b"\x00" * 68
    chunks = rw_chunks(b)
    assert len(chunks) == 1
    assert chunks[0]["type"] == 0x0809
    assert chunks[0]["size"] == 68
    assert chunks[0]["version"] == 0x1003FFFF


def test_roster_unique_and_complete():
    assert len(RACECARS) == 22
    assert len(set(RACECARS)) == 22
    assert all(c.islower() for c in RACECARS)


@pytest.mark.skipif(not os.environ.get("GBOX_BURNOUT2_ISO"), reason="owned ISO not mounted")
def test_full_inventory_integration():
    m = inventory(os.environ["GBOX_BURNOUT2_ISO"])
    assert m["game_id"] == DISC_ID
    assert m["iso_sha256"] == ISO_SHA256
    assert m["dol"]["offset"] == DOL_OFFSET
    assert m["dol"]["entry"] == hex(DOL_ENTRY)
    assert set(m["racecars"]) == set(RACECARS)
    # every car carries exactly the four expected files
    for car, files in m["racecars"].items():
        assert set(files) == {f"{car}.rcf", f"{car}.rcx", f"{car}a.rws", f"{car}e.rws"}
    # fingerprint claims: RenderWare streams + GameCube TPL textures
    assert m["fst"]["extensions"][".rws"] >= 150
    assert m["fst"]["extensions"][".tpl"] == 2
