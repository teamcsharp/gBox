"""Def Jam: Vendetta PS2 (SLUS_206.39) disc inventory: synthetic ELF tables + WRS slots, owned-ISO pins."""
import os
import struct
from pathlib import Path

import pytest

from gbox import defjam_inventory as I

ISO = Path(os.environ.get("GBOX_DEFJAM_PS2_ISO") or Path.home() / "gBox_alt/gbox-cache" / "deabd11481aa5a0c" / "source.iso")
VA = 0x100000


def _elf(body: bytes) -> bytes:
    """A one-segment little-endian ELF: file offset 0x1000 -> vaddr 0x100000."""
    h = bytearray(0x1000)
    h[:4] = b"\x7fELF"
    struct.pack_into("<I", h, 0x1C, 0x34)
    struct.pack_into("<HH", h, 0x2A, 0x20, 1)
    struct.pack_into("<6I", h, 0x34, 1, 0x1000, VA, VA, len(body), len(body))
    return bytes(h) + body


def test_file_table_found_by_content_including_short_tail():
    counts = [3, 5, 2, 7] * 5
    pairs, pos = [], 0
    for c in counts:
        pairs += [pos, c]
        pos += c
    elf = _elf(b"\0" * 0x40 + struct.pack(f"<{len(pairs)}I", *pairs) + struct.pack("<2I", 0x10, 0))
    assert I.file_table(elf, pos * 2048) == list(zip(pairs[::2], pairs[1::2]))
    assert len(I.file_table(elf, (pos + 1) * 2048)) == len(counts)
    with pytest.raises(I.FormatError):
        I.file_table(elf, (pos + 64) * 2048)


def test_wrestler_table_names_costumes_and_end():
    strings = b"BRIGGS\0\0" + b"6'1\"\0\0\0\0" + b"210lbs\0\0" + b"DMX\0\0\0\0\0"
    s = {"BRIGGS": VA, "h": VA + 8, "w": VA + 16, "DMX": VA + 24}
    recs = b"".join(struct.pack("<8I", s[n], s[n], s["h"], s["w"], k, k, k, idx)
                    for k, (n, idx) in enumerate([("BRIGGS", 198), ("BRIGGS", 199), ("DMX", 239)]))
    recs += struct.pack("<8I", 0x7FFFFFF0, 0, 0, 0, 0, 0, 0, 0)            # pointer outside the ELF ends the table
    body = strings + recs
    elf = _elf(body)
    t = I.wrestler_table(elf, VA + len(strings))
    assert [(r["name"], r["data_index"]) for r in t] == [("BRIGGS", 198), ("BRIGGS", 199), ("DMX", 239)]
    assert t[0]["height"] == "6'1\"" and t[0]["weight"] == "210lbs"


def test_fighter_names_count_costumes(monkeypatch):
    rows = [{"record": 0, "name": "BRIGGS", "short": "BRIGGS", "height": "", "weight": "", "ids": [0] * 3, "data_index": 198},
            {"record": 1, "name": "BRIGGS", "short": "BRIGGS", "height": "", "weight": "", "ids": [1] * 3, "data_index": 199},
            {"record": 2, "name": "LUDACRIS", "short": "LUDACRIS", "height": "", "weight": "", "ids": [2] * 3, "data_index": 238},
            {"record": 3, "name": "LUDACRIS", "short": "LUDACRIS", "height": "", "weight": "", "ids": [3] * 3, "data_index": 238},
            {"record": 4, "name": "Character A", "short": "", "height": "NO DATA", "weight": "", "ids": [0] * 3, "data_index": 0}]
    monkeypatch.setattr(I, "wrestler_table", lambda elf: rows)
    n = I.fighter_names(b"")
    assert sorted(n) == [198, 199, 238]
    assert (n[199]["costume"], n[199]["costumes"]) == (2, 2) and n[238]["records"] == [2, 3]


def _wrs(slots):
    out = bytearray(b"WRS " + b"\0" * 12 + b"\xff" * 4 * I.WRS_SLOTS)
    for i in sorted(slots):
        while len(out) % 16:
            out.append(0)
        struct.pack_into("<I", out, 0x10 + 4 * i, len(out) - (0x10 + 4 * i))
        out += slots[i]
    struct.pack_into("<I", out, 4, len(out))
    return bytes(out)


def test_wrs_slots_are_self_relative_named_and_bounded():
    b = _wrs({1: b"a" * 32, 3: b"b" * 48, 18: b"c" * 16})
    w = I.parse_wrs(b)
    assert w["slots"][1]["start"] == 0x90 and w["slots"][1]["end"] == w["slots"][3]["start"]
    assert [w["slots"][i]["name"] for i in (1, 3, 18)] == ["body", "face", "texture"]
    with pytest.raises(I.FormatError):
        I.parse_wrs(b"XXXX" + b[4:])
    bad = bytearray(b)
    struct.pack_into("<I", bad, 0x10 + 4, 0x10_0000)                          # slot 1 points past the container
    with pytest.raises(I.FormatError):
        I.parse_wrs(bytes(bad))


def test_iso_reader_walks_a_tiny_image(tmp_path):
    img = bytearray(2048 * 20)
    pvd = bytearray(2048)
    pvd[0], pvd[1:6] = 1, b"CD001"

    def rec(name: bytes, lba: int, size: int, flags: int) -> bytes:
        r = bytearray(33 + len(name) + (len(name) + 1) % 2)
        r[0] = len(r)
        struct.pack_into("<I", r, 2, lba)
        struct.pack_into("<I", r, 10, size)
        r[25], r[32] = flags, len(name)
        r[33:33 + len(name)] = name
        return bytes(r)
    root = rec(b"\0", 17, 2048, 2) + rec(b"\1", 17, 2048, 2) + rec(b"SYSTEM.CNF;1", 18, 5, 0)
    pvd[156:156 + 34] = rec(b"\0", 17, 2048, 2)
    img[16 * 2048:17 * 2048] = pvd
    img[17 * 2048:17 * 2048 + len(root)] = root
    img[18 * 2048:18 * 2048 + 5] = b"hello"
    p = tmp_path / "t.iso"
    p.write_bytes(img)
    iso = I.Iso(p)
    assert iso.files == {"SYSTEM.CNF": (18, 5)} and iso.read("system.cnf", 1, 3) == b"ell"
    with pytest.raises(I.FormatError):
        iso.read("SYSTEM.CNF", 3, 9)
    assert I.identify(iso)["exact_build"] is False


@pytest.mark.skipif(not ISO.exists(), reason="owned SLUS_206.39 ISO not staged")
def test_owned_iso_identity_kinds_and_names():
    disc = I.Iso(ISO)
    ident = I.identify(disc)
    assert ident["exact_build"] and ident["files"] == 293 and ident["elf_sha256"] == I.ELF_SHA256
    assert ident["wrestler_records"] == 63
    ents = I.entries(disc)
    kinds = [e["kind"] for e in ents]
    assert kinds[198:256] == ["fighter"] * 58 and kinds.count("fighter") == 58
    names = I.fighter_names(disc.read(I.SERIAL))
    assert len(names) == 58 and names[239]["name"] == "DMX" and names[198]["name"] == "BRIGGS"
    from gbox import defjam_models as M
    assert {i: n["name"] for i, n in names.items()} == M.NAMES
