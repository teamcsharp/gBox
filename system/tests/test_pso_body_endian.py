"""CP12/CP13 regression: a built GameCube body must parse, including its empty polygon lists.

The round-87 defect: `build_swap` wrote the empty polygon list as `struct.pack("<HH", 0xFF, 0)` - hard-coded little-endian -
so in a big-endian body the end marker became the null chunk `0xFF00` and the parser walked past it into the model's
centre/radius floats. It only crashed when those float bytes happened to be a chunk type (Cloud's 0x14), which is why one
donor looked clean and another did not.
"""
import struct

import pytest

from gbox import ninja


def _body_with_empty_list(be: bool) -> bytes:
    """A two-node body where the first node has geometry and the second has only an empty polygon list."""
    import numpy as np
    e = ">" if be else "<"
    tris = [((0, 1, 2), ((0, 0), (0, 1), (1, 1)))]
    nrm = np.tile([0.0, 0.0, 1.0], (3, 1))
    vl, pl, c, r = ninja.cnk_model_lists(np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=float), nrm, tris, 1, b"", e=e)
    empty = struct.pack(e + "HH", 0xFF, 0)
    nodes = [
        {"flags": 0, "trs": struct.pack(e + "3f3i3f", 0, 0, 0, 0, 0, 0, 1, 1, 1), "child": None, "sibling": 1},
        {"flags": 0, "trs": struct.pack(e + "3f3i3f", 0, 0, 0, 0, 0, 0, 1, 1, 1), "child": None, "sibling": None},
    ]
    models = {0: (vl, pl, c, r), 1: (b"", empty, [0.0, 0.0, 0.0], 0.0)}
    data, _root, _ptrs = ninja.write_tree(nodes, models, 0, e)
    return b"NJCM" + struct.pack("<I", len(data)) + data


@pytest.mark.parametrize("be", [True, False])
def test_empty_polygon_list_parses_in_both_endiannesses(be):
    body = _body_with_empty_list(be)
    nj = ninja.NJ(body, be=be)
    assert len(nj.bones) == 2
    assert nj.tris, "the first node's strip should still produce triangles"


def test_a_little_endian_empty_list_in_a_big_endian_body_would_break():
    """The exact round-87 bytes: 00 FF (LE at write time) read big-endian is 0xFF00, a null chunk, not the end."""
    word = struct.unpack_from(">H", struct.pack("<HH", 0xFF, 0))[0]
    assert word == 0xFF00                      # null chunk: the parser walks on, which is the bug
    assert struct.unpack_from(">H", struct.pack(">HH", 0xFF, 0))[0] == 0x00FF
