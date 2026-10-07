"""Unreal Engine 3 cooked packages (PS3/X360 big-endian, e.g. Stranglehold .xxx): decompress, names, imports, exports.

Enough to map a game's script systems (classes, functions, properties, states) and pull an export's serialized bytes
(UnrealScript bytecode for functions) for analysis. Only zlib-compressed packages (PS3 default); LZO/LZX raise.
"""
import struct
import zlib
from pathlib import Path

TAG = 0x9E2A83C1


def unpack(b: bytes) -> bytes:
    """A 'fully compressed' cooked file (tag, block size, summary, block table, zlib blocks) -> the raw package."""
    if struct.unpack(">I", b[:4])[0] != TAG:
        raise ValueError("not a UE3 package")
    block = struct.unpack(">I", b[4:8])[0]
    if block & 0xFFFF:                                         # a version word, not a block size: already raw
        return b
    _, usz = struct.unpack(">II", b[8:16])
    n = (usz + block - 1) // block
    table = [struct.unpack(">II", b[16 + 8 * i:24 + 8 * i]) for i in range(n)]
    o, out = 16 + 8 * n, bytearray()
    for c, _u in table:
        out += zlib.decompress(b[o:o + c])
        o += c
    return bytes(out)


class Package:
    def __init__(self, path_or_bytes):
        b = Path(path_or_bytes).read_bytes() if not isinstance(path_or_bytes, (bytes, bytearray)) else bytes(path_or_bytes)
        self.d = d = unpack(b)
        v = struct.unpack(">I", d[4:8])[0]
        self.version, self.licensee = v & 0xFFFF, v >> 16
        # summary: Midway adds fields before FolderName; find it by the "None" folder string (always present in cooked data)
        o = d.index(b"\x00\x00\x00\x05None\x00") + 9
        self.flags, nc, no, ec, eo, ic, io = struct.unpack(">7I", d[o:o + 28])
        self.names = []
        p = no
        for _ in range(nc):
            n = struct.unpack(">i", d[p:p + 4])[0]
            self.names.append(d[p + 4:p + 3 + n].decode("latin1"))
            p += 4 + n + 8                                     # string + 64-bit object flags
        self.imports = []
        p = io
        for _ in range(ic):
            cp, _, cn, _, outer, on, num = struct.unpack(">iiiiiii", d[p:p + 28])
            self.imports.append({"class": self.names[cn], "name": self._n(on, num), "outer": outer, "package": self.names[cp]})
            p += 28
        self.exports = []
        p = eo
        for _ in range(ec):
            cls, sup, outer, on, num, arch = struct.unpack(">iiiiii", d[p:p + 24])
            p += 24 + 8                                        # + ObjectFlags (u64)
            size = struct.unpack(">i", d[p:p + 4])[0]
            p += 4
            off = 0
            if size > 0:
                off = struct.unpack(">i", d[p:p + 4])[0]
                p += 4
            comps = struct.unpack(">i", d[p:p + 4])[0]
            p += 4 + 12 * comps
            p += 4                                             # ExportFlags
            nets = struct.unpack(">i", d[p:p + 4])[0]
            p += 4 + 4 * nets + 16                             # net object counts + package guid
            self.exports.append({"class": cls, "super": sup, "outer": outer, "name": self._n(on, num), "size": size, "offset": off})

    def _n(self, i, num=0):
        s = self.names[i] if 0 <= i < len(self.names) else f"?{i}"
        return f"{s}_{num - 1}" if num else s

    def ref(self, i):
        """Object reference -> (class name, object name): >0 export, <0 import, 0 = Class."""
        if i > 0:
            e = self.exports[i - 1]
            return (self.ref(e["class"])[1] if e["class"] else "Class"), e["name"]
        if i < 0:
            m = self.imports[-i - 1]
            return m["class"], m["name"]
        return "Class", "None"

    def path(self, i):
        parts = []
        while i:
            parts.append(self.ref(i)[1])
            i = self.exports[i - 1]["outer"] if i > 0 else self.imports[-i - 1]["outer"]
        return ".".join(reversed(parts))

    def blob(self, i) -> bytes:
        e = self.exports[i - 1]
        return self.d[e["offset"]:e["offset"] + e["size"]]

    def members(self):
        """{class path: [(kind, name)]} for every Function/State/Property declared in this package."""
        out = {}
        for i, e in enumerate(self.exports, 1):
            kind = self.ref(e["class"])[1] if e["class"] else "Class"
            if kind == "Class":
                out.setdefault(e["name"], [])
            elif e["outer"] > 0:
                owner = self.path(e["outer"])
                out.setdefault(owner, []).append((kind, e["name"]))
        return out


