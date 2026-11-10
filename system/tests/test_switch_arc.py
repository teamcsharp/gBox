"""gbox.switch_arc: the RE6 `ARC` header/entry-table parse and the donor-vs-game comparison, on synthetic data."""
import struct

import pytest

from gbox import switch_arc as A


def arc(entries, version=7, path="data\\chara\\pl\\pl0000\\model\\pl0003"):
    blob = bytearray(A.MAGIC + struct.pack("<HH", version, 5))
    blob += path.encode()[:A.PATH_SIZE].ljust(A.PATH_SIZE, b"\x00")
    for hash_, flags, offset, size, entry_path in entries:
        blob += struct.pack("<4I", hash_, flags, offset, size)
        blob += entry_path.encode()[:A.PATH_SIZE].ljust(A.PATH_SIZE, b"\x00")
    return bytes(blob)


def test_parse_reads_the_table():
    blob = arc([(0x2749C8A8, 0x7F, 0x400002B0, 0x8000, "data\\chara\\pl\\pl0000\\model\\pl0003"),
                (0x58A1A856, 0x7F, 0x400026B4, 0x807F, "data\\chara\\pl\\pl0000\\model\\pl0004")])
    parsed = A.parse(blob)
    assert parsed["version"] == 7
    assert parsed["path"].startswith("data\\chara")
    assert [e["path"].rsplit("\\", 1)[-1] for e in parsed["entries"]] == ["pl0003", "pl0004"]
    assert parsed["entries"][0]["words"][3] == 0x8000


def test_compare_flags_smaller_donor_resources():
    game = arc([(1, 0x7F, 0x40000010, 0x1000, "a"), (2, 0x7F, 0x40001010, 0x2000, "b")])
    donor = arc([(1, 0x7F, 0x40000010, 0x0400, "a"), (2, 0x7F, 0x40000410, 0x0800, "b")])
    out = A.compare(game, donor)
    assert out["same_paths"] is True and out["game_entries"] == 2
    assert [r["ratio"] for r in out["sizes"]] == [0.25, 0.25]
    assert out["worst_ratio"] == 0.25


def test_compare_reports_different_paths():
    game = arc([(1, 0x7F, 0x10, 0x100, "a")])
    donor = arc([(1, 0x7F, 0x10, 0x100, "other")])
    out = A.compare(game, donor)
    assert out["same_paths"] is False


def test_a_non_arc_blob_is_refused():
    with pytest.raises(ValueError, match="not an ARC"):
        A.parse(b"NOPE" + bytes(0x60))
    with pytest.raises(ValueError, match="not an ARC"):
        A.parse(b"ARC\x00")
