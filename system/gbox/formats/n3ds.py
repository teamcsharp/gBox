"""Bounded read-only Nintendo 3DS cartridge/CXI walker and CGFX table reader.

NCSD -> NCCH -> ExeFS / RomFS (IVFC + level-3 directory/file metadata), the
ExeFS ``.code`` backwards-LZ ("BLZ") decoder, and the CGFX DATA dictionary
counts. Layouts: 3dbrew NCSD/NCCH/ExeFS/RomFS pages and the CGFX spec.
Only unencrypted (NoCrypto or plaintext) NCCH is handled; encrypted content is
rejected explicitly. No writer support is implied.
"""
import struct

class N3DSError(ValueError):
    pass

MU = 0x200
CGFX_TYPES = ('model', 'texture', 'luts', 'material', 'shader', 'camera', 'light',
              'fog', 'scene', 'skeletal_anim', 'material_anim', 'visibility_anim',
              'camera_anim', 'light_anim', 'emitter')
NONE = 0xFFFFFFFF

def _need(raw, off, n, what):
    if off < 0 or n < 0 or off + n > len(raw):
        raise N3DSError('Truncated ' + what)

def parse_ncsd(raw):
    _need(raw, 0, 0x160, 'NCSD header')
    if raw[0x100:0x104] != b'NCSD':
        raise N3DSError('Not NCSD')
    size = struct.unpack_from('<I', raw, 0x104)[0] * MU
    parts = []
    for i in range(8):
        off, ln = struct.unpack_from('<2I', raw, 0x120 + i * 8)
        if ln:
            if (off + ln) * MU > max(size, len(raw)):
                raise N3DSError('NCSD partition %d out of range' % i)
            parts.append({'index': i, 'offset': off * MU, 'size': ln * MU})
    if not parts:
        raise N3DSError('NCSD has no partitions')
    return {'size': size, 'partitions': parts}

def parse_ncch(raw, base):
    _need(raw, base, 0x200, 'NCCH header')
    h = raw[base:base + 0x200]
    if h[0x100:0x104] != b'NCCH':
        raise N3DSError('Not NCCH')
    flags = h[0x188:0x190]
    if not flags[7] & 4:
        # Encrypted unless the content is actually plaintext; callers verify
        # by checking ExeFS/RomFS magic below.
        pass
    u = lambda o: struct.unpack_from('<I', h, o)[0] * MU
    out = {
        'base': base, 'content_size': u(0x104),
        'partition_id': struct.unpack_from('<Q', h, 0x108)[0],
        'product_code': h[0x150:0x160].split(b'\0')[0].decode('ascii', 'replace'),
        'exheader_size': struct.unpack_from('<I', h, 0x180)[0],
        'flags': list(flags), 'no_crypto_flag': bool(flags[7] & 4),
        'exefs_off': u(0x1A0), 'exefs_size': u(0x1A4),
        'romfs_off': u(0x1B0), 'romfs_size': u(0x1B4),
    }
    for k in ('exefs', 'romfs'):
        if out[k + '_size'] and out[k + '_off'] + out[k + '_size'] > out['content_size']:
            raise N3DSError('NCCH ' + k + ' out of range')
    return out

def parse_exefs(raw, base):
    _need(raw, base, 0x200, 'ExeFS header')
    files = []
    for i in range(10):
        name, off, size = struct.unpack_from('<8sII', raw, base + i * 16)
        if not name.strip(b'\0'):
            continue
        nm = name.split(b'\0')[0].decode('ascii', 'replace')
        if not nm.isprintable():
            raise N3DSError('ExeFS name is not plaintext (encrypted?)')
        _need(raw, base + 0x200 + off, size, 'ExeFS file ' + nm)
        files.append({'name': nm, 'offset': base + 0x200 + off, 'size': size})
    if not files:
        raise N3DSError('ExeFS empty')
    return files

def blz_decompress(data):
    """Backwards LZ (CTR .code). Footer: u32 (hdr_len<<24 | enc_len), u32 extra."""
    n = len(data)
    if n < 8:
        raise N3DSError('BLZ too short')
    top, inc = struct.unpack_from('<2I', data, n - 8)
    enc, hdr = top & 0xFFFFFF, top >> 24
    if hdr < 8 or hdr > enc or enc > n or inc > 0x4000000:
        raise N3DSError('Invalid BLZ footer')
    dec = n + inc
    out = bytearray(dec)
    out[:n] = data
    pi, end_in, po = n - hdr, n - enc, dec
    while pi > end_in:
        pi -= 1
        flags = data[pi]
        for _ in range(8):
            if pi <= end_in:
                break
            if not flags & 0x80:
                if po <= 0:
                    raise N3DSError('BLZ output underrun')
                pi -= 1; po -= 1
                out[po] = data[pi]
            else:
                if pi < end_in + 2:
                    raise N3DSError('BLZ truncated')
                b1 = data[pi - 1]; b2 = data[pi - 2]; pi -= 2
                ln = (b1 >> 4) + 3
                disp = (((b1 & 0xF) << 8) | b2) + 3
                if po < ln or po + disp > dec:
                    raise N3DSError('BLZ bad back-reference')
                for _ in range(ln):
                    po -= 1
                    out[po] = out[po + disp]
            flags = (flags << 1) & 0xFF
    return bytes(out)

def _utf16(raw, off, nbytes):
    return raw[off:off + nbytes].decode('utf-16-le', 'replace')

