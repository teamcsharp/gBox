"""gbox.pso_evt: the `.evt` event table's first-pass structure, checked against the disc."""
import struct
from pathlib import Path

import pytest

from gbox import pso_evt as EV

DISC = Path(r"D:\gBox\cache\436e0bb84d5337d1\Phantasy Star Online Episode I & II Plus (USA).gcz")


def make(header_words, recs):
    out = struct.pack("<4I", *header_words)
    for rid, flags, page, opcode, arg, value, offset in recs:
        out += struct.pack("<IHHHHII", rid, flags, page, opcode, arg, value, offset)
    return out


def test_a_header_and_records_round_trip():
    data = make((0x18C, 0x10, 0x13, 0), [(0x6F, 0, 1, 0xB, 1, 50, 0)])
    h = EV.header(data)
    assert h == {"a": 0x18C, "b": 0x10, "c": 0x13, "d": 0}
    recs = EV.records(data)
    assert len(recs) == 1
    r = recs[0]
    assert (r["id"], r["page"], r["opcode"], r["arg"], r["value"], r["offset"]) == (0x6F, 1, 0xB, 1, 50, 0)


def test_the_last_word_stepping_by_six_is_visible_in_the_parse():
    data = make((1, 2, 3, 0), [(0x457, 0, 1, 0xB, 2, 50, 6), (0x458, 0, 1, 0xB, 3, 50, 12)])
    assert [r["offset"] for r in EV.records(data)] == [6, 12]


def test_a_trailing_partial_record_is_ignored_not_guessed():
    data = make((0, 0, 0, 0), [(1, 0, 0, 0xB, 0, 0, 0)]) + b"\x01\x02\x03"
    assert len(EV.records(data)) == 1
    assert EV.summary(data)["trailing_bytes"] == 3


def test_a_short_file_is_refused_with_its_size():
    with pytest.raises(EV.EventError, match="smaller than the 16-byte header"):
        EV.header(b"\x00\x01\x02")


def test_the_summary_reports_ids_and_opcodes():
    data = make((0x18C, 0x10, 2, 0), [(0x10, 0, 1, 0xB, 1, 50, 0), (0x11, 0, 1, 0xB, 2, 50, 6)])
    s = EV.summary(data)
    assert s["records"] == 2 and s["opcodes"] == {0xB: 2}
    assert (s["first_id"], s["id_min"], s["id_max"], s["consecutive_pairs"]) == (0x10, 0x10, 0x11, 1)


@pytest.mark.skipif(not DISC.is_file(), reason="the disc is not on this machine")
def test_the_real_event_table_matches_the_measured_framing():
    """16-byte header + 20-byte records + a 4-byte footer, records in groups sharing an opcode.

    The figures here are the ones measured from the file, not ones chosen to make the parser look right: header
    (396, 16, 19, 0), 24 records, 4 trailing bytes, first id 0x6f, and a four-record group at opcode 0x0b whose arguments
    are 1..4 and whose trailing word steps 0, 6, 12, 18.
    """
    from gbox import gcdisc, pso_map_write as W

    d = gcdisc.GCDisc(str(DISC))
    data, _where = W.read_set(d, "map_forest01_00.evt")
    s = EV.summary(data)
    assert s["header"] == {"a": 396, "b": 16, "c": 19, "d": 0}
    assert (s["records"], s["trailing_bytes"]) == (24, 4)
    assert s["first_id"] == 0x6F
    group = [r for r in EV.records(data) if r["opcode"] == 0x0B]
    assert [r["arg"] for r in group] == [1, 2, 3, 4]
    assert [r["offset"] for r in group] == [0, 6, 12, 18]
    assert [r["value"] for r in group] == [50, 50, 50, 50]


@pytest.mark.skipif(not DISC.is_file(), reason="the disc is not on this machine")
def test_every_event_file_on_the_disc_parses_with_this_framing():
    """All of them, not a sample: if the 16 + n*20 + 4 framing is right, every file should frame cleanly.

    This is also where the state of the *city* is recorded: there is no city event script at all. The event archive holds
    143 files covering 28 field and boss areas, and none for Pioneer 2 -- so no placement or script on the disc is what
    carries a party from the city to a floor.
    """
    from gbox import gcdisc, pso_map_write as W

    d = gcdisc.GCDisc(str(DISC))
    entries = sorted(W.set_archive_files(d, "event"))
    assert len(entries) == 143
    assert not [e for e in entries if "city" in e or "lobby" in e or "pioneer" in e]
    bad = []
    for name in entries:
        data, _ = W.read_set(d, name)
        try:
            recs = EV.records(data)
        except Exception as exc:                       # noqa: BLE001
            bad.append((name, str(exc)[:60]))
            continue
        if not recs or EV.summary(data)["trailing_bytes"] >= EV.RECORD_SIZE:
            bad.append((name, "no records or a whole trailing record"))
    assert bad == [], bad[:4]


@pytest.mark.skipif(not DISC.is_file(), reason="the disc is not on this machine")
def test_the_event_archive_covers_fields_and_bosses_only():
    from gbox import gcdisc, pso_map_write as W

    d = gcdisc.GCDisc(str(DISC))
    names = sorted(W.set_archive_files(d, "event"))
    areas = set()
    for name in names:
        stem = name.rsplit(".", 1)[0]                       # map_forest01_00_00 or map_boss01
        stem = stem[len("map_"):] if stem.startswith("map_") else stem
        areas.add(stem.split("_")[0])                       # forest01 / boss01
    for area in ("forest", "cave", "ruins", "jungle", "seabed", "machine", "space", "ancient"):
        assert any(a.startswith(area) for a in areas), f"{area} has no event script: {sorted(areas)}"
    assert any(a.startswith("boss") for a in areas)
