"""VR Missions Snake body roles (#1364): the collected model must carry rig.roles so it is retargetable."""
import hashlib
import json
import os
import shutil
import struct
from pathlib import Path

import numpy as np
import pytest

from gbox import characters as C

# KMD object local offsets of the decoded US Snake (5dda0c64...) in the library frame, and MetalMintSolid's node names.
LOCAL = [(0, 0, 0), (0, 0, 0), (-190, 265, -29), (0, -260, -50), (0, -249, 47), (0, 310, -55), (0, 94, 55),
         (190, 265, -29), (0, -260, -50), (0, -249, 47), (-90, -255, -10), (0, -311, 37), (0, -508, -47),
         (90, -253, -11), (0, -312, 39), (0, -508, -47)]
NAMES = ["bone_0", "bone_1", "bone_4", "bone_7", "bone_8", "bone_5", "bone_9", "bone_6", "bone_10", "bone_11",
         "bone_2", "bone_12", "bone_13", "bone_3", "bone_14", "bone_15"]
LIBRARY_GLB = Path(os.environ.get("GBOX_CHARACTERS", "/home/ehm_eckx/gBox_alt/gbox-cache/characters")) / "mgs_vr_snake/mgs_vr_snake.glb"


def _snake_glb(path: Path, mirror: bool = False, toes: float = 120.0, parents=None) -> Path:
    """A minimal skinned GLB with Snake's KMD tree: a joint-local triangle per object, feet with toes along +Z."""
    s = -1.0 if mirror else 1.0
    nodes = [{"name": NAMES[i], "translation": [s * LOCAL[i][0], LOCAL[i][1], LOCAL[i][2]]} for i in range(16)]
    for i, p in enumerate(parents or C.MGS_VR_SNAKE_PARENTS):
        if p >= 0:
            nodes[p].setdefault("children", []).append(i)
    pos, jts = [], []
    for i in range(16):
        tri = [(-10, 0, 0), (10, 0, 0), (0, 10, toes)] if i in (12, 15) else [(-10, 0, 0), (10, 0, 0), (0, 20, 5)]
        pos += tri
        jts += [i] * 3
    P = np.array(pos, np.float32).tobytes()
    J = np.array([[j, 0, 0, 0] for j in jts], np.uint16).tobytes()
    Wt = np.array([[1, 0, 0, 0]] * len(jts), np.float32).tobytes()
    blob = P + J + Wt
    n = len(jts)
    nodes.append({"name": "snake", "mesh": 0, "skin": 0})
    gl = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0, 16]}], "nodes": nodes,
          "skins": [{"joints": [0, 1, 10, 13, 2, 5, 7, 3, 4, 6, 8, 9, 11, 12, 14, 15]}],
          "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "JOINTS_0": 1, "WEIGHTS_0": 2}}]}],
          "buffers": [{"byteLength": len(blob)}],
          "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(P)},
                          {"buffer": 0, "byteOffset": len(P), "byteLength": len(J)},
                          {"buffer": 0, "byteOffset": len(P) + len(J), "byteLength": len(Wt)}],
          "accessors": [{"bufferView": 0, "componentType": 5126, "count": n, "type": "VEC3",
                         "min": np.array(pos).min(0).tolist(), "max": np.array(pos).max(0).tolist()},
                        {"bufferView": 1, "componentType": 5123, "count": n, "type": "VEC4"},
                        {"bufferView": 2, "componentType": 5126, "count": n, "type": "VEC4"}]}
    js = json.dumps(gl).encode()
    js += b" " * (-len(js) % 4)
    blob += b"\0" * (-len(blob) % 4)
    path.write_bytes(struct.pack("<III", 0x46546C67, 2, 28 + len(js) + len(blob)) + struct.pack("<II", len(js), 0x4E4F534A)
                     + js + struct.pack("<II", len(blob), 0x004E4942) + blob)
    return path


def test_roles_resolve_kmd_objects_to_decoded_node_names(tmp_path):
    roles = C.mgs_vr_snake_roles(_snake_glb(tmp_path / "s.glb"))
    assert roles["r_upper"] == "bone_4" and roles["head"] == "bone_9" and roles["l_foot"] == "bone_15"
    assert set(roles) == set(C.MGS_VR_SNAKE_OBJECTS)
    rig = C.rig_from_gltf(tmp_path / "s.glb", roles)
    assert len(rig["roles"]) == 16                         # every role reaches a skin joint, so retargeting can use it
    J, R = rig["joints"], rig["roles"]
    assert J[R["l_hand"]][0] > 0 > J[R["r_hand"]][0] and J[R["head"]][1] > J[R["chest"]][1] > J[R["l_foot"]][1]


