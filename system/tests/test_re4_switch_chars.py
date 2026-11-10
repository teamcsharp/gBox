"""RE4 Switch character reader: GLB container, roster/dispatch wiring, and an owned-build export check."""
import json
import struct
from pathlib import Path

import pytest

from gbox import characters as CH
from gbox import re4_switch_chars as R

ROOT = Path.home() / "gBox_alt/switch/romfs/010099A00BC1E000/bio4"


def read_glb(data):
    magic, version, length = struct.unpack_from("<III", data, 0)
    assert (magic, version, length) == (0x46546C67, 2, len(data))
    jl, jt = struct.unpack_from("<II", data, 12)
    assert jt == 0x4E4F534A
    js = json.loads(data[20:20 + jl])
    bl, bt = struct.unpack_from("<II", data, 20 + jl)
    assert bt == 0x004E4942
    return js, data[28 + jl:28 + jl + bl]


def test_glb_container_is_4_aligned_and_parses():
    js, blob = read_glb(R._glb({"asset": {"version": "2.0"}}, b"abcde"))
    assert js["asset"]["version"] == "2.0" and len(blob) == 8 and blob[:5] == b"abcde"


def test_roster_and_dispatch():
    ros = R.roster()
    assert ros[0]["key"] == "pl00" and ros[0]["slug"] == "re4switch_pl00"
    assert len({e["slug"] for e in ros}) == len(ros) == 27
    assert next(n for n, t, _ro, _run in CH.DEDICATED if t("resident evil 4", "switch")) == "re4_switch"
    assert next(n for n, t, _ro, _run in CH.DEDICATED if t("resident evil 4", "ps2")) == "re4_ps2"
    assert CH.reader_version("re4_switch") == R.READER_VERSION


def test_missing_romfs_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    with pytest.raises(FileNotFoundError, match="no extracted RE4 Switch romfs"):
        R._romfs_root({"game_id": "x"})


@pytest.mark.skipif(not (ROOT / "em/pl00.udas").exists(), reason="owned RE4 Switch romfs not extracted")
def test_owned_pl00_export_is_consistent(tmp_path):
    class _Ctx:
        def progress(self, *a, **k):
            pass
    res = R.extract_run(_Ctx(), {"game_id": "270a15eb98dab4d7"}, R.roster()[0], tmp_path)
    js, blob = read_glb((tmp_path / "model.glb").read_bytes())
    assert len(res["source_sha256"]) == 64 and res["source_files"] == ["bio4/em/pl00.udas"]
    # Counts measured by re4_switch_assets on the owned pack
    pos = next(a for a in js["accessors"] if a["type"] == "VEC3")
    assert pos["count"] == 3425 and len(js["skins"][0]["joints"]) == 119
    assert len(js["images"]) == 8 and len(js["materials"]) == 14
    # every primitive index/attribute stays inside the vertex table and buffer
    for prim in js["meshes"][0]["primitives"]:
        acc = js["accessors"][prim["indices"]]
        v = js["bufferViews"][acc["bufferView"]]
        idx = struct.unpack_from(f"<{acc['count']}I", blob, v["byteOffset"])
        assert max(idx) < pos["count"] and acc["count"] % 3 == 0
    # PNG textures are real images
    for im in js["images"]:
        v = js["bufferViews"][im["bufferView"]]
        assert blob[v["byteOffset"]:v["byteOffset"] + 8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.skipif(not (ROOT / "em/pl0e.udas").exists(), reason="owned RE4 Switch romfs not extracted")
@pytest.mark.parametrize("key,verts,tex", [("pl0e", 6482, 17), ("pl0f", 2042, 4)])
def test_eff_led_packs_use_first_bin_slot(key, verts, tex):
    # pl0e/pl0f slot 0 is an EFF container; the body BIN is slot 1 and its TPL slot 2 (read from the slot table).
    glb, stats = R.export_udas((ROOT / "em" / f"{key}.udas").read_bytes(), ROOT)
    js, _ = read_glb(glb)
    assert stats["vertices"] == verts and len(js["images"]) == tex and stats["textures_missing"] == 0


@pytest.mark.skipif(not (ROOT / "em/pl07.udas").exists(), reason="owned RE4 Switch romfs not extracted")
def test_pl07_bin_bin_tpl_group_resolves_textures():
    # pl07 slots are BIN,BIN,TPL(3 images): the body's TPL follows the BIN run, not the next slot.
    glb, stats = R.export_udas((ROOT / "em" / "pl07.udas").read_bytes(), ROOT)
    js, _ = read_glb(glb)
    assert stats["vertices"] == 4371 and len(js["images"]) == 3 and stats["textures_missing"] == 0
