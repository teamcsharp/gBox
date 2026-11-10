import struct, pytest
from gbox.psp_cmf import parse_cmf


def make(n=3, body=32):
    hdr = 0x40 + 8 * n + 8
    b = bytearray(hdr + body)
    b[:4] = b'CMF\x10'
    struct.pack_into('<III', b, 4, len(b), 0, hdr)
    struct.pack_into('<I', b, 0x30, n)
    for i in range(n):
        struct.pack_into('<II', b, 0x40 + 8 * i, 0x1000 + i, 16 * (i + 1))
    return bytes(b)


def test_parse_header_and_entries():
    r = parse_cmf(make())
    assert r['count'] == 3 and r['header_size'] == 0x60 and r['body_size'] == 32
    assert r['entries'][1] == (0x1001, 32)


def test_rejects_bad_magic_size_and_overrun():
    good = make()
    with pytest.raises(ValueError):
        parse_cmf(b'XXXX' + good[4:])
    with pytest.raises(ValueError):
        parse_cmf(good + b'\0')
    bad = bytearray(good); struct.pack_into('<I', bad, 0x30, 99)
    with pytest.raises(ValueError):
        parse_cmf(bytes(bad))


def test_real_snake_cmf_if_present():
    import os
    p = os.path.expanduser('~/.hermes/cache/scratch/snake.cmf')
    if not os.path.exists(p):
        pytest.skip('owned extract absent')
    r = parse_cmf(open(p, 'rb').read())
    assert (r['total'], r['header_size'], r['count']) == (117856, 0x110, 25)
