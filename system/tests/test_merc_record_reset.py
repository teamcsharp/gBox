"""reset_records: the saved high-score reset hook. Pure byte-edit tests (no emulator) + dispatch guards."""
import struct

import pytest

from gbox import merc_record_reset as mrr


def test_re6_clears_only_score_fields():
    """RE6 X360: zero every Mercenaries cell's played/rank/score/kills/combo and nothing else."""
    spec = mrr.RECORDS["0871eee3b68cdea3"]
    size = spec["records_off"] + spec["rec_count"] * spec["rec_stride"] + 0x100
    d = bytearray(size)
    struct.pack_into(">I", d, 0xBC, 0xFFFFFFFF)          # mUnlockFlag (must survive)
    struct.pack_into(">I", d, 0x974, 0x3FF)             # stage mask (must survive)
    for i in (5, 100, spec["rec_count"] - 1):           # scores in three cells, plus a costume byte to keep
        r = spec["records_off"] + i * spec["rec_stride"]
        d[r] = 1
        struct.pack_into(">I", d, r + 2, 123456)
        d[r + 8] = 7                                     # costume (offset 8, outside the 8-byte clear window)

    assert mrr.re6_count_records(d) == 3
    had = mrr.re6_clear_records(d)
    assert had == 3
    for i in (5, 100, spec["rec_count"] - 1):
        r = spec["records_off"] + i * spec["rec_stride"]
        assert struct.unpack_from(">I", d, r + 2)[0] == 0   # score wiped
        assert d[r] == 0                                    # played wiped
        assert d[r + 8] == 7                                # costume preserved
    assert struct.unpack_from(">I", d, 0xBC)[0] == 0xFFFFFFFF   # unlock flag preserved
    assert struct.unpack_from(">I", d, 0x974)[0] == 0x3FF       # stage mask preserved
    assert mrr.re6_count_records(d) == 0


def test_re5_zeros_records_keeps_reunion_open_and_checksummed_region():
    """RE5 Gold PS3: zero the Gold block records, re-open Reunion fully, never touch the checksummed region."""
    spec = mrr.RECORDS["e7ca89bbeb67360d"]
    lo, hi = spec["block"]
    d = bytearray(hi + 0x100)
    for i in range(0x10, 0x4BC0):                        # the checksummed region (0x10..0x4BBF): must survive verbatim
        d[i] = (i * 7) & 0xFF
    guarded = bytes(d[0x10:0x4BC0])
    struct.pack_into(">i", d, lo, 2)                     # old Reunion-open value
    struct.pack_into(">I", d, 0x5640, 0x3)              # partial stage mask
    struct.pack_into(">I", d, 0x565C, 0x4)             # default character mask
    struct.pack_into(">I", d, lo + 0x40, 16843009)     # a Reunion record (SS from a 0x01 fill)

    assert mrr.re5_clear_block(d) is True
    assert struct.unpack_from(">I", d, lo + 0x40)[0] == 0          # record wiped
    assert struct.unpack_from(">i", d, lo)[0] == 1                 # Reunion / Desperate Escape open
    assert struct.unpack_from(">I", d, 0x5640)[0] == 0xFF         # all stages open
    assert struct.unpack_from(">I", d, 0x565C)[0] == 0xFF        # all characters open
    assert bytes(d[0x10:0x4BC0]) == guarded                       # checksummed region untouched


def test_pending_title_refuses_reset():
    """RE4 Switch (priority) is not measured yet: reset refuses rather than guess a save offset."""
    with pytest.raises(mrr.Unsupported):
        mrr.run("270a15eb98dab4d7", "reset", cfg=None, adapter=None)
    st = mrr.run("270a15eb98dab4d7", "status", cfg=None, adapter=None)
    assert st["confirmed"] is False and st["resettable"] is False


def test_pso_has_no_resettable_records():
    st = mrr.run("436e0bb84d5337d1", "status", cfg=None, adapter=None)
    assert st["resettable"] is False
    with pytest.raises(mrr.Unsupported):
        mrr.run("436e0bb84d5337d1", "reset", cfg=None, adapter=None)


def test_unknown_game_id_refuses():
    with pytest.raises(mrr.Unsupported):
        mrr.run("deadbeefdeadbeef", "status", cfg=None, adapter=None)


def test_tool_is_registered():
    from gbox.registry import REGISTRY
    assert "reset_records" in REGISTRY
    assert "mod" in REGISTRY["reset_records"].capabilities
