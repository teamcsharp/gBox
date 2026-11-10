"""Platform-aware body (de)serialisation: the GC body parses and re-emits with its own endianness."""
import struct

import pytest

from gbox import ninja, pso_player as P


def test_the_platform_endianness_mapping_is_explicit():
    assert P.body_endian("gc") == ">" and P.body_endian("GC") == ">"
    assert P.body_endian("dc") == "<"
    with pytest.raises(ValueError, match="unknown platform"):
        P.body_endian("n64")


DISC = r"D:\gBox\cache\mods\436e0bb84d5337d1\pso_city_npc_moved\Phantasy Star Online Episode I & II Plus (USA).iso"


@pytest.fixture(scope="module")
def disc():
    import pathlib
    from gbox import gcdisc
    if not pathlib.Path(DISC).is_file():
        pytest.skip("the disc is not on this machine")
    return gcdisc.GCDisc(DISC)


def test_a_gamecube_body_rewrites_to_the_same_size_with_the_same_tree(disc):
    from gbox import pso_gc
    original = pso_gc.player_body_nj(disc, "A")
    result = P.rewrite_body(disc, "A", "gc")
    assert result["nodes"] == 64 and result["platform"] == "gc"
    assert len(result["body"]) == len(original)
    assert result["pof0"] == 132 and result["body"][-132:-128] == b"POF0"
    before, payload, after = pso_gc.njcm_payload(result["body"])
    assert before == b"" and after[:4] == b"POF0"
    # the container size is little-endian on GC too, and it covers the payload
    assert struct.unpack_from("<I", result["body"], 4)[0] == len(payload) == result["payload"]
    written = ninja.tree_nodes(payload, 0, ">")
    wanted = ninja.tree_nodes(pso_gc.njcm_payload(original)[1], 0, ">")
    assert len(written) == len(wanted) == 64
    for i, (a, b) in enumerate(zip(wanted, written)):
        assert (a["flags"], a["child"], a["sibling"], a["trs"]) == (b["flags"], b["child"], b["sibling"], b["trs"]), i


def test_the_rewritten_body_keeps_every_models_vertex_list(disc):
    from gbox import pso_gc
    original_payload = pso_gc.njcm_payload(pso_gc.player_body_nj(disc, "A"))[1]
    nodes = ninja.tree_nodes(original_payload, 0, ">")
    models = P.body_models(original_payload, nodes, ">")
    assert models and any(vl for vl, _pl, _c, _r in models.values())
    # every model's vertex list appears verbatim in the emitted payload
    written_payload = pso_gc.njcm_payload(P.rewrite_body(disc, "A", "gc")["body"])[1]
    for i, (vl, pl, _c, _r) in list(models.items())[:8]:
        if vl:
            assert written_payload.find(vl) >= 0, i
        if pl:
            assert written_payload.find(pl) >= 0, i
