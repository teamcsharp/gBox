"""PSO Ver.2 (DC) player classes in the native collection (#1485): every class body is one 64-node tree, the role map is
checked against each class's own tree (synthetic NJ bodies in each class's proportions, no disc), entries collected
before extraction reported roles get them back from their manifest, and a stored partial collection result is
re-checked against the library so the session observer stops filing the gap. The owned-disc test at the end reads the
nine bodies off the operator's GDI when it is reachable (PSO_GDI or the Spark cache path) and skips otherwise."""
import json
import os
import struct
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from gbox import characters as C, ninja, pso_player as P
from gbox.character_collection import AutoCollection
from gbox.store import Store

# hip height per class letter on the disc (HUcast 14.31 ... HUnewearl 10.47): the synthetic bodies are scaled to it
HIP = {"A": 11.89, "B": 10.47, "C": 14.31, "D": 12.87, "E": 13.26, "F": 10.68, "G": 11.31, "H": 11.88, "I": 10.54}
# local offsets (HUcast proportions, model facing +Z with its left at +X); every other node sits on its parent
LOCAL = {1: (0, 14.3, 0), 3: (0.9, -1.2, 0), 5: (0.4, -5, 0), 7: (0.5, -6.8, 0), 12: (-0.9, -1.2, 0),
         14: (-0.4, -5, 0), 16: (-0.5, -6.8, 0), 24: (0, 0.4, 0), 26: (2.9, 3.3, 0), 29: (0, -3, 0), 31: (0, -3.3, 0),
         39: (-2.9, 3.3, 0), 42: (0, -3, 0), 44: (0, -3.3, 0), 55: (0, 5, 0)}
ROLE_NAMES = {"hip": "node002", "chest": "node025", "head": "node056", "l_upper": "node028", "l_fore": "node029",
              "l_hand": "node034", "r_upper": "node041", "r_fore": "node042", "r_hand": "node047",
              "l_thigh": "node004", "l_shin": "node005", "l_foot": "node008", "r_thigh": "node013",
              "r_shin": "node014", "r_foot": "node017"}


def body(cls="C", parents=None, mirror=False, mesh=None) -> bytes:
    """A PL<x>BDY00.NJ-like file: the player node tree (parents), scaled to the class's hip height, a triangle on every
    mesh node (default: the role nodes)."""
    parents = P.PLAYER_PARENTS if parents is None else parents
    s = HIP[cls] / 14.31
    mesh = set(P.PLAYER_ROLES.values()) if mesh is None else set(mesh)
    nodes = []
    for i, p in enumerate(parents):
        x, y, z = LOCAL.get(i, (0, 0, 0))
        nodes.append({"flags": 0x04, "trs": struct.pack("<3f3i3f", (-x if mirror else x) * s, y * s, z * s, 0, 0, 0, 1, 1, 1),
                      "parent": None if p < 0 else p, "child": None, "sibling": None})
    for i in range(len(nodes)):
        kids = [k for k, n in enumerate(nodes) if n["parent"] == i]
        if kids:
            nodes[i]["child"] = kids[0]
        for a, b in zip(kids, kids[1:]):
            nodes[a]["sibling"] = b
    tri = np.array([[0, 0, 0], [0.3, 0, 0], [0, 0.3, 0.1]], float)
    models = {j: ninja.cnk_model_lists(tri, np.tile([0, 0, 1.0], (3, 1)), [((0, 1, 2), ((0, 0), (1, 0), (0, 1)))], 0, b"",
                                       base=3 * j) for j in sorted(mesh) if j < len(nodes)}
    data, _root, ptrs = ninja.write_tree(nodes, models, 0)
    return P.nj_file(data, ptrs)


# ---------------------------------------------------------------- the role map on each class's tree

@pytest.mark.parametrize("cls", list("ABCDEFGHI"))
def test_every_class_body_takes_the_role_map(cls):
    f = body(cls)
    nodes = ninja.tree_nodes(f[8:], 0)
    assert [-1 if n["parent"] is None else n["parent"] for n in nodes] == P.PLAYER_PARENTS
    roles = P.body_roles(f, cls)
    assert roles == P.CLASS_ROLES[cls] == P.PLAYER_ROLES
    assert P.joint_roles(roles) == ROLE_NAMES


def test_all_nine_classes_have_a_complete_map():
    assert sorted(P.CLASS_ROLES) == list("ABCDEFGHI") and len(P.CLASSES) == 9
    need = {r for ch in P.ROLE_CHAINS for r in ch}
    for cls, roles in P.CLASS_ROLES.items():
        assert set(roles) == need, cls
        assert P.check_roles(P.PLAYER_PARENTS, _world(body(cls)), roles) == []


def _world(f):
    return [[b["m"][k][3] for k in range(3)] for b in ninja.NJ(f).bones]


def test_a_mirrored_body_is_refused():
    with pytest.raises(ValueError, match="l_upper .* is on the right"):
        P.body_roles(body("B", mirror=True), "B")


