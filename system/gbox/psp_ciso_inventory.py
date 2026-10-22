#!/usr/bin/env python3
"""Streaming CISO (v1) reader + ISO9660 walker + PARAM.SFO parser + magic census for PSP images."""
import struct, zlib, hashlib, json, sys, collections

class Ciso:
    def __init__(self, path):
        self.f = open(path, 'rb')
        h = self.f.read(24)
        if h[:4] != b'CISO': raise ValueError('not CISO')
        _, self.total, self.bs, self.ver, self.align = struct.unpack('<IQIBB', h[4:22])
        n = self.total // self.bs
        self.idx = struct.unpack('<%dI' % (n + 1), self.f.read(4 * (n + 1)))
        self.n = n
        self.cache = (None, b'')
    def block(self, i):
        if self.cache[0] == i: return self.cache[1]
        a, b = self.idx[i], self.idx[i + 1]
        plain = a & 0x80000000
        off = (a & 0x7FFFFFFF) << self.align
        end = (b & 0x7FFFFFFF) << self.align
        self.f.seek(off); d = self.f.read(end - off)
        if not plain:
            d = zlib.decompressobj(-15).decompress(d)
        d = d[:self.bs].ljust(self.bs, b'\0')
        self.cache = (i, d); return d
    def read(self, off, size):
        out = []
        while size > 0:
            i, o = divmod(off, self.bs)
            if i >= self.n: break
            c = self.block(i)[o:o + size]
            out.append(c); off += len(c); size -= len(c)
        return b''.join(out)

def walk(c, lba, size, path, out):
    data = c.read(lba * 2048, size); p = 0
    while p < len(data):
        l = data[p]
        if l == 0:
            p = (p // 2048 + 1) * 2048; continue
        rec = data[p:p + l]; p += l
        el, = struct.unpack('<I', rec[2:6]); sz, = struct.unpack('<I', rec[10:14])
        fl = rec[25]; nl = rec[32]; nm = rec[33:33 + nl]
        if nm in (b'\0', b'\1'): continue
        name = nm.decode('latin1').split(';')[0]
        full = path + '/' + name
        if fl & 2: walk(c, el, sz, full, out)
        else: out.append((full, el, sz))

def sfo(b):
    magic, ver, kt, dt, n = struct.unpack('<4sIIII', b[:20])
    assert magic == b'\0PSF'
    r = {}
    for i in range(n):
        ko, fmt, ln, mx, do = struct.unpack('<HHIII', b[20 + 16 * i:36 + 16 * i])
        k = b[kt + ko:b.index(b'\0', kt + ko)].decode()
        v = b[dt + do:dt + do + ln]
        r[k] = struct.unpack('<I', v[:4])[0] if fmt == 0x404 else v.rstrip(b'\0').decode('utf8', 'replace')
    return r

def main(path, outp):
    c = Ciso(path)
    pvd = c.read(16 * 2048, 2048)
    assert pvd[1:6] == b'CD001', 'no PVD'
    root = pvd[156:190]
    el, = struct.unpack('<I', root[2:6]); sz, = struct.unpack('<I', root[10:14])
    files = []; walk(c, el, sz, '', files)
    magics = collections.Counter(); exts = collections.Counter(); tot = 0; members = []
    param = None
    for full, lba, size in files:
        head = c.read(lba * 2048, min(size, 16))
        ext = full.rsplit('.', 1)[-1].lower() if '.' in full.rsplit('/', 1)[-1] else ''
        exts[ext] += 1; tot += size
        magics[head[:4].hex() + ':' + ''.join(chr(x) if 32 <= x < 127 else '.' for x in head[:4])] += 1
        h = None
        if size <= 64 * 1024 * 1024:
            h = hashlib.sha256(c.read(lba * 2048, size)).hexdigest()
        if full.upper().endswith('PARAM.SFO'): param = sfo(c.read(lba * 2048, size))
        members.append({'path': full, 'lba': lba, 'size': size, 'head16': head.hex(), 'sha256': h})
    out = {'source': path, 'container': 'CISO v%d block=%d align=%d uncompressed=%d' % (c.ver, c.bs, c.align, c.total),
           'volume_id': pvd[40:72].decode('latin1').strip(), 'file_count': len(files), 'total_bytes': tot,
           'param_sfo': param, 'ext_census': exts.most_common(), 'magic_census': magics.most_common(25), 'members': members}
    json.dump(out, open(outp, 'w'), indent=1)
    print(json.dumps({k: v for k, v in out.items() if k != 'members'}, indent=1))

if __name__ == '__main__': main(sys.argv[1], sys.argv[2])