def parse_romfs(raw, base, size):
    """Return list of {path, offset, size}; offsets are absolute in raw."""
    _need(raw, base, 0x60, 'IVFC header')
    if raw[base:base + 4] != b'IVFC':
        raise N3DSError('RomFS IVFC magic missing (encrypted or absent)')
    master = struct.unpack_from('<I', raw, base + 8)[0]
    bs3 = struct.unpack_from('<I', raw, base + 0x4C)[0]
    if bs3 > 24 or bs3 < 9:
        raise N3DSError('Bad IVFC level-3 block size')
    blk = 1 << bs3
    l3 = (0x60 + master + blk - 1) // blk * blk
    l3abs = base + l3
    _need(raw, l3abs, 0x28, 'RomFS level-3 header')
    hl = struct.unpack_from('<I', raw, l3abs)[0]
    if hl != 0x28:
        raise N3DSError('Bad RomFS level-3 header length')
    # fields: dirhash(off,size) dirmeta(off,size) filehash(off,size) filemeta(off,size) data offset
    dh_off, dh_sz, d_off, d_sz, fh_off, fh_sz, f_off, f_sz, data_off = \
        struct.unpack_from('<9I', raw, l3abs + 4)
    for o, s, w in ((d_off, d_sz, 'dir meta'), (f_off, f_sz, 'file meta')):
        _need(raw, l3abs + o, s, 'RomFS ' + w)
    dbase, fbase = l3abs + d_off, l3abs + f_off
    files, seen = [], set()

    def walk(doff, prefix, depth):
        if depth > 64:
            raise N3DSError('RomFS directory depth')
        while doff != NONE:
            if doff in seen or doff + 24 > d_sz:
                raise N3DSError('RomFS directory cycle/range')
            seen.add(doff)
            par, sib, child, first_file, _nh, nlen = struct.unpack_from('<6I', raw, dbase + doff)
            if doff + 24 + nlen > d_sz:
                raise N3DSError('RomFS dir name range')
            name = _utf16(raw, dbase + doff + 24, nlen)
            path = prefix + (name + '/' if name else '')
            foff = first_file
            while foff != NONE:
                if foff + 32 > f_sz:
                    raise N3DSError('RomFS file range')
                _p, fsib, doff2, dsz, _nh2, fnl = struct.unpack_from('<IIQQII', raw, fbase + foff)
                if foff + 32 + fnl > f_sz or data_off + doff2 + dsz > size - l3:
                    raise N3DSError('RomFS file entry out of range')
                fname = _utf16(raw, fbase + foff + 32, fnl)
                files.append({'path': path + fname, 'offset': l3abs + data_off + doff2, 'size': dsz})
                foff = fsib
            if child != NONE:
                walk(child, path, depth + 1)
            if depth == 0:
                break
            doff = sib
    walk(0, '', 0)
    return files

def parse_cgfx(raw):
    """CGFX header + DATA dictionary counts (no model decoding)."""
    if len(raw) < 0x14 + 8 + 16 * 8 or raw[:4] != b'CGFX':
        raise N3DSError('Not CGFX')
    bom = struct.unpack_from('<H', raw, 4)[0]
    if bom != 0xFEFF:
        raise N3DSError('Unsupported CGFX byte order')
    hsz, rev, fsz, nent = struct.unpack_from('<HIII', raw, 6)
    if fsz > len(raw) or hsz < 0x14 or raw[hsz:hsz + 4] != b'DATA':
        raise N3DSError('Bad CGFX header or DATA block')
    base = hsz + 8
    out = {'revision': rev, 'size': fsz, 'blocks': nent, 'counts': {}, 'names': {}}
    for i, t in enumerate(CGFX_TYPES):
        cnt, off = struct.unpack_from('<2I', raw, base + i * 8)
        if not cnt:
            continue
        dict_off = base + i * 8 + 4 + off
        if dict_off + 16 + 16 * (cnt + 1) > fsz or raw[dict_off:dict_off + 4] != b'DICT':
            raise N3DSError('Bad CGFX DICT for ' + t)
        dcount = struct.unpack_from('<I', raw, dict_off + 8)[0]
        if dcount != cnt:
            raise N3DSError('CGFX DICT count mismatch for ' + t)
        out['counts'][t] = cnt
        names = []
        for k in range(cnt):
            e = dict_off + 0xC + 0x10 * (k + 1)
            noff = struct.unpack_from('<I', raw, e + 8)[0]
            p = e + 8 + noff
            if p >= fsz:
                raise N3DSError('CGFX name out of range')
            end = raw.find(b'\0', p, min(fsz, p + 256))
            if end < 0:
                raise N3DSError('Unterminated CGFX name')
            names.append(raw[p:end].decode('ascii', 'replace'))
        out['names'][t] = names
    return out

def open_cartridge(raw):
    """Walk NCSD -> partition 0 NCCH -> ExeFS list + RomFS file list."""
    ncsd = parse_ncsd(raw)
    p0 = ncsd['partitions'][0]
    ncch = parse_ncch(raw, p0['offset'])
    exefs = parse_exefs(raw, p0['offset'] + ncch['exefs_off']) if ncch['exefs_size'] else []
    romfs = parse_romfs(raw, p0['offset'] + ncch['romfs_off'], ncch['romfs_size']) if ncch['romfs_size'] else []
    return {'ncsd': ncsd, 'ncch': ncch, 'exefs': exefs, 'romfs': romfs}
