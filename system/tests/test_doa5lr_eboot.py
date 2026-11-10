import os
import struct
import pytest
from gbox import doa5lr_eboot as eb

ELF = os.environ.get(
    "DOA5LR_EBOOT_ELF",
    "/home/ehm_eckx/gBox_alt/gbox-cache/research/doa5lr_samples_2450/eboot/EBOOT.elf")
ELF_SHA = "7747903ecdda5b686658654bcfbcd4590815f6416220e24ef458338ca446533c"


def _synthetic():
    hdr = bytearray(0x40)
    hdr[:6] = b"\x7fELF\x02\x02"
    struct.pack_into(">H", hdr, 18, 0x15)
    struct.pack_into(">Q", hdr, 0x20, 0x40)
    struct.pack_into(">HH", hdr, 0x36, 56, 1)
    ph = struct.pack(">IIQQQQQQ", 1, 5, 0x100, 0x10000, 0, 0x30, 0x30, 0x10000)
    body = bytearray(0x100 - 0x40 - 56) + b"..chara_rtm.lnk\0LFMO"
    return bytes(hdr) + ph + bytes(body)


def test_synthetic_probe():
    d = _synthetic()
    info = eb.probe_elf(d)
    assert info["machine"] == 0x15 and info["segments"][0]["type"] == 1
    a = eb.find_anchors(d)
    assert len(a["chara_rtm.lnk"]) == 1 and len(a["LFMO"]) == 1
    assert eb.file_offset_to_vaddr(info, 0x100) == 0x10000


def test_reject_non_elf():
    with pytest.raises(ValueError):
        eb.probe_elf(b"SCE\0" + bytes(100))


@pytest.mark.skipif(not os.path.exists(ELF), reason="owned decrypted EBOOT absent")
def test_real_eboot():
    assert eb.sha256(ELF) == ELF_SHA
    d = open(ELF, "rb").read()
    info = eb.probe_elf(d)
    assert info["machine"] == 0x15
    loads = [s for s in info["segments"] if s["type"] == 1 and s["filesz"]]
    assert [hex(s["vaddr"]) for s in loads] == ["0x10000", "0x1350000"]
    a = eb.find_anchors(d)
    assert a["chara_common.bin"], a
    assert a["LFMO"] == [0x11a77f4]
    assert eb.file_offset_to_vaddr(info, 0x11a77f4) == 0x11a77f4 + 0x10000
