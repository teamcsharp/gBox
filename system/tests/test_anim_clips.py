"""#1384 animation extraction: clips a reader decoded -> glTF animations stored with the collection entry."""
import json
import struct
import types
from pathlib import Path

import pytest

from gbox import anim_clips as A
from gbox import uap
from gbox.doa2_motion import BASE_SCALE, CHANNELS

N = 9                                                     # native frames per synthetic clip


def floats(bin_chunk: bytes, gl: dict, idx: int) -> list:
    acc = gl["accessors"][idx]
    view = gl["bufferViews"][acc["bufferView"]]
    width = {"SCALAR": 1, "VEC3": 3, "VEC4": 4}[acc["type"]]
    flat = struct.unpack_from(f"<{acc['count'] * width}f", bin_chunk, view["byteOffset"])
    return list(flat) if width == 1 else [list(flat[i:i + width]) for i in range(0, len(flat), width)]


def skeleton():
    return [{"name": "hips", "parent": None, "translation": [0, 1, 0]},
            {"name": "spine", "parent": 0, "translation": [0, 0.3, 0]},
            {"name": "head", "parent": 1, "translation": [0, 0.4, 0], "rotation": [0, 0, 0, 1]}]


def walk():
    times = [0.0, 0.5, 1.0]
    half = [0, 0, 0.70710677, 0.70710677]
    return {"name": "walk", "extras": {"fps": 30}, "channels": [
        {"node": "spine", "path": "rotation", "times": times, "values": [[0, 0, 0, 1], half, [0, 0, 0, 1]]},
        {"node": "hips", "path": "translation", "times": times, "values": [[0, 1, 0], [0, 1.1, 0], [0, 1, 0]]},
        {"node": "head", "path": "scale", "times": [0.0, 1.25], "values": [[1, 1, 1], [2, 2, 2]], "interpolation": "STEP"}]}


def test_synthetic_skeleton_keyframes_become_valid_gltf_channels_and_samplers():
    data = A.build_glb(skeleton(), [walk()], extras={"source": "test"})
    assert data[:4] == b"glTF" and struct.unpack_from("<I", data, 8)[0] == len(data)
    gl, binc = A.read_glb(data)
    assert [n["name"] for n in gl["nodes"]] == ["hips", "spine", "head"]
    assert gl["nodes"][0]["children"] == [1] and gl["nodes"][1]["children"] == [2]
    assert gl["scenes"][0]["nodes"] == [0] and gl["extras"]["gbox"]["source"] == "test"
    (anim,) = gl["animations"]
    assert anim["name"] == "walk" and anim["extras"] == {"fps": 30}
    assert [(c["target"]["node"], c["target"]["path"]) for c in anim["channels"]] == [(1, "rotation"), (0, "translation"), (2, "scale")]
    s = anim["samplers"]
    assert [x["interpolation"] for x in s] == ["LINEAR", "LINEAR", "STEP"]
    assert s[0]["input"] == s[1]["input"] != s[2]["input"]           # one shared times accessor per key list
    tin = gl["accessors"][s[0]["input"]]
    assert tin["type"] == "SCALAR" and tin["min"] == [0.0] and tin["max"] == [1.0] and tin["componentType"] == 5126
    assert gl["accessors"][s[2]["input"]]["max"] == [1.25]
    assert gl["accessors"][s[0]["output"]]["type"] == "VEC4" and gl["accessors"][s[1]["output"]]["type"] == "VEC3"
    assert floats(binc, gl, s[0]["input"]) == [0.0, 0.5, 1.0]
    assert floats(binc, gl, s[0]["output"])[1] == pytest.approx([0, 0, 0.70710677, 0.70710677])
    assert floats(binc, gl, s[1]["output"])[1] == pytest.approx([0, 1.1, 0])
    for v in gl["bufferViews"]:
        assert v["byteOffset"] % 4 == 0 and v["byteOffset"] + v["byteLength"] <= gl["buffers"][0]["byteLength"]


def test_invalid_clips_are_refused_with_reasons():
    bad = {"name": "bad", "channels": [
        {"node": "tail", "path": "rotation", "times": [0, 1], "values": [[0, 0, 0, 1], [0, 0, 0, 1]]},
        {"node": "hips", "path": "rotation", "times": [0, 0], "values": [[0, 0, 0, 1], [0, 0, 0, 1]]},
        {"node": "hips", "path": "translation", "times": [0, 1], "values": [[0, 0, 0, 1], [0, 0, 0]]},
        {"node": "hips", "path": "weights", "times": [0], "values": [[1]]}]}
    problems = A.check(skeleton(), [bad, {"name": "empty", "channels": []}])
    text = " | ".join(problems)
    for reason in ("target node missing", "not strictly increasing", "value width != 3", "path must be", "no channels"):
        assert reason in text
    with pytest.raises(ValueError):
        A.build_glb(skeleton(), [bad])
    with pytest.raises(ValueError, match="unique"):
        A.build_glb(skeleton() + [{"name": "hips", "parent": None}], [walk()])


