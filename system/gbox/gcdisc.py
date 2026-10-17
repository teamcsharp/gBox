"""Read-only GameCube disc (ISO/GCM) filesystem: list and extract files via the FST. No writes to the source image."""
import struct
from pathlib import Path


class GCDisc:
    """path: a plain .iso/.gcm, or a Dolphin .gcz read in place (gbox.gcz; only the touched blocks are inflated)."""

    def __init__(self, path):
        self._gcz = None
        if str(path).lower().endswith(".gcz"):
            from .gcz import GCZ
            self._gcz = GCZ(str(path))
            self.f = self._gcz._f
        else:
            self.f = open(path, "rb")
        h = self._r(0, 0x440)
        self.game_id = h[:6].decode("ascii", "replace")
        self.title = h[0x20:0x60].split(b"\0")[0].decode("latin-1")
        fst_off, fst_size = struct.unpack(">II", self._r(0x424, 8))
        from .formats.gcfst import parse_fst              # the shared FST walk (gbox.formats)
        self.files: dict[str, tuple[int, int]] = {}
        self.entries: dict[str, int] = {}                  # file -> disc offset of its FST entry (size at +8)
        for path, a, b, entry in parse_fst(self._r(fst_off, fst_size), fst_off):
            self.files[path] = (a, b)
            self.entries[path] = entry

    def _r(self, off, n):
        if self._gcz is not None:
            out = self._gcz.read(off, n)
            self._gcz._cache.clear()                     # keep memory flat over a whole-disc walk
            return out
        self.f.seek(off)
        return self.f.read(n)

    def read(self, name: str) -> bytes:
        off, size = self.files[name]
        return self._r(off, size)

    def extract(self, name: str, dst: Path) -> Path:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(self.read(name))
        return dst


    def dol(self) -> bytes:
        """The main executable (main.dol): its offset is in the disc header at 0x420."""
        off = struct.unpack(">I", self._r(0x420, 4))[0]
        hdr = self._r(off, 0x100)
        offs, sizes = struct.unpack_from(">18I", hdr, 0), struct.unpack_from(">18I", hdr, 0x90)
        end = max(o + s for o, s in zip(offs, sizes) if s)
        return self._r(off, end)


def dol_to_elf(dol: bytes) -> bytes:
    """GameCube DOL -> ELF32 big-endian PowerPC (one PT_LOAD per text/data section + bss), so Ghidra imports it
    with correct addresses and entry point."""
    offs, addrs, sizes = (struct.unpack_from(">18I", dol, o) for o in (0x00, 0x48, 0x90))
    bss_addr, bss_size, entry = struct.unpack_from(">3I", dol, 0xD8)
    segs = [(offs[i], addrs[i], sizes[i], 5 if i < 7 else 6) for i in range(18) if sizes[i]]   # 5 = R+X, 6 = R+W
    phnum = len(segs) + (1 if bss_size else 0)
    data_off = 52 + 32 * phnum
    body, ph = bytearray(), bytearray()
    for (o, va, n, flags) in segs:
        ph += struct.pack(">8I", 1, data_off + len(body), va, va, n, n, flags, 32)
        body += dol[o:o + n]
    if bss_size:
        ph += struct.pack(">8I", 1, data_off + len(body), bss_addr, bss_addr, 0, bss_size, 6, 32)
    ehdr = b"ELF" + bytes([1, 2, 1, 0]) + bytes(8) + struct.pack(">HHIIIIIHHHHHH", 2, 20, 1, entry, 52, 0, 0, 52, 32, phnum, 40, 0, 0)
    return ehdr + bytes(ph) + bytes(body)


def ram_to_elf(ram: bytes, base: int, entry: int, machine: int = 20, big_endian: bool = True) -> bytes:
    """Live-memory snapshot -> ELF32 with one RWX PT_LOAD at `base`, for static analysis of code that the game
    unpacks or loads at runtime (PSO's main.dol is only a loader). machine 20 = PowerPC, 42 = SuperH."""
    e = ">" if big_endian else "<"
    ehdr = b"ELF" + bytes([1, 2 if big_endian else 1, 1, 0]) + bytes(8) + struct.pack(
        e + "HHIIIIIHHHHHH", 2, machine, 1, entry, 52, 0, 0, 52, 32, 1, 40, 0, 0)
    ph = struct.pack(e + "8I", 1, 84, base, base, len(ram), len(ram), 7, 32)
    return ehdr + ph + ram


REL_BASE = 0x80300000


def rel_sections(rel: bytes, base: int = REL_BASE) -> list[tuple[int, int, bool] | None]:
    """A GameCube REL module's sections laid out as OSLink does in place: [(address, size, executable) | None];
    bss goes right after the image (32-aligned)."""
    n, so = struct.unpack_from(">II", rel, 0x0C)
    bss = (base + len(rel) + 31) & ~31
    out = []
    for i in range(n):
        o, s = struct.unpack_from(">II", rel, so + 8 * i)
        out.append(None if not s else (bss, s, False) if not (o & ~1) else (base + (o & ~1), s, bool(o & 1)))
    return out


