import os, struct, hashlib
import pytest
from gbox.formats import n3ds

def le(fmt, *a):
    return struct.pack('<' + fmt, *a)

def build_cartridge():
    """Hand-laid per 3dbrew: NCSD(0x4000) -> NCCH -> ExeFS + RomFS(IVFC, L3 at 0x1000)."""
    ncch = bytearray(0x10000)
    ncch[0x100:0x104] = b'NCCH'
    struct.pack_into('<I', ncch, 0x104, len(ncch) // 0x200)
    ncch[0x150:0x15a] = b'CTR-P-TEST'
    struct.pack_into('<II', ncch, 0x1A0, 0x20, 2)       # ExeFS @0x4000, 0x400
    struct.pack_into('<II', ncch, 0x1B0, 0x40, 0x40)    # RomFS @0x8000, 0x8000
    ex = 0x4000
    ncch[ex:ex + 16] = le('8sII', b'.code', 0, 4)
    ncch[ex + 0x200:ex + 0x204] = b'ABCD'
    rf = 0x8000
    ncch[rf:rf + 4] = b'IVFC'
    struct.pack_into('<I', ncch, rf + 8, 0x20)          # master hash size
    struct.pack_into('<I', ncch, rf + 0x4C, 12)
    l3 = rf + 0x1000
    names_d = '' ; fname = 'a.bcmdl'.encode('utf-16-le')
    dmeta = le('6I', 0, NONE, NONE, 0, NONE, 0)         # root dir, first file @0
    fmeta = le('IIQQII', 0, NONE, 0, 5, NONE, len(fname)) + fname
    fmeta += b'\0' * (-len(fmeta) % 4)
    base = 0x28
    dh_off = base; d_off = dh_off + 8; f_off = d_off + len(dmeta) + 8; data_off = (f_off + len(fmeta) + 15) // 16 * 16
    struct.pack_into('<10I', ncch, l3, 0x28, dh_off, 4, d_off, len(dmeta), 0, 4, f_off, len(fmeta), data_off)
    ncch[l3 + d_off:l3 + d_off + len(dmeta)] = dmeta
    ncch[l3 + f_off:l3 + f_off + len(fmeta)] = fmeta
    ncch[l3 + data_off:l3 + data_off + 5] = b'hello'
    raw = bytearray(0x4000) + ncch
    raw[0x100:0x104] = b'NCSD'
    struct.pack_into('<I', raw, 0x104, len(raw) // 0x200)
    struct.pack_into('<2I', raw, 0x120, 0x4000 // 0x200, len(ncch) // 0x200)
    return bytes(raw)

NONE = 0xFFFFFFFF

def test_walk_synthetic_cartridge():
    c = n3ds.open_cartridge(build_cartridge())
    assert c['ncch']['product_code'] == 'CTR-P-TEST'
    assert [(f['name'], f['size']) for f in c['exefs']] == [('.code', 4)]
    assert [(f['path'], f['size']) for f in c['romfs']] == [('a.bcmdl', 5)]
    raw = build_cartridge(); f = c['romfs'][0]
    assert raw[f['offset']:f['offset'] + 5] == b'hello'

def test_rejects_bad_and_truncated():
    raw = build_cartridge()
    with pytest.raises(n3ds.N3DSError): n3ds.parse_ncsd(raw[:0x100])
    with pytest.raises(n3ds.N3DSError): n3ds.parse_ncsd(b'\0' * 0x200)
    bad = bytearray(raw); bad[0x4000 + 0x8000:0x4000 + 0x8004] = b'\0\0\0\0'
    with pytest.raises(n3ds.N3DSError): n3ds.open_cartridge(bytes(bad))

def test_blz_literals_and_backref():
    # Consumption order (end -> start): flags 0b0001_0000, literals z y x, then
    # b1=0xC0 (len 15) b2=0 (disp 3). Output is built backwards: 'xyz' * 6.
    consumed = [0b00010000, ord('z'), ord('y'), ord('x'), 0xC0, 0x00]
    comp = bytes(reversed(consumed))
    enc = len(comp) + 8
    data = b'PRE_' + comp + struct.pack('<II', (8 << 24) | enc, 18 - enc)
    out = n3ds.blz_decompress(data)
    assert out[:4] == b'PRE_' and out[4:] == b'xyz' * 6
    with pytest.raises(n3ds.N3DSError): n3ds.blz_decompress(b'\0' * 8)

def test_cgfx_synthetic_dict():
    b = bytearray(0x200)
    b[:4] = b'CGFX'; struct.pack_into('<HHIII', b, 4, 0xFEFF, 0x14, 0x05000000 & 0xFFFFFFFF, len(b), 1)
    b[0x14:0x18] = b'DATA'; struct.pack_into('<I', b, 0x18, 0x100)
    base = 0x1C
    d = 0xC0
    struct.pack_into('<2I', b, base, 1, d - (base + 4))     # model: count 1, relative offset
    b[d:d + 4] = b'DICT'; struct.pack_into('<II', b, d + 4, 0x30, 1)
    node = d + 0xC + 0x10
    name = b'robo\0'
    struct.pack_into('<IHHII', b, node, 0, 0, 0, (d + 0x40) - (node + 8), 0)
    b[d + 0x40:d + 0x40 + len(name)] = name
    r = n3ds.parse_cgfx(bytes(b))
    assert r['counts'] == {'model': 1} and r['names']['model'] == ['robo']
    with pytest.raises(n3ds.N3DSError): n3ds.parse_cgfx(bytes(b[:0x20]))

ROM = '/home/ehm_eckx/.hermes/cache/scratch/axis/Tetris Axis (USA).3ds'

@pytest.mark.skipif(not os.path.exists(ROM), reason='owned Tetris Axis dump not present')
def test_owned_build_manifest():
    raw = open(ROM, 'rb').read()
    assert hashlib.sha256(raw).hexdigest() == 'd47d0bd35cd210567574a302623bb96f6ec40dc8d644f4548dbbed173575dd01'
    c = n3ds.open_cartridge(raw)
    assert c['ncch']['product_code'] == 'CTR-P-ATLE' and c['ncch']['partition_id'] == 0x0004000000043800
    assert len(c['romfs']) == 515
    ext = {}
    for f in c['romfs']:
        e = f['path'].rsplit('.', 1)[-1]; ext[e] = ext.get(e, 0) + 1
    assert ext['bcmdl'] == 239 and ext['arc'] == 41 and ext['bcskla'] == 49
    code = [f for f in c['exefs'] if f['name'] == '.code'][0]
    d = n3ds.blz_decompress(raw[code['offset']:code['offset'] + code['size']])
    assert len(d) == 3608576
    m = [f for f in c['romfs'] if f['path'] == 'co03/co03_ef_m00_0.bcmdl'][0]
    r = n3ds.parse_cgfx(raw[m['offset']:m['offset'] + m['size']])
    assert r['counts']['model'] == 1 and r['names']['model'] == ['co03_ef_m00_0']