def test_clips_in_reads_back_names_and_durations(tmp_path):
    p = tmp_path / "x.anims.glb"
    p.write_bytes(A.build_glb(skeleton(), [walk(), {"name": "idle", "channels": [
        {"node": "hips", "path": "translation", "times": [0, 2.5], "values": [[0, 1, 0], [0, 1, 0]]}]}]))
    assert A.clips_in(p) == [{"name": "walk", "duration_s": 1.25, "channels": 3, "nodes": 3},
                             {"name": "idle", "duration_s": 2.5, "channels": 1, "nodes": 1}]
    assert A.clips_in(tmp_path / "missing.glb") == []


def manifest_with_clip():
    return uap.Manifest(name="dummy", source={"game_id": "t"}, provenance=[{"file": "t"}],
                        meshes=[uap.Mesh(name="m", positions=[[0, 0, 0], [1, 0, 0], [0, 1, 0]], indices=[0, 1, 2],
                                         joints=[[0, 0, 0, 0]] * 3, weights=[[1, 0, 0, 0]] * 3)],
                        nodes=[uap.Node(name="body", mesh=0, skinned=True)],
                        skeleton=[uap.Bone(name="root"), uap.Bone(name="arm", parent=0, translation=[1, 0, 0])],
                        animations=[uap.Clip(name="wave", channels=[uap.Channel(bone=1, path="rotation", times=[0, 0.75],
                                                                                values=[[0, 0, 0, 1], [0, 0, 1, 0]])])])


def test_skeleton_nodes_follow_the_skin_and_embedded_clips_are_listed(tmp_path):
    p = tmp_path / "model.glb"
    p.write_bytes(uap.to_glb(manifest_with_clip(), tmp_path))
    bones = A.skeleton_nodes(p)
    assert [(b["name"], b["parent"]) for b in bones] == [("root", None), ("arm", 0)]
    assert bones[1]["translation"] == [1, 0, 0]
    rows = A.embedded_entries(p)
    assert rows == [{"name": "wave", "duration_s": 0.75, "source": "embedded in model.glb", "file": "model.glb", "drives": "skeleton"}]
    # an anims GLB sharing that skeleton binds by name
    clip = {"name": "raise", "channels": [{"node": "arm", "path": "rotation", "times": [0, 1], "values": [[0, 0, 0, 1], [0, 0, 1, 0]]}]}
    gl, _ = A.read_glb(A.build_glb(bones, [clip]))
    assert gl["nodes"][gl["animations"][0]["channels"][0]["target"]["node"]]["name"] == "arm"


def test_matrix_nodes_decompose_to_trs():
    t, r, s = A._decompose([2, 0, 0, 0, 0, 0, 2, 0, 0, -2, 0, 0, 5, 6, 7, 1])   # 90 deg about X, scale 2
    assert t == [5, 6, 7] and s == pytest.approx([2, 2, 2])
    assert r == pytest.approx([0.70710677, 0, 0, 0.70710677], abs=1e-6)


# ------------------------------------------------------------------------------------------------ DOA2 MOT

def linear(base, final, n=N):
    return struct.pack("<Hh", (n << 2) | 1, base) + struct.pack("<Hh", 0, final)


def raw3(n=N):
    return b"".join(struct.pack("<3h", f, -f, 100 + f) for f in range(n + 1))


def mot(second_clip=True, alias=False):
    """indexed compact44 bank: channels 3..5 share one raw int16x3 stream, the rest are linear compact scalars."""
    tracks = {k: linear(k * 10, k * 10 + 90) for k in range(CHANNELS) if k not in (3, 4, 5)}
    tracks[3] = raw3()
    refs = 2 + (1 if alias else 0) if second_clip else 1
    data = bytearray(4 * (refs + 1))
    starts = {}
    for k in sorted(tracks):
        starts[k] = len(data)
        data.extend(tracks[k])
    for k in (4, 5):
        starts[k] = starts[3]
    tables = [len(data)]
    data.extend(struct.pack("<44I", *(starts[k] for k in range(CHANNELS))))
    if second_clip:
        extra = len(data)
        data.extend(linear(-50, 50, 4))
        tables.append(len(data))
        data.extend(struct.pack("<44I", *([extra] * CHANNELS)))
    order = tables + ([tables[0]] if alias else [])
    for i, off in enumerate(order):
        struct.pack_into("<I", data, 4 * i, off)
    return bytes(data)


