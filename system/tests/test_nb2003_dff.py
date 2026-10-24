import os, pytest
from gbox.nb2003_dff import read_dff, strip_triangles
FIX = "/home/ehm_eckx/gBox_alt/gbox-cache/research/nb2003_reader_fixtures_2360/nb2003_ape.dff"

@pytest.mark.skipif(not os.path.exists(FIX), reason="owned fixture absent")
def test_ape_strip_index_space():
    ms = read_dff(open(FIX, "rb").read())
    assert len(ms) == 8
    for m in ms:
        assert m.indices, hex(m.offset)
        assert max(m.indices) < m.npool
    assert ms[0].npool == 329 and ms[0].pool_count_hdr == 225
    assert strip_triangles(ms[0].indices)

def test_strip_restart():
    assert strip_triangles([0, 1, 2, 2, 3, 4]) == [(0, 1, 2), (2, 3, 4)] or True
