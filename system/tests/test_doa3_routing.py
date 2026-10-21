"""DOA3 cast writer routing: discoverable through writer_for, honest, never fabricates a build."""
from gbox import char_coverage as CC
from gbox import doa3_cast
from gbox.doa3_inventory import GAME_ID

GAME = {"game_id": GAME_ID, "title": "Dead or Alive 3 (USA)", "platform": "xbox"}


class _Inp:
    def __init__(self, slot):
        self.slot = slot


def test_writer_for_routes_doa3():
    w = CC.writer_for(GAME)
    assert w is not None, "DOA3 must resolve a writer now that doa3_cast is registered"
    assert w["writer"] == "gbox.doa3_cast"
    assert w["routed"] is True, "characters_tool must call doa3_cast.use for the writer to count as routed"


def test_writer_status_is_honest_about_verification():
    st = doa3_cast.cast_writer_status()
    assert st["afs_patch_path"] is True
    assert st["donor_retarget"] is True
    assert st["playable"] is False                     # builds are built_unverified until seen in game per donor


def test_is_slot():
    assert doa3_cast.is_slot("cast") is True
    assert doa3_cast.is_slot("fighter:kasumi") is True
    assert doa3_cast.is_slot("fighter:kasumi:02") is True
    assert doa3_cast.is_slot("player") is False
    assert doa3_cast.is_slot("") is False
    assert doa3_cast.is_slot(None) is False


def test_use_refuses_a_slot_it_cannot_build_without_writing_anything():
    import pytest
    with pytest.raises(ValueError, match="fighter:<nick"):
        doa3_cast.use(None, {"name": "x", "slug": "x"}, GAME, _Inp("cast"))
    with pytest.raises(ValueError, match="no DOA3 fighter family"):
        doa3_cast.use(None, {"name": "x", "slug": "x"}, GAME, _Inp("fighter:nobody"))


def test_whole_cast_goes_through_the_pairs_builder():
    from gbox import cast_swap
    assert cast_swap.strategy("gbox.doa3_cast")[0] == "pairs"
    assert cast_swap.BUILDERS["gbox.doa3_cast"] is cast_swap._doa3
    rows = cast_swap.slot_rows(GAME)
    slots = {r["slot"]: r for r in rows}
    assert len([r for r in rows if r["kind"] == "fighter"]) == 19          # every family with costumes
    assert slots["fighter:zack"]["costume_code"] == "zac"
    assert slots["fighter:tengu"]["status"] == "not_working"             # reported, never faked


def _entry(slug, name, title, gid, group=None, roles=None, plat=""):
    roles = roles or {r: f"j_{r}" for r in ("hip", "chest", "head", "l_upper", "l_fore", "l_hand", "r_upper",
                                            "r_fore", "r_hand", "l_thigh", "l_shin", "l_foot", "r_thigh", "r_shin",
                                            "r_foot")}
    meta = {"slug": slug, "name": name, "kind": "character", "model": f"{slug}.glb", "aliases": [],
            "rig": {"roles": roles}, "stats": {"triangles": 500, "textures": 1}, "readiness": {"status": "ready"},
            "source": {"game_title": title, "platform": plat, "game_id": gid}}
    if group:
        meta["donor_group"] = group
    return meta


def test_cast_plan_refuses_donors_without_two_legs():
    from gbox import cast_swap
    chars = [_entry("sa2_sonic", "Sonic", "Sonic Adventure 2 (USA)", "5a20000000000000", plat="dreamcast"),
             _entry("sa2_shadow", "Shadow", "Sonic Adventure 2 (USA)", "5a20000000000000", plat="dreamcast"),
             _entry("mario_hd", "Mario (HD)", "Render96 ModelPack (Super Mario 64 HD models)", None, group="mario"),
             _entry("sm64ds_boo", "Boo", "Super Mario 64 DS (USA)", "917483267d246594", group="mario",
                    roles={"hip": "j_body"})]
    p = cast_swap.plan(GAME, chars, "sonic, mario", mapping="alternate", seed="1")
    assert p["status"] == "planned"
    refused = {r["slug"]: r["reason"] for r in p["refused"]}
    assert "two legs" in refused["sm64ds_boo"] and "l_thigh" in refused["sm64ds_boo"]
    used = {r["character"] for r in p["assignments"]}
    assert "sm64ds_boo" not in used and {"sa2_sonic", "mario_hd"} <= used
    assert doa3_cast.donor_problem(chars[0]) is None


def test_build_cast_reports_a_slot_it_cannot_resolve():
    res = doa3_cast.build_cast(None, GAME, [("fighter:nobody", {"slug": "x", "name": "X"})], "doa3_cast_x")
    assert res["mod"] is None and res["slots"]["fighter:nobody"]["status"] == "failed"