NATIVES = {114: "==", 119: "!=", 129: "!", 130: "&&", 131: "^^", 132: "||", 144: "*", 145: "/", 146: "+", 147: "-",
           150: "<", 151: ">", 152: "<=", 153: ">=", 154: "==", 155: "!=", 171: "*", 172: "/", 174: "+", 175: "-",
           176: "<", 177: ">", 180: "==", 181: "!=", 197: "IsA"}


def function_script(pkg: "Package", i: int) -> tuple[bytes, int]:
    """(bytecode, function flags) of export i. ponytail: layout measured on v375/licensee 25 (Stranglehold);
    the script size sits at +0x28 and the code ends with EX_EndOfScript (0x53) -- other licensees may shift it."""
    b = pkg.blob(i)
    n = struct.unpack(">i", b[0x28:0x2C])[0]
    code = b[0x2C:0x2C + n]
    if not code or code[-1] != 0x53:
        raise ValueError("unrecognised function layout")
    flags = struct.unpack(">I", b[0x2C + n + 3:0x2C + n + 7])[0]
    return code, flags


def disassemble(pkg: "Package", code: bytes, linked: list | None = None) -> list[str]:
    """UnrealScript bytecode -> one line per statement: '0012: expr'. Unknown tokens stop the listing with hex.
    linked (optional list) collects (offset, size) of object/name references, which differ once the game is running."""
    o = 0
    linked = [] if linked is None else linked

    def u8():
        nonlocal o
        o += 1
        return code[o - 1]

    def u16():
        nonlocal o
        o += 2
        return struct.unpack(">H", code[o - 2:o])[0]

    def i32():
        nonlocal o
        o += 4
        return struct.unpack(">i", code[o - 4:o])[0]

    def obj():
        linked.append((o, 4))
        v = i32()
        return pkg.path(v).rsplit(".", 1)[-1] if v else "None"

    def name():
        linked.append((o, 8))
        v, _ = i32(), i32()
        return pkg.names[v] if 0 <= v < len(pkg.names) else f"?{v}"

    def args():
        out = []
        while code[o] != 0x16:
            out.append(expr())
        u8()
        return out

    def expr():
        nonlocal o
        t = u8()
        if t in (0x00, 0x01, 0x02, 0x29, 0x48):
            return obj()
        if t == 0x04:
            return f"return {expr()}"
        if t == 0x06:
            return f"goto {u16():04x}"
        if t == 0x07:
            j = u16()
            return f"if !({expr()}) goto {j:04x}"
        if t == 0x0B:
            return ""
        if t in (0x0F, 0x14):
            a = expr()
            return f"{a} = {expr()}"
        if t == 0x10 or t == 0x1A:
            a = expr()
            return f"{expr()}[{a}]"
        if t == 0x12 or t == 0x19:
            a = expr()
            u16(), u8()
            return f"{a}.{expr()}"
        if t == 0x15 or t == 0x16:
            return ""
        if t == 0x17:
            return "self"
        if t == 0x18:
            u16()
            return expr()
        if t == 0x1B:
            n = name()
            return f"{n}({', '.join(args())})"
        if t == 0x1C:
            n = obj()
            return f"{n}({', '.join(args())})"
        if t == 0x1D:
            return str(i32())
        if t == 0x1E:
            return repr(struct.unpack(">f", struct.pack(">i", i32()))[0])
        if t == 0x1F:
            e = code.index(0, o)
            s, o = code[o:e].decode("latin1"), e + 1
            return repr(s)
        if t in (0x22, 0x23):                                  # rotator / vector constant
            v = struct.unpack(">3f" if t == 0x23 else ">3i", code[o:o + 12])
            o += 12
            return ("vect" if t == 0x23 else "rot") + repr(v)
        if t == 0x2F:                                          # foreach
            a = expr()
            return f"foreach {a} (end {u16():04x})"
        if t in (0x30, 0x31):
            return "iterator_pop" if t == 0x30 else "iterator_next"
        if t == 0x36:
            return f"{expr()}.Length"
        if t == 0x49:                                          # default parameter value: skip, expr, EndParmValue
            u16()
            a = expr()
            u8()
            return f"default {a}"
        if t == 0x3A:                                          # return nothing (the return-value property)
            obj()
            return ""
        if t in (0x4A, 0x50):                                  # empty optional parameter
            return "_"
        if t == 0x35:                                          # struct member: property, struct, struct expr (v375)
            m = obj()
            obj()
            return f"{expr()}.{m}"
        if t == 0x20:
            return obj()
        if t == 0x21:
            return f"'{name()}'"
        if t == 0x24 or t == 0x2C:
            return str(u8())
        if t in (0x25, 0x26, 0x27, 0x28, 0x2A):
            return {0x25: "0", 0x26: "1", 0x27: "true", 0x28: "false", 0x2A: "None"}[t]
        if t == 0x2D:
            return expr()
        if t == 0x2E:
            c = obj()
            return f"{c}({expr()})"
        if t == 0x38:
            u8()
            return expr()
        if t == 0x53:
            return "end"
        if 0x60 <= t <= 0x6F:
            n = (t - 0x60) * 256 + u8()
        elif t >= 0x70:
            n = t
        else:
            raise ValueError(f"token {t:02x}")
        a = args()
        op = NATIVES.get(n, f"native{n}")
        if op == "IsA" and len(a) == 1:
            return f"IsA({a[0]})"
        return f"({f' {op} '.join(a)})" if op in NATIVES.values() and len(a) == 2 else f"{op}({', '.join(a)})"

    lines = []
    while o < len(code):
        at = o
        try:
            s = expr()
        except (ValueError, IndexError, struct.error) as e:
            lines.append(f"{at:04x}: ?? {e}: {code[at:].hex(' ')}")
            break
        if s:
            lines.append(f"{at:04x}: {s}")
    return lines


