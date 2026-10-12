"""John Woo Presents Stranglehold (PS3, BLUS30081) native package reader tests."""
import json
import struct
import zlib
from pathlib import Path

import pytest

from gbox import stranglehold as S

COOKED = Path("/mnt/gbox/quickswap2/Emulation/PS3/John Woo Presents Stranglehold (USA) (En,Fr,De,Es,It) (Collector's Edition)/PS3_GAME/USRDIR/StrangleholdGame/CookedPS3")


def test_placeholder_glb_roundtrip(tmp_path):
    glb = S._placeholder_glb("TestChar", {"source": "synthetic"})
    assert glb[:4] == b"glTF"
    magic, ver, total = struct.unpack_from("<III", glb, 0)
    jl = struct.unpack_from("<I", glb, 12)[0]
    gl = json.loads(glb[20:20 + jl])
    assert magic == 0x46546C67 and ver == 2 and total == len(glb)
    prim = gl["meshes"][0]["primitives"][0]
    assert gl["accessors"][prim["indices"]]["count"] == 3
    assert "POSITION" in prim["attributes"]


def test_registered_reader_and_roster():
    from gbox import characters as C
    r = next(r for r in C.DEDICATED if r[0] == "stranglehold")
    assert r[1]("john woo presents stranglehold", "ps3")
    assert not r[1]("john woo presents stranglehold", "xbox")


@pytest.mark.skipif(not (COOKED / "char_tequila_MP.xxx").is_file(), reason="Stranglehold mount not present on this node")
def test_container_parses_tequila():
    con = S.Container(COOKED / "char_tequila_MP.xxx")
    assert len(con.names) >= 100
    assert len(con.imports) > 0
    assert len(con.exports) > 0
    meshes = con.mesh_exports()
    textures = con.texture_exports()
    assert len(meshes) >= 1
    assert len(textures) >= 1
    for m in meshes:
        assert m["class_name"] == "SkeletalMesh"
        assert m["size"] > 0
        blob = con.blob(m["index"])
        assert len(blob) == m["size"]
    for t in textures:
        assert t["class_name"] == "Texture2D"
        assert t["size"] > 0


@pytest.mark.skipif(not (COOKED / "char_tequila_MP.xxx").is_file(), reason="Stranglehold mount not present on this node")
def test_container_parses_multiple_characters():
    for name in ["char_tequila_MP.xxx", "char_CaptainLee_MP.xxx", "char_damonZakarov_MP.xxx", "char_hkCop_MP.xxx"]:
        path = COOKED / name
        if not path.is_file():
            continue
        con = S.Container(path)
        assert len(con.mesh_exports()) >= 1
        assert len(con.texture_exports()) >= 1


@pytest.mark.skipif(not (COOKED / "char_tequila_MP.xxx").is_file(), reason="Stranglehold mount not present on this node")
def test_extract_run_produces_glb_manifest_and_blob(tmp_path):
    class Cfg:
        cache = str(tmp_path / "cache")
    class FakeCtx:
        config = Cfg()
    game = {"game_id": "9c436f5a9754f777", "title": "John Woo Presents Stranglehold (Collector's Edition)", "platform": "ps3", "path": str(COOKED.parent.parent)}
    e = {"slug": "stranglehold_tequila_MP", "name": "Stranglehold Tequila"}
    result = S.extract_run(FakeCtx(), game, e, tmp_path)
    assert result["tool"] == "gbox.stranglehold"
    glb = result["files"][0]
    assert glb.exists() and glb.stat().st_size > 0
    slug_dir = glb.parent
    assert (slug_dir / "manifest.json").is_file()
    assert len(list(slug_dir.glob("*.bin"))) == 1
