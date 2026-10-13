"""Focused tests for gbox.doapp_inventory (Dead Or Alive ++ / Tecmo TPS).

Self-contained: synthetic zips only, no SMB/network access.
"""

import hashlib
import json
import os
import tempfile
import zipfile

import pytest

from gbox.doapp_inventory import (
    BANKED_ROMS,
    ROSTER,
    SCEI_LICENSE,
    find_roster,
    inventory,
    merge_banked,
    tim_count,
    verify_rom_sha1,
)


def _make_zip(path, members):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    return path


@pytest.fixture
def src_dir(tmp_path):
    """Synthetic clone/parent/bios zips with the right member NAMES.

    Content is fake, so the dat-sha1 verification is expected to fail;
    that failure path is itself asserted.
    """
    d = tmp_path / "roms"
    d.mkdir()
    _make_zip(
        str(d / "doappk.zip"),
        {"doapp_u0119.119": b"\x11" * 0x100, "doapp_u0120.120": b"\x22" * 0x100},
    )
    parent = {"doapp-0.216": b"\x33" * 0x100}
    for name in ("doapp-1.217", "doapp-2.218", "doapp-3.219",
                 "doapp-4.220", "doapp-5.221"):
        parent[name] = b"\x00" * 0x40
    parent.update({"doapp119.bin": b"\x44" * 0x100,
                   "doapp120.bin": b"\x55" * 0x100, "mg05": b"\x00" * 8})
    _make_zip(str(d / "doapp.zip"), parent)
    _make_zip(
        str(d / "coh1002m.zip"),
        {"m534002c-61.ic353": b"\x66" * 0x100, "mg01.ic652": b"\x00" * 8},
    )
    return str(d)


def test_merge_banked_interleave(src_dir):
    merged = merge_banked(src_dir + "/doappk.zip", src_dir + "/doapp.zip")
    assert len(merged) == 0x2800000
    # 119 = odd bytes, 120 = even bytes (ROM_LOAD16_BYTE +1/+0)
    assert merged[0] == 0x22 and merged[1] == 0x11
    assert merged[0x400000] == 0x33  # doapp-0.216 at 0x400000
    assert SCEI_LICENSE not in merged  # synthetic data has no license string


def test_merge_banked_layout_offsets(src_dir):
    merged = merge_banked(src_dir + "/doappk.zip", src_dir + "/doapp.zip")
    for name, (off, size, _) in BANKED_ROMS.items():
        if name.startswith("doapp_u0"):
            continue  # interleaved pair, checked in test above
        blob = merged[off:off + 0x40]
        assert len(blob) == 0x40


def test_find_roster_finds_ordered_table():
    data = bytearray(0x1000)
    names = b"....".join(n.encode() for n in ROSTER)
    data[0x333:0x333 + len(names)] = names
    hits = find_roster(bytes(data))
    assert 0x333 in {o for o, _ in hits}
    assert 0x123 not in {o for o, _ in hits}


def test_find_roster_rejects_shuffled_order():
    data = b"".join(n.encode() + b".." for n in reversed(ROSTER))
    assert find_roster(data) == []


def test_verify_rom_sha1_reports_mismatch(tmp_path):
    p = _make_zip(str(tmp_path / "r.zip"), {"m": b"data"})
    problems = verify_rom_sha1(p, {"m": "00" * 40, "absent": "00" * 40})
    assert any("m: expected" in x for x in problems)
    assert any("absent: missing" in x for x in problems)


def test_verify_rom_sha1_passes_match(tmp_path):
    data = b"data"
    p = _make_zip(str(tmp_path / "r.zip"), {"m": data})
    assert verify_rom_sha1(p, {"m": hashlib.sha1(data).hexdigest()}) == []


def test_tim_count():
    assert tim_count(b"\x10\x00\x00\x00" * 3 + b"\x10\x01\x00\x00") == 3


def test_inventory_manifest_structure(src_dir, tmp_path):
    out = str(tmp_path / "manifest.json")
    m = inventory(src_dir, out)
    assert m["game_id"] == "59c55e95af61abbe"
    assert m["mame_set"] == "doappk" and m["clone_of"] == "doapp"
    assert m["bios_set"] == "coh1002m"
    assert m["platform"]["driver"] == "zn2p"
    assert m["characters"]["roster"] == ROSTER
    assert m["container"]["bankedroms_size"] == 0x2800000
    assert m["sources"]["clone_zip"]["sha256"]
    # synthetic ROM contents must fail the dat check loudly, not silently
    flat = " ".join(json.dumps(m["rom_verification"]).split())
    assert "expected" in flat
    assert json.load(open(out))["launch"]["mame_set"] == "doappk"


def test_inventory_requires_all_zips(tmp_path):
    with pytest.raises(FileNotFoundError):
        inventory(str(tmp_path))


# ------------------------------------------------------------------------------------------ Japan parent (doapp)
import struct  # noqa: E402

from gbox import doapp_inventory as D  # noqa: E402

OWNED = os.environ.get("GBOX_DOAPP_ROMS", "")
needs_roms = pytest.mark.skipif(not (OWNED and os.path.isfile(os.path.join(OWNED, "doapp.zip"))),
                                reason="set GBOX_DOAPP_ROMS to the directory with doapp.zip + coh1002m.zip")


