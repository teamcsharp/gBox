from gbox import raidou2_king_mode_research as k


def test_pinned_evidence():
    assert k.STATUS == "pending_research"
    assert len(k.BOOT_ELF_SHA256) == 64 and len(k.ISO_SHA256) == 64
    fake = bytearray(b"x" * 0x500000)
    off = 0x455750 - k.VADDR_DELTA
    fake[off:off + 22] = b"King Mode difficulty.\0"
    assert k.string_at(bytes(fake), 0x455750) == "King Mode difficulty."
    assert not k.verify_boot_elf(b"nope")
