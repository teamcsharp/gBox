import struct
import pytest
from gbox import s3k_analysis as an, s3k_inventory as inv

def test_find_xrefs_and_disasm_synthetic():
    d = bytes(8) + bytes.fromhex("45f90014a08a") + bytes(4)
    assert an.find_xrefs(d, 0x14A08A) == [10]
    ins = an.disasm(d, 8, 6)
    assert ins[0]["text"] == "lea.l $14a08a.l, a2"
    assert an.instr_at_xref(d, 10)["addr"] == 8

@pytest.mark.skipif(not inv.DEFAULT_SRC.exists(), reason="owned ROM not mounted")
def test_tails_loader_facts_from_owned_rom():
    a = an.analyse()
    assert a["source_sha256"] == "fba0677fde9f76df93f3e98d6310d8af68b9847bde16e253d73cd4dd8134ed23"
    txt = [i["text"] for i in a["loader_disasm"]]
    assert "lea.l $14a08a.l, a2" in txt and "move.l #$3200e0, d6" in txt
    assert "cmpi.w #$1a2, d0" in txt and "move.l #$143d00, d6" in txt
    assert a["bank_switch_frame"] == 0x1A2 // 2 and a["dplc_frames"] == 251
    assert a["max_tiles_per_frame"] == 24
