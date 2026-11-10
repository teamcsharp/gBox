import struct
import pytest

pytest.importorskip("cryptography")
from gbox.formats import nca, cpk
from gbox.formats.dat_platinum import parse_dat

HK = bytes(range(32))


def _plain_header():
    h = bytearray(nca.HEADER_SIZE)
    h[0x200:0x204] = b"NCA3"
    h[0x205] = 0
    h[0x206] = 4
    h[0x207] = 0
    struct.pack_into("<QQ", h, 0x208, 0x2000, 0x01007960049A0000)
    h[0x220] = 4
    struct.pack_into("<II", h, 0x240, 6, 8)        # section 0: 0xC00..0x1000
    h[0x400 + 2] = 1                               # PartitionFS
    h[0x400 + 3] = 2
    h[0x400 + 4] = 3                               # AesCtr
    h[0x400 + 0x140:0x400 + 0x148] = bytes(range(8))
    h[0x300:0x340] = bytes(range(64))
    return bytes(h)


def test_header_roundtrip():
    enc = nca.encrypt_header(_plain_header(), HK)
    assert enc[0x200:0x204] != b"NCA3"
    hdr = nca.parse_header(nca.decrypt_header(enc, HK))
    assert hdr.content_type == "Program" and hdr.title_id == 0x01007960049A0000
    assert hdr.key_generation == 4 and not hdr.has_rights_id
    assert nca.key_area_key_name(hdr) == "key_area_key_application_03"
    s = hdr.sections[0]
    assert (s.start, s.end, s.fs_type, s.hash_type, s.encryption) == (0xC00, 0x1000, "PartitionFS", 2, "AesCtr")


def test_bad_magic():
    with pytest.raises(ValueError):
        nca.parse_header(bytes(nca.HEADER_SIZE))


def test_key_area_and_ctr():
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    kaek = bytes(range(16, 32))
    plain = _plain_header()
    ka = bytes(range(100, 164))
    e = Cipher(algorithms.AES(kaek), modes.ECB()).encryptor()
    plain = plain[:0x300] + e.update(ka) + e.finalize() + plain[0x340:]
    hdr = nca.parse_header(plain)
    assert b"".join(nca.decrypt_key_area(hdr, {"key_area_key_application_03": kaek})) == ka
    key = ka[32:48]
    upper = bytes(range(8))
    ct = Cipher(algorithms.AES(key), modes.CTR(bytes(reversed(upper)) + (0xC20 >> 4).to_bytes(8, "big"))).encryptor()
    blob = ct.update(b"hello world 1234") + ct.finalize()
    assert nca.decrypt_ctr(key, upper, 0x20, blob, 0xC00) == b"hello world 1234"


def test_pfs0():
    names = b"main\0main.npdm\0"
    hdr = struct.pack("<4sII4x", b"PFS0", 2, len(names))
    hdr += struct.pack("<QQII", 0, 3, 0, 0) + struct.pack("<QQII", 3, 2, 5, 0)
    buf = hdr + names + b"abcde"
    assert [(n, s) for n, _o, s in nca.parse_pfs0(buf)] == [("main", 3), ("main.npdm", 2)]


def _utf(cols_rows):
    # one row, per-row storage: (name, type 4=u32 / 0xA=str / 6=u64)
    strings = b"\0tbl\0"
    soff = {}
    for n, _t, _v in cols_rows:
        soff[n] = len(strings); strings += n.encode() + b"\0"
    svals = {}
    for n, t, v in cols_rows:
        if t == 0xA:
            svals[n] = len(strings); strings += v.encode() + b"\0"
    cols = b"".join(bytes([0x50 | t]) + struct.pack(">I", soff[n]) for n, t, _ in cols_rows)
    row = b""
    for n, t, v in cols_rows:
        row += struct.pack(">I", svals[n]) if t == 0xA else struct.pack(">I" if t == 4 else ">Q", v)
    rows_off = 0x18 + len(cols)
    str_off = rows_off + len(row)
    data_off = str_off + len(strings)
    hdr = struct.pack(">IIIIIHHI", data_off, rows_off, str_off, data_off, 1, len(cols_rows), len(row), 1)
    return b"@UTF" + hdr + cols + row + strings


def test_utf_parse():
    name, rows = cpk.parse_utf(_utf([("A", 4, 7), ("B", 0xA, "hi"), ("C", 6, 2**40)]))
    assert name == "tbl" and rows == [{"A": 7, "B": "hi", "C": 2**40}]


def _literal_crilayla(body: bytes, prefix: bytes) -> bytes:
    bits = []
    for b in reversed(body):
        bits.append(0)
        bits += [(b >> i) & 1 for i in range(7, -1, -1)]
    while len(bits) % 8:
        bits.append(0)
    by = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    stream = bytes(reversed(by))
    return b"CRILAYLA" + struct.pack("<II", len(body), len(stream)) + stream + prefix


def test_crilayla_literals():
    prefix = bytes(range(256)); body = b"The quick brown fox"
    assert cpk.crilayla_decompress(_literal_crilayla(body, prefix)) == prefix + body


def test_dat():
    names = [b"a.wmb", b"b.wtp"]
    nl = 8
    off_o, ext_o, nam_o, siz_o, hm = 0x20, 0x28, 0x30, 0x30 + 4 + nl * 2, 0x60
    data = bytearray(0x80)
    data[:4] = b"DAT\0"
    struct.pack_into("<6I", data, 4, 2, off_o, ext_o, nam_o, siz_o, hm)
    struct.pack_into("<2I", data, off_o, 0x70, 0x74)
    data[ext_o:ext_o + 8] = b"wmb\0wtp\0"
    struct.pack_into("<I", data, nam_o, nl)
    for i, n in enumerate(names):
        data[nam_o + 4 + nl * i: nam_o + 4 + nl * i + len(n)] = n
    struct.pack_into("<2I", data, siz_o, 4, 4)
    es = parse_dat(bytes(data))
    assert [(e.name, e.ext, e.offset, e.size) for e in es] == [("a.wmb", "wmb", 0x70, 4), ("b.wtp", "wtp", 0x74, 4)]
