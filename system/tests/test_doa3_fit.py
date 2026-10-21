"""gbox.doa3_fit: CAT render-list roles and the per-part donor fit into DOA3 joint frames (synthetic fixtures)."""
import struct

import numpy as np
import pytest

from gbox import doa3_cast as C
from gbox import doa3_fit as F
from gbox import doa3_writer as W

from tests.test_doa3_writer import _seed


def render_list_cat(lists: list[tuple[int, list[int]]], header_word: int = 0x18) -> bytes:
    """A CAT head with the fixed 0x100/1 signature and render lists at 0x14 + word@0x1C."""
    body = bytearray(0x40)
    struct.pack_into("<8I", body, 0, 1, 0x14, 0x40, 0x80, 0x100, 0x100, 1, header_word)
    start = 0x14 + header_word
    stream = bytearray()
    for marker, objs in lists:
        stream.append(marker)
        stream.extend(objs)
    stream.append(0xFF)
    out = bytearray(max(len(body), start + len(stream)) + 16)
    out[:len(body)] = body
    out[start:start + len(stream)] = stream
    return bytes(out)


def test_render_lists_and_roles():
    primary = list(range(15))
    lod = list(range(15, 30))
    cat = render_list_cat([(0xFE, primary), (0xFD, [30, 31]), (0xFB, [32, 33]), (0xF9, lod),
                           (0xF8, list(range(34, 49))), (0xF7, [49])])
    roles = F.costume_roles(cat, 52)
    assert roles["primary"]["chest"] == 0 and roles["primary"]["r_upper"] == 14
    assert roles["lod"]["head"] == 16
    assert roles["eyes"] == [30, 31] and roles["twist"] == [32, 33] and roles["other"] == [49]
    assert roles["unlisted"] == [50, 51]
    hidden = F.hidden_parts(roles, set(primary) | set(lod), 52)
    assert hidden == {30, 31, 32, 33, 49, 50, 51}                  # shadows (0xF8) stay native


def test_roles_need_fifteen_primary_parts():
    with pytest.raises(ValueError, match="15"):
        F.costume_roles(render_list_cat([(0xFE, [0, 1, 2])]), 3)


def test_family_codes():
    assert F.family_code("zack") == "zac" and F.family_code("zac") == "zac"
    assert F.family_code("Hayate") == "nin"                         # display name through FIGHTER_DISPLAY
    with pytest.raises(ValueError):
        F.family_code("tengu")


def _box(center, size, joint):
    c, s = np.asarray(center, float), size / 2
    corners = np.array([[x, y, z] for x in (-s, s) for y in (-s, s) for z in (-s, s)]) + c
    faces = [(0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 4, 5), (0, 5, 1), (2, 3, 7), (2, 7, 6),
             (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3)]
    n = len(corners)
    return {"pos": corners, "nrm": (corners - c) / np.linalg.norm(corners - c, axis=1, keepdims=True),
            "uv": np.zeros((n, 2)), "tris": np.array(faces), "J": np.full((n, 1), joint),
            "W": np.ones((n, 1)), "owner": np.full(n, joint), "tex": None, "color": (200, 40, 40, 255),
            "material_name": f"m{joint}"}


def stick_rig():
    names = ["hip", "chest", "head", "l_upper", "l_fore", "l_hand", "r_upper", "r_fore", "r_hand",
             "l_thigh", "l_shin", "l_foot", "r_thigh", "r_shin", "r_foot"]
    J = np.array([(0, 1, 0), (0, 1.2, 0), (0, 1.6, 0), (0.2, 1.45, 0), (0.5, 1.2, 0), (0.75, 1.0, 0),
                  (-0.2, 1.45, 0), (-0.5, 1.2, 0), (-0.75, 1.0, 0), (0.1, 0.95, 0), (0.1, 0.5, 0), (0.1, 0.08, 0),
                  (-0.1, 0.95, 0), (-0.1, 0.5, 0), (-0.1, 0.08, 0)], float)
    parent = [-1, 0, 1, 1, 3, 4, 1, 6, 7, 0, 9, 10, 0, 12, 13]
    prims = []
    for k in range(len(names)):
        child = parent.index(k) if k in parent else None
        center = (J[k] + J[child]) / 2 if child is not None else J[k] + (0, -0.04, 0.03)
        prims.append(_box(center, 0.08, k))
    return {"joints": J, "parent": parent, "roles": {n: k for k, n in enumerate(names)}, "prims": prims,
            "names": names, "source": "stick"}


def fifteen_part_costume():
    """15 primary OBJs with native-shaped extents (limbs along +-z, a foot below its ankle) + render lists."""
    seed = _seed(15, ((W.DXT1, 8, 8),))
    shapes = {"l_thigh": (0, 0, 0.4), "r_thigh": (0, 0, 0.4), "l_upper": (0, 0, 0.25), "r_upper": (0, 0, 0.25),
              "l_shin": (0, 0, -0.4), "r_shin": (0, 0, -0.4), "l_fore": (0, 0, -0.25), "r_fore": (0, 0, -0.25),
              "l_hand": (0.18, 0, 0), "r_hand": (-0.18, 0, 0), "l_foot": (0, -0.1, 0.25), "r_foot": (0, -0.1, 0.25),
              "chest": (0, 0.35, 0), "head": (0, 0.25, 0), "hip": (0, 0.1, 0)}
    parts = {}
    for k, role in enumerate(F.ROLES):
        end = np.array(shapes[role], float)
        verts = np.zeros((4, 8), np.float32)
        verts[:, :3] = [np.zeros(3), end, end + (0.03, 0.03, 0), (0.03, -0.03, 0.02)]
        verts[:, 5] = 1
        parts[k] = {"vertices": verts, "materials": [{"texture": 0, "triangles": [(0, 1, 2), (0, 2, 3)]}]}
    return W.encode_costume(seed, parts), render_list_cat([(0xFE, list(range(15)))])