def test_mirrored_or_backward_decodes_are_refused(tmp_path):
    with pytest.raises(ValueError, match="mirrored"):
        C.mgs_vr_snake_roles(_snake_glb(tmp_path / "m.glb", mirror=True))
    with pytest.raises(ValueError, match="face"):
        C.mgs_vr_snake_roles(_snake_glb(tmp_path / "b.glb", toes=-120.0))


def test_a_different_tree_is_refused(tmp_path):
    parents = list(C.MGS_VR_SNAKE_PARENTS)
    parents[12] = 10                                       # foot hung off the thigh: not Snake's KMD tree
    with pytest.raises(ValueError, match="KMD tree"):
        C.mgs_vr_snake_roles(_snake_glb(tmp_path / "t.glb", parents=parents))


def test_collector_returns_roles(tmp_path, monkeypatch):
    from gbox import mgs_vr_swap
    src = _snake_glb(tmp_path / "decoded.glb")
    monkeypatch.setattr(C, "HOST_OS", "windows")
    monkeypatch.setattr(mgs_vr_swap, "decode_original_player", lambda cfg, out, progress: shutil.copy(src, out))
    ctx = type("Ctx", (), {"config": None, "progress": staticmethod(lambda *_: None)})()
    res = C._mgs_vr_run(ctx, {"game_id": "afd2fc507bb69843"}, {}, tmp_path)
    assert res["roles"] == C.mgs_vr_snake_roles(src) and len(res["roles"]) == 16


@pytest.mark.skipif(not LIBRARY_GLB.is_file(), reason="no collected VR Missions Snake in the local library")
def test_collected_library_snake_gets_roles():
    roles = C.mgs_vr_snake_roles(LIBRARY_GLB)
    assert roles["r_upper"] == "bone_4" and roles["l_thigh"] == "bone_3"
    assert len(C.rig_from_gltf(LIBRARY_GLB, roles)["roles"]) == 16


def _self_retarget(path: Path):
    """Snake retargeted onto Snake's own KMD skeleton through sm64_swap.retarget (the generic role-driven fitter)."""
    from gbox import sm64_swap as S
    rig = S.load_rig(path, C.mgs_vr_snake_roles(path))
    T = np.zeros((16, 3))
    for r, i in C.MGS_VR_SNAKE_OBJECTS.items():
        T[i] = rig["joints"][rig["roles"][r]]
    P = np.concatenate([q["pos"] for q in rig["prims"]])
    head = P[np.concatenate([q["owner"] for q in rig["prims"]]) == rig["roles"]["head"]]
    tgt = {"T": T, "ground": float(P[:, 1].min()), "head_h": float(np.ptp(head[:, 1])), "height": float(np.ptp(P[:, 1]))}
    prims, rep = S.retarget(rig, tgt, None, jmap=C.MGS_VR_SNAKE_OBJECTS)
    return P, np.concatenate([q["pos"] for q in prims]), rep


def test_roles_drive_the_generic_retarget(tmp_path):
    P, out, rep = _self_retarget(_snake_glb(tmp_path / "s.glb"))
    assert sorted(rep["roles_used"]) == sorted(C.MGS_VR_SNAKE_OBJECTS)
    assert np.abs(out - P).max() < 1e-6                    # onto its own skeleton the fit is the identity


@pytest.mark.skipif(not LIBRARY_GLB.is_file(), reason="no collected VR Missions Snake in the local library")
def test_collected_library_snake_self_retarget_is_identity():
    P, out, rep = _self_retarget(LIBRARY_GLB)
    assert len(P) == 580 and rep["scale"] == 1.0 and len(rep["roles_used"]) == 16
    assert np.abs(out - P).max() < 1e-6


# Forced re-extract evidence (#1364 run 3): characters op=mgs_vr_decode, job 3952f6506c6f437e (receipt
# 6917cb4e7b6042e7, JAYBUILTFINALE) decoded the US disc (SLUS_009.57) to exactly this GLB, byte-identical to the
# collected library file.
DECODED_SNAKE_GLB_SHA256 = "d92d171ddeee7a1eddf82e27976caab62ba3a5183c1654007d706d232ac2fa89"


@pytest.mark.skipif(not LIBRARY_GLB.is_file(), reason="no collected VR Missions Snake in the local library")
def test_reextracting_the_verified_decode_keeps_the_library_roles():
    """A forced re-collect decodes this same GLB, so the reader's roles must equal the stored rig.roles. Otherwise a
    re-extract would silently drop or change retargetability."""
    if hashlib.sha256(LIBRARY_GLB.read_bytes()).hexdigest() != DECODED_SNAKE_GLB_SHA256:
        pytest.skip("the library holds a different Snake decode")
    meta = json.loads((LIBRARY_GLB.parent / "meta.json").read_text())
    roles = C.mgs_vr_snake_roles(LIBRARY_GLB)
    assert roles == meta["rig"]["roles"] and len(roles) == 16
    assert C.verify_entry(LIBRARY_GLB.parent.parent, meta)["ok"]
