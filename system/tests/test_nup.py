"""gbox.nup: the NUP v1 reader, extractor, verifier and its library/model hand-offs.

The fixture is the format project's own sample container (tests/fixtures/sample_game.nup): 2 packages, 9 directories,
5 files, raw + Zstandard extents. Failure cases patch that container's TOC and recompute its SHA-256, so the reader
still sees a structurally valid header and the specific rule under test is what rejects it.
"""
import hashlib
import json
import shutil
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

from gbox import catalog, nup, nup_models, switch_nsp, switch_nup, switch_mods, tools
from gbox.config import Config

FIXTURE = Path(__file__).parent / "fixtures" / "sample_game.nup"
TOC_OFFSET = 0x80
TOC_SHA_AT = 0x18
FILE0_CODEC_IN_TOC = nup._TOC_HEAD.size + 2 * nup.PKG_SIZE + 9 * nup.DIR_SIZE + 0x40   # sample: 2 packages, 9 dirs


def patched(tmp_path, *, at: int, data: bytes, fix_toc_hash: bool = True) -> Path:
    """A copy of the fixture with `data` written at TOC-relative offset `at` (and a valid TOC hash unless asked)."""
    raw = bytearray(FIXTURE.read_bytes())
    toc_size = struct.unpack_from("<Q", raw, 0x10)[0]
    raw[TOC_OFFSET + at:TOC_OFFSET + at + len(data)] = data
    if fix_toc_hash:
        raw[TOC_SHA_AT:TOC_SHA_AT + 32] = hashlib.sha256(raw[TOC_OFFSET:TOC_OFFSET + toc_size]).digest()
    out = tmp_path / "patched.nup"
    out.write_bytes(raw)
    return out


def patched_super(tmp_path, *, at: int, data: bytes) -> Path:
    """A copy with `data` written into the superblock at absolute offset `at`."""
    raw = bytearray(FIXTURE.read_bytes())
    raw[at:at + len(data)] = data
    out = tmp_path / "super.nup"
    out.write_bytes(raw)
    return out


def test_superblock_and_toc_parse():
    with nup.NupReader(FIXTURE) as r:
        assert r.super["header_size"] == 0x80 and r.super["header_version"] == 1
        assert r.super["toc_offset"] == 0x80 and r.super["blob_offset"] == 0x420
        assert (r.dir_count, r.file_count) == (9, 5)
        assert [p.kind_name for p in r.packages] == ["base", "update"]
        assert r.packages[0].title_id_hex == "0100123456789ABC"
        assert r.packages[1].version == 0x10000 and r.packages[1].version_str == "1.0.0"


def test_metadata_title_publisher_version_build_id_and_icon():
    with nup.NupReader(FIXTURE) as r:
        info = r.describe()
        assert info["title"] == "Sample NX Adventure"
        assert info["publisher"] == "Nintendo"
        assert info["primary"]["display_version"] == "1.1.0"
        assert len(info["primary"]["build_id"]) == 64
        icon = r.icon(r.packages[0])
        assert icon["mime"] == "image/png" and icon["bytes"][:8] == b"\x89PNG\r\n\x1a\n"
        assert r.title_name(r.packages[0]) == "Sample NX Adventure"


def test_light_reader_skips_the_tree_but_keeps_identity():
    with nup.NupReader(FIXTURE, light=True) as r:
        info = r.describe()
        assert r.dirs == [] and r.files == []
        assert info["title_id"] == "0100123456789ABC" and info["title"] == "Sample NX Adventure"
        assert info["counts"] == {"packages": 2, "dirs": 9, "files": 5}
        assert "files_total" not in info


def test_walk_plan_and_subtree():
    with nup.NupReader(FIXTURE) as r:
        base = r.package_of("base")
        rels = {rel: f.size for rel, f in r.walk(base)}
        assert rels == {"exefs/main": 2144, "romfs/data/config.json": 92,
                        "romfs/data/levels/level01.dat": 8000, "romfs/textures/ui_sheet.bin": 13000}
        allplan = {p.relpath: p.size for p in r.plan(mode="all")}
        assert allplan["base/exefs/main"] == 2144
        assert allplan["updates/65536/romfs/data/patch_notes.txt"] == 77
        sub = {p.relpath for p in r.plan(mode="subtree", subtree="romfs", package="base")}
        assert sub == {"data/config.json", "data/levels/level01.dat", "textures/ui_sheet.bin"}
        assert r.resolve(base, "ROMFS/data").is_dir                     # case-insensitive on each component


