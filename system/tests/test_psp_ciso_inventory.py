import struct, zlib, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'gbox'))
import psp_ciso_inventory as m

def make_sfo():
    ks = b'DISC_ID\0TITLE\0'; ds = b'ULES01372\0' + b'\0' * 6 + b'T\0\0\0'
    kt = 20 + 32
    b = struct.pack('<4sIIII', b'\0PSF', 0x101, kt, kt + len(ks), 2)
    b += struct.pack('<HHIII', 0, 0x204, 10, 16, 0) + struct.pack('<HHIII', 8, 0x204, 2, 4, 16)
    return b + ks + ds

def test_sfo():
    r = m.sfo(make_sfo()); assert r == {'DISC_ID': 'ULES01372', 'TITLE': 'T'}

def test_ciso(tmp_path):
    blocks = [b'A' * 2048, bytes(range(256)) * 8]
    comp = zlib.compressobj(9, zlib.DEFLATED, -15); c0 = comp.compress(blocks[0]) + comp.flush()
    base = 24 + 4 * 3; offs = [base, base + len(c0), base + len(c0) + 2048]
    hdr = b'CISO' + struct.pack('<IQIBB', 0, 4096, 2048, 1, 0) + b'\0\0'
    idx = struct.pack('<3I', offs[0], offs[1] | 0x80000000, offs[2] | 0x80000000)
    p = tmp_path / 'x.cso'; p.write_bytes(hdr + idx + c0 + blocks[1])
    c = m.Ciso(str(p)); assert c.read(0, 4096) == b''.join(blocks); assert c.read(2040, 16) == b'A' * 8 + blocks[1][:8]
