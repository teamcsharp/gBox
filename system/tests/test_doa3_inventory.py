import json
import struct
from pathlib import Path

import pytest

from gbox import doa3_inventory as d3


def make_xbe(key=d3.XBE_KEYS["retail"], tid=0x5443000D, name="Dead or Alive 3", region=1):
    base = 0x10000
    data = bytearray(0x1000)
    data[:4] = b"XBEH"
    struct.pack_into("<I", data, 0x104, base)
    struct.pack_into("<I", data, 0x108, 0x800)        # header size
    struct.pack_into("<I", data, 0x10C, 0x10000)      # image size
    struct.pack_into("<I", data, 0x118, base + 0x200)  # certificate
    struct.pack_into("<I", data, 0x11C, 1)            # sections
    struct.pack_into("<I", data, 0x120, base + 0x400)
    struct.pack_into("<I", data, 0x128, (base + 0x1000) ^ key[0])
    struct.pack_into("<I", data, 0x158, (base + 0x2000) ^ key[1])
    struct.pack_into("<I", data, 0x160, 1)
    struct.pack_into("<I", data, 0x164, base + 0x500)
    c = 0x200
    struct.pack_into("<III", data, c, 0x1D0, 0, tid)
    w = name.encode("utf-16-le")
    data[c + 0x0C:c + 0x0C + len(w)] = w
    struct.pack_into("<I", data, c + 0xA0, region)
    struct.pack_into("<I", data, c + 0xAC, 2)
    struct.pack_into("<6I", data, 0x400, 6, base + 0x1000, 0x100, 0x800, 0x100, base + 0x480)
    data[0x480:0x486] = b".text\x00"
    data[0x500:0x508] = b"XAPILIB\x00"
    struct.pack_into("<4H", data, 0x508, 1, 0, 4627, 0)
    return bytes(data)


def test_parse_xbe_retail_certificate():
    x = d3.parse_xbe(make_xbe())
    assert x["type"] == "retail"
    assert x["entry_point"] == "0x00011000"
    c = x["certificate"]
    assert c["title_id"] == "5443000D" and c["title_code"] == "TC-013"
    assert c["title_name"] == "Dead or Alive 3"
    assert c["regions"] == ["NA"] and c["version"] == 2
    assert x["sections"][0]["name"] == ".text" and x["sections"][0]["rsize"] == 0x100
    assert x["libraries"] == [{"name": "XAPILIB", "version": "1.0.4627", "flags": 0}]


def test_parse_xbe_debug_key_and_rejects():
    assert d3.parse_xbe(make_xbe(key=d3.XBE_KEYS["debug"]))["type"] == "debug"
    with pytest.raises(ValueError):
        d3.parse_xbe(b"MZ" + bytes(0x200))
    bad = bytearray(make_xbe())
    struct.pack_into("<I", bad, 0x128, 0x12345678)
    with pytest.raises(ValueError):
        d3.parse_xbe(bytes(bad))


