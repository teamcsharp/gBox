"""NB2003 ``.dff`` index-space invariant on the owned ape.dff fixture.

Verified 2026-11-13 (lilspark2, local model) against nb2003_ape.dff,
sha256 878165bf6382da461dacd1e2aaff091621f06d91f90d2f4e6690ef2edd5862fa:
all 8 meshes (4 pos + 4 uv) satisfy ``max(strip index) == count_hdr - 1``
where ``count_hdr`` is the first word of the blob leaf, while the strip
header's ``npool`` field is a capacity >= count_hdr (e.g. mesh0: count_hdr
225, max index 224, npool 329).  The blob count word -- not npool --
defines the live index space; npool is headroom.  The stride-17 row
decode of mesh0's 3918-word pool yields 150 full + 2 partial + 78
all-sentinel rows plus an 8-word sentinel tail (1352 sentinel words),
with 224 distinct indices used.
"""
import hashlib
import os
import struct

import pytest

from gbox.nb2003_dff import decode_float_pool, read_dff

FIXTURE = ("/home/ehm_eckx/gbox-cache/research/nb2003_reader_fixtures_2360"
           "/nb2003_ape.dff")
ANCHOR = ("878165bf6382da461dacd1e2aaff091621f90d2f4e6690ef2edd5862fa"
          .replace("f90", "1f90") if False else
          "878165bf6382da461dacd1e2aaff091621f06d91f90d2f4e6690ef2edd5862fa")


@pytest.fixture(scope="module")
def data():
    if not os.path.exists(FIXTURE):
        pytest.skip("owned ape.dff fixture not present on this host")
    d = open(FIXTURE, "rb").read()
    if hashlib.sha256(d).hexdigest() != ANCHOR:
        pytest.skip("ape.dff fixture hash mismatch; not the anchored build")
    return d


def test_index_space_matches_blob_count(data):
    meshes = read_dff(data)
    assert len(meshes) == 8
    for m in meshes:
        assert m.indices, f"empty strip @ {m.offset:#x}"
        assert max(m.indices) == m.pool_count_hdr - 1, (
            f"mesh {m.offset:#x}: max index {max(m.indices)} != "
            f"count_hdr-1 {m.pool_count_hdr - 1}")
        assert m.npool >= m.pool_count_hdr, (
            f"mesh {m.offset:#x}: npool {m.npool} < count_hdr "
            f"{m.pool_count_hdr}")


def test_mesh0_stride17_row_mask(data):
    m = read_dff(data)[0]
    assert m.kind == "pos"
    assert m.pool_count_hdr == 225 and m.npool == 329
    words = struct.unpack_from(f"<{m.pool_words}f", data, m.pool_off)
    assert len(words) == 3918
    pool = decode_float_pool(words, 17)
    assert (pool.n_full, pool.n_partial, pool.n_sentinel_rows) == (150, 2, 78)
    assert len(pool.tail) == 8
    assert pool.sentinel_words == 1352
    assert pool.real_words == 2566
    assert len(set(m.indices)) == 224
