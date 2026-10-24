"""Tests for gbox.pd_model (Perfect Dark modeldef probe).

Synthetic fixture bytes follow n64decomp/perfect_dark types.h
(struct modeldef / modelnode, pointers relative to VMA 0x05000000).
The owned-ROM test runs only when PD_ROM points at the pal-final z64.
"""
import os
import struct
from pathlib import Path

import pytest

from gbox import pd_model


def _fixture() -> bytes:
    b = bytearray(0x100)
    # modeldef @0: rootnode=0x40, skel=3, parts=0x1c, numparts=1,
    # nummatrices=2, scale=1.0, rwdatalen=0, numtexconfigs=0, texconfigs=0
    struct.pack_into(">IIIhhfhhI", b, 0, 0x05000040, 3, 0x0500001C, 1, 2, 1.0, 0, 0, 0)
    struct.pack_into(">I", b, 0x1C, 0x05000040)   # parts[0]
    struct.pack_into(">h", b, 0x20, 0)            # part number
    # root node @0x40: type 0x02 POSITION, rodata @0x80
    struct.pack_into(">HxxIIIII", b, 0x40, 2, 0x05000080, 0, 0, 0, 0)
    struct.pack_into(">fffhhhhf", b, 0x80, 1.0, 2.0, 3.0, 0, 0, -1, -1, 100.0)
    return bytes(b)


def test_header_fields():
    m = pd_model.parse(_fixture())
    assert (m.skel_index, m.numparts, m.nummatrices, m.scale) == (3, 1, 2, 1.0)
    assert m.rootnode_offset == 0x40
    assert m.node_count() == 1
    assert m.nodes[0].type_name == "POSITION"


def test_rejects_short_header():
    with pytest.raises(ValueError):
        pd_model.parse(b"\x00" * 8)


def _rom():
    p = os.environ.get("PD_ROM")
    if not p or not Path(p).exists():
        pytest.skip("PD_ROM not set")
    from gbox import n64_rom
    return n64_rom.read(Path(p))


def test_owned_rom_cdark_combat():
    m = pd_model.load_from_rom(_rom(), "Cdark_combatZ")
    assert (m.rootnode_offset, m.skel_index, m.numparts) == (0x1E0, 9, 7)
    assert (m.nummatrices, m.numtexconfigs, m.node_count()) == (19, 34, 61)


def test_owned_rom_all_chr_invariants():
    from gbox import pd_inventory as inv
    rom = _rom()
    n = 0
    for f in inv.inventory(rom)["files"]:
        if f["kind"] != "chr":
            continue
        blob = rom[f["offset"]:f["end"]]
        data, _ = inv.unzip_pd(blob) if f["zipped"] else (blob, 0)
        m = pd_model.parse(data)
        offs = {x.file_offset: x for x in m.nodes}
        for x in m.nodes:
            if x.child_offset is not None:
                assert offs[x.child_offset].parent_offset == x.file_offset
            if x.next_offset is not None:
                assert offs[x.next_offset].prev_offset == x.file_offset
            if x.type_name == "DL":
                r = x.rodata
                assert r["vertices_offset"] + r["numvertices"] * 16 <= len(data)
        n += 1
    assert n == 148
