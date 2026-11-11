"""CP12 follow-up: `ninja.NJ`'s per-corner snapshot - two nodes reusing a vertex-cache base must not merge.

Round 81's "exploded body" render came from resolving indices against the final `vbuf`; `NJ.tris` carries the draw-time
snapshot precisely because player bodies reuse cache slots. This builds a real two-node tree with `cnk_model_lists` (the
same writer the swap uses), forcing both nodes onto cache base 5 with different positions.
"""
import struct

import numpy as np
import pytest

from gbox import ninja


def _two_node_njcm(pos_a: list, pos_b: list, base: int = 5) -> bytes:
    tris = [((0, 1, 2), ((0, 0), (0, 1), (1, 1)))]
    nrm = np.tile([0.0, 0.0, 1.0], (3, 1))
    vl_a, pl_a, centre_a, radius_a = ninja.cnk_model_lists(np.array(pos_a, dtype=float), nrm, tris, 1, b"", base=base)
    vl_b, pl_b, centre_b, radius_b = ninja.cnk_model_lists(np.array(pos_b, dtype=float), nrm, tris, 1, b"", base=base)
    nodes = [
        {"flags": 0, "trs": struct.pack("<3f3i3f", 0, 0, 0, 0, 0, 0, 1, 1, 1), "child": None, "sibling": 1},
        {"flags": 0, "trs": struct.pack("<3f3i3f", 0, 0, 0, 0, 0, 0, 1, 1, 1), "child": None, "sibling": None},
    ]
    models = {0: (vl_a, pl_a, centre_a, radius_a), 1: (vl_b, pl_b, centre_b, radius_b)}
    data, _root, _ptrs = ninja.write_tree(nodes, models, 0, "<")
    return b"NJCM" + struct.pack("<I", len(data)) + data


def test_two_nodes_reusing_a_cache_base_keep_distinct_snapshots():
    njcm = _two_node_njcm([(1, 2, 3), (2, 2, 3), (2, 3, 3)], [(10, 20, 30), (11, 20, 30), (11, 21, 30)])
    nj = ninja.NJ(njcm)
    assert len(nj.bones) == 2
    # the cache itself only holds the last writer's positions: that is exactly why the snapshot exists
    final = {tuple(round(v, 3) for v in v["pos"]) for v in nj.vbuf.values()}
    assert (10.0, 20.0, 30.0) in final
    assert (1.0, 2.0, 3.0) not in final
    # the triangles still see both nodes' own vertices through their snapshots
    positions = {tuple(round(v, 3) for v in c[2]["pos"])
                 for tris in nj.tris.values() for tri in tris for c in tri if c[2]}
    assert (1.0, 2.0, 3.0) in positions
    assert (10.0, 20.0, 30.0) in positions
