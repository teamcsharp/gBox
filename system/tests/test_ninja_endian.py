"""The node-tree writer in big-endian (GameCube): a tree it writes must parse back to the same tree."""
import struct

import pytest

from gbox import ninja


def _nodes_two():
    trs = bytes(range(36))
    return [
        {"flags": 0x17, "trs": trs, "child": 1, "sibling": None},
        {"flags": 0x05, "trs": bytes(36), "child": None, "sibling": None},
    ]


@pytest.mark.parametrize("e", ["<", ">"])
def test_a_tree_round_trips_through_the_writer_in_both_endiannesses(e):
    nodes = _nodes_two()
    models = {0: (b"\x01\x02\x03\x04" * 3, b"\xAA" * 8, (1.0, 2.0, -3.0), 4.5)}
    out, root, ptrs = ninja.write_tree(nodes, models, 0, e)
    back = ninja.tree_nodes(out, 0, e)
    assert len(back) == 2
    assert back[0]["flags"] == nodes[0]["flags"] and back[0]["trs"] == nodes[0]["trs"]
    assert back[0]["child"] == 1 and back[1]["sibling"] is None
    assert back[0]["model"] == root + 52 * 2                       # the model sits after the node array
    vo, po, cx, cy, cz, r = struct.unpack_from(e + "II4f", out, back[0]["model"])
    assert (cx, cy, cz, r) == (1.0, 2.0, -3.0, 4.5)
    assert out[vo:vo + 12] == models[0][0] and out[po:po + 8] == models[0][1]
    assert struct.unpack_from(e + "I", out, back[0]["model"] + 8)[0] != 0


def test_the_pointer_fields_are_reported_for_a_pof0_table():
    out, root, ptrs = ninja.write_tree(_nodes_two(), {0: (b"\x00" * 4, b"", (0, 0, 0), 1.0)}, 0, ">")
    # every pointer field the writer filled is in the list, and the list is what pof0 encodes
    assert ptrs and all(0 <= p < len(out) for p in ptrs)
    table = ninja.pof0(ptrs)
    assert table[:4] == b"POF0" and len(table) > 8


def test_a_real_gamecube_body_tree_parses_and_round_trips_to_itself():
    import pathlib
    from gbox import gcdisc, pso_gc
    disc = pathlib.Path(r"D:\gBox\cache\mods\436e0bb84d5337d1\pso_city_npc_moved"
                        r"\Phantasy Star Online Episode I & II Plus (USA).iso")
    if not disc.is_file():
        pytest.skip("the disc is not on this machine")
    d = gcdisc.GCDisc(str(disc))
    body = pso_gc.player_body_nj(d, "A")
    _before, payload, _after = pso_gc.njcm_payload(body)
    nodes = ninja.tree_nodes(payload, 0, ">")
    assert len(nodes) == 64 and nodes[0]["flags"] == 7
    models = {}
    for i, nd in enumerate(nodes):
        mo = nd["model"]
        if not mo:
            continue
        vo, po, cx, cy, cz, r = struct.unpack_from(">II4f", payload, mo)
        vl = payload[vo:vo + ninja.chunk_list_len(payload, vo, "v", ">")] if vo else b""
        pl = payload[po:po + ninja.chunk_list_len(payload, po, "p", ">")] if po else b""
        models[i] = (vl, pl, (cx, cy, cz), r)
    assert models, "the body has no models"
    out, root, _ptrs = ninja.write_tree(nodes, models, 0, ">")
    back = ninja.tree_nodes(out, 0, ">")
    assert len(back) == len(nodes)
    for i, (a, b) in enumerate(zip(nodes, back)):
        assert (a["flags"], a["child"], a["sibling"], a["trs"]) == (b["flags"], b["child"], b["sibling"], b["trs"]), i
        if a["model"]:
            want = struct.unpack_from(">II4f", payload, a["model"])
            got = struct.unpack_from(">II4f", out, b["model"])
            assert (want[2], want[3], want[4], want[5]) == (got[2], got[3], got[4], got[5]), i
            assert out[got[0]:got[0] + len(models[i][0])] == models[i][0]
