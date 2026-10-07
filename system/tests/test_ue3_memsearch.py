from gbox import ue3
from gbox.tools import _finds


def test_ue3_roundtrip():
    ue3._selftest()


def test_aligned_value_search():
    b = b"\x00\x00\x00\x01" + b"\xff\x00\x00\x00" + b"\x01\xff\xff\xff" + b"\x00\x00\x00\x01"
    assert list(_finds(b, b"\x00\x00\x00\x01", 4)) == [0, 12]       # the unaligned hit at offset 5 is skipped
