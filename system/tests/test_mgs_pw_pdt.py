import os, sys, struct, hashlib
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'gbox'))
import mgs_pw_pdt as m

ROM = '/mnt/gbox/hyperspin/Arcade/collections/Sony PlayStation Portable/roms/Metal Gear Solid - Peace Walker (USA).cso'


def build_pdt(members, key=0x13):
    # member offsets are FILE-relative; data region starts at file 0x800
    inner = struct.pack('<IHHHHI', m.MAGIC, 0, 1, len(members), 2, 32 + 12 * len(members))
    ents = b''
    off = 0x800
    for data in members:
        ents += struct.pack('<III', len(data), 0xDEADBEEF, off)
        off += len(data)
    payload = inner + ents + b'\0' * 16
    payload += b'\0' * (0x800 - 16 - len(payload))
    for data in members:
        payload += data
    return bytes([key, 0x88, 0x1b, 0]) + b'\0' * 8 + struct.pack('<I', 7) + bytes(b ^ key for b in payload)


def test_synthetic_roundtrip():
    m0 = b'confession.pdt\x00'
    m1 = b'Beyond the Bounds'
    raw = build_pdt([m0, m1])
    p = m.PdtFile(raw)
    assert p.count == 2
    assert p.table_end == 32 + 24
    assert [(x['size'], x['offset']) for x in p.members] == [(len(m0), 0x800), (len(m1), 0x800 + len(m0))]
    assert p.extract(0) == m0 and p.extract(1) == m1
    try:
        m.PdtFile(raw[:10])
        raise AssertionError('short PDT accepted')
    except m.PdtError:
        pass


def test_owned_cso_members():
    if not os.path.exists(ROM):
        import pytest
        pytest.skip('owned CSO not mounted')
    import psp_ciso_inventory as ci
    c = ci.Ciso(ROM)
    p = m.open_from_ciso(c, ci.read_members, '/PSP_GAME/USRDIR/dlc/WMP00000.PDT')
    assert p.count == 4
    assert p.extract(0).startswith(b'DLCB_MP\x001wm001_confession.pdt\x00')
    assert b'Confession' in p.extract(1)
    assert p.extract(2).startswith(b'SP\x00') and p.extract(3).startswith(b'SP\x10')  # inner name blobs
    v = m.open_from_ciso(c, ci.read_members, '/PSP_GAME/USRDIR/dlc/VEP00000.PDT')
    assert v.count == 14 and b'Beyond the B' in v.extract(1)
    vp = m.open_from_ciso(c, ci.read_members, '/PSP_GAME/USRDIR/VOICEPS.PDT')
    assert vp.count == 219
    # member 0 = name table; members 1+ are 'SP' sound clips whose header
    # u16@5 stores size/0x100 (e.g. 8192 -> 0x20)
    x = vp.members[1]
    h = vp.extract(1)
    assert h[:2] == b'SP' and int.from_bytes(h[5:7], 'little') << 8 == x['size']


def test_stagedat_rejected():
    if not os.path.exists(ROM):
        import pytest
        pytest.skip('owned CSO not mounted')
    import psp_ciso_inventory as ci
    c = ci.Ciso(ROM)
    for name, lba, size in ci.read_members(c, None):
        if name.upper().endswith('STAGEDAT.PDT'):
            try:
                m.PdtFile(c.read(lba * 2048, 4096))
                raise AssertionError('STAGEDAT accepted as XOR-variant')
            except m.PdtError:
                return
    raise AssertionError('STAGEDAT.PDT not found')
