import os, struct, hashlib
import pytest
from gbox.formats.j3d import chunks, J3DError

def model(tags=(b'INF1', b'VTX1', b'JNT1')):
    body = b''.join(t + struct.pack('>I', 32) + bytes(24) for t in tags)
    return b'J3D2bdl4' + struct.pack('>II', 0x20 + len(body), len(tags)) + b'SVR3' + b'\xff' * 12 + body

def test_walk():
    r = chunks(model())
    assert r['type'] == 'bdl4' and [c[0] for c in r['chunks']] == ['INF1', 'VTX1', 'JNT1']
    assert [c[1] for c in r['chunks']] == [0x20, 0x40, 0x60]

@pytest.mark.parametrize('mut', [lambda b: b[:0x1f], lambda b: b'XXXX' + b[4:],
    lambda b: b[:8] + struct.pack('>I', 1) + b[12:], lambda b: b[:12] + struct.pack('>I', 9) + b[16:],
    lambda b: b[:0x24] + struct.pack('>I', 0x7fffffff) + b[0x28:], lambda b: b[:0x24] + struct.pack('>I', 4) + b[0x28:],
    lambda b: b + b'\0'])
def test_rejects(mut):
    with pytest.raises(J3DError):
        chunks(mut(model()))

OWNED = "/mnt/gbox/hyperspin/Arcade/collections/Nintendo GameCube/roms/Legend of Zelda, The - The Wind Waker (USA).gcz"

@pytest.mark.skipif(not os.path.exists(OWNED), reason="owned TWW disc not mounted")
def test_owned_link_cl_bdl():
    from gbox.gcdisc import GCDisc
    from gbox.formats import rarc, lz
    d = GCDisc(OWNED)
    assert d.game_id == 'GZLE01'
    dec = lz.yaz0_decompress(d.read('res/Object/Link.arc'))
    assert hashlib.sha256(dec).hexdigest() == 'b4b4c6111e79e1346573108d9d2a41566001bb137cbc7a0779e4aaf9c98e353f'
    m = {n: (o, s) for n, o, s in rarc.walk(dec)}
    o, s = m['bdl/cl.bdl']
    assert (o, s) == (80800, 364544)
    r = chunks(dec[o:o + s])
    tags = [c[0] for c in r['chunks']]
    assert r['type'] == 'bdl4' and {'VTX1', 'SHP1', 'JNT1', 'TEX1'} <= set(tags)