def make_afs(payloads, names=None, align=0x800):
    n = len(payloads)
    head = 16 + 8 * n
    off = -(-head // align) * align
    table, body = [], bytearray()
    for p in payloads:
        table.append((off, len(p)))
        body += p + bytes(-(-len(p) // align) * align - len(p))
        off += -(-len(p) // align) * align
    out = bytearray(b"AFS\x00" + struct.pack("<I", n))
    for o, z in table:
        out += struct.pack("<II", o, z)
    nd_off = off
    out += struct.pack("<II", nd_off if names else 0, 48 * n if names else 0)
    out += bytes(table[0][0] - len(out)) + body
    if names:
        for nm, (o, z) in zip(names, table):
            r = nm.encode().ljust(32, b"\x00") + struct.pack("<6HI", 2001, 11, 15, 1, 2, 3, z)
            out += r
    return bytes(out)


def test_afs_table_names_rooms_and_sniff(tmp_path):
    pays = [b"XPR0" + bytes(60), b"\x01\x02\x03\x04" * 10, b""]
    p = tmp_path / "loadfile.afs"
    p.write_bytes(make_afs(pays, names=["KAS_C01.xpr", "KAS_C01.bin", "AYA_C01.bin"]))
    a = d3.read_afs(p)
    assert a["count"] == 3 and a["name_dir"] is not None
    e = a["entries"]
    assert [x["name"] for x in e] == ["KAS_C01.xpr", "KAS_C01.bin", "AYA_C01.bin"]
    assert e[0]["magic"] == "XPR0" and e[1]["magic"] == "hex:01020304" and e[2]["magic"] == "empty"
    assert e[0]["room"] == 0x800 and e[1]["room"] == 0x800
    assert e[0]["date"].startswith("2001-11-15")
    g = d3.fighter_groups(e)
    assert g == {"KAS": ["KAS_C01.bin", "KAS_C01.xpr"]}
    assert d3.fighter_groups(e, codes=["AYA"]) == {"AYA": ["AYA_C01.bin"]}


def test_afs_rejects_overlap_and_out_of_range():
    head = b"AFS\x00" + struct.pack("<I", 2) + struct.pack("<4I", 0x800, 0x100, 0x880, 0x10) + bytes(8)
    with pytest.raises(ValueError):
        d3.afs_table(head)
    head = b"AFS\x00" + struct.pack("<I", 1) + struct.pack("<2I", 0x800, 0x1000) + bytes(8)
    with pytest.raises(ValueError):
        d3.afs_table(head, archive_size=0x1000)
    with pytest.raises(ValueError):
        d3.afs_table(b"AFX\x00" + bytes(12))


def test_build_manifest(tmp_path):
    g = tmp_path / "Dead or Alive 3"
    g.mkdir()
    (g / "default.xbe").write_bytes(make_xbe())
    (g / "loadfile.afs").write_bytes(make_afs([b"XPR0" + bytes(12)] * 2, names=["TIN_A.xpr", "TIN_B.xpr"]))
    (g / "mv_tn.sfd").write_bytes(b"\x00\x00\x01\xba")
    m = d3.build(g, source_sha256="ab" * 32)
    assert m["actual_platform"] == "xbox" and m["catalog_platform"] == "windows_native"
    assert m["source"]["sha256"] == "ab" * 32
    assert {f["name"] for f in m["files"]} == {"default.xbe", "loadfile.afs", "mv_tn.sfd"}
    assert m["archives"]["loadfile.afs"]["magics"] == {"XPR0": 2}
    assert m["loadfile_code_groups"] == {"TIN": ["TIN_A.xpr", "TIN_B.xpr"]}
    assert m["movies"] == ["mv_tn.sfd"]
    json.dumps(m)
    with pytest.raises(FileNotFoundError):
        d3.build(tmp_path)


def xpr(total=0x4000, hsize=0x800, tag=b"MDL\x00"):
    return b"XPR0" + struct.pack("<IIII", total, hsize, 0x80000000, 0x100) + tag + bytes(0x40)


def test_xpr_header_mdl_tag_and_rejects():
    h = d3.xpr_header(xpr())
    assert h == {"total": 0x4000, "header_size": 0x800, "first_type": "80000000",
                 "first_size": 0x100, "first_tag": "MDL"}
    with pytest.raises(ValueError):
        d3.xpr_header(b"XPR1" + bytes(0x40))
    with pytest.raises(ValueError):
        d3.xpr_header(xpr(total=0x100, hsize=0x800))


def test_fighter_families_from_layout(tmp_path):
    names = ["comon.mot", "c_zack.mot", "dmy.bin", "zack.bin", "zack.mot", "m_zack.mot",
             "zac00.xpr", "zac00.cat", "dmy.bin", "zac01.xpr", "zac01.cat",
             "tengu.bin", "tengu.mot", "m_tengu.mot", "dmy.bin",
             "leifang.bin", "leifan.mot", "m_leifan.mot", "lei00.xpr", "lei00.cat", "lei01.xpr",
             "t_ay_km.mot", "stgTST.xpr", "sTST_dat.bin"]
    pays = []
    for n in names:
        pays.append(b"wwww" + bytes(12) if n == "dmy.bin" else xpr() if n.endswith(".xpr")
                    else b"\x88\x00\x00\x00" + bytes(60))
    g = tmp_path / "Dead or Alive 3"
    g.mkdir()
    (g / "default.xbe").write_bytes(make_xbe())
    (g / "loadfile.afs").write_bytes(make_afs(pays, names=names))
    m = d3.build(g, source_sha256="cd" * 32)
    fams = {f["nick"]: f for f in m["fighter_families"]}
    assert list(fams) == ["zack", "tengu", "leifang"]
    assert fams["zack"]["code"] == "zac" and fams["zack"]["complete_costumes"] == ["zac00", "zac01"]
    assert fams["zack"]["mot"] == ["zack.mot", "m_zack.mot"]
    assert fams["tengu"]["costumes"] == {} and fams["tengu"]["code"] is None
    assert fams["leifang"]["complete_costumes"] == ["lei00"]  # lei01 has no .cat
    assert fams["zack"]["costumes"]["zac00"]["xpr_header"]["first_tag"] == "MDL"
    assert m["counts"] == {"families": 3, "families_with_costumes": 2, "costumes": 3,
                           "xpr_with_mdl": 4}


def test_roster_has_no_duplicate_fighters():
    # 20 person slots: 17 playable + 2 bosses (Genra/Omega, Tengu) + 1 cameo (Chen).
    assert len(d3.NICKNAME_TO_CHARACTER) == 20
    assert len(d3.ROSTER) == len(set(d3.ROSTER)) == 20
    assert len(d3.PLAYABLE_ROSTER) == 17
    assert d3.CHARACTER_KIND == {"Genra": "boss", "Tengu": "boss", "Chen": "cameo"}
    assert "Ein" in d3.PLAYABLE_ROSTER and "Leon" in d3.PLAYABLE_ROSTER
    assert "Hayate" in d3.PLAYABLE_ROSTER and "Lei Fang" not in d3.ROSTER


def test_nickname_mapping_style_codenames():
    # DOA3 modding community BIN-file documentation (Free Step Dodge / TCRF): the style-codenamed
    # families map to specific fighters, NOT their obvious names.
    assert d3.NICKNAME_TO_CHARACTER["karate"] == "Ein"      # Ein is the 3-costume karateka
    assert d3.NICKNAME_TO_CHARACTER["koryu"] == "Hitomi"    # Hitomi's codename
    assert d3.NICKNAME_TO_CHARACTER["sambo"] == "Leon"      # Leon's codename; Bayman is "bayman"
    assert d3.NICKNAME_TO_CHARACTER["bayman"] == "Bayman"
    assert d3.NICKNAME_TO_CHARACTER["gokei"] == "Christie"
    assert d3.NICKNAME_TO_CHARACTER["hika"] == "Helena"
    assert d3.NICKNAME_TO_CHARACTER["ninja"] == "Hayate"
    assert d3.NICKNAME_TO_CHARACTER["suiken"] == "Brad Wong"
    assert d3.NICKNAME_TO_CHARACTER["bosnin"] == "Genra"
    assert d3.NICKNAME_TO_CHARACTER["tengu"] == "Tengu"
    assert d3.NICKNAME_TO_CHARACTER["chin"] == "Chen"
    # the direct-name families stay direct
    assert d3.NICKNAME_TO_CHARACTER["kasumi"] == "Kasumi"
    assert d3.NICKNAME_TO_CHARACTER["ryu"] == "Ryu Hayabusa"
    assert d3.NICKNAME_TO_CHARACTER["janlee"] == "Jann Lee"


def test_fighter_roster_joins_name_kind_and_costumes():
    fams = [
        {"nick": "kasumi", "code": "kas", "complete_costumes": ["kas00", "kas01"], "mot": ["kasumi.mot"]},
        {"nick": "tengu", "code": None, "complete_costumes": [], "mot": ["tengu.mot"]},
        {"nick": "chin", "code": "chi", "complete_costumes": ["chi00"], "mot": ["suiken.mot"]},
        {"nick": "mystery", "code": None, "complete_costumes": [], "mot": []},
    ]
    r = d3.fighter_roster(fams)
    assert [x["character"] for x in r] == ["Kasumi", "Tengu", "Chen", None]
    assert [x["kind"] for x in r] == ["playable", "boss", "cameo", "unknown"]
    assert [x["costumes"] for x in r] == [2, 0, 1, 0]


def test_xbe_voice_codes_ordered_and_deduped():
    blob = b"voice\\bn\\v_bn_en_ad24.adx\x00voice\\ni\\v_ni_en_ad69.adx\x00voice\\bn\\v_bn_en_ad23.adx\x00"
    assert d3.xbe_voice_codes(blob) == ["bn", "ni"]
    assert d3.xbe_voice_codes(b"none") == []


def test_xbe_motion_banks_ordered_and_deduped():
    blob = (b"PAD" + b"D:\\bin\\c_sambo.mot" + b"\x00" + b"D:\\bin\\c_gokei.mot" + b"\x00"
            + b"junk c_sambo.mot again" + b"\x00" + b"D:\\bin\\c_kasumi.mot" + b"\x00")
    assert d3.xbe_motion_banks(blob) == ["sambo", "gokei", "kasumi"]
    assert d3.xbe_motion_banks(b"no banks here") == []


def test_xbe_motion_banks_real_disc_order():
    # The owned DOA3 default.xbe lists every character motion bank in the game's internal
    # order; the martial-art nicknames (karate/ninja/koryu/suiken/gokei/sambo/bosnin/hika)
    # are how the select table names those fighters, and 'chin' reuses suiken.mot (absent).
    xbe = Path.home() / "gbox-cache/b8edf7040116f3aa/extract/Dead or Alive 3/default.xbe"
    if not xbe.is_file():
        pytest.skip("owned DOA3 default.xbe not present")
    banks = d3.xbe_motion_banks(xbe.read_bytes())
    assert banks == ["sambo", "gokei", "suiken", "bosnin", "tengu", "koryu", "ayane",
                     "leifan", "ninja", "bass", "bayman", "hika", "genfu", "kasumi", "ryu",
                     "karate", "janlee", "tina", "zack"]
    assert "chin" not in banks


def test_sonic_donors_distinct_and_pinned():
    # 14 distinct Sonic Adventure 1/2 characters; SA1+SA2 overlap (Sonic/Tails/Knuckles/
    # Amy/Tikal/Super Sonic) is one canonical entry each with both slugs. The collection is
    # verified: SA1 -> 8, SA2 -> 10 characters (vehicles cyclone/egg_walker excluded).
    names = [d["character"] for d in d3.SONIC_DONORS]
    assert len(names) == len(set(names)) == 14
    assert d3.SONIC_DONOR_GAMES == {"1a3f4cd416db9ffd": "sa1", "d95ed7ed1e40552a": "sa2"}
    by_name = {d["character"]: d for d in d3.SONIC_DONORS}
    assert by_name["Sonic"]["slugs"] == ["sa1_sonic", "sonic"]
    assert by_name["Shadow"]["slugs"] == ["sa2_shadow"]          # SA2 only
    assert by_name["Big the Cat"]["slugs"] == ["sa1_big"]        # SA1 only
    assert by_name["Amy Rose"]["slugs"] == ["sa1_amy", "sa2_amy_rose"]


def test_sonic_cast_assignment_exhausts_distinct_before_repeat():
    plan = d3.sonic_cast_assignment()
    rows = plan["assignment"]
    assert plan["donors_distinct"] == 14 and plan["slots"] == 20
    assert [r["slot_character"] for r in rows] == d3.ROSTER
    # first 14 slots use every distinct donor exactly once (no repeat before exhaustion)
    first14 = [r["donor"] for r in rows[:14]]
    assert len(set(first14)) == 14
    # counts stay within one: 6 donors twice, 8 once (14 donors over 20 slots)
    counts = list(plan["usage"].values())
    assert max(counts) - min(counts) <= 1 and set(counts) <= {1, 2}
    assert sum(counts) == 20 and len(plan["usage"]) == 14
    # boss/cameo slots carry their kind and a donor, never a blank
    kinds = {r["slot_character"]: r["kind"] for r in rows}
    assert kinds["Genra"] == "boss" and kinds["Tengu"] == "boss" and kinds["Chen"] == "cameo"
    assert all(r["donor"] and r["donor_slug"] for r in rows)


def test_sonic_cast_assignment_deterministic_and_custom():
    a = d3.sonic_cast_assignment()
    b = d3.sonic_cast_assignment()
    assert a == b
    small = d3.sonic_cast_assignment(roster={"kasumi": "Kasumi", "ayane": "Ayane", "ryu": "Ryu Hayabusa"},
                                     donors=[{"character": "Sonic", "slugs": ["sa1_sonic"]},
                                             {"character": "Shadow", "slugs": ["sa2_shadow"]}])
    assert [r["donor"] for r in small["assignment"]] == ["Sonic", "Shadow", "Sonic"]
    assert small["usage"] == {"Sonic": 2, "Shadow": 1}
    with pytest.raises(ValueError):
        d3.sonic_cast_assignment(roster={"kasumi": "Kasumi"}, donors=[])
