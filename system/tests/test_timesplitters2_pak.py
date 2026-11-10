import struct, pytest
from gbox.timesplitters2_pak import parse_pak, census

def build():
    f1, f2 = b'A' * 0x20, b'B' * 0x10
    body = f1 + f2
    diro = 0x10 + len(body)
    def rec(n, o, s): return n.ljust(48, b'\0') + struct.pack('<III', o, s, 0)
    d = rec(b'a/x.war', 0x10, 0x20) + rec(b'b/y.gcr', 0x30, 0x10)
    return b'P4CK' + struct.pack('<III', diro, len(d), 0) + body + d

def test_parse():
    e = parse_pak(build())
    assert [x['name'] for x in e] == ['a/x.war', 'b/y.gcr']
    assert e[1]['offset'] == 0x30 and census(e)['war'] == 1

def test_bad():
    with pytest.raises(ValueError): parse_pak(b'XXXX' + b'\0' * 12)

def test_p8ck_names():
    from gbox.timesplitters2_pak import parse_p8ck_names
    nm = b'a.gcr\0b.gct\0'
    d = b'P8CK' + struct.pack('<4I', 0, 2, 0x14, len(nm)) + nm
    assert parse_p8ck_names(d) == ['a.gcr', 'b.gct']
