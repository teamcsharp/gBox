"""Native assets keep exact identity and never imply decoded or writable models."""
import hashlib
import json
from pathlib import Path
import struct

import pytest

from gbox import doa3_assets as assets
from gbox.registry import ToolUnavailable

GID = "b8edf7040116f3aa"


def make_afs(names, payloads):
    count, alignment = len(names), 0x800
    position = ((16 + len(names) * 8 + alignment - 1) // alignment) * alignment
    result = bytearray(position)
    result[:8] = b"AFS\0" + struct.pack("<I", count)
    for index, payload in enumerate(payloads):
        struct.pack_into("<II", result, 8 + index * 8, position, len(payload))
        result += payload
        result += bytes((-len(payload)) % alignment)
        position = len(result)
    struct.pack_into("<II", result, 8 + count * 8, position, count * 48)
    for name, payload in zip(names, payloads):
        result += name.encode("ascii").ljust(32, b"\0") + struct.pack("<6HI", 2001, 10, 1, 0, 0, 0, len(payload))
    return bytes(result)


def model():
    return b"XPR0" + struct.pack("<IIII", 64, 32, 0x80000000, 16) + b"MDL\0" + bytes(40)


@pytest.fixture
def source(tmp_path, monkeypatch):
    root = tmp_path / "disc"
    root.mkdir()
    xbe = b"XBEH exact fixture executable"
    (root / "default.xbe").write_bytes(xbe)
    monkeypatch.setattr(assets, "XBE_HASHES", {hashlib.sha256(xbe).hexdigest()})
    names = ["comon.mot", "anime_cm.bin", "c_zack.mot", "zack.bin", "zack.mot", "m_zack.mot",
             "zac00.xpr", "zac00.cat", "dmy.bin"]
    payloads = [b"common animation", b"common data", b"character animation", b"fighter data",
                b"animation", b"more animation", model(), b"paired native CAT", b"wwww"]
    (root / "loadfile.afs").write_bytes(make_afs(names, payloads))
    return root, names, payloads


def test_inventory_records_source_member_hashes_and_native_status(source):
    root, names, payloads = source
    result = assets.inventory(root, game_id=GID)
    assert result["title_id"] == "54430001" and result["platform"] == "xbox"
    assert result["source"]["archive_sha256"] == hashlib.sha256((root / "loadfile.afs").read_bytes()).hexdigest()
    assert [row["name"] for row in result["members"]] == names
    assert [row["sha256"] for row in result["members"]] == [hashlib.sha256(data).hexdigest() for data in payloads]
    assert result["members"][6]["kind"] == "model"
    assert result["members"][8]["placeholder"] and not result["members"][6]["placeholder"]
    assert result["members"][6]["xpr"]["first_tag"] == "MDL"
    for row in result["members"]:
        assert row["raw"] and not any(row[key] for key in ("decoded", "writable", "reimportable", "full_character_replacement"))
    family = result["fighters"][0]
    assert family["nick"] == "zack" and family["bin"] == 3
    assert family["motion_indices"] == [4, 5]
    assert family["shared_indices"] == [0, 1, 2]
    assert family["costumes"] == {"zac00": {"xpr": 6, "cat": 7}}


def test_export_pairs_fighter_dependencies_and_validates_reuse(source, tmp_path):
    root, names, payloads = source
    before = {path.name: path.read_bytes() for path in root.iterdir()}
    first = assets.export_selected(root, tmp_path / "library", game_id=GID, costume="zac00")
    folder = Path(first["bundle_dir"])
    assert not first["reused"] and first["selection"]["fighter"] == "zack"
    assert [row["index"] for row in first["members"]] == list(range(8))
    assert first["fighters"][0]["complete_costumes"] == ["zac00"]
    assert first["fighters"][0]["missing_companion_indices"] == []
    for row in first["members"]:
        assert (folder / row["path"]).read_bytes() == payloads[row["index"]]
    assert {path.name: path.read_bytes() for path in root.iterdir()} == before
    timestamp = (folder / first["members"][0]["path"]).stat().st_mtime_ns
    second = assets.export_selected(root, tmp_path / "library", game_id=GID, costume="zac00")
    assert second["reused"] and second["bundle_dir"] == first["bundle_dir"]
    assert (folder / first["members"][0]["path"]).stat().st_mtime_ns == timestamp


def test_all_native_selection_omits_placeholders_and_is_not_a_cast_build(source, tmp_path):
    root, _, _ = source
    result = assets.export_selected(root, tmp_path / "library", game_id=GID, all_assets=True)
    assert result["counts"]["members"] == 8
    assert result["capabilities"]["full_character_replacement"] is False
    assert all(row["kind"] != "placeholder" for row in result["members"])
    assert not list(Path(result["bundle_dir"]).rglob("*.glb"))


def test_partial_member_selection_does_not_claim_complete_costume(source, tmp_path):
    root, _, _ = source
    result = assets.export_selected(root, tmp_path / "library", game_id=GID, entry_ids=[6])
    family = result["fighters"][0]
    assert family["complete_costumes"] == []
    assert family["missing_companion_indices"] == [0, 1, 2, 3, 4, 5, 7]
    assert family["included_indices"] == [6]


def test_duplicate_member_names_have_distinct_indexed_outputs(source, tmp_path):
    root, _, _ = source
    (root / "loadfile.afs").write_bytes(make_afs(["same.bin", "same.bin"], [b"first", b"second"]))
    result = assets.export_selected(root, tmp_path / "library", game_id=GID, entry_ids=[0, 1])
    assert result["members"][0]["path"] != result["members"][1]["path"]
    assert [(Path(result["bundle_dir"]) / row["path"]).read_bytes() for row in result["members"]] == [b"first", b"second"]


@pytest.mark.parametrize("name", ["../escape.bin", "C:evil.bin", "x\\evil.bin", "CON.bin", "name."])
def test_unsafe_member_names_fail_without_output(source, tmp_path, name):
    root, _, _ = source
    (root / "loadfile.afs").write_bytes(make_afs([name], [b"payload"]))
    with pytest.raises(ToolUnavailable, match="unsafe"):
        assets.export_selected(root, tmp_path / "library", game_id=GID, entry_ids=[0])
    assert not (tmp_path / "library").exists()


@pytest.mark.parametrize("change", ["count", "overlap", "header", "name_overlap", "name_size", "member_limit", "xpr_size"])
def test_malformed_native_archives_fail_closed(source, tmp_path, monkeypatch, change):
    root, _, _ = source
    path = root / "loadfile.afs"
    data = bytearray(path.read_bytes())
    count = struct.unpack_from("<I", data, 4)[0]
    if change == "count": struct.pack_into("<I", data, 4, assets.MAX_ENTRIES + 1)
    elif change == "overlap": struct.pack_into("<I", data, 16, 0x800)
    elif change == "header": struct.pack_into("<I", data, 8, 8)
    elif change == "name_overlap": struct.pack_into("<I", data, 8 + count * 8, 0x800)
    elif change == "name_size":
        names = struct.unpack_from("<I", data, 8 + count * 8)[0]
        struct.pack_into("<I", data, names + 44, 999)
    elif change == "member_limit": monkeypatch.setattr(assets, "MAX_MEMBER_BYTES", 8)
    elif change == "xpr_size":
        offset = struct.unpack_from("<I", data, 8 + 6 * 8)[0]
        struct.pack_into("<I", data, offset + 4, 1000000)
    path.write_bytes(data)
    with pytest.raises(ToolUnavailable):
        assets.export_selected(root, tmp_path / "library", game_id=GID, all_assets=True)
    assert not (tmp_path / "library").exists()


@pytest.mark.parametrize("kwargs", [{}, {"fighter": "zack", "all_assets": True}, {"entry_ids": []},
                                    {"entry_ids": [True]}, {"entry_ids": [-1]}, {"entry_ids": [8]},
                                    {"fighter": "unknown"}, {"costume": "zac99"}, {"all_assets": "false"}])
def test_empty_ambiguous_or_invalid_selection_has_no_output(source, tmp_path, kwargs):
    root, _, _ = source
    with pytest.raises((ValueError, ToolUnavailable)):
        assets.export_selected(root, tmp_path / "library", game_id=GID, **kwargs)
    assert not (tmp_path / "library").exists()


def test_budget_and_source_output_guard(source, tmp_path, monkeypatch):
    root, _, _ = source
    with pytest.raises(ValueError, match="outside"):
        assets.export_selected(root, root / "modified", game_id=GID, all_assets=True)
    with pytest.raises(ValueError, match="outside"):
        assets.export_selected(root, tmp_path / "other" / ".." / "disc" / "modified", game_id=GID, all_assets=True)
    monkeypatch.setattr(assets, "MAX_EXPORT_BYTES", 1)
    with pytest.raises(ToolUnavailable, match="budget"):
        assets.export_selected(root, tmp_path / "library", game_id=GID, all_assets=True)
    assert not (root / "modified").exists() and not (tmp_path / "library").exists()


def test_unknown_executable_and_invalid_provenance_are_rejected(source):
    root, _, _ = source
    with pytest.raises(ValueError, match="catalog"):
        assets.inventory(root, game_id="guessed-title")
    with pytest.raises(ValueError, match="complete"):
        assets.inventory(root, game_id=GID, source_sha256="abc")
    (root / "default.xbe").write_bytes(b"unreviewed revision")
    with pytest.raises(ToolUnavailable, match="reviewed USA"):
        assets.inventory(root, game_id=GID)


@pytest.mark.parametrize("damage", ["member", "extra", "manifest"])
def test_damaged_existing_bundle_is_preserved_and_refused(source, tmp_path, damage):
    root, _, _ = source
    first = assets.export_selected(root, tmp_path / "library", game_id=GID, entry_ids=[6, 7])
    folder = Path(first["bundle_dir"])
    if damage == "member": (folder / first["members"][0]["path"]).write_bytes(b"modified")
    elif damage == "extra": (folder / "unexpected.glb").write_bytes(b"not a model")
    else: (folder / "manifest.json").write_text("{}")
    before = {path.relative_to(folder): path.read_bytes() for path in folder.rglob("*") if path.is_file()}
    with pytest.raises(ToolUnavailable):
        assets.export_selected(root, tmp_path / "library", game_id=GID, entry_ids=[6, 7])
    assert {path.relative_to(folder): path.read_bytes() for path in folder.rglob("*") if path.is_file()} == before


def test_source_change_during_copy_never_publishes_bundle(source, tmp_path):
    root, _, _ = source
    def progress(percent, message):
        if percent >= 20 and message.startswith("Preserving"):
            path = root / "loadfile.afs"
            data = bytearray(path.read_bytes())
            data[0x800] ^= 1
            path.write_bytes(data)
    with pytest.raises(ToolUnavailable, match="changed"):
        assets.export_selected(root, tmp_path / "library", game_id=GID, all_assets=True, progress=progress)
    assert not list((tmp_path / "library").glob("doa3-native-*"))
    assert not list((tmp_path / "library").glob("doa3-stage-*"))
