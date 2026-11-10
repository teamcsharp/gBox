import os
import struct

import pytest

from gbox import mkda_ssf as S

ISO = "/home/ehm_eckx/gBox_alt/gbox-cache/modbase/cebc0be06b2ec8c7/Mortal Kombat - Deadly Alliance (USA).iso"


def _sec(records, total):
    b = b"SEC " + struct.pack(">5I", 4, 0, 0x7e, len(records), total)
    for r in records:
        b += struct.pack(">3I", *r)
    return b.ljust(total, b"\0")


def test_synthetic_nested():
    child = _sec([(7, 0x40, 4)], 0x44)
    top = _sec([(6, 0x30, len(child))], 0x30 + len(child))
    top = top[:0x30] + child
    c = S.census(top)
    assert c["sections"] == 2 and c["by_type"] == {6: 1, 7: 1}


def test_bad_magic_and_range():
    with pytest.raises(S.SSFError):
        S.parse_section(b"XXXX" + b"\0" * 32)
    with pytest.raises(S.SSFError):
        S.parse_section(_sec([(6, 0x100, 0x100)], 0x40))


@pytest.mark.skipif(not os.path.exists(ISO), reason="owned disc not present")
def test_scorpion_on_owned_disc():
    from gbox.gcdisc import GCDisc
    b = GCDisc(ISO).read("artgc/scorpion.ssf")
    top = S.parse_section(b)
    assert top["count"] == 15 and top["total"] == len(b) == 2355200
    assert [r["type"] for r in top["records"]][:4] == [6, 6, 6, 7]
    assert S.census(b)["sections"] == 300
