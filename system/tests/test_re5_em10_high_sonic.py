"""The import probe must address the exact model and keep its paired resources intact."""
import importlib.util
from pathlib import Path
import zlib

import pytest

from gbox import mt_arc, mt_model, mtf_author
from tests.test_mtf_author import make_target, import_triangle


spec = importlib.util.spec_from_file_location(
    "re5_em10_high_sonic", Path(__file__).parents[1] / "tools/probes/re5_em10_high_sonic.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def make_archive():
    entries = []
    for name, data in (("em1000_low", make_target(1)), ("em1000", b"MRL\0unchanged"),
                       ("em1000", make_target(2))):
        entries.append(mt_arc.Entry("pawn\\em\\em10\\model\\" + name, 0x241F5DEB,
                                    0x40000000 | len(data), 0, 0, zlib.compress(data, 6)))
    return mt_arc.build(mt_arc.Arc(7, entries))


def test_exact_mod_selection_keeps_low_model_and_paired_mrl():
    source = make_archive()
    built, raw, receipt = probe.build_archive(source, import_triangle(), [(0, 1, 2)])
    before, after = mt_arc.parse(source), mt_arc.parse(built)
    assert after.entries[0].data == before.entries[0].data
    assert after.entries[1].data == before.entries[1].data
    assert zlib.decompress(after.entries[2].data) == raw
    assert after.entries[2].tag == 0x40000000 | len(raw)
    assert mt_model.parse_mod(raw).meshes() == mt_model.parse_mod(make_target(2)).meshes()
    assert receipt["dropped_triangles"] == 0 and receipt["live_verified"] is False


def test_missing_model_is_not_silently_substituted_by_another_variant():
    with pytest.raises(mtf_author.AuthorError, match="exactly one MOD"):
        probe.build_archive(make_archive(), import_triangle(), [(0, 1, 2)], model_name="em100")


def test_fit_preserves_aspect_and_places_feet_inside_all_three_bounds():
    vertices = [{"position": p} for p in ((-100., 0., -10.), (100., 10., 10.), (0., 100., 0.))]
    bounds = mt_model.parse_mod(make_target(1)).bounds()
    fitted = probe.fit_vertices(vertices, bounds)
    assert fitted[0]["position"][1] == bounds["min"]["y"]
    assert fitted[1]["position"][0] - fitted[0]["position"][0] == pytest.approx(80.)
    assert fitted[2]["position"][1] - fitted[0]["position"][1] == pytest.approx(40.)


def test_cli_emits_complete_overlay_and_honest_receipt(tmp_path, monkeypatch):
    import json
    from gbox import re5_ips
    source = tmp_path / "uEm10.arc"
    source.write_bytes(make_archive())
    monkeypatch.setattr(probe, "source_mesh", lambda _: (import_triangle(), [(0, 1, 2)]))
    output, overlay = tmp_path / "test.arc", tmp_path / "overlay"
    assert probe.main(["--archive", str(source), "--output", str(output), "--overlay", str(overlay)]) == 0
    assert (overlay / re5_ips.ARCHIVE_PATH).read_bytes() == output.read_bytes()
    assert (overlay / "exefs/main.ips").read_bytes() == re5_ips.make_ips()
    assert json.loads(output.with_suffix(".json").read_text())["live_verified"] is False
