"""Midway 'SEC ' slot-file (.ssf) directory + MKD GameCube ELF file-table probe.

Verified on GQNE5D (Mortal Kombat: Deception, GC, mk6gc_release.elf):
 SSF header (big endian): 'SEC ', u32 version(4), u32 0, u32 slots(0xb9 in ashrah; NOT the entry count), u32 0x14,
   u32 tag, u32 total_size, then count * 16-byte entries
   (u32 kind, u32 offset, u32 size, u32 aux), terminated by an all-zero entry
   (ashrah.ssf: 20 sections). Offsets are 0x800-aligned and
   the last entry ends <= total_size.
 ELF (PowerPC BE, has .symtab): *_file_table objects in .rodata are
   [handle_ptr_ssf, 0, 0, (handle_ptr, offset, size)*]; a handle is
   {name_ptr, table_ptr, index}; the (offset,size) pairs equal the SSF directory.
"""
import struct

SSF_MAGIC = b"SEC "


def parse_ssf_directory(buf):
    if buf[:4] != SSF_MAGIC:
        raise ValueError("not a SEC ssf")
    ver, _z, count, hdr, tag, total = struct.unpack(">6I", buf[4:28])
    ents = []
    for i in range(count):
        kind, off, size, aux = struct.unpack(">4I", buf[28 + 16 * i:44 + 16 * i])
        if not (kind or off or size or aux):
            break  # zero terminator; the rest of the 'count' region is a different (name/index) table
        ents.append({"i": i, "kind": kind, "offset": off, "size": size, "aux": aux})
    return {"version": ver, "count_field": count, "count": len(ents), "tag": tag, "total_size": total, "entries": ents}


def validate_ssf_directory(d):
    last = 0
    for e in d["entries"]:
        if e["offset"] % 0x800 or e["offset"] < last or e["offset"] + e["size"] > d["total_size"]:
            return False
        last = e["offset"]
    return True


class PpcElf:
    def __init__(self, data):
        if data[:4] != b"\x7fELF" or data[4] != 1 or data[5] != 2:
            raise ValueError("expected ELF32 big-endian")
        self.d = data
        shoff, = struct.unpack(">I", data[32:36])
        shentsize, shnum = struct.unpack(">HH", data[46:50])
        self.sec = [struct.unpack(">10I", data[shoff + i * shentsize:shoff + i * shentsize + 40]) for i in range(shnum)]
        self.syms = {}
        sym = next(s for s in self.sec if s[1] == 2)
        st = self.sec[sym[6]]
        for i in range(sym[5] // 16):
            n, v, sz, _i, _o, _sh = struct.unpack(">IIIBBH", data[sym[4] + i * 16:sym[4] + i * 16 + 16])
            b = data[st[4] + n:st[4] + n + 200]
            self.syms.setdefault(b.split(b"\0")[0].decode("latin-1"), []).append((v, sz))

    def read(self, va, n):
        for s in self.sec:
            if s[1] == 1 and s[3] and s[3] <= va < s[3] + s[5]:
                o = s[4] + va - s[3]
                return self.d[o:o + n]
        raise KeyError(hex(va))

    def u32s(self, va, n):
        return struct.unpack(">%dI" % n, self.read(va, 4 * n))

    def cstr(self, va):
        b = self.read(va, 96)
        return b.split(b"\0")[0].decode("latin-1")

    def handle(self, va):
        name, tbl, idx = self.u32s(va, 3)
        return {"name": self.cstr(name), "table": tbl, "index": idx}

    def file_table(self, symname):
        va, sz = self.syms[symname][0]
        w = self.u32s(va, sz // 4)
        ssf = self.handle(w[0])
        secs = []
        for k in range(3, len(w) - 2, 3):
            if not w[k]:
                break
            h = self.handle(w[k])
            secs.append({"name": h["name"], "offset": w[k + 1], "size": w[k + 2]})
        return {"ssf": ssf, "sections": secs}

    def char_names(self):
        """pselect_char_tbl: 12-word records (id, ?, name_ptrs...) -> HEAD_* strings."""
        va, sz = self.syms["pselect_char_tbl"][0]
        out = set()
        for w in self.u32s(va, sz // 4):
            if 0x80000000 <= w < 0x80600000:
                try:
                    s = self.cstr(w)
                except KeyError:
                    continue
                if s.startswith("HEAD_"):
                    out.add(s)
        return sorted(out)


# ---- SEC resource (kind-1 container, e.g. ashrah.sec / krypt.sec) -----------
# Layout (big-endian, verified on owned GQNE5D ashrah.sec/krypt.sec):
#   'SEC ', version(4), 0, tag, n_entries, name_pool_size, total_size  (28 B)
#   n_entries * (type, offset, size, name_off)   offsets contiguous, relative to sec start
#   name pool (NUL-separated) ; entry payloads.
# type 3 = texture: 0x100-byte header (little-endian fields, 'PAD32' fill) + GX CMPR data
# (hypothesis: type 4 = geometry/display-list blobs, type 2 = CI8 textures; unproved).

def parse_sec_resource(buf):
    import struct
    if buf[:4] != b"SEC ":
        raise ValueError("not a SEC resource")
    ver, _z, tag, n, pool_sz, total = struct.unpack(">6I", buf[4:28])
    ents = []
    for i in range(n):
        t, o, s, nm = struct.unpack(">4I", buf[28 + 16 * i:44 + 16 * i])
        ents.append({"i": i, "type": t, "offset": o, "size": s, "name_off": nm})
    pool = buf[28 + 16 * n:28 + 16 * n + pool_sz]
    return {"version": ver, "tag": tag, "count": n, "pool_size": pool_sz,
            "total_size": total, "entries": ents, "names": [x.decode("latin1") for x in pool.split(b"\0") if x]}


def validate_sec_resource(r):
    e = r["entries"]
    return all(e[i]["offset"] == e[i - 1]["offset"] + e[i - 1]["size"] for i in range(2, len(e))) \
        and e[-1]["offset"] + e[-1]["size"] == r["total_size"]


def decode_gx_cmpr(data, w, h):
    """GameCube CMPR (S3TC/DXT1 in 8x8 tiles of 2x2 4x4 sub-blocks) -> RGBA bytes."""
    import struct
    out = bytearray(w * h * 4)
    p = 0
    for ty in range(0, h, 8):
        for tx in range(0, w, 8):
            for sy in (0, 4):
                for sx in (0, 4):
                    c0, c1, idx = struct.unpack(">HHI", data[p:p + 8]); p += 8

                    def rgb(c):
                        return (((c >> 11) & 31) * 255 // 31, ((c >> 5) & 63) * 255 // 63, (c & 31) * 255 // 31)
                    a, b = rgb(c0), rgb(c1)
                    if c0 > c1:
                        pal = [a + (255,), b + (255,), tuple((2 * x + y) // 3 for x, y in zip(a, b)) + (255,),
                               tuple((x + 2 * y) // 3 for x, y in zip(a, b)) + (255,)]
                    else:
                        pal = [a + (255,), b + (255,), tuple((x + y) // 2 for x, y in zip(a, b)) + (255,), (0, 0, 0, 0)]
                    for py in range(4):
                        for px in range(4):
                            v = pal[(idx >> (30 - 2 * (py * 4 + px))) & 3]
                            o = ((ty + sy + py) * w + tx + sx + px) * 4
                            out[o:o + 4] = bytes(v)
    return bytes(out)