def rel_link(rel: bytes, base: int = REL_BASE) -> bytes:
    """Apply a REL's relocations (its own sections at `base`, module 0 = main.dol by absolute address) -> the module
    image as it sits in RAM (Ghidra then sees the real call targets and data pointers)."""
    img = bytearray(rel)
    secs = rel_sections(rel, base)
    mid, imp_off, imp_size = struct.unpack_from(">I", rel, 0)[0], *struct.unpack_from(">II", rel, 0x28)
    for k in range(imp_size // 8):
        mod, p = struct.unpack_from(">II", rel, imp_off + 8 * k)
        cur = None
        while True:
            delta, typ, sec, add = struct.unpack_from(">HBBI", rel, p)
            p += 8
            if typ == 203:                                  # R_DOLPHIN_END
                break
            if typ == 202:                                  # R_DOLPHIN_SECTION
                cur = secs[sec][0]
                continue
            cur += delta
            if typ in (0, 201):
                continue
            S = (secs[sec][0] + add) if mod == mid else add
            fo = cur - base
            ins = struct.unpack_from(">I", img, fo)[0] if typ in (2, 10, 11) else 0
            if typ == 1:
                struct.pack_into(">I", img, fo, S & 0xFFFFFFFF)
            elif typ in (4, 5, 6):
                v = S & 0xFFFF if typ == 4 else (S >> 16) & 0xFFFF if typ == 5 else ((S + 0x8000) >> 16) & 0xFFFF
                struct.pack_into(">H", img, fo, v)
            elif typ == 10:
                struct.pack_into(">I", img, fo, (ins & 0xFC000003) | ((S - cur) & 0x3FFFFFC))
            elif typ == 2:
                struct.pack_into(">I", img, fo, (ins & 0xFC000003) | (S & 0x3FFFFFC))
            elif typ == 11:
                struct.pack_into(">I", img, fo, (ins & 0xFFFF0003) | ((S - cur) & 0xFFFC))
            else:
                raise ValueError(f"REL relocation type {typ} not handled")
    return bytes(img)


def depair(code: bytes) -> bytes:
    """Gekko paired-single instructions rewritten for stock Ghidra PowerPC (no Gekko language): psq_l(u) ->
    lfs(u), psq_st(u) -> stfs(u) (12-bit offset sign-extended), the other opcode-4 ops -> nop. Integer / pointer
    data flow stays intact, which is what format work needs (TTS model loader and draw loop: docs/twin_snakes.md)."""
    b = bytearray(code)
    for o in range(0, len(b) - 3, 4):
        w = struct.unpack_from(">I", b, o)[0]
        op = w >> 26
        if op in (56, 57, 60, 61):
            d = w & 0xFFF
            d = d - 0x1000 if d & 0x800 else d
            w = ({56: 48, 57: 49, 60: 52, 61: 53}[op] << 26) | (w & 0x03FF0000) | (d & 0xFFFF)
            struct.pack_into(">I", b, o, w)
        elif op == 4:
            struct.pack_into(">I", b, o, 0x60000000)
    return bytes(b)


def dol_rel_to_elf(dol: bytes, rel: bytes, base: int = REL_BASE, gekko: bool = True) -> bytes:
    """main.dol + a REL module (linked at `base`) -> one ELF32 for Ghidra. Games whose code lives in a REL (Twin
    Snakes: shared/mgso.rel; main.dol is the SDK) need both. gekko=True runs depair() over the executable segments."""
    img = rel_link(rel, base)
    offs, addrs, sizes = (struct.unpack_from(">18I", dol, o) for o in (0x00, 0x48, 0x90))
    dbss, dbss_size, entry = struct.unpack_from(">3I", dol, 0xD8)
    segs = [(dol[offs[i]:offs[i] + sizes[i]], addrs[i], sizes[i], 5 if i < 7 else 6) for i in range(18) if sizes[i]]
    if dbss_size:
        segs.append((b"", dbss, dbss_size, 6))
    for s in rel_sections(rel, base):
        if s:
            a, n, ex = s
            data = b"" if a >= base + len(rel) else img[a - base:a - base + n]
            segs.append((data, a, n, 5 if ex else 6))
    if gekko:
        segs = [(depair(d) if f == 5 else d, a, n, f) for d, a, n, f in segs]
    data_off = 52 + 32 * len(segs)
    body, ph = bytearray(), bytearray()
    for data, va, n, flags in segs:
        ph += struct.pack(">8I", 1, data_off + len(body), va, va, len(data), n, flags, 32)
        body += data
    ehdr = b"\x7fELF" + bytes([1, 2, 1, 0]) + bytes(8) + struct.pack(">HHIIIIIHHHHHH", 2, 20, 1, entry, 52, 0, 0, 52,
                                                                      32, len(segs), 40, 0, 0)
    return ehdr + bytes(ph) + bytes(body)


if __name__ == "__main__":
    import sys
    d = GCDisc(sys.argv[1])
    print(d.game_id, d.title, len(d.files), "files")
    for k, (o, s) in sorted(d.files.items()):
        if len(sys.argv) < 3 or sys.argv[2].lower() in k.lower():
            print(f"{s:10d}  {k}")
