from pathlib import Path

import pytest

from gbox import doa2_lab as L


def listing():
    return {f"DOA2/{stem}.{extension}": (1, 8)
            for stem in ("KAS00", "KAS01", "AYA00", "KTE02") for extension in ("CHR", "BIN", "SUP")}


def test_selects_actual_costumes_and_named_fighters():
    assert L.selected_costumes(listing(), "all", "all") == [("KAS", "00"), ("KAS", "01"), ("AYA", "00"), ("KTE", "02")]
    assert L.selected_costumes(listing(), "Ein", "all") == [("KTE", "02")]
    assert L.selected_costumes(listing(), "Kasumi:1", "00") == [("KAS", "01")]


def test_missing_costume_and_incomplete_archive_triplet_rejected():
    with pytest.raises(ValueError, match="absent"):
        L.selected_costumes(listing(), "Ein", "00")
    files = listing()
    del files["DOA2/KTE02.SUP"]
    with pytest.raises(ValueError, match="absent"):
        L.selected_costumes(files, "Ein", "02")


def test_profile_path_remains_inside_game_rig_directory(tmp_path):
    root = tmp_path / "rigs"
    root.mkdir()
    (root / "verified.json").write_text("{}")
    (tmp_path / "other.json").write_text("{}")
    assert L.profile_file(root, "verified.json") == root / "verified.json"
    for path in ("../other.json", "missing.json", ""):
        with pytest.raises(ValueError):
            L.profile_file(root, path)


def test_native_cache_path_cannot_escape_game_analysis(tmp_path):
    assert L.cache_directory(tmp_path, 'native-cloth-cache') == tmp_path / 'native-cloth-cache'
    for path in ('', '../outside', str(tmp_path.parent / 'outside')):
        with pytest.raises(ValueError, match='inside'):
            L.cache_directory(tmp_path, path)


def test_detail_summary_preserves_costume_results_and_bounds_vertex_payload():
    value = {'costumes': [{'costume': str(i), 'status': 'verified',
                          'provenance': [{'vertex': j} for j in range(1200)]} for i in range(79)]}
    summary = L.compact_report(value)
    assert len(summary['costumes']) == 79
    assert summary['costumes'][0]['provenance']['count'] == 1200
    assert summary['costumes'][0]['provenance']['details_artifact'] == 'doa2-details.json'
    assert len(summary['costumes'][0]['provenance']['preview']) == 2
    assert isinstance(value['costumes'][0]['provenance'], list)


def test_corrupt_native_cache_is_not_a_successful_tool_result(tmp_path, monkeypatch):
    from gbox.doa2_native_export import generate_cache
    monkeypatch.setattr(generate_cache, 'verify', lambda _: {'errors': ['changed source hash']})
    with pytest.raises(ValueError, match='verification failed'):
        L.run_cache(None, None, tmp_path, tmp_path, 'verify')


def test_complete_source_summary_keeps_counts_and_full_artifact_pointer():
    report = {'stem': 'GEN00', 'triangles': 7512, 'joints': 17, 'vertices': 5264,
              'native_chains': [{'vertex': i} for i in range(10000)],
              'limits': {'physics': 'frozen neutral source'}}
    summary = L.compact_report({'native_report': report, 'files': ['GEN00_rigged.gltf'] * 70})
    assert summary['native_report']['triangles'] == 7512
    assert summary['native_report']['report_file'] == 'core-report.json'
    assert summary['native_report']['details_artifact'] == 'doa2-details.json'
    assert summary['native_report']['limits_in'] == 'source_export_limits'
    assert 'native_chains' not in summary['native_report']
    assert summary['files']['count'] == 70
    assert len(summary['files']['preview']) == 2
    assert len(report['native_chains']) == 10000
