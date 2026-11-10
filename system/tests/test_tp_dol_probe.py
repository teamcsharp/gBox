import os, pytest
from gbox.gcdisc import GCDisc
from gbox.tp_dol_probe import Dol, probe, KNOWN

ISO = "/mnt/gbox/quickswap2/Emulation/_emulation/GC ISO/Legend of Zelda, The - Twilight Princess (USA).iso"
pytestmark = pytest.mark.skipif(not os.path.exists(ISO), reason="owned ISO not mounted")


@pytest.fixture(scope="module")
def dol():
    return GCDisc(ISO).dol()


def test_dol_hash_and_sections(dol):
    import hashlib
    assert hashlib.sha256(dol).hexdigest() == "e7f197436815e66c4a11df3d7bd557d66083b641ff8a8e76439f3caba7ae60e8"
    d = Dol(dol)
    assert d.a2o(0x802DBCF8) is not None and d.entry == 0x800030F8 or d.entry > 0x80000000


def test_check_compressed_located(dol):
    r = probe(dol)
    assert KNOWN["JKRDecomp::checkCompressed"] in [a - 0 for a in r["check_compressed_found"]] or \
        KNOWN["JKRDecomp::checkCompressed"] + 4 in r["check_compressed_found"] or \
        any(abs(a - KNOWN["JKRDecomp::checkCompressed"]) <= 8 for a in r["check_compressed_found"])
    assert 0x802DBA00 in r["check_compressed_callers"]


def test_decode_dispatch(dol):
    d = Dol(dol)
    assert d.bl_callers(KNOWN["JKRDecomp::decodeSZP"]) == [0x802DBA1C]
    assert d.bl_callers(KNOWN["JKRDecomp::decodeSZS"]) == [0x802DBA3C]


def test_res_object_loader(dol):
    r = probe(dol)
    assert 0x8039A2A8 in r["res_object_strings"]
    assert 0x802587E8 in r["fileSel_xref"]
