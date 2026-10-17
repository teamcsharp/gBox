"""Enter the Matrix writer (gbox.etm_swap): slots, the fit onto the shared skeleton, the plain-triangle encoding read
back by the reader, the slot budget, a synthetic disc build (only the cast entries change), the cast builder and
the registrations (WRITERS, cast_swap, characters_tool routing)."""
import json
from pathlib import Path

import numpy as np
import pytest

from gbox import etm_inventory as inv
from gbox import etm_models as M
from gbox import etm_swap as S
from gbox.defjam_inventory import Iso
from gbox.shiny_dfu import Dfu
from matrix_synth import humanoid_dcn, make_dfu, make_iso


@pytest.fixture(scope="module")
def donor(tmp_path_factory):
    """A rigged donor GLB with roles: the synthetic character through the reader (as the collection stores one)."""
    d = tmp_path_factory.mktemp("donor")
    r = M.extract_bytes(humanoid_dcn("Donor"), d / "donor.glb", "donor")
    (d / "meta.json").write_text(json.dumps({"slug": "donor", "name": "Donor", "model": "donor.glb",
                                             "rig": {"roles": r["roles"]}}))
    return d / "donor.glb", r["roles"]


def test_slots_cover_the_cast():
    rows = S.cast_slots()
    slots = [r["slot"] for r in rows]
    assert slots[0] == "player" and rows[0]["aggregate"]
    assert {"niobe", "ghost", "agent_smith", "trinity", "morpheus", "neo", "seraph", "swat", "police"} <= set(slots)
    assert {r["kind"] for r in rows} <= {"player", "character", "enemy", "npc", "pedestrian"}
    assert S.resolve_slot("player") == S.SLOTS["niobe"][2] + S.SLOTS["ghost"][2]
    assert S.resolve_slot("Agent Smith") == ["AgentSmith"] and S.resolve_slot("cast:swat")[0] == "Swat"
    assert S.resolve_slot("niobe_costume03") == ["Niobe_Costume03"]
    with pytest.raises(S.SwapError):
        S.resolve_slot("tank")


def test_fit_encode_and_read_back(donor):
    glb, roles = donor
    base = humanoid_dcn("Niobe_Costume01")
    tgt = S.target(M.parse_dcn(base))
    fitted = S.fit(glb, roles, tgt)
    full = S.triangles(fitted, 2)
    assert len(full["pages"]) == 2 and full["pages"][0].shape == (256, 256, 4)
    data = S.encode(base, full)
    v = S.verify(data, full)
    assert v["ok"] and v["triangles"] == len(full["pos"]) and v["max_position_error"] < 1e-3
    m = M.parse_dcn(data)
    assert m["checksum"] == inv.SKELETON_CHECKSUM and m["name"] == "Niobe_Costume01"
    assert np.allclose(m["joint_positions"], M.parse_dcn(base)["joint_positions"])
    assert len(m["configs"]) == 2 and all(c["meshes"] == [0] for c in m["configs"])   # as many configs as the base
    assert [t["bpp"] for t in m["textures"]] == [8, 8] and m["meshes"][0]["flags"] == S.MESH_FLAGS
    a = M.assemble(m, 0, 1)
    assert a["flipped"] > 0.9 * a["triangles"]           # the game's own plain-triangle winding (Morpheus: 508/512)
    assert set(np.unique(full["joint"])) <= set(M.ROLE_JOINTS.values())


def test_fit_entry_shrinks_into_the_slot(donor):
    glb, roles = donor
    base = humanoid_dcn(extra_pages=8)
    fitted = S.fit(glb, roles, S.target(M.parse_dcn(base)))
    big = S.fit_entry(base, 10 ** 7, fitted)
    assert big["pages"] == 4 and big["cluster"] == 0
    cap = big["packed"] - 1500                             # a slot a little too small for 4 full pages
    small = S.fit_entry(base, cap, fitted)
    assert small["packed"] <= cap and (small["pages"], small["cluster"]) != (4, 0)
    with pytest.raises(S.SwapError):
        S.fit_entry(base, 500, fitted)


def test_clustering_keeps_corner_uvs_and_drops_collapsed_triangles(donor):
    glb, roles = donor
    fitted = S.fit(glb, roles, S.target(M.parse_dcn(humanoid_dcn())))
    full = S.triangles(fitted, 1)
    c = S.clustered(full, 0.05)
    assert 0 < len(c["pos"]) < len(full["pos"]) and c["uv"].shape[1:] == (3, 2)
    assert S.clustered(full, 0) is full


def _disc(tmp_path, monkeypatch):
    files = {"actors\\Niobe_Costume01.dcn": humanoid_dcn("Niobe_Costume01", 6),      # room for 4 pages
             "actors\\Niobe_Costume02.dcn": humanoid_dcn("Niobe_Costume02", 6),
             "actors\\AgentSmith.dcn": humanoid_dcn("AgentSmith", 6), "Animation\\AnimList.txt": b"a.asb\n"}
    w1, w2 = make_dfu(files, packed={k for k in files if k.endswith(".dcn")}, split=200000)
    iso = tmp_path / "etm.iso"
    iso.write_bytes(make_iso({"SYSTEM.CNF": b"BOOT2 = cdrom0:\\SLUS_204.54;1\n", "SLUS_204.54": b"\x7fELF",
                              "WAD1.DFU": w1, "WAD1_B.DFU": w2}))
    monkeypatch.setattr(inv, "identify", lambda disc: {"exact_build": True, "boot": "SLUS_204.54"})
    return iso, files