def test_raw_and_zstd_content_matches_the_container_hashes():
    with nup.NupReader(FIXTURE) as r:
        main = r.file_bytes(0)
        assert main[:4] == b"NSO0" and len(main) == 2144
        assert hashlib.sha256(main).hexdigest() == r.files[0].sha256_hex
        assert r.head(0, 4) == b"NSO0"                                  # zstd: the uncompressed head
        assert r.head(1, 4).startswith(b"{")                            # raw json


def test_extract_package_then_verify_every_written_byte(tmp_path):
    with nup.NupReader(FIXTURE) as r:
        out = r.extract(tmp_path / "pkg", mode="package", package=0)
        assert out["files"] == 4 and out["bytes"] == 23236
        data = (tmp_path / "pkg" / "romfs" / "textures" / "ui_sheet.bin").read_bytes()
        assert hashlib.sha256(data).hexdigest() == r.files[3].sha256_hex
        with pytest.raises(nup.NupError, match="already exists"):
            r.extract(tmp_path / "pkg", mode="package", package=0)


def test_materialize_overlays_updates_and_writes_the_marker(tmp_path):
    with nup.NupReader(FIXTURE) as r:
        out = r.materialize(tmp_path / "game")
        assert out["has_exefs"] and out["has_romfs"] and out["files"] == 5
        assert (tmp_path / "game" / "exefs" / "main").read_bytes()[:4] == b"NSO0"
        assert (tmp_path / "game" / "romfs" / "data" / "patch_notes.txt").is_file()   # the update overlaid
        marker = json.loads((tmp_path / "game" / nup.MARKER).read_text())
        assert marker["kind"] == "nup-materialized" and marker["title_id"] == "0100123456789ABC"
        assert [p["kind"] for p in marker["packages"]] == ["base", "update"]


def test_verify_structural_and_deep():
    with nup.NupReader(FIXTURE) as r:
        assert r.verify()["ok"] and r.verify(deep=True)["ok"]
        assert r.verify(deep=True)["files"] == 5


def test_bad_magic_and_bad_toc_hash_are_rejected(tmp_path):
    bad = bytearray(FIXTURE.read_bytes())
    bad[0:4] = b"NUP\x02"
    p = tmp_path / "badmagic.nup"; p.write_bytes(bad)
    with pytest.raises(nup.NupError, match="major version"):
        nup.NupReader(p)
    p2 = tmp_path / "badtoc.nup"
    raw = bytearray(FIXTURE.read_bytes()); raw[TOC_OFFSET + 0x30] ^= 0xFF; p2.write_bytes(raw)
    with pytest.raises(nup.NupError, match="TOC SHA-256 mismatch"):
        nup.NupReader(p2)


def test_unknown_codec_is_rejected_even_with_a_valid_toc_hash(tmp_path):
    p = patched(tmp_path, at=FILE0_CODEC_IN_TOC, data=b"\x07")
    with pytest.raises(nup.NupError, match="unknown extent codec"):
        nup.NupReader(p)


def test_an_unsafe_output_path_is_refused_before_any_write(tmp_path):
    with nup.NupReader(FIXTURE) as r:
        plan = [nup.PlannedFile(0, "../escaped.bin", 2144)]
        with pytest.raises(nup.NupError, match="unsafe file name"):
            r.extract(tmp_path / "out", plan=plan)
        assert not (tmp_path / "escaped.bin").exists()


def test_short_and_missing_files_fail_closed(tmp_path):
    short = tmp_path / "short.nup"; short.write_bytes(FIXTURE.read_bytes()[:64])
    with pytest.raises(nup.NupError, match="too short"):
        nup.NupReader(short)
    wrong_size = patched_super(tmp_path, at=0x40, data=struct.pack("<Q", FIXTURE.stat().st_size + 1))
    with pytest.raises(nup.NupError, match="file_size"):
        nup.NupReader(wrong_size)


def test_switch_nup_catalog_fields_and_launchability(tmp_path):
    serial, extra = switch_nup.catalog_fields(FIXTURE)
    assert serial == "0100123456789ABC"
    assert extra["nup"] is True and extra["nup_title"] == "Sample NX Adventure"
    assert extra["nup_display_version"] == "1.1.0" and extra["nup_packages"] == 2
    assert switch_nup.launchable(FIXTURE)[0] is False
    with nup.NupReader(FIXTURE) as r:
        r.materialize(tmp_path / "game")
    assert switch_nup.materialized(tmp_path / "game")["title_id"] == "0100123456789ABC"
    assert switch_nup.launchable(tmp_path / "game") == (True, "")
    assert switch_nsp.launchable(FIXTURE)[0] is False
    assert switch_nsp.title_id(tmp_path / "game") == "0100123456789ABC"


