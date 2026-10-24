import hashlib, os, struct
from pathlib import Path

import pytest

from gbox import madden2005_terf as t

GCZ = Path(os.environ.get("GBOX_MADDEN2005_GCZ", "/mnt/gbox/hyperspin/Arcade/collections/Nintendo GameCube/roms/Madden NFL 2005 (USA).gcz"))
DOL_SHA = "06d962171ca5db73db1dc6b6e209faf85231540d7ac43d43655efd8567860cb5"


def _synthetic(entries, dir_off=0x40):
    count = len(entries)
    dsz = (16 + 8 * count + 63) & ~63
    body = bytearray()
    ds = []
    for payload in entries:
        ds.append((len(body), len(payload)))
        body += payload + b"\0" * (-len(payload) % 0x80)
    hdr = bytearray(dir_off)
    hdr[:4] = b"TERF"; hdr[4:8] = struct.pack(">I", dir_off); hdr[8:12] = bytes([2, 2, 1, 6])
    hdr[12:14] = struct.pack(">H", dir_off); hdr[14:16] = struct.pack(">H", count)
    d = bytearray(b"DIR1" + struct.pack(">III", dsz, 64, 0))
    for o, s in ds:
        d += struct.pack(">II", o, s)
    d += b"\0" * (dsz - len(d))
    return bytes(hdr + d + body)


def test_synthetic_roundtrip():
    buf = _synthetic([b"MMAPxxxx", b"", b"FAC\0yy"])
    idx = t.parse_terf(buf)
    assert idx.count == 3 and idx.members[1].size == 0
    assert t.member_bytes(buf, idx, 0) == b"MMAPxxxx" and t.member_bytes(buf, idx, 2) == b"FAC\0yy"


def test_rejects_bad_archives():
    with pytest.raises(ValueError):
        t.parse_terf(b"QL01" + b"\0" * 100)
    buf = bytearray(_synthetic([b"abcd"]))
    buf[0x40 + 16 + 4:0x40 + 16 + 8] = struct.pack(">I", 1 << 28)
    with pytest.raises(ValueError):
        t.parse_terf(bytes(buf))


def test_lis_addi_and_ori_resolution():
    # lis r3,0x5445 ; addi r3,r3,0x5246 ; lis r4,0x8052 ; addi r4,r4,-0x4588
    words = [0x3C605445, 0x38635246, 0x3C808052, 0x3884BA78]
    code = b"".join(struct.pack(">I", w) for w in words) + b"\x4e\x80\x00\x20"
    dol = bytearray(0x100) + code
    struct.pack_into(">I", dol, 0, 0x100); struct.pack_into(">I", dol, 0x48, 0x80003100); struct.pack_into(">I", dol, 0x90, len(code))
    r = t.find_lis_refs(bytes(dol), {0x54455246, t.FILENAME_TABLE_VA})
    assert r[0x54455246] == [0x80003100] and r[t.FILENAME_TABLE_VA] == [0x80003108]


@pytest.fixture(scope="module")
def disc():
    if not GCZ.exists():
        pytest.skip("owned Madden NFL 2005 GCZ not available")
    from gbox.gcdisc import GCDisc
    d = GCDisc(str(GCZ))
    assert d.game_id == "GNQE69"
    return d


def test_owned_dol_loader_xrefs_and_filename_table(disc):
    dol = disc.dol()
    assert hashlib.sha256(dol).hexdigest() == DOL_SHA
    x = t.loader_xrefs(dol)
    funcs = {r["function"] for k in ("TERF", "DIR1") for r in x[k]}
    # functions that build both the 'TERF' and 'DIR1' magics = archive index readers
    both = {r["function"] for r in x["TERF"]} & {r["function"] for r in x["DIR1"]}
    assert {"0x8040d098", "0x8040e558", "0x8040eaec", "0x804121e0"} <= both <= funcs
    assert x["filename_table"], "no code references the .dat filename table"
    names = t.filename_table(dol)
    on_disc = {n.lower() for n in disc.files if n.lower().endswith((".dat", ".qkl", ".db"))}
    # exact table-vs-disc delta: the table lists one name that is not shipped; fe.qkl is loaded via a separate string
    assert len(names) == 60
    assert set(names) - on_disc == {"uis_lib_soundlib.dat"}
    assert on_disc - set(names) == {"fe.qkl"}


@pytest.mark.parametrize("name,count,live", [("PLADATA.DAT", 435, 434), ("PLYRFACE.DAT", 436, 435),
                                              ("ANIMDATA.DAT", 710, 707), ("FACEGEOM.DAT", 21, 20)])
def test_owned_character_archives_parse(disc, name, count, live):
    buf = disc.read(name)
    idx = t.parse_terf(buf)
    assert idx.count == count and sum(1 for m in idx.members if m.size) == live
    heads = {t.member_bytes(buf, idx, m.index)[:4] for m in idx.members[:50] if m.size}
    if name == "PLYRFACE.DAT":
        assert heads == {b"MMAP"}
    if name == "FACEGEOM.DAT":
        assert heads == {b"FAC\0"}
