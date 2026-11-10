"""Peace Walker (ULES01372) EBOOT.OLD static probe: CMF loader thread.

Source: PSP_GAME/SYSDIR/EBOOT.OLD sha256 bc020306e00b8a59f8a6a76471c0c5b1122972654069166e0c828be58778db8f
(PRX ELF, e_type 0xFFA0, MIPS LE; PT_LOAD0 file 0xA0 -> vaddr 0, filesz 0x383... base-relative; hi/lo pairs are
pre-relocation, so offsets == vaddrs here).  Findings (static, hypotheses beyond what is listed as 'verified'):
  verified: string 'cmf_load' (vaddr 0x380320) is referenced from the loader-thread dispatcher at 0x2a31a4
    which jumps through an 18-entry state table at 0x37b1f0 (lui 0x38 / addiu -0x4e10).
  verified: read-request queue helper 0x2a2798 appends (offset,len,len,dest,arg) 20-byte records at ctx+0x660,
    count at ctx+0x654, max 0x100; 0x2a2854 qsorts them (cmp 0x2a2830) and merges contiguous ranges.
  hypothesis: CMF entries (id,len) are streamed through this queue; body codec still unknown.
"""
import struct

PRX_TYPE = 0xFFA0


def load_image(elf):
    """Return (code bytes indexed by vaddr, segment list) for the first PT_LOAD of a PSP PRX ELF."""
    if elf[:4] != b'\x7fELF':
        raise ValueError('not ELF')
    etype, mach = struct.unpack_from('<HH', elf, 16)
    phoff, = struct.unpack_from('<I', elf, 28)
    phnum, = struct.unpack_from('<H', elf, 44)
    segs = [struct.unpack_from('<8I', elf, phoff + 32 * i) for i in range(phnum)]
    loads = [s for s in segs if s[0] == 1]
    if not loads:
        raise ValueError('no PT_LOAD')
    t, off, va, pa, fsz, msz, fl, al = loads[0]
    image = bytearray(msz)
    image[va:va + fsz] = elf[off:off + fsz]
    return bytes(image), {'etype': etype, 'machine': mach, 'segments': segs}


def _s16(x):
    return x - 65536 if x >= 32768 else x


def string_xrefs(code, va, window=12):
    """Code offsets of lui+addiu/ori/load pairs (same reg, <=window insns apart) that resolve to va."""
    words = struct.unpack('<%dI' % (len(code) // 4), code[:len(code) // 4 * 4])
    hits = []
    for i, w in enumerate(words):
        if w >> 26 != 0xF:
            continue
        rt, hi = (w >> 16) & 31, w & 0xFFFF
        for j in range(1, window):
            if i + j >= len(words):
                break
            v = words[i + j]
            if v >> 26 in (9, 0xD, 0x20, 0x21, 0x23, 0x24, 0x25) and (v >> 21) & 31 == rt \
                    and ((hi << 16) + _s16(v & 0xFFFF)) & 0xFFFFFFFF == va:
                hits.append(i * 4)
                break
    return hits


def func_start(code, addr):
    """Scan back for the enclosing 'addiu $sp,$sp,-N' prologue."""
    a = addr & ~3
    while a >= 0:
        w, = struct.unpack_from('<I', code, a)
        if w >> 16 == 0x27BD and w & 0x8000:
            return a
        a -= 4
    raise ValueError('no prologue')


def jump_table(code, va, n):
    return [struct.unpack_from('<I', code, va + 4 * i)[0] for i in range(n)]


def cstr(code, va):
    return code[va:code.index(b'\0', va)]


def cmf_loader_report(elf):
    code, info = load_image(elf)
    off = elf.find(b'cmf_load\0')
    sva = off - 160  # file offset 0xA0 == vaddr 0 for PT_LOAD0 of this build
    if cstr(code, sva) != b'cmf_load':
        raise ValueError('cmf_load string not at expected vaddr')
    xr = string_xrefs(code, sva)
    funcs = sorted({func_start(code, x) for x in xr})
    return {'etype': info['etype'], 'string_vaddr': sva, 'xrefs': xr, 'funcs': funcs}


if __name__ == '__main__':
    import json
    import sys
    print(json.dumps(cmf_loader_report(open(sys.argv[1], 'rb').read()), indent=1, default=hex))
