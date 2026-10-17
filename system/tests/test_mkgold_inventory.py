import struct

import pytest

from gbox import mkgold_inventory as mk


def _geo(records, blobs):
    """records [(flags, n)]; blobs {index: bytes} for the non-sprite records, laid out after the table in order."""
    table_end = 0x20 + 32 * len(records)
    table, body = bytearray(), bytearray()
    for i, (flags, n) in enumerate(records):
        at = 0x20 + 32 * i
        if flags & mk.SPRITE:
            table += struct.pack("<HH", flags, n) + b"\x90\x01\x00\x01" + bytes(24)    # inline sprite words
        else:
            table += struct.pack("<HHI", flags, n, table_end + len(body) - (at + 4)) + bytes(24)
            body += blobs[i]
    return mk.MAGIC + struct.pack("<II", table_end + len(body), len(records)) + bytes(20) + table + body


def _img(pages, count=None):
    body = b"".join(struct.pack("<HH", w, h) + bytes(28) + bytes(w * h * 2) for w, h in pages)
    return mk.MAGIC + struct.pack("<II", 0x20 + len(body), len(pages) if count is None else count) + bytes(20) + body


def test_geo_records_use_self_relative_offsets_and_skip_inline_sprites():
    d = _geo([(1, 25), (0x80, 0), (1, 7)], {0: b"a" * 48, 2: b"b" * 16})
    recs = mk.geo_records(d)
    assert [(r["flags"], r["n"]) for r in recs] == [(1, 25), (0x80, 0), (1, 7)]
    assert recs[0]["offset"] == 0x80 and recs[0]["bytes"] == 48
    assert "offset" not in recs[1]
    assert recs[2]["offset"] == 0xB0 and recs[2]["bytes"] == 16 and d[0xB0:0xC0] == b"b" * 16
    bad = bytearray(d)
    struct.pack_into("<I", bad, 0x24, 0x1000)                                    # points past the end
    with pytest.raises(ValueError, match="outside"):
        mk.geo_records(bytes(bad))
    with pytest.raises(ValueError, match="file size"):
        mk.geo_records(d + b"\0")
    with pytest.raises(ValueError, match="0.1v"):
        mk.geo_records(b"GBIX" + d[4:])


def test_img_pages_interleave_records_and_texels():
    pages = mk.img_pages(_img([(4, 2), (2, 2)]))
    assert [(p["width"], p["height"], p["offset"], p["bytes"]) for p in pages] == [(4, 2, 0x40, 16), (2, 2, 0x70, 8)]
    with pytest.raises(ValueError, match="left after 1"):
        mk.img_pages(_img([(4, 2), (2, 2)], count=1))
    with pytest.raises(ValueError, match="page 1: record past the end"):
        mk.img_pages(_img([(4, 2)], count=2))
    big = bytearray(_img([(4, 2)]))
    struct.pack_into("<HH", big, 0x20, 8, 8)                                     # claims 128 texel bytes, has 16
    with pytest.raises(ValueError, match="8x8 texels overrun"):
        mk.img_pages(bytes(big))


def _exe():
    """Synthetic 1ST_READ: string pool + the four tables inventory reads, at made-up offsets."""
    buf, at, pos = bytearray(0x1000), {}, 0x400

    def put(s):
        nonlocal pos
        at[s] = mk.KEY + pos
        buf[pos:pos + len(s)] = s.encode()
        pos = (pos + len(s) + 4) & ~3
        return at[s]

    def words(off, items):
        for i, s in enumerate(items):
            struct.pack_into("<I", buf, off + 4 * i, put(s) if s and s not in at else at.get(s, 0))

    words(0x100, ["scorpion", "raiden", "reiko", "noob saibot", "belokk", "NOVICE"])
    words(0x140, ["mvmidway.sfd", "mvbiosc.sfd", "mvbiora.sfd", "mvbions.sfd", None,
                  "mvendsc.sfd", None, "mvendns.sfd"])
    words(0x180, ["fx.kat", "menu.kat", "ch_scorp.kat", "ch_raid.kat", "ch_reiko.kat", "ch_noob.kat"])
    for i, (g, v) in enumerate([("sc_geo", 0x8FFFF), ("nns_geo", 0xAFFFF), ("cave_geo", 0x91000B)]):
        struct.pack_into("<5I", buf, 0x200 + 20 * i, put(g + ".geo"), put(g + ".img"), v, 0, 0)
    return bytes(buf)