def test_jp_identity_and_table_shape():
    assert D.GAME_IDS[D.GAME_ID_JP] == "doapp" and D.GAME_IDS[D.GAME_ID] == "doappk"
    assert len(D.FILE_TABLE) == D.FILE_COUNT == 280
    assert D.FILE_TABLE[0] == (0, 0xA0000, 0x90930)          # the plain overlay right after the encoded program
    for bank, off, size in D.FILE_TABLE:
        assert 0 <= bank <= 3 and off + size <= D.BANK_SIZE
        assert bank * D.BANK_SIZE + off + size <= 0x1C00000  # inside the six data ROMs + program


def test_jp_fighters_cover_roster_with_distinct_costume_files():
    names = {f["name"].replace(" ", "-") for f in D.FIGHTERS}
    assert names == set(ROSTER)
    seen = set()
    for f in D.FIGHTERS:
        assert len(f["models"]) == D.COSTUMES
        assert D.FILE_TABLE[f["hidden_costume_file"]][2] == 0  # slot 4 is a zero-size table entry
        for m in f["models"]:
            assert D.FILE_TABLE[m][2] > 0x10000 and m not in seen
            seen.add(m)
    assert seen == set(range(49, 103)) - {53, 58, 63, 68, 73, 78, 83, 88, 93, 98}
    assert D.fighter("lei-fang")["id"] == 12 and D.fighter("jannlee")["name"] == "JANN LEE"
    assert D.fighter(13)["name"] == "AYANE"
    with pytest.raises(KeyError):
        D.fighter("ryu")


def test_merge_parent_interleaves_program_and_places_banks(tmp_path):
    members = {"doapp119.bin": b"\x11" * 16, "doapp120.bin": b"\x22" * 16}
    for i, n in enumerate(D.DATA_BANKS):
        members[n] = bytes([0x30 + i]) * 8
    p = _make_zip(str(tmp_path / "doapp.zip"), members)
    m = D.merge_parent(p)
    assert len(m) == 0x1C00000 and m[:4] == b"\x22\x11\x22\x11"
    assert m[0x400000] == 0x30 and m[0x1800000] == 0x35


def _ram_with(table, fighters):
    ram = bytearray(0x200000)
    base = D.FILE_TABLE_RAM & 0x1FFFFF
    for i, rec in enumerate(table):
        struct.pack_into("<III", ram, base + 12 * i, *rec)
    for f in fighters:
        for c, m in enumerate(f["models"] + [f["hidden_costume_file"]]):
            struct.pack_into("<H", ram, (D.MODEL_TABLE_RAM & 0x1FFFFF) + 4 * (f["id"] * D.COSTUME_SLOTS + c), m)
        for key, addr in D.CHAR_TABLES.items():
            struct.pack_into("<H", ram, (addr & 0x1FFFFF) + 2 * f["id"], f[key])
    return bytes(ram)


def test_tables_read_back_from_a_program_image():
    ram = _ram_with(D.FILE_TABLE, D.FIGHTERS)
    assert D.file_table_from_ram(ram) == D.FILE_TABLE
    assert D.fighters_from_ram(ram) == [dict(f) for f in D.FIGHTERS]


def test_file_table_from_ram_rejects_out_of_range_records():
    bad = list(D.FILE_TABLE)
    bad[7] = (5, 0, 0x10)
    with pytest.raises(ValueError):
        D.file_table_from_ram(_ram_with(bad, []))
    with pytest.raises(ValueError):
        D.file_table_from_ram(b"\0" * 100)


def test_file_span_read_and_room():
    start, size = D.file_span(49)
    assert (start, size) == (0x800000, 0x1BAB4)
    banked = bytes(0x1C00000)
    assert len(D.read_file(banked, 49)) == size
    assert D.file_room(49) == size                          # model files are packed back to back
    assert D.file_room(94) > D.FILE_TABLE[94][2]            # Bass C1 ends before the 0x400000 ROM boundary
    with pytest.raises(IndexError):
        D.file_span(280)
    with pytest.raises(ValueError):
        D.read_file(b"\0" * 0x10, 49)


def test_cli_doapp_manifest(tmp_path, capsys):
    members = {"doapp119.bin": b"\0" * 16, "doapp120.bin": b"\0" * 16, "mg05": b"\0" * 8}
    for n in D.DATA_BANKS:
        members[n] = b"\0" * 16
    _make_zip(str(tmp_path / "doapp.zip"), members)
    _make_zip(str(tmp_path / "coh1002m.zip"), {"m534002c-61.ic353": b"\0", "mg01.ic652": b"\0" * 8})
    out = tmp_path / "m.json"
    assert D.main([str(tmp_path), "--out", str(out)]) == 0
    m = json.load(open(out))
    assert m["game_id"] == "a19b4e641b155364" and m["program"]["known"] is False
    assert len(m["files"]) == 280 and m["rom_verification"]          # synthetic zips fail the dat check loudly
    assert m["fighters"][0]["model_sizes"][0] == D.FILE_TABLE[59][2]
    assert '"files": 280' in capsys.readouterr().out


@needs_roms
def test_owned_roms_decode_to_the_snapshot():
    banked, ram, entry = D.decode_owned(OWNED)
    assert entry == D.ENTRY_POINT
    assert hashlib.sha1(banked[:0x200000]).hexdigest() == D.PROGRAM_SHA1["doapp"]
    assert D.file_table_from_ram(ram) == D.FILE_TABLE
    assert D.fighters_from_ram(ram) == [dict(f) for f in D.FIGHTERS]
    model = D.read_file(banked, D.fighter("tina")["models"][0])
    assert struct.unpack_from("<I", model)[0] < len(model) and model[struct.unpack_from("<I", model)[0]] == 0x10