def test_romfs_registry_is_what_switch_mods_reads(tmp_path):
    with nup.NupReader(FIXTURE) as r:
        r.materialize(tmp_path / "game")
    cfg = Config(data_dir=tmp_path / "data", cache_dir=tmp_path / "cache")
    switch_nup.register_romfs(cfg, "0100123456789ABC", tmp_path / "game")
    assert switch_nup.romfs_for(cfg, "0100123456789ABC") == tmp_path / "game" / "romfs"
    assert switch_mods.base_romfs(cfg, "0100123456789ABC") == tmp_path / "game" / "romfs"
    assert switch_mods.title_id_for(tmp_path / "game") == "0100123456789ABC"
    assert switch_mods.title_id_for(FIXTURE) == "0100123456789ABC"


def test_catalog_lists_the_archive_and_the_extracted_title(tmp_path):
    lib = tmp_path / "switch"
    lib.mkdir()
    shutil.copy2(FIXTURE, lib / "Sample NX Adventure [0100123456789ABC].nup")
    with nup.NupReader(lib / "Sample NX Adventure [0100123456789ABC].nup") as r:
        r.materialize(lib / "Sample NX Adventure")
    entries, problems = catalog.scan([lib], {"switch": "configured"}, lib_id="test-switch", do_hash=False,
                                     platform_hint="switch")
    assert problems == []
    by_format = {e.format: e for e in entries}
    assert set(by_format) == {"nup", "nup_folder"}
    assert by_format["nup"].serial == "0100123456789ABC"
    assert by_format["nup"].launch["nup_extract_required"] is True
    folder = by_format["nup_folder"]
    assert folder.serial == "0100123456789ABC" and folder.launch["nup_folder"] is True
    assert folder.size == 23313 and folder.source_paths == [str(lib / "Sample NX Adventure")]


def test_model_sources_are_extracted_with_a_manifest(tmp_path):
    out = tmp_path / "game"
    result = switch_nup.extract_models(FIXTURE, out, extra_patterns=[r".*\.json$"])
    assert result["files"] == 1
    assert (out / "models_src" / "romfs" / "data" / "config.json").is_file()
    manifest = json.loads((out / "models_src" / "manifest.json").read_text())
    assert manifest["kind"] == "nup-models" and manifest["title_id"] == "0100123456789ABC"
    assert manifest["counts"] == {"containers": 0, "models": 1, "importable": 0}
    assert manifest["next"]


def test_model_classification_and_re_engine_magic():
    assert nup_models.classify("romfs/re_chunk_000.pak") == "container"
    assert nup_models.classify("romfs/data/patch_01.pak") == "container"
    assert nup_models.classify("romfs/ch/cha0/body.mesh.221108797") == "model"
    assert nup_models.classify("romfs/ch/cha0/body.glb") == "model"
    assert nup_models.classify("romfs/data/config.json") is None
    assert nup_models.magic_kind(b"KPKA\x02\x00") == "re-engine-pak"
    assert nup_models.magic_kind(b"ARC\x00\x07\x00") == "mt-framework-arc"
    handoff = nup_models._converter("re-engine-pak")
    assert "re4r" in handoff["reader"] and "Windows" in handoff["needs"]


def test_switch_nup_tool_info_extract_materialize_and_models(tmp_path):
    cfg = Config(data_dir=tmp_path / "data", cache_dir=tmp_path / "cache")

    class Ctx:
        config = cfg
        artifacts = []

        @staticmethod
        def progress(pct, msg):
            pass

    out = tools.switch_nup_tool(tools.SwitchNupIn(op="info", nup=str(FIXTURE)), Ctx)["result"]
    assert out["title"] == "Sample NX Adventure" and out["title_id"] == "0100123456789ABC"
    listed = tools.switch_nup_tool(tools.SwitchNupIn(op="list", nup=str(FIXTURE), pattern="romfs"), Ctx)["result"]
    assert listed["files"] == 3
    extracted = tools.switch_nup_tool(tools.SwitchNupIn(op="extract", nup=str(FIXTURE), out=str(tmp_path / "x"),
                                                         mode="subtree", subtree="exefs"), Ctx)["result"]
    assert extracted["files"] == 1 and (tmp_path / "x" / "main").is_file()
    made = tools.switch_nup_tool(tools.SwitchNupIn(op="materialize", nup=str(FIXTURE), out=str(tmp_path / "game")),
                                 Ctx)["result"]
    assert made["has_exefs"] and made["registered_romfs"].endswith("romfs")
    models = tools.switch_nup_tool(tools.SwitchNupIn(op="models", nup=str(FIXTURE), out=str(tmp_path / "g2"),
                                                      pattern=r".*\.dat$"), Ctx)["result"]
    assert models["files"] == 1 and models["models"][0]["rel"] == "romfs/data/levels/level01.dat"
