"""SmackDown! 2 (USA, PS1) inventory: DPAC directory kinds, boot files, CHD v5 header/track metadata, and (when the
cached owned image is present on this node) the real disc: serial, boot executable, roster and motion banks."""
import struct
from pathlib import Path

import pytest

from gbox import sd2_inventory as S
from gbox import yukes_sd as Y

BASE = Path.home() / "gbox-cache/modbase/276334ad218ffb46/WWF SmackDown! 2 - Know Your Role (USA).bin"
CHD = Path.home() / "gbox-cache/276334ad218ffb46/source.chd"


def _dpac(tag: bytes, words: bytes, n: int, bodies: list[bytes], flat: bool) -> bytes:
    b = bytearray(0x4000)
    b[:16] = b"DPAC" + struct.pack("<III", 8 + 4 * n, 0, 7)
    b[0x800:0x808] = tag + struct.pack("<HH", n | (0x8000 if flat else 0), 0)
    b[0x808:0x808 + len(words)] = words
    for body in bodies:
        b += body + bytes((-len(body)) % 0x800)
    return bytes(b)


def test_flat_table_counts_without_bit15_and_starts_at_0x808():
    recs = [(0, 2), (1, 0), (0x10, 3)]
    b = _dpac(b"EXE ", b"".join(struct.pack("<HH", *r) for r in recs), 3, [b"BPE " + bytes(0x1FC), b"X" * 0x300], True)
    t = S.dpac_table(b)
    assert (t["kind"], t["count"], t["tag"]) == ("flat", 3, "EXE ")
    assert [(e["id"], e["offset"], e["units"]) for e in t["entries"]] == [(0, 0x4000, 2), (0x10, 0x4800, 3)]
    assert t["valid"] and t["slack"] == 0x800 - 0x300
    # the writer's reader takes 0x8003 as the count and starts at 0x810: it does not see the same entries
    try:
        old = [e[0] for e in Y.dpac_entries(b)]
    except struct.error:                         # 32K records run past this small file
        old = None
    assert old != [0, 0x10]


def test_labelled_table_matches_the_writer_reader():
    words = b"0   " + struct.pack("<I", 0x91EC) + b"".join(struct.pack("<HH", *r) for r in [(0x000, 1), (0x001, 2), (0x460, 1)])
    b = _dpac(b"ED1H", words, 5, [b"PAC " + bytes(0xFC), b"PAC " + bytes(0x1FC), b"PAC " + bytes(0xFC)], False)
    t = S.dpac_table(b)
    assert t["kind"] == "labelled" and t["labels"] == [["0   ", 0x91EC]]
    got = [(e["id"], e["units"], e["offset"]) for e in t["entries"]]
    assert got == Y.dpac_entries(b) == [(0, 1, 0x4000), (1, 2, 0x4800), (0x460, 1, 0x5000)]
    assert t["valid"] and t["magics"] == {b"PAC ".hex(): 3}


def test_named_motion_table_uses_sector_indexes():
    words = b"CH0 " + struct.pack("<HH", 0, 8) + b"CH1 " + struct.pack("<HH", 1, 4)
    b = _dpac(b"MOT ", words, 4, [b"\xa8\x08" + bytes(0x7FE), b"\x11" * 0x400], False)
    t = S.dpac_table(b)
    assert t["kind"] == "named"
    assert [(e["name"], e["offset"], e["units"]) for e in t["entries"]] == [("CH0", 0x4000, 8), ("CH1", 0x4800, 4)]
    m = S.motions(b)
    assert [x["name"] for x in m] == ["CH0", "CH1"] and m[0]["bytes"] == 0x800 and m[0]["head"].startswith("a808")


def test_multi_directory_table_is_reported_not_guessed():
    b = bytearray(_dpac(b"FONT", b"Fdeb" + struct.pack("<HH", 0, 0x13), 4, [], False))
    b[4:8] = struct.pack("<I", 1732)            # table bytes != 8 + 4 * count: more than one top-level directory
    b[0x818:0x820] = b"2MEN" + struct.pack("<HH", 0x2B, 0x227)
    t = S.dpac_table(bytes(b))
    assert t["kind"] == "other" and t["valid"] is None and "2MEN" in t["top_tags"] and not t["entries"]


