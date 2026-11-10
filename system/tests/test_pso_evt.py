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
    data = make((16 + 20, 0x10, 1, 0), [(0x6F, 0, 1, 0xB, 1, 50, 0)])
    assert EV.build(EV.header(data), EV.records(data), EV.script(data)) == data
    h = EV.header(data)
    assert h == {"a": 16 + 20, "b": 0x10, "c": 1, "d": 0}
    recs = EV.records(data)
    assert len(recs) == 1
    r = recs[0]
    assert (r["id"], r["page"], r["opcode"], r["arg"], r["value"], r["offset"]) == (0x6F, 1, 0xB, 1, 50, 0)


def test_the_last_word_stepping_by_six_is_visible_in_the_parse():
    data = make((16 + 40, 2, 2, 0), [(0x457, 0, 1, 0xB, 2, 50, 6), (0x458, 0, 1, 0xB, 3, 50, 12)])
    assert [r["offset"] for r in EV.records(data)] == [6, 12]


def test_a_trailing_partial_record_is_ignored_not_guessed():
    # the tail is the script, not a record: it is returned as-is even when it is not a multiple of 20
    data = make((16 + 20, 0, 1, 0), [(1, 0, 0, 0xB, 0, 0, 0)]) + b"\x01\x02\x03"
    assert len(EV.records(data)) == 1
    assert EV.script(data) == b"\x01\x02\x03"
    assert EV.summary(data)["script_bytes"] == 3


def test_a_short_file_is_refused_with_its_size():
    with pytest.raises(EV.EventError, match="smaller than the 16-byte header"):
        EV.header(b"\x00\x01\x02")


def test_the_summary_reports_ids_and_opcodes():
    data = make((16 + 40, 0x10, 2, 0), [(0x10, 0, 1, 0xB, 1, 50, 0), (0x11, 0, 1, 0xB, 2, 50, 6)])
    s = EV.summary(data)
    assert s["records"] == 2 and s["opcodes"] == {0xB: 2}
    assert (s["first_id"], s["id_min"], s["id_max"], s["consecutive_pairs"]) == (0x10, 0x10, 0x11, 1)


@pytest.mark.skipif(not DISC.is_file(), reason="the disc is not on this machine")
def test_the_real_event_table_matches_the_corrected_framing():
    """16-byte header + `count` 20-byte records + the script blob - corrected in CP6.

    The old reading here was "24 records + a 4-byte footer" for this file. That tail is **not** records: decoded as
    records its ids are 284,428, 1,477,181,696 and so on, while the real records carry ids around 0x6f. The header's own
    size word (396) equals 16 + 20 * 19 and does so in **147 of 147** event files, so the count in the header is what
    bounds the table, and the 104 bytes after it are the script.
    """
    from gbox import gcdisc, pso_map_write as W

    d = gcdisc.GCDisc(str(DISC))
    data, _where = W.read_set(d, "map_forest01_00.evt")
    s = EV.summary(data)
    assert s["header"] == {"a": 396, "b": 16, "c": 19, "d": 0}
    assert (s["records"], s["script_bytes"]) == (19, 104)
    assert s["first_id"] == 0x6F
    group = [r for r in EV.records(data) if r["opcode"] == 0x0B]
    assert [r["arg"] for r in group] == [1, 2, 3, 4]
    assert [r["offset"] for r in group] == [0, 6, 12, 18]
    assert [r["value"] for r in group] == [50, 50, 50, 50]
    assert EV.build(EV.header(data), EV.records(data), EV.script(data)) == data


@pytest.mark.skipif(not DISC.is_file(), reason="the disc is not on this machine")
def test_every_event_file_on_the_disc_round_trips_with_this_framing():
    """All of them: the count bounds the table, the script follows it, and the rebuild is byte-identical.

    This is also where the state of the *city* is recorded: there is no city event script at all. The event archive holds
    143 files covering 28 field and boss areas, and none for Pioneer 2 - so no placement or script on the disc is what
    carries a party from the city to a floor.
    """
    from gbox import gcdisc, pso_map_write as W

    d = gcdisc.GCDisc(str(DISC))
    entries = sorted(W.set_archive_files(d, "event"))
    assert len(entries) == 143
    assert not [e for e in entries if "city" in e or "lobby" in e or "pioneer" in e]
    bad, scripts = [], 0
    for name in entries:
        data, _ = W.read_set(d, name)
        try:
            h, recs, sc = EV.header(data), EV.records(data), EV.script(data)
            if len(recs) != h["c"] or EV.build(h, recs, sc) != data:
                bad.append((name, "count or rebuild mismatch"))
            scripts += len(sc)
        except Exception as exc:                       # noqa: BLE001
            bad.append((name, str(exc)[:60]))
    assert bad == [], bad[:4]
    assert scripts > 20000


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


# ---- CP6.1: the record count is in the file, and the script is not records ---------------------------------------------------

def test_the_record_count_comes_from_the_header_not_from_the_file_length():
    """The bug CP6 found: 138 of 147 files had records fabricated out of the script's bytes."""
    body = (struct.pack("<IHHHHII", 1, 0, 0, 3, 0, 0, 0)
            + struct.pack("<IHHHHII", 2, 0, 0, 3, 0, 0, 0))
    script = bytes(range(8))
    data = struct.pack("<4I", 16 + len(body), 0x10, 2, 0) + body + script
    assert EV.table_end(data) == 16 + len(body)
    assert EV.script(data) == script
    assert len(EV.records(data)) == 2
    assert EV.build(EV.header(data), EV.records(data), EV.script(data)) == data


def test_a_count_that_disagrees_with_the_size_field_is_refused():
    data = struct.pack("<4I", 16 + 20 * 3, 0x10, 2, 0) + bytes(20 * 2)
    with pytest.raises(EV.EventError, match="size field"):
        EV.table_end(data)


def test_every_event_file_on_the_disc_round_trips_byte_identically():
    import pathlib as _p
    from gbox import gcdisc, pso_map_write as W
    disc = _p.Path(r"D:\gBox\cache\mods\436e0bb84d5337d1\pso_city_npc_moved"
                   r"\Phantasy Star Online Episode I & II Plus (USA).iso")
    if not disc.is_file():
        pytest.skip("the disc is not on this machine")
    d = gcdisc.GCDisc(str(disc))
    checked = scripts = 0
    for name, (path, off, size) in W.set_archive_files(d, "event").items():
        data = d.read(path)[off:off + size]
        h, recs, sc = EV.header(data), EV.records(data), EV.script(data)
        assert len(recs) == h["c"], name
        assert EV.build(h, recs, sc) == data, name
        scripts += len(sc)
        checked += 1
    assert checked >= 143 and scripts > 20000
