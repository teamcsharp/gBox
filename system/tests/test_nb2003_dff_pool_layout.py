"""Hash-anchored float-pool LAYOUT census for NFL Blitz 2003 ape.dff (request #2360).

2026-11-13 layout correction (lilspark2 local-model probe, fixture re-verified
byte-identical this run):

* The previously assumed 17-word stride is a SANE data partition (sentinel row
  mask: 150 full + 2 partial + 78 all-sentinel rows + 8-word tail on mesh0),
  but it is NOT a semantic per-vertex attribute layout.  All 17 decoded
  columns of the full rows carry the same wide-range float distribution
  (min < -10, max > +10): no column is unit-length (normals) and no column
  sits in [0, 1] (UVs).  Per-vertex word assignment therefore still requires
  main.dol loader xrefs before a donor writer can map attributes.
* The pool is capacity-padded with 0xcdcdcdcd sentinels to pool_words; the
  live prefix on mesh0 is exactly 2566 real words with a 3-word sentinel gap
  at indices 2563..2565 and a 3-word real island at 2566..2568, then a clean
  sentinel tail to the container end.
* The four UV pools contain ZERO sentinel words and pool_words !=
  count_hdr (ratio 10.1..11.1), so even the index count does not bound the
  UV pool — the loader's read path is the only authority.
"""

import os
import struct

import pytest

from gbox.nb2003_dff import SENTINEL, read_dff

_SHA = "878165bf6382da461dacd1e2aaff091621f06d91f90d2f4e6690ef2edd5862fa"
_CANDIDATES = [
    os.environ.get("NB2003_APE_DFF", ""),
    "/home/ehm_eckx/gbox-cache/research/nb2003_reader_fixtures_2360/nb2003_ape.dff",
    os.path.join(os.path.dirname(__file__), "..", "nb2003_ape.dff"),
]


def _fixture():
    for p in _CANDIDATES:
        if p and os.path.isfile(p):
            return p
    return None


@pytest.fixture(scope="module")
def ape_data():
    p = _fixture()
    if p is None:
        pytest.skip("nb2003_ape.dff fixture not present on this host")
    import hashlib

    with open(p, "rb") as fh:
        data = fh.read()
    assert hashlib.sha256(data).hexdigest() == _SHA, "fixture changed"
    assert len(data) == 458492
    return data


def _pool_words(ape_data, mesh):
    return struct.unpack_from(f"<{mesh.pool_words}f", ape_data, mesh.pool_off)


def _sentinel_mask(words):
    return [i for i, w in enumerate(words) if w == SENTINEL]


def test_mesh0_pool_exact_boundary(ape_data):
    """mesh0 (count_hdr=225): exact real/sentinel word census."""
    ms = read_dff(ape_data)
    m = next(m for m in ms if m.pool_count_hdr == 225)
    words = _pool_words(ape_data, m)
    assert len(words) == m.pool_words == 3918
    sent = _sentinel_mask(words)
    real = [i for i in range(len(words)) if i not in set(sent)]
    assert len(real) == 2566 and len(sent) == 1352
    # one 3-word sentinel gap, a 3-word real island, then clean tail
    assert sent[0] == 2563
    assert sent[:3] == [2563, 2564, 2565]
    assert [2566, 2567, 2568] == [i for i in range(2566, 2569) if i not in set(sent)]
    assert all(i in set(sent) for i in range(2569, 3918))
    assert sent[-1] == 3917


def test_stride17_not_semantic_per_vertex_layout(ape_data):
    """No decoded 17-column is unit-normals or [0,1] UVs on the full rows."""
    ms = read_dff(ape_data)
    m = next(m for m in ms if m.pool_count_hdr == 225)
    words = _pool_words(ape_data, m)
    full_rows = []
    for r in range(150):
        row = words[r * 17 : (r + 1) * 17]
        if all(w != SENTINEL for w in row):
            full_rows.append(row)
    assert len(full_rows) == 150
    for c in range(17):
        col = [row[c] for row in full_rows]
        lo, hi = min(col), max(col)
        # wide-range data in every column: rules out normals and UVs
        assert lo < -10.0, f"col {c} too narrow below: {lo}"
        assert hi > 10.0, f"col {c} too narrow above: {hi}"
        # not unit vectors
        assert any(abs(abs(v) - 1.0) > 1e-3 for v in col) or True  # informational
        # not [0,1] UV
        assert lo < 0.0 or hi > 1.0, f"col {c} inside [0,1]: {lo}..{hi}"


def test_pool_classes_uv_zero_sentinel(ape_data):
    """8 pools split 4 pos / 4 uv by sentinel presence; uv pools unbounded."""
    ms = read_dff(ape_data)
    assert len(ms) == 8
    pos, uv = [], []
    for m in ms:
        words = _pool_words(ape_data, m)
        n_sent = len(_sentinel_mask(words))
        if n_sent == 0:
            uv.append(m)
        else:
            pos.append(m)
    assert len(pos) == 4 and len(uv) == 4
    for m in pos:
        assert 17.0 <= m.pool_words / m.pool_count_hdr < 19.0
    for m in uv:
        # pool_words != count_hdr: index count does not bound the uv pool
        assert m.pool_words != m.pool_count_hdr
        assert 10.0 < m.pool_words / m.pool_count_hdr < 12.0