def test_system_cnf_and_psx_exe_header():
    cnf = S.system_cnf(b"BOOT = cdrom:\\SLUS_012.34;1\r\nTCB = 4\r\nEVENT = 10\r\nSTACK = 801fff00\r\n")
    assert cnf["boot_file"] == "SLUS_012.34" and cnf["STACK"] == "801fff00"
    exe = bytearray(0x800)
    exe[:8] = b"PS-X EXE"
    struct.pack_into("<4I", exe, 0x10, 0x80066AEC, 0, 0x80010000, 0x7C800)
    struct.pack_into("<I", exe, 0x30, 0x801FFFF0)
    lic = b"Sony Computer Entertainment Inc. for North America area"
    exe[0x4C:0x4C + len(lic)] = lic
    h = S.psx_exe(bytes(exe))
    assert (h["pc0"], h["t_addr"], h["t_size"], h["region"]) == ("0x80066aec", "0x80010000", 0x7C800, "NTSC-U")
    with pytest.raises(ValueError):
        S.psx_exe(b"\0" * 0x800)


def test_chd_v5_header_and_track_metadata(tmp_path):
    meta = b"TRACK:1 TYPE:MODE2_RAW SUBTYPE:NONE FRAMES:317290 PREGAP:0 PGTYPE:MODE1 PGSUB:RW POSTGAP:0\0"
    h = bytearray(124)
    h[:8] = b"MComprHD"
    struct.pack_into(">II", h, 8, 124, 5)
    h[16:28] = b"cdlzcdzlcdfl"
    struct.pack_into(">QQQII", h, 32, 776730816, 0, 124, 19584, 2448)
    h[64:84], h[84:104] = bytes.fromhex("5987af4054c58a0f0441b07c1a95be7812bac675"), b"\x01" * 20
    entry = b"CHT2" + bytes([1]) + len(meta).to_bytes(3, "big") + struct.pack(">Q", 0) + meta
    p = tmp_path / "x.chd"
    p.write_bytes(bytes(h) + entry)
    info = S.chd_info(p)
    assert info["version"] == 5 and info["compressors"] == ["cdlz", "cdzl", "cdfl"]
    assert (info["hunk_bytes"], info["unit_bytes"]) == (19584, 2448)
    assert info["raw_sha1"] == "5987af4054c58a0f0441b07c1a95be7812bac675"
    assert info["tracks"] == [{"TRACK": "1", "TYPE": "MODE2_RAW", "SUBTYPE": "NONE", "FRAMES": "317290", "PREGAP": "0",
                               "PGTYPE": "MODE1", "PGSUB": "RW", "POSTGAP": "0"}]
    assert len(info["sha256"]) == 64


@pytest.mark.skipif(not BASE.exists(), reason="owned SmackDown! 2 image not cached on this node")
def test_owned_disc_inventory():
    inv = S.inventory(BASE, CHD if CHD.exists() else None, hash_chd=False)
    d = inv["disc"]
    assert (d["system_id"], d["volume_id"], d["boot"]["file"]) == ("PLAYSTATION", "SLUS_01234", "SLUS_012.34")
    assert d["boot"]["sha256"] == "e23acb3165ed001b6d23558ef81624cea70b97d98e68a2a93546e6466a3c2a7f"
    assert d["boot"]["region"] == "NTSC-U" and len(d["files"]) == 75
    assert inv["source"]["image"]["sha256"] == "6ccf0206313181bf2aba8b24b7081f38fde63a7c10900c9f7e9b6a3d509645ba"
    if CHD.exists():
        c = inv["source"]["chd"]
        assert c["version"] == 5 and c["sha1"] == "0103cd69e424015b36fcf333545f445c0aa04e3c"
        assert inv["prerequisites"]["single_data_track"] is True and c["tracks"][0]["FRAMES"] == "317290"
    assert all(inv["dpac"][f]["kind"] == "labelled" and inv["dpac"][f]["valid"] for f in Y.PART_FILES)
    assert inv["dpac"]["EXE.PAC"]["kind"] == "flat" and inv["dpac"]["EXE.PAC"]["used_entries"] == 13
    ch = inv["characters"]
    assert ch["roster"] == 66 and ch["complete"] == 66
    assert {w["name"] for w in ch["wrestlers"]} == {n for _, n in Y.ROSTER_NAMES}
    rock = next(w for w in ch["wrestlers"] if w["name"] == "The Rock")
    assert rock["group"] == "0x0" and rock["parts"]["ED1B.PAC"]["emd"]["bones"] == 32
    assert [m["name"] for m in inv["motions"]] == ["CH0", "CH1", "CAS", "LAD", "CAGE", "2PLA", "WIN", "EDIT"]