def test_a_different_tree_is_refused():
    parents = P.PLAYER_PARENTS[:-1]                         # 63 nodes: not a player body
    with pytest.raises(ValueError, match="not the PSO player body tree"):
        P.body_roles(body("A", parents=parents), "A")
    assert P.check_roles([-1, 0, 1], [[0, 0, 0]] * 3, P.PLAYER_ROLES)


def test_a_role_node_without_vertices_is_refused():
    mesh = set(P.PLAYER_ROLES.values()) - {P.PLAYER_ROLES["l_hand"]}
    with pytest.raises(ValueError, match="l_hand .* draws no vertices"):
        P.body_roles(body("G", mesh=mesh), "G")
    with pytest.raises(ValueError, match="unknown PSO class"):
        P.body_roles(body("A"), "J")


def test_check_roles_wants_the_chains_and_the_heights():
    world = _world(body("C"))
    swapped = P.PLAYER_ROLES | {"l_fore": 28, "l_upper": 29}
    assert any("isn't below" in b for b in P.check_roles(P.PLAYER_PARENTS, world, swapped))
    assert P.check_roles(P.PLAYER_PARENTS, world, {k: v for k, v in P.PLAYER_ROLES.items() if k != "head"}) == ["no head"]
    upside = [[x, -y, z] for x, y, z in world]
    assert any("heights out of order" in b for b in P.check_roles(P.PLAYER_PARENTS, upside, P.PLAYER_ROLES))


# ---------------------------------------------------------------- roles on extraction and for entries collected before

def _entry_dir(tmp_path, cls, slug, method="gbox.pso_player", mirror=False):
    d = tmp_path / slug
    d.mkdir(parents=True)
    m = ninja.to_manifest(ninja.NJ(body(cls, mirror=mirror)), f"pso_{slug}_h0_c0",
                          {"class": cls, "files": [f"PSO/PL{cls}BDY00.NJ"], "extraction_method": method})
    (d / "manifest.json").write_text(m.model_dump_json())
    (d / f"pso_{slug}_h0_c0.glb").write_bytes(b"glTF")
    return d / f"pso_{slug}_h0_c0.glb"


@pytest.mark.parametrize("cls", list("ABCDEFGHI"))
def test_model_roles_reads_the_class_off_the_manifest(tmp_path, cls):
    assert P.model_roles(_entry_dir(tmp_path, cls, "x")) == ROLE_NAMES


def test_model_roles_leaves_other_models_unmapped(tmp_path):
    assert P.model_roles(_entry_dir(tmp_path / "a", "A", "x", method="gbox.pso_enemy")) == {}
    assert P.model_roles(_entry_dir(tmp_path / "b", "A", "x", mirror=True)) == {}
    with pytest.raises(OSError):
        P.model_roles(tmp_path / "nowhere" / "x.glb")


def test_pso_run_reports_the_roles(monkeypatch, tmp_path):
    import gbox.gdrom
    read = []

    class Disc:
        def __init__(self, path):
            pass

        def read(self, name):
            read.append(name)
            return body("F")
    monkeypatch.setattr(gbox.gdrom, "GDRom", Disc)
    monkeypatch.setattr(C, "_dc_gdi", lambda ctx, game: tmp_path / "disc.gdi")
    monkeypatch.setattr(P, "export", lambda gdi, out, cls: Path(out) / "x.glb")
    e = {"key": "F", "slug": "pso_racaseal", "name": "RAcaseal", "kind": "character"}
    r = C._pso_run(None, {}, e, tmp_path)
    assert r["roles"] == ROLE_NAMES and read == ["PSO/PLFBDY00.NJ"]


def test_role_backfill_maps_an_entry_collected_without_roles(tmp_path):
    model = _entry_dir(tmp_path, "H", "pso_fonewm")
    meta = {"slug": "pso_fonewm", "name": "FOnewm", "model": model.name, "kind": "character",
            "rig": {"skinned": True, "joints": 64}}
    C.put_meta(tmp_path, meta)
    out = C.backfill_roles(tmp_path, "pso", meta)
    assert out["rig"]["roles"] == ROLE_NAMES and out["rig"]["joints"] == 64
    assert C.get(tmp_path, "pso_fonewm")["rig"]["roles"] == ROLE_NAMES


# ---------------------------------------------------------------- the collection status computation

def test_collection_status_counts_characters_not_props():
    rows = [{"slug": "a", "verified": True, "retargetable": True, "kind": "character"},
            {"slug": "b", "verified": True, "retargetable": True},                     # old rows carry no kind
            {"slug": "crate", "verified": True, "retargetable": False, "kind": "prop"}]
    s = C.collection_status(rows)
    assert s["status"] == "complete" and s["characters"] == 2 and s["retargetable"] == 2 and s["collected"] == 3
    rows.append({"slug": "c", "verified": True, "retargetable": False, "kind": "character"})
    s = C.collection_status(rows)
    assert s["status"] == "partial" and s["retargetable"] == 2 and s["characters"] == 3
    rows[2]["verified"] = False
    rows[3]["retargetable"] = True
    assert C.collection_status(rows)["status"] == "partial"                          # a prop still needs its model
    assert C.collection_status([])["status"] == "partial"


