import hashlib
import io
import struct

import pytest

from gbox import cso, re4ps2_inventory as inv
from gbox.romexport import iso_files


def _payload(n):
    out = bytearray()
    for i in range(n):
        out += (b"%08d" % i) * 3 + bytes([i % 251]) * 5
    return bytes(out)


@pytest.mark.parametrize("block,shift,plain", [(2048, 0, 0), (16384, 2, 3), (2048, 2, 1)])
def test_cso_random_reads_match_plain(tmp_path, block, shift, plain):
    data = _payload(5000)                          # ~145 KB, last block partial
    p = cso.write_cso(data, tmp_path / "x.cso", block=block, shift=shift, plain_every=plain)
    c = cso.CSO(p)
    assert c.size == len(data) and c.info["block"] == block and c.info["shift"] == shift
    for off, n in [(0, 10), (block - 3, 9), (len(data) - 7, 100), (3 * block + 5, 2 * block + 11), (len(data), 4)]:
        c.seek(off)
        assert c.read(n) == data[off:off + n]
    c.seek(-5, 2)
    assert c.read() == data[-5:]
    assert io.BufferedReader(cso.CSO(p)).read() == data


def test_to_iso_hashes_source_and_image(tmp_path):
    data = _payload(3000)
    p = cso.write_cso(data, tmp_path / "x.cso", block=2048, shift=2, plain_every=4)
    r = cso.to_iso(p, tmp_path / "x.iso")
    assert (tmp_path / "x.iso").read_bytes() == data
    assert r["iso_sha256"] == hashlib.sha256(data).hexdigest()
    assert r["source_sha256"] == hashlib.sha256(p.read_bytes()).hexdigest()
    assert not (tmp_path / "x.iso.part").exists()


def test_cso_rejects_zso_and_garbage(tmp_path):
    (tmp_path / "z.cso").write_bytes(b"ZISO" + b"\0" * 40)
    with pytest.raises(cso.CSOError, match="LZ4"):
        cso.CSO(tmp_path / "z.cso")
    (tmp_path / "g.cso").write_bytes(b"\0" * 64)
    with pytest.raises(cso.CSOError):
        cso.CSO(tmp_path / "g.cso")


# --- a tiny ISO9660 laid out like the RE4 PS2 disc -----------------------------------------------------------------

def _rec(name: bytes, lba: int, size: int, d=False) -> bytes:
    n = 33 + len(name)
    n += n & 1
    r = bytearray(n)
    r[0] = n
    struct.pack_into("<I", r, 2, lba)
    struct.pack_into(">I", r, 6, lba)
    struct.pack_into("<I", r, 10, size)
    struct.pack_into(">I", r, 14, size)
    r[25] = 2 if d else 0
    r[32] = len(name)
    r[33:33 + len(name)] = name
    return bytes(r)


def _dat(exts):
    n = len(exts)
    head = 16 + 8 * n
    head += -head % 32
    body, offs = bytearray(), []
    for e in exts:
        offs.append(head + len(body) if e else 0)
        if e:
            body += e.encode().ljust(32, b"\xcd")
    return (struct.pack("<I12x", n) + struct.pack(f"<{n}I", *offs)
            + b"".join(e.encode().ljust(4, b"\0") for e in exts)).ljust(head, b"\0") + bytes(body)


def _afs(files):
    n = len(files)
    head = 8 + 8 * n + 8
    pos = (head + 2047) // 2048 * 2048
    ent, blob = [], bytearray()
    for _nm, data in files:
        ent.append((pos + len(blob), len(data)))
        blob += data + b"\0" * (-len(data) % 2048)
    dpos = pos + len(blob)
    names = b"".join(nm.encode().ljust(32, b"\0") + struct.pack("<6HI", 2005, 9, 1, 0, 0, 0, 0xDEAD) for nm, _ in files)
    h = b"AFS\0" + struct.pack("<I", n) + b"".join(struct.pack("<II", *e) for e in ent) + struct.pack("<II", dpos, len(names))
    return h.ljust(pos, b"\0") + bytes(blob) + names