def test_doa2_mot_becomes_control_clips_per_native_frame():
    nodes, clips, report = A.doa2_clips(mot(), "DOA2/KASUMI.MOT")
    assert nodes[0] == {"name": "doa2_mot_controls", "parent": None} and len(nodes) == 1 + CHANNELS
    assert {n["parent"] for n in nodes[1:]} == {0}
    assert [c["name"] for c in clips] == ["kasumi_000", "kasumi_001"]
    first = clips[0]
    assert len(first["channels"]) == CHANNELS and first["extras"]["native_frames"] == N
    assert first["extras"]["drives"] == "controls" and first["extras"]["undecoded_channels"] == []
    ch7 = next(c for c in first["channels"] if c["node"] == "mot_ch07")
    assert ch7["path"] == "translation" and ch7["times"] == pytest.approx([f / 60 for f in range(N + 1)])
    for f in range(N + 1):                                # codec 1: straight line from base to the final value
        assert ch7["values"][f] == pytest.approx([BASE_SCALE * (70 + 90 * f / N), 0, 0], rel=1e-5)
    raws = {c["node"]: [v[0] for v in c["values"]] for c in first["channels"] if c["node"] in ("mot_ch03", "mot_ch04", "mot_ch05")}
    assert raws["mot_ch03"] == [float(f) for f in range(N + 1)]
    assert raws["mot_ch04"] == [float(-f) for f in range(N + 1)]
    assert raws["mot_ch05"] == [float(100 + f) for f in range(N + 1)]
    assert clips[1]["channels"][0]["times"][-1] == pytest.approx(4 / 60)
    assert report["exported"] == 2 and report["fps_assumed"] == 60 and report["runtime_interpolation_verified"] is False
    gl, _ = A.read_glb(A.build_glb(nodes, clips))       # and the GLB is valid
    assert len(gl["animations"]) == 2 and len(gl["animations"][0]["channels"]) == CHANNELS
    assert gl["nodes"][0]["children"] == list(range(1, CHANNELS + 1))


def test_doa2_shared_clip_tables_export_once_with_aliases():
    nodes, clips, report = A.doa2_clips(mot(alias=True), "DOA2/AYANE.MOT")
    assert [c["name"] for c in clips] == ["ayane_000", "ayane_001"]
    assert clips[0]["extras"]["aliases"] == [2] and report["clips"] == 3 and report["exported"] == 2
    assert len(A.doa2_clips(mot(), "DOA2/X.MOT", limit=1)[1]) == 1


def test_doa2_unsupported_bank_raises():
    from gbox.doa2_motion import MotionFormatError
    with pytest.raises(MotionFormatError):
        A.doa2_clips(b"\x01\x02\x03\x04" * 8, "DOA2/BAD.MOT")


# ------------------------------------------------------------------------------------------------ collection

def entry(root: Path, slug: str, **extra) -> dict:
    from gbox import characters as C
    (root / slug).mkdir(parents=True)
    (root / slug / "model.glb").write_bytes(b"glTF")
    return C.put_meta(root, {"slug": slug, "name": slug, "model": "model.glb", "kind": "character", **extra})


def test_attach_writes_sibling_glb_and_records_meta(tmp_path):
    from gbox import characters as C
    sprite = {"clip": "walk", "name": "walk", "sheet": "clips/walk/sheet.png", "preview": "clips/walk/preview.apng"}
    embedded = {"name": "wave", "duration_s": 0.75, "source": "embedded in model.glb", "file": "model.glb", "drives": "skeleton"}
    entry(tmp_path, "doa2_kas", animations=[sprite, embedded])
    nodes, clips, _ = A.doa2_clips(mot(), "DOA2/KASUMI.MOT")
    meta = A.attach(tmp_path, "doa2_kas", nodes, clips, "DOA2/KASUMI.MOT", "controls")
    assert meta["anims_file"] == "doa2_kas.anims.glb" and (tmp_path / "doa2_kas" / "doa2_kas.anims.glb").is_file()
    rows = meta["animations"]
    assert rows[:2] == [sprite, embedded]
    assert rows[2] == {"name": "kasumi_000", "duration_s": pytest.approx(N / 60, abs=1e-4), "source": "DOA2/KASUMI.MOT",
                       "file": "doa2_kas.anims.glb", "drives": "controls"}
    assert len(rows) == 4 and C.get(tmp_path, "doa2_kas")["animations"] == rows
    again = A.attach(tmp_path, "doa2_kas", nodes, clips[:1], "DOA2/KASUMI.MOT", "controls")   # replaces its own rows
    assert [a["name"] for a in again["animations"]] == ["walk", "wave", "kasumi_000"]
    assert A.clips_in(tmp_path / "doa2_kas" / "doa2_kas.anims.glb")[0]["name"] == "kasumi_000"


