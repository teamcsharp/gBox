"""Tests for gbox.pso3_inventory (PSO Episode III, GPSE8P)."""
import struct
from pathlib import Path

import pytest

from gbox import pso3_inventory as inv

GCZ = Path("/mnt/gbox/hyperspin/Arcade/collections/Nintendo GameCube/roms/Phantasy Star Online Episode III - C.A.R.D. Revolution (USA).gcz")


def test_njcm_header():
    assert inv.parse_njcm_header(b"NJCM" + struct.pack("<I", 0x52B0)) == {"tag": "NJCM", "body_size": 0x52B0, "end": 0x52B8}
    with pytest.raises(ValueError):
        inv.parse_njcm_header(b"NJTL\0\0\0\0")


def test_afs_toc():
    blob = b"AFS\0" + struct.pack("<I", 2) + struct.pack("<IIII", 0x800, 10, 0x1000, 20)
    assert inv.parse_afs_toc(blob) == [(0x800, 10), (0x1000, 20)]
    with pytest.raises(ValueError):
        inv.parse_afs_toc(b"XXXX")


def test_player_names():
    assert inv.player_name_parts("plAbdy00.nj") == ("A", "bdy", "00")
    assert inv.player_name_parts("plAtex.afs") is None


def test_owned_disc():
    if not GCZ.is_file():
        pytest.skip("owned source not reachable")
    r = inv.inventory(str(GCZ), source_sha256="0" * 64, image_sha256=False)
    assert r["build"] == "GPSE8P" and r["image_size"] == 1459978240
    assert len(r["player_models"]) == 198
    assert all(p["njcm"] and p["njcm"]["body_size"] + 8 <= p["size"] for p in r["player_models"])
    assert r["plAtex_afs"]["entries"] == 137 and r["plAtex_afs"]["in_range"]
    assert r["gvm_count"] == 440


def test_player_model_probe():
    from gbox import pso3_analysis as an
    if not GCZ.is_file():
        pytest.skip("owned source not reachable")
    with inv.GCZ(str(GCZ)) as g:
        fo, fs = struct.unpack(">II", g.read(0x424, 8))
        files = {p.split("/", 2)[-1]: (o, s) for p, o, s in inv.FST(g.read(fo, fs)).walk()}
        d = g.read(*files["plAbdy00.nj"])
        r = an.analyze_nj(d)
        assert (r["bones"], r["tree_nodes"], r["vertices"], r["triangles"]) == (64, 64, 269, 692)
        assert r["bytes_covered"] == 21158 and r["body_size"] == 21168
        o, s = files["plAtex.afs"]
        toc = inv.parse_afs_toc(g.read(o, 0x4000))
        gv = [an.parse_gvr_header(g.read(o + a, 0x20)) for a, _ in toc]
        assert len(gv) == 137 and len({x["gbix"] for x in gv}) == 137


def test_njcm_body_errors():
    from gbox import pso3_analysis as an
    with pytest.raises(ValueError):
        an.njcm_body(b"XXXX0000")
    with pytest.raises(ValueError):
        an.njcm_body(b"NJCM" + struct.pack("<I", 99) + b"\0" * 4)


def test_export_body_glb(tmp_path):
    from gbox import pso3_analysis as an
    if not GCZ.is_file():
        pytest.skip("owned source not reachable")
    with inv.GCZ(str(GCZ)) as g:
        fo, fs = struct.unpack(">II", g.read(0x424, 8))
        files = {p.split("/", 2)[-1]: (o, s) for p, o, s in inv.FST(g.read(fo, fs)).walk()}
        d = g.read(*files["plAbdy00.nj"])
        o, _ = files["plAtex.afs"]
        ents = [g.read(o + a, n) for a, n in inv.parse_afs_toc(g.read(o, 0x4000))]
    glb, used, problems = an.export_body_glb(d, ents, "pso3_plAbdy00", tmp_path)
    assert used == {0: 0, 1: 1, 2: 2, 3: 3, 4: 4}
    assert problems == []
    b = glb.read_bytes()
    assert b[:4] == b"glTF" and len(b) > 100_000
    assert len(list((tmp_path / "textures").glob("*.png"))) == 5