def ram_pattern(pkg: "Package", code: bytes) -> "re.Pattern":
    """Regex that finds this function's bytecode in a running game's RAM (32-bit big-endian targets: same layout
    as on disc, with object pointers and name indices wildcarded)."""
    import re
    linked = []
    disassemble(pkg, code, linked)
    rx, last = b"", 0
    for off, n in sorted(linked):
        rx += re.escape(code[last:off]) + b"." * n
        last = off + n
    return re.compile(rx + re.escape(code[last:]), re.S)


def _selftest():
    names = [b"None", b"Core", b"Thing"]
    body = bytearray(struct.pack(">II", TAG, 0x00190177) + struct.pack(">I", 0) + struct.pack(">i", 5) + b"None\x00")
    hdr = len(body) + 28
    nt = b"".join(struct.pack(">i", len(n) + 1) + n + b"\x00" + b"\x00" * 8 for n in names)
    ex = struct.pack(">iiiiii", 0, 0, 0, 2, 0, 0) + b"\x00" * 8 + struct.pack(">ii", 0, 0) + struct.pack(">ii", 0, 0) + b"\x00" * 16
    body += struct.pack(">7I", 0, 3, hdr, 1, hdr + len(nt), 0, hdr + len(nt) + len(ex)) + nt + ex
    p = Package(bytes(body))
    assert p.names == ["None", "Core", "Thing"] and p.exports[0]["name"] == "Thing" and p.members() == {"Thing": []}
    comp = zlib.compress(bytes(body))
    fc = struct.pack(">II", TAG, 0x10000) + struct.pack(">II", len(comp), len(body)) + struct.pack(">II", len(comp), len(body)) + comp
    assert unpack(fc) == bytes(body)
    print("ue3 selftest ok")


if __name__ == "__main__":
    _selftest()