def test_fit_costume_appends_smaller_donor_images_when_the_slot_is_tight():
    xpr, cat = fifteen_part_costume()
    rig = stick_rig()
    rig["prims"][0]["tex"] = np.full((256, 256, 4), 255, np.uint8)     # one opaque 256x256 donor image
    full, _res, _hide, steps = F.fit_costume(xpr, cat, rig, native_slots=False)
    assert steps == []
    small, res, _hide, steps = F.fit_costume(xpr, cat, rig, native_slots=False, budget=len(full) - 1)
    assert len(small) < len(full) and steps[-1].startswith("donor images appended at most 128 px")
    assert C.costume_geometry(small)["object_count"] == 15
    with pytest.raises(ValueError, match="costume slot holds 4096"):
        F.fit_costume(xpr, cat, rig, native_slots=False, budget=4096)


def _dense_rig(cuts: int = 6):
    """The stick rig with every box subdivided into a dense grid (thousands of triangles)."""
    rig = stick_rig()
    prims = []
    for p in rig["prims"]:
        c = np.asarray(p["pos"]).mean(0)
        g = np.linspace(-0.04, 0.04, cuts + 1)
        pos, tris = [], []
        for axis in range(3):
            for sign in (-0.04, 0.04):
                base = len(pos)
                for a in g:
                    for b in g:
                        q = [a, b]
                        q.insert(axis, sign)
                        pos.append(c + np.array(q))
                for i in range(cuts):
                    for j in range(cuts):
                        v = base + i * (cuts + 1) + j
                        tris += [(v, v + 1, v + cuts + 2), (v, v + cuts + 2, v + cuts + 1)]
        pos = np.array(pos)
        n = len(pos)
        prims.append({**p, "pos": pos, "nrm": (pos - c) / np.linalg.norm(pos - c, axis=1, keepdims=True),
                      "uv": np.zeros((n, 2)), "tris": np.array(tris), "J": np.full((n, 1), p["J"][0, 0]),
                      "W": np.ones((n, 1)), "owner": np.full(n, p["J"][0, 0])})
    return rig | {"prims": prims}


def test_fit_costume_decimates_a_dense_donor_into_a_tight_slot():
    xpr, cat = fifteen_part_costume()
    rig = _dense_rig()
    full, _res, _hide, steps = F.fit_costume(xpr, cat, rig, native_slots=False)
    assert steps == []
    lean, res, _hide, steps = F.fit_costume(xpr, cat, rig, native_slots=False, budget=len(full) - 0x2000)
    assert len(lean) <= len(full) - 0x2000 and res["report"]["decimated"] in F.DECIMATE_STEPS
    assert steps[-1].startswith("donor reduced to")
    assert C.costume_geometry(lean)["triangle_total"] < C.costume_geometry(full)["triangle_total"]
    assert F.decimated_rig(rig, res["report"]["decimated"]) is F.decimated_rig(rig, res["report"]["decimated"])


def test_collapsed_corners_share_a_vertex_unless_a_seam_splits_them():
    # three corners collapsed onto one point: two with nearby UVs merge, the third (across a UV seam) stays split
    pos = np.array([[0, 0, 0], [0, 0, 0], [0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]], float)
    prim = {"nrm": np.array([[0, 0, 1], [0, 1, 0], [0, 0, 1], [0, 0, 1], [0, 0, 1], [0, 0, 1]], float),
            "uv": np.array([[0.1, 0.1], [0.12, 0.1], [0.8, 0.1], [0.3, 0.1], [0.1, 0.3], [0.9, 0.3]], float)}
    tris = np.array([[0, 3, 4], [1, 4, 3], [2, 5, 4]])
    out, nrm = F._merge_corners(prim, pos, tris)
    assert out[1][0] == 0 and out[2][0] == 2                   # corner 1 joins corner 0; corner 2 is a seam
    assert np.allclose(nrm[0], np.array([0, 1, 1]) / np.sqrt(2))


def test_fit_places_every_role_in_its_joint_frame_and_encodes():
    xpr, cat = fifteen_part_costume()
    geo = C.costume_geometry(xpr)
    roles = F.costume_roles(cat, geo["object_count"])
    res = F.fit(stick_rig(), geo, roles)
    assert set(res["parts"]) == set(range(15))
    rep = res["report"]
    assert rep["scale"] > 0 and set(rep["limb_stretch"]) == {"l_upper", "l_fore", "r_upper", "r_fore",
                                                               "l_thigh", "l_shin", "r_thigh", "r_shin"}
    thigh = res["parts"][roles["primary"]["l_thigh"]]["vertices"][:, :3]
    shin = res["parts"][roles["primary"]["l_shin"]]["vertices"][:, :3]
    hand = res["parts"][roles["primary"]["l_hand"]]["vertices"][:, :3]
    foot = res["parts"][roles["primary"]["l_foot"]]["vertices"][:, :3]
    assert thigh[:, 2].mean() > 0.1 and shin[:, 2].mean() < -0.1            # thigh +z, shin -z from the joint
    assert hand[:, 0].mean() > 0                                             # left fingers +x
    assert foot[:, 1].min() == pytest.approx(-0.1, abs=1e-4)                 # the sole stands on the native sole
    blob = W.encode_costume(xpr, res["parts"], res["textures"], shrink_textures={0})
    out = C.costume_geometry(blob)
    assert out["triangle_total"] == 15 * 12
    assert C.mdl_descriptor_table(blob)["texture_count"] == 1 + rep["textures"]