def test_build_disc_rewrites_only_the_slot_entries(tmp_path, monkeypatch, donor):
    iso, files = _disc(tmp_path, monkeypatch)
    glb, roles = donor
    out = tmp_path / "mod" / "etm.iso"
    r = S.build_disc(iso, out, [{"slot": "niobe", "model": glb, "roles": roles, "name": "Donor"},
                                {"slot": "neo", "model": glb, "roles": {}, "name": "No roles"}])
    niobe, neo = r["reports"]
    assert niobe["status"] == "partial"                   # 2 of the 7 Niobe files exist on this disc
    built = [e for e in niobe["entries"] if e["status"] == "built"]
    assert [e["model"] for e in built] == ["actors\\Niobe_Costume01.dcn", "actors\\Niobe_Costume02.dcn"]
    assert all(e["read_back"] for e in built)
    assert neo["status"] == "failed" and "roles" in neo["reason"]
    d0, d1 = Dfu(Iso(iso), "etm"), Dfu(Iso(out), "etm")
    assert d1.read("actors\\AgentSmith.dcn") == d0.read("actors\\AgentSmith.dcn")
    assert d1.read("Animation\\AnimList.txt") == b"a.asb\n"
    m = M.parse_dcn(d1.read("actors\\Niobe_Costume01.dcn"))
    assert [p["kind"] for p in m["meshes"][0]["patches"]][:1] == ["tri3"]
    assert iso.read_bytes() == Path(iso).read_bytes()     # the source image is never written


def test_build_cast_reports_per_slot(tmp_path, monkeypatch, donor):
    iso, _files = _disc(tmp_path, monkeypatch)
    glb, roles = donor

    class Cfg:
        cache = str(tmp_path / "cache")
    meta = {"slug": "donor", "name": "Donor", "model": glb.name, "rig": {"roles": roles}}
    game = {"game_id": inv.GAME_ID, "title": "Enter the Matrix (USA)"}
    monkeypatch.setattr(S, "base_iso", lambda cfg, g, src, progress=None: iso)
    monkeypatch.setattr(M, "source_disc", lambda ctx, g: iso)
    root = tmp_path / "lib"
    (root / "donor").mkdir(parents=True)
    (root / "donor" / glb.name).write_bytes(glb.read_bytes())
    res = S.build_cast(Cfg(), game, [("agent_smith", meta), ("trinity", meta)], "etm_cast_test",
                       progress=lambda p, m: None, root=root)
    assert res["mod"] == "etm_cast_test"
    assert res["slots"]["agent_smith"] == {"status": "built"}
    assert res["slots"]["trinity"]["status"] == "failed"   # Trinity_zen isn't on the synthetic disc
    rec = json.loads((Path(Cfg.cache) / "mods" / inv.GAME_ID / "etm_cast_test" / ".gbox-mod.json").read_text())
    assert rec["writer"] == "gbox.etm_swap" and rec["files"] == ["actors\\AgentSmith.dcn"]


OWNED = Path(__import__("os").environ.get("GBOX_ETM_PS2_CHD") or
             "//10.89.1.125/HyperSpin Attraction/Arcade/collections/Sony Playstation 2/roms/USA/Enter the Matrix (USA).chd")


@pytest.mark.skipif(not OWNED.exists(), reason="owned Enter the Matrix CHD not reachable")
def test_owned_slots_exist_and_a_donor_fits_niobe(donor):
    _disc, d, _ident = M.open_archive(OWNED)
    missing = [st for _n, _k, sts in S.SLOTS.values() for st in sts if M.model_path(st) not in d]
    assert not missing
    e = d.entry(M.model_path("Niobe_Costume01"))
    base = d.read(e)
    glb, roles = donor
    r = S.fit_entry(base, e.packed, S.fit(glb, roles, S.target(M.parse_dcn(base))), e.compressed)
    assert r["verify"]["ok"] and r["packed"] <= e.packed and r["size"] <= e.size
    plan = d.replace_plan(e, r["data"])
    assert plan["patches"][-1][0] == "WAD1.DFU" and len(plan["patches"][-1][2]) == 16


def test_registrations():
    from gbox import cast_swap, char_coverage, characters as C
    game = {"game_id": inv.GAME_ID, "title": "Enter the Matrix (USA)", "platform": "windows_native"}
    w = char_coverage.writer_for(game)
    assert w["writer"] == "gbox.etm_swap" and w["routed"]
    slots = char_coverage.cast_slots(game)
    assert {"player", "niobe", "agent_smith"} <= {s["slot"] for s in slots}
    rows = cast_swap.slot_rows(game)
    assert "player" not in {r["slot"] for r in rows} and {"niobe", "ghost"} <= {r["slot"] for r in rows
                                                                               if r["kind"] == "player"}
    assert cast_swap.strategy("gbox.etm_swap")[0] == "pairs" and "gbox.etm_swap" in cast_swap.BUILDERS
    import inspect
    assert "etm_swap.use(" in inspect.getsource(C.characters_tool)
