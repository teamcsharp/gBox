import io
import os
import struct

import pytest

from gbox import re2ps2_inventory as inv


def build_afs(items):
    n = len(items)
    hdr = 8 + 8 * n + 8
    pos = (hdr + 2047) // 2048 * 2048
    offs, body = [], b""
    for _, data in items:
        offs.append(pos + len(body))
        body += data + b"\0" * (-len(data) % 2048)
    doff = pos + len(body)
    names = b"".join(nm.encode().ljust(32, b"\0") + b"\0" * 12 + struct.pack("<I", len(d))
                     for nm, d in items)
    out = AFS = b"AFS\0" + struct.pack("<I", n)
    for o, (_, d) in zip(offs, items):
        out += struct.pack("<II", o, len(d))
    out += struct.pack("<II", doff, len(names))
    out = out.ljust(pos, b"\0") + body + names
    return out


ITEMS = [("pl00_tbl.bin", b"\0" * 16), ("pl00_pc_000.bin", b"\1" * 40), ("pl00_pc_001.bin", b"\1" * 8),
         ("E00_00.NBD", b"TEX\0" + b"\0" * 12), ("x.tm2", b"TIM2" + b"\0" * 4), ("w.wmd", b"\0" * 8)]


def test_read_afs_names_and_magic():
    ents = inv.read_afs(io.BytesIO(build_afs(ITEMS)))
    assert [e["name"] for e in ents] == [n for n, _ in ITEMS]
    assert ents[3]["magic"] == b"TEX\0" and ents[3]["offset"] % 2048 == 0
    assert ents[1]["size"] == 40


def test_nested_base_offset():
    inner = build_afs(ITEMS)
    outer = b"\xed" * 4096 + inner
    ents = inv.read_afs(io.BytesIO(outer), 4096)
    assert len(ents) == 6


def test_not_afs():
    with pytest.raises(inv.AfsError):
        inv.read_afs(io.BytesIO(b"\xed" * 64))


def test_classify_census_players():
    ents = inv.read_afs(io.BytesIO(build_afs(ITEMS)))
    c = inv.census(ents)
    assert c["kinds"]["texture_bank"] == 1 and c["kinds"]["player_chunk"] == 2
    p = inv.players(ents)
    assert p["re2ps2_pl00"]["chunks"] == 2 and p["re2ps2_pl00"]["chunk_bytes"] == 48
    assert p["re2ps2_pl00"]["table"]["size"] == 16


ISO = "/home/ehm_eckx/gBox_alt/gbox-cache/modbase/c27a7d09fdbb5eea/Resident Evil Outbreak (USA).iso"


@pytest.mark.skipif(not os.path.exists(ISO), reason="disc image not present")
def test_real_disc():
    r = inv.inventory(ISO)
    assert r["containers"]["NETBIO00.DAT"]["entries"] == 13
    rom = r["containers"]["NETBIO00.DAT"]["archives"][inv.ROMDATA]
    assert rom["entries"] == 1342 and rom["kinds"]["texture_bank"] == 510
    assert sorted(r["players"]) == [f"re2ps2_pl0{i}" for i in range(8)]
    assert r["players"]["re2ps2_pl00"]["chunks"] >= 20