def test_exe_tables_are_found_by_content():
    t = mk.exe_tables(_exe())
    assert t["roster"]["names"] == ["scorpion", "raiden", "reiko", "noob saibot", "belokk"]
    assert t["roster"]["addr"] == f"0x{mk.KEY + 0x100:08X}"
    assert t["sound_banks"]["names"][2:] == ["ch_scorp.kat", "ch_raid.kat", "ch_reiko.kat", "ch_noob.kat"]
    assert t["movies"]["entries"] == ["mvmidway.sfd", "mvbiosc.sfd", "mvbiora.sfd", "mvbions.sfd", None,
                                      "mvendsc.sfd", None, "mvendns.sfd"]
    geo = t["geo_table"]["entries"]
    assert [(e["geo"], e["img"], e["id"], e["slot"]) for e in geo] == [
        ("sc_geo.geo", "sc_geo.img", 8, 0xFFFF), ("nns_geo.geo", "nns_geo.img", 10, 0xFFFF),
        ("cave_geo.geo", "cave_geo.img", 0x91, 0xB)]
    attract, bio, end = mk.split_movies(t["movies"]["entries"])
    assert attract == ["mvmidway.sfd"] and bio == ["mvbiosc.sfd", "mvbiora.sfd", "mvbions.sfd", None]
    assert end == ["mvendsc.sfd", None, "mvendns.sfd", None]


def test_codes_come_from_bio_movies_and_noob_by_elimination():
    disc = {"SC_GEO.GEO", "SC_A_GEO.GEO", "RA_GEO.GEO", "RA_A_GEO.GEO", "NS_GEO.GEO", "NS_A_GEO.GEO",
            "NNS_GEO.GEO", "NNS_A_GE.GEO", "CAVE_GEO.GEO", "PED_GEO.GEO"}
    chars = mk.assign_codes(["scorpion", "raiden", "reiko", "noob saibot", "belokk"],
                            ["mvbiosc.sfd", "mvbiora.sfd", "mvbions.sfd", None],
                            ["ch_scorp.kat", "ch_raid.kat", "ch_reiko.kat", "ch_noob.kat"], disc)
    assert [c["code"] for c in chars] == ["sc", "ra", "ns", "nns", None]
    assert chars[3]["code_source"].startswith("elimination") and chars[2]["code_source"] == "bio movie table"
    assert chars[4]["sound_bank"] is None                         # belokk: cut, no assets


def test_8_3_stems_and_file_room():
    assert mk.stem("kl") == "KL_GEO" and mk.stem("nns", "a") == "NNS_A_GE" and mk.stem("sc", "fat2") == "SC_FAT2_"
    assert mk.stem("sc", "fat") == "SC_FAT_G" and mk.stem("kl", "vs") == "VS_KL_GE" and mk.stem("ki", "m") == "KI_M_GEO"
    room = mk.file_room({"A": (45000, 5000), "B": (45003, 10), "C": (218718, 4096)},
                        [(45000, 79393), (218718, 549150)])
    assert room["A"]["room"] == 3 * 2048 and room["B"]["room"] == (79393 - 45003) * 2048
    assert room["C"] == {"lba": 218718, "track": 218718, "room": (549150 - 218718) * 2048}


def test_ip_header():
    hdr = (b"SEGA SEGAKATANA " b"SEGA ENTERPRISES" b"2F0A GD-ROM1/1  " b" U      " b"0799A10 " b"T-9701N   "
           b"V1.006" b"19990909        " b"1ST_READ.BIN    " b"MIDWAY          " b"MORTAL KOMBAT GOLD").ljust(256)
    ip = mk.ip_info(hdr)
    assert (ip["product"], ip["version"], ip["date"], ip["area"]) == ("T-9701N", "V1.006", "19990909", "U")
    assert ip["boot"] == "1ST_READ.BIN" and ip["company"] == "MIDWAY" and ip["title"] == "MORTAL KOMBAT GOLD"


def test_12_byte_stub_is_an_empty_container_but_other_short_files_fail():
    stub = mk.MAGIC + struct.pack("<II", 12, 0)                    # VS_NS_GE.GEO/.IMG: Reiko has no versus art
    assert mk.geo_records(stub) == [] and mk.img_pages(stub) == []
    with pytest.raises(ValueError, match="short header"):
        mk.geo_records(mk.MAGIC + struct.pack("<II", 16, 1) + bytes(4))
