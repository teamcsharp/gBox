import json
import struct

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
    assert len(d3.ROSTER) == len(set(d3.ROSTER)) == 16
    assert "Ein" in d3.ROSTER and "Lei Fang" not in d3.ROSTER


# --------------------------------------------------------------------------- cxbx_unlock_plan


def _game():
    return {"game_id": d3.GAME_ID, "platform": "xbox", "title": "Dead or Alive 3 (USA)"}


def _worker(name="i9-NUC", wid="w-nuc"):
    return {"id": wid, "name": name, "status": "idle"}


def test_cxbx_plan_rejects_wrong_game():
    r = d3.cxbx_unlock_plan({"game_id": "abcdef0123456789", "platform": "xbox"}, _worker())
    assert r["status"] == "unsupported_game" and r["jobs"] == []


def test_cxbx_plan_rejects_wrong_platform():
    r = d3.cxbx_unlock_plan({"game_id": d3.GAME_ID, "platform": "ps2"}, _worker())
    assert r["status"] == "unsupported_game" and r["jobs"] == []


def test_cxbx_plan_rejects_operator_play_pc():
    r = d3.cxbx_unlock_plan(_game(), _worker(name="JAYBUILTFINALE", wid="w-jay"),
                            session_id="s1", save_root="/saves", allow_save_upgrade=True)
    assert r["status"] == "wrong_worker" and r["jobs"] == []
    assert "Never target the operator play PC" in r["reason"]


def test_cxbx_plan_requires_save_upgrade_opt_in():
    r = d3.cxbx_unlock_plan(_game(), _worker(), session_id="s1", save_root="/saves")
    assert r["status"] == "save_upgrade_opt_in_required" and r["jobs"] == []


def test_cxbx_plan_requires_save_root():
    r = d3.cxbx_unlock_plan(_game(), _worker(), session_id="s1", allow_save_upgrade=True)
    assert r["status"] == "save_root_required" and r["jobs"] == []


def test_cxbx_plan_requires_session():
    r = d3.cxbx_unlock_plan(_game(), _worker(), save_root="/saves", allow_save_upgrade=True)
    assert r["status"] == "session_required" and r["jobs"] == []


def test_cxbx_plan_emits_three_jobs_when_all_gates_pass():
    r = d3.cxbx_unlock_plan(_game(), _worker(), session_id="sess-1",
                            save_root="/saves/UDATA", allow_save_upgrade=True)
    assert r["status"] == "planned" and r["profile"] == d3.DOA3_UNLOCK_PROFILE
    assert r["executed"] is False
    ops = [j["input"]["op"] for j in r["jobs"]]
    assert ops == ["backup_save", "unlock_all", "verify_unlock"]
    assert all(j["require_worker"] == "w-nuc" and j["agent_use"] is True for j in r["jobs"])
    assert all(j["input"]["title_id"] == d3.DOA3_TITLE_ID for j in r["jobs"])
    assert all(j["input"]["save_root"] == "/saves/UDATA" for j in r["jobs"])
    assert r["jobs"][1]["input"]["chars"] == list(d3.ROSTER)
    assert r["roster"] == list(d3.ROSTER)


def test_cxbx_plan_accepts_spark_deux_worker():
    r = d3.cxbx_unlock_plan(_game(), _worker(name="sparkDeux", wid="w-spark"),
                            session_id="s", save_root="/saves", allow_save_upgrade=True)
    assert r["status"] == "planned"


def test_cxbx_plan_is_read_only():
    r = d3.cxbx_unlock_plan(_game(), _worker(), session_id="s",
                            save_root="/saves", allow_save_upgrade=True)
    assert r["executed"] is False
    for job in r["jobs"]:
        assert "dispatch" not in job and "run" not in job
