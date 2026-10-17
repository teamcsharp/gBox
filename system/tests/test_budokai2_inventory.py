"""Focused tests for gbox.budokai2_inventory: the #XXX chunk header and (when the disc is mounted)
the live disc inventory/roster for Dragon Ball Z: Budokai 2 (GZ3E70)."""
from __future__ import annotations

import struct
from pathlib import Path

import pytest

from gbox import budokai2_inventory as b2

GCZ = Path("/mnt/gbox/hyperspin/Arcade/collections/Nintendo GameCube/roms/Dragon Ball Z - Budokai 2 (USA).gcz")
SOURCE_SHA256 = "0defc8e19a79bceab72ce70c773fe522633a0e580d9a651c9a582db4e2485002"


def test_chunk_header_section_table_form():
    data = b"#CFC" + struct.pack(">II", 10, 0x10) + b"\x00" * 8 + struct.pack(">10I", *range(10))
    h = b2.chunk_header(data)
    assert h["magic"] == "#CFC"
    assert h["label"] == "face_config"
    assert h["count"] == 10


def test_chunk_header_csk_non_count_form():
    # #CSK's first u32 is 0x20 (header/version), not a count; word1 != 0x10 so count stays None.
    data = b"#CSK" + struct.pack(">II", 0x20, 0x00)
    h = b2.chunk_header(data)
    assert h["magic"] == "#CSK"
    assert h["count"] is None


def test_chunk_header_rejects_garbage():
    assert b2.chunk_header(b"\x00\x01\x02\x03" + b"\x00" * 4) is None
    assert b2.chunk_header(b"#CS") is None
    assert b2.chunk_header(b"#ab1" + b"\x00" * 4) is None      # lower-case magic is not a chunk


@pytest.mark.skipif(not GCZ.exists(), reason="Budokai 2 GCZ not mounted")
def test_live_inventory_and_roster():
    inv = b2.inventory(GCZ, SOURCE_SHA256)
    assert inv["image"]["disc_id"] == "GZ3E70"
    assert inv["main_dol"]["size"] == 3035872
    assert inv["main_dol"]["sha256"] == "e8940f32d9e91a34a0b4d7c3e67c1467bfd52f49ad8d9f476a516adbf3cebe17"
    assert inv["fst_files"] == 6642
    # 41 playable characters, each with a .ccm material table + .csk model + .spx texture atlas.
    assert len(inv["characters"]) == 41
    for code in ("gok", "frz", "cel", "rad", "pic"):
        assert code in inv["characters"], code
        files = inv["characters"][code]["files"]
        assert {"ccm", "csk", "spx", "act"} <= set(files), (code, files)
    # the chunk census confirms the Dimps #XXX family and the absence of AFS/CPK containers.
    assert inv["chunk_magics"]["#CSK"] == 41
    assert inv["chunk_magics"]["#CCM"] == 41
    assert "#SPX" in inv["chunk_magics"]
    assert "afs" not in inv["extensions"] and "cpk" not in inv["extensions"]
    # the story-mode name table resolves base slots to display names in game order; fusions carry code=None.
    by_code = {r["code"]: r["name"] for r in inv["roster"] if r["code"]}
    assert by_code["gok"] == "GOKOU"
    assert by_code["frz"] == "FREEZA"
    assert by_code["rad"] == "RADITZ"
    assert by_code["pic"] == "PICCOLO"
    names = [r["name"] for r in inv["roster"]]
    assert "GOTAN (GOKOU)" in names                      # fusion/absorption entries are recorded
    assert all(r["code"] is None for r in inv["roster"] if "(" in r["name"])


@pytest.mark.parametrize("size", range(4, 12))
def test_chunk_header_rejects_every_truncated_word_pair(size):
    assert b2.chunk_header((b"#CCM" + bytes(8))[:size]) is None


def test_cli_prints_fusion_without_a_code(monkeypatch, capsys):
    value = dict(image={}, main_dol={}, fst_files=0, chunk_magics={}, containers="",
                 roster=[dict(index=0, code=None, name="GOTAN (GOKOU)")])
    monkeypatch.setattr(b2, "inventory", lambda *args: value)
    assert b2.main(["unused.gcz"]) == 0
    assert "GOTAN (GOKOU)" in capsys.readouterr().out