def _iso(tmp_path):
    elf = bytearray(b"\x7fELF\x01\x01\x01" + b"\0" * 9)
    elf += struct.pack("<HH", 2, 8) + b"\0" * 64
    cnf = b"BOOT2 = cdrom0:\\SLUS_211.34;1\r\nVER = 1.01\r\nVMODE = NTSC\r\n"
    afs = _afs([("pl00.snd", b"\xca\xb6\xbe\x20" * 8), ("pl00.dat", _dat(["BIN", "TPL", "", "SEQ", "FCV", "FCV"])),
                ("pl00.dat", b""), ("pl10.snd", b"\xca\xb6\xbe\x20" * 8), ("pl10.dat", _dat(["BIN", "TPL"])),
                ("pl10.dat", b""), ("pl10.rel", b"SNR2" + b"\0" * 60), ("em13low.dat", _dat(["BIN"])),
                ("r100.dat", b"not a pack")])
    files = {"SYSTEM.CNF": cnf, "SLUS_211.34": bytes(elf), "AFS": afs}
    lba = {"SYSTEM.CNF": 24, "SLUS_211.34": 25, "AFS": 27}
    root = _rec(b"\0", 20, 2048, True) + _rec(b"\1", 20, 2048, True) + _rec(b"DATA", 21, 2048, True) \
        + _rec(b"SLUS_211.34;1", 25, len(elf)) + _rec(b"SYSTEM.CNF;1", 24, len(cnf))
    data = _rec(b"\0", 21, 2048, True) + _rec(b"\1", 20, 2048, True) + _rec(b"BIO4DAT.AFS;1", 27, len(afs))
    img = bytearray(27 * 2048 + len(afs) + 2048)
    pvd = bytearray(2048)
    pvd[0:6] = b"\x01CD001"
    pvd[156:190] = _rec(b"\0", 20, 2048, True)[:34]
    pvd[813:829] = b"2005092113000000"
    img[16 * 2048:17 * 2048] = pvd
    img[20 * 2048:20 * 2048 + len(root)] = root
    img[21 * 2048:21 * 2048 + len(data)] = data
    for k, v in files.items():
        img[lba[k] * 2048:lba[k] * 2048 + len(v)] = v
    p = tmp_path / "re4.iso"
    p.write_bytes(bytes(img))
    return p


def test_inventory_on_iso_and_cso_agree(tmp_path):
    iso = _iso(tmp_path)
    with open(iso, "rb") as f:
        assert "DATA/BIO4DAT.AFS" in iso_files(f)
    a = inv.inventory(iso, "ab" * 32)
    c = cso.write_cso(iso.read_bytes(), tmp_path / "re4.cso", block=16384, shift=2)
    b = inv.inventory(c)
    assert a["system_cnf"]["boot_file"] == "SLUS_211.34" and a["system_cnf"]["VER"] == "1.01"
    assert a["volume_date"] == "2005092113000000"
    assert a["afs"]["entries"] == 9 and a["afs"]["nonempty"] == 7
    ids = [(x["id"], x["variant"]) for x in a["characters"]]
    assert ids == [("pl00", ""), ("pl10", ""), ("em13", "low")]
    pl00, pl10 = a["characters"][0], a["characters"][1]
    assert pl00["sections"] == {"BIN": 1, "TPL": 1, "SEQ": 1, "FCV": 2} and pl00["slots"] == 6
    assert pl00["snd_index"] == 0 and pl00["rel_index"] is None and pl00["label"].startswith("Leon")
    assert pl00["unknown"] is False
    assert pl10["rel_index"] == 6 and pl10["rel_name"] == "pl10.rel" and pl10["label"] is None
    assert pl10["unknown"] is True
    assert a["player_ids"] == ["pl00", "pl10"] and a["enemy_ids"] == ["em13"]
    for k in ("characters", "afs", "boot_elf", "system_cnf"):
        assert a[k] == b[k]
    assert b["container"] == "cso" and a["source_sha256"] == "ab" * 32


def test_dat_sections_rejects_non_packs():
    assert inv.dat_sections(b"not a pack at all") is None
    assert inv.dat_sections(_dat(["BIN", "", "TPL"])) [1] == (0, "")