SLUGS = {"A": "pso_humar", "B": "pso_hunewearl", "C": "hucast", "D": "pso_ramar", "E": "pso_racast",
         "F": "pso_racaseal", "G": "pso_fomarl", "H": "pso_fonewm", "I": "pso_fonewearl"}


def _ticket_library(root):
    """The #1485 state: nine verified PSO classes, only HUcast with rig.roles; the stored job result as reported."""
    entries = []
    for cls, slug in SLUGS.items():
        model = _entry_dir(root, cls, slug)
        rig = {"skinned": True, "joints": 64} | ({"roles": ROLE_NAMES} if cls == "C" else {})
        C.put_meta(root, {"slug": slug, "name": P.CLASSES["ABCDEFGHI".index(cls)], "model": model.name,
                          "rig": rig} | ({} if cls == "C" else {"kind": "character"}))
        entries.append({"slug": slug, "name": P.CLASSES["ABCDEFGHI".index(cls)],
                        "status": "in_collection" if cls == "C" else "extracted", "verified": True,
                        "retargetable": cls == "C",
                        "message": "" if cls == "C" else "Model or mapped rig needs verification before retargeting."})
    return {"status": "partial", "game_id": "daba7a3b195dcf6b", "extractor": "pso", "collected": 9, "total": 9,
            "retargetable": 1, "entries": entries}


def test_refresh_turns_the_ticket_result_complete(monkeypatch, tmp_path):
    monkeypatch.setattr(C, "verify_entry", lambda root, meta: {"ok": True})
    result = _ticket_library(tmp_path)
    out = C.refresh_collection(tmp_path, result)
    assert out["status"] == "complete" and out["retargetable"] == 9 and out["characters"] == 9
    assert all(e["retargetable"] and e["message"] == "" for e in out["entries"])
    assert out["extractor"] == "pso" and out["game_id"] == "daba7a3b195dcf6b"
    assert result["retargetable"] == 1                                                # the stored result is untouched
    assert C.get(tmp_path, "pso_humar")["rig"]["roles"] == ROLE_NAMES


def test_refresh_keeps_failed_and_unmappable_entries_partial(monkeypatch, tmp_path):
    monkeypatch.setattr(C, "verify_entry", lambda root, meta: {"ok": True})
    result = _ticket_library(tmp_path)
    man = tmp_path / "pso_ramar" / "manifest.json"
    m = json.loads(man.read_text())
    m["source"]["extraction_method"] = "something else"
    man.write_text(json.dumps(m))
    result["entries"].append({"slug": "pso_gone", "name": "Gone", "status": "failed", "verified": False,
                              "retargetable": False, "error": "corrupt"})
    out = C.refresh_collection(tmp_path, result)
    assert out["status"] == "partial" and out["retargetable"] == 8 and out["total"] == 10
    assert next(e for e in out["entries"] if e["slug"] == "pso_ramar")["message"]
    assert C.refresh_collection(tmp_path, {"status": "complete"}) == {"status": "complete"}


def test_collection_status_read_refreshes_a_partial_result(monkeypatch, tmp_path):
    """The session observer reads AutoCollection.status: with the roles backfilled it no longer sees 'partial' (no gap
    request), and the roster job isn't queued again."""
    lib = tmp_path / "characters"
    lib.mkdir()
    result = _ticket_library(lib)
    monkeypatch.setattr(C, "verify_entry", lambda root, meta: {"ok": True})
    monkeypatch.setattr(C, "library_root", lambda cfg: lib)
    store = Store(tmp_path / "data")
    store.put("job", "j1", {"id": "j1", "state": "succeeded", "output": {"result": result}})
    store.put("character_collection", "daba7a3b195dcf6b", {"state": "queued", "job_id": "j1"})
    auto = AutoCollection(store, SimpleNamespace(cache=str(tmp_path)))
    status = auto.status("daba7a3b195dcf6b")
    assert status["state"] == "succeeded" and status["result"]["status"] == "complete"
    assert store.get("job", "j1")["output"]["result"]["retargetable"] == 1
    game = {"game_id": "daba7a3b195dcf6b", "title": "Phantasy Star Online Ver. 2 (USA)", "platform": "dreamcast"}
    auto.after_launch({"input": {"game": game}}, {}, lambda request: pytest.fail("re-queued the roster"))
    assert AutoCollection(store, None).status("daba7a3b195dcf6b")["result"]["status"] == "partial"


# ---------------------------------------------------------------- the owned disc (skipped when it isn't reachable)

GDI = os.environ.get("PSO_GDI") or "//10.89.1.246/ehm_eckx/gbox-cache/dc/daba7a3b195dcf6b/disc.gdi"


@pytest.mark.skipif(not Path(GDI).is_file(), reason="the owned PSO Ver.2 GDI isn't reachable")
def test_owned_disc_every_class_body_takes_the_role_map():
    from gbox.gdrom import GDRom
    disc = GDRom(GDI)
    for cls in "ABCDEFGHI":
        assert P.body_roles(disc.read(f"PSO/PL{cls}BDY00.NJ"), cls) == P.PLAYER_ROLES
