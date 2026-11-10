import os, struct, zlib, pytest
from gbox import tspfp_pak as P


def build(members):
    body = bytearray(b"P5CK" + b"\0" * 12)
    ents = []
    for name, data in members:
        while len(body) % 16:
            body.append(0)
        ents.append((zlib.crc32(name.encode()), len(body), len(data)))
        body += data
    while len(body) % 16:
        body.append(0)
    d = len(body)
    for c, o, s in ents:
        body += struct.pack("<4I", c, o, s, 0)
    body[4:12] = struct.pack("<II", d, 16 * len(ents))
    rows = [(zlib.crc32(n.encode()), n) for n, _ in members]
    return bytes(body), rows


def test_roundtrip_and_gcr_refs():
    gct = b"\0" * 64
    tref = struct.pack(">4I", 0xBD0D6B, 0xBD0D6B, 0, 0)
    gcr = struct.pack(">I", 12) + b"\0" * 8 + tref + struct.pack(">4I", 0xFFFFFFFF, 0xFFFFFFFF, 0, 0)
    pak, rows = build([("m/a.gcr", gcr), ("textures/bd0d6b.gct", gct)])
    ents = P.parse_pak(pak, rows)
    assert [e["path"] for e in ents] == ["m/a.gcr", "textures/bd0d6b.gct"]
    assert P.member(pak, ents[1]) == gct
    ids = {P.texture_id(e["path"]) for e in ents if e["path"].endswith(".gct")}
    assert P.gcr_texture_refs(P.member(pak, ents[0]), ids) == [0xBD0D6B]
    gcr2 = struct.pack(">I", 12) + b"\0" * 8 + tref + tref
    assert P.gcr_texture_refs(gcr2, ids) == [0xBD0D6B, 0xBD0D6B]


def test_bad_crc_rejected():
    pak, rows = build([("x.gcr", b"abcd")])
    with pytest.raises(ValueError):
        P.parse_pak(pak, [(rows[0][0] ^ 1, "x.gcr")])


REAL = os.environ.get("TSFP_CHR_PAK")


@pytest.mark.skipif(not REAL, reason="set TSFP_CHR_PAK=dir containing chr.pak/chr.c2n")
def test_real_chr_pak():
    d = open(REAL + "/chr.pak", "rb").read()
    rows = P.parse_c2n(open(REAL + "/chr.c2n").read())
    ents = P.parse_pak(d, rows)
    assert len(ents) == 908
    ids = {P.texture_id(e["path"]) for e in ents if e["path"].endswith(".gct")}
    refs = sum(len(P.gcr_texture_refs(P.member(d, e), ids)) for e in ents if e["path"].endswith(".gcr"))
    assert refs == 1063
