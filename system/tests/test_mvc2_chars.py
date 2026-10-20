"""MVC2 DC DEDICATED sprite reader (#1315 reader stage).

Tests use the owned disc cache; they are skipped when it is absent.
"""

import json
from pathlib import Path

import pytest

from gbox import mvc2_chars as C

GDI = Path.home() / "gBox_alt/gbox-cache/dc/02db6d37c0e20375/disc.gdi"


@pytest.mark.skipif(not GDI.exists(), reason="unpacked MVC2 disc cache not present")
class TestCoverage:
    def test_all_59_parse(self):
        cov = C.coverage(GDI)
        assert cov["parsed"] == 59
        assert cov["total"] == 59
        assert not cov["failed"]

    def test_ryu_counts(self):
        ryu = next(r for r in C.coverage(GDI)["results"] if r["cid"] == 0)
        assert ryu["n_parts"] == 1533
        assert ryu["n_sprites"] == 441
        assert ryu["n_anim_groups"] == 26


@pytest.mark.skipif(not GDI.exists(), reason="unpacked MVC2 disc cache not present")
class TestExport:
    def test_ryu_export_files(self, tmp_path):
        res = C.export_character(GDI, 0, tmp_path)
        paths = {f.name for f in res["files"]}
        assert "mvc2_ryu.glb" in paths
        assert "mvc2_ryu.json" in paths
        assert "mvc2_ryu.parts.png" in paths
        assert "mvc2_ryu.sprites.png" in paths

    def test_ryu_manifest(self, tmp_path):
        res = C.export_character(GDI, 0, tmp_path)
        manifest = json.loads((tmp_path / "mvc2_ryu.json").read_text())
        assert manifest["meta"]["slug"] == "mvc2_ryu"
        assert manifest["meta"]["n_parts"] == 1533
        assert manifest["meta"]["n_sprites"] == 441
        assert len(manifest["parts"]) == 1533
        assert manifest["parts"][0]["atlas_x"] >= 0
        assert len(manifest["sprites"]) == 441
        assert "atlas" in manifest
        assert "parts" in manifest["atlas"]
        assert "sprites" in manifest["atlas"]

    def test_ryu_atlas_reasonable_size(self, tmp_path):
        res = C.export_character(GDI, 0, tmp_path)
        pa = res["manifest"]["atlas"]["parts"]
        sa = res["manifest"]["atlas"]["sprites"]
        assert pa["w"] <= 4096
        assert sa["w"] <= 4096

    def test_preview_glb_valid(self, tmp_path):
        res = C.export_character(GDI, 0, tmp_path)
        glb = tmp_path / "mvc2_ryu.glb"
        assert glb.stat().st_size > 0
        d = glb.read_bytes()
        assert d[:4] == b"glTF"
        jl = int.from_bytes(d[12:16], "little")
        gl = json.loads(d[20:20 + jl])
        assert gl["asset"]["version"] == "2.0"
        assert gl["meshes"]
        assert gl["images"][0]["uri"].endswith(".png")


def test_roster_has_59_entries():
    ros = C.roster()
    assert len(ros) == 59
    assert ros[0]["slug"] == "mvc2_ryu"
    assert ros[0]["key"] == "00"
    assert ros[-1]["slug"] == "mvc2_servbot"
    assert ros[-1]["key"] == "3A"


def test_pack_shelves():
    rects = [(10, 10, 0), (10, 20, 1), (10, 10, 2)]
    w, h, pos = C._pack_shelves(rects, max_width=100)
    assert w <= 100
    assert len(pos) == 3
    w2, h2, pos2 = C._pack_shelves([(10, 10, 0), (30, 10, 1)], max_width=100)
    assert pos2 == [(30, 0), (0, 0)]          # caller's tile order, not the packing order (atlas was clipping wide tiles)