def test_collection_add_records_embedded_clips_and_keeps_attached_ones(tmp_path, monkeypatch):
    from gbox import characters as C
    work = tmp_path / "work"
    work.mkdir()
    (work / "dummy.glb").write_bytes(uap.to_glb(manifest_with_clip(), work))
    monkeypatch.setattr(C, "render_preview", lambda model, out, **kw: Path(out).write_bytes(b"png"))
    root = tmp_path / "lib"
    meta = C.add(root, "dummy", "Dummy", [work / "dummy.glb"], {"game_id": "t"}, "test")
    assert meta["animations"] == [{"name": "wave", "duration_s": 0.75, "source": "embedded in dummy.glb",
                                   "file": "dummy.glb", "drives": "skeleton"}]
    nodes, clips, _ = A.doa2_clips(mot(second_clip=False), "DOA2/KASUMI.MOT")
    A.attach(root, "dummy", nodes, clips, "DOA2/KASUMI.MOT", "controls")
    again = C.add(root, "dummy", "Dummy", [work / "dummy.glb"], {"game_id": "t"}, "test")    # re-extraction
    assert [a["file"] for a in again["animations"]] == ["dummy.glb", "dummy.anims.glb"]
    assert again["anims_file"] == "dummy.anims.glb"


def test_doa2_extraction_writes_the_bank_beside_the_model(tmp_path):
    from gbox import characters as C
    (tmp_path / "KASUMI.MOT").write_bytes(mot())
    extra = C.doa2_motion_extra(tmp_path, "doa2_kas", ["KAS00_rigged.gltf", "KASUMI.MOT"])
    assert extra["anims_file"] == "doa2_kas.anims.glb" and (tmp_path / "doa2_kas.anims.glb").is_file()
    assert [a["name"] for a in extra["animations"]] == ["kasumi_000", "kasumi_001"]
    assert extra["anims_report"]["exported"] == 2 and extra["anims_report"]["skipped"] == 0
    assert C.doa2_motion_extra(tmp_path, "doa2_x", ["X.CHR"])["anims_report"]["status"] == "missing"
    (tmp_path / "BAD.MOT").write_bytes(b"\x01" * 16)
    assert C.doa2_motion_extra(tmp_path, "doa2_x", ["BAD.MOT"])["anims_report"]["status"] == "unsupported"


def test_doa2_assets_motion_clips_op_fills_the_fighters_entry(tmp_path, monkeypatch):
    from gbox import doa2_lab
    monkeypatch.setenv("GBOX_CHARACTERS", str(tmp_path))
    entry(tmp_path, "doa2_kas", source={"game_id": "1de2e7634f3161ff"})
    disc = types.SimpleNamespace(files={"DOA2/KASUMI.MOT": (0, 0)}, read=lambda name: mot())
    ctx = types.SimpleNamespace(config=None, progress=lambda *a: None)
    out = doa2_lab.motion_clips(doa2_lab.Doa2In(op="motion_clips", fighter="Kasumi"), ctx, disc)
    assert out["slug"] == "doa2_kas" and out["clips"] == 2 and out["file"] == "doa2_kas.anims.glb"
    meta = json.loads((tmp_path / "doa2_kas" / "meta.json").read_text())
    assert [a["drives"] for a in meta["animations"]] == ["controls", "controls"]
    with pytest.raises(ValueError, match="explicit fighter"):
        doa2_lab.motion_clips(doa2_lab.Doa2In(op="motion_clips", fighter="nobody"), ctx, disc)
    with pytest.raises(ValueError, match="unconfirmed"):
        doa2_lab.motion_clips(doa2_lab.Doa2In(op="motion_clips", fighter="Ein"), ctx, disc)
    with pytest.raises(ValueError, match="not in the collection"):
        doa2_lab.motion_clips(doa2_lab.Doa2In(op="motion_clips", fighter="Ayane"), ctx, disc)
