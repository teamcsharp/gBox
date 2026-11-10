import os
import pytest
from gbox.mercs.titles import re4_switch_blasts as B

MAIN = os.path.expanduser("~/gBox_alt/switch/work/re4-nsp/main.bin")


def test_table_shape():
    assert B.BLASTS["flash"]["area_class"] == 0x17 and B.BLASTS["grenade"]["area_class"] == 0x13
    assert B.BLASTS["flash"]["radius"] > B.BLASTS["grenade"]["radius"]


@pytest.mark.skipif(not os.path.exists(MAIN), reason="main.bin not available")
def test_anchors_match_main_bin():
    assert B.verify(open(MAIN, "rb").read()) == []
