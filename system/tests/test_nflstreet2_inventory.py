"""Focused checks for the owned NFL Street 2 (GameCube) inventory.

Every expectation below was read out of the owned build
(``/mnt/gbox/hyperspin/.../NFL Street 2 (USA).gcz``, build GN7E69), not copied
from another title.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gbox.nflstreet2_inventory import BUILD_ID, inventory  # noqa: E402

SRC = "/mnt/gbox/hyperspin/Arcade/collections/Nintendo GameCube/roms/NFL Street 2 (USA).gcz"

_MANIFEST = None


def manifest():
    global _MANIFEST
    if _MANIFEST is None:
        _MANIFEST = inventory(SRC)
    return _MANIFEST


def test_manifest_identity_and_census():
    m = manifest()
    assert m["build_id"] == BUILD_ID
    assert m["disc_title"] == "NFL STREET 2"
    assert m["file_count"] == 63
    assert m["kinds"] == {"terf": 48, "qkl": 13, "db": 1, "bnr": 1}
    assert m["engine"]["engine"] == "ea_terf_qkl"
    assert len(m["source_sha256"]) == 64
    assert len(m["main_dol"]["sha256"]) == 64
    assert m["main_dol"]["size"] > 0


def test_character_containers_are_mapped():
    m = manifest()
    roles = {k: v["role"] for k, v in m["character_containers"].items()}
    assert roles["plamodel.dat"] == "player_models"
    assert roles["platex.dat"] == "player_textures"
    assert roles["plaface.dat"] == "player_face_textures"
    assert roles["objmodel.dat"] == "object_models"
    assert roles["animdata.dat"] == "animations"


def test_native_target_asset_is_identified():
    m = manifest()
    t = m["native_target_asset"]
    assert t is not None
    assert t["name"] == "Obj_Barre01.ea3"
    assert t["format"] == "ea3"
    assert t["name_offset"] == 0x2860
    assert t["skeleton_chunk_offsets"][0] == 0x2000
    assert t["terf"]["header_size"] == 0x800
    assert t["terf"]["version"] == [2, 2, 1, 6]
    assert t["terf"]["subchunk"] == "HSH1"
    assert t["terf"]["entry_count"] == 175
    assert t["model_count"] >= 12
    assert t["disc_offset"] == t["member_offset"] + t["name_offset"]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS", name)
