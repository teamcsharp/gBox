"""Read-only GameCube disc (ISO/GCM) filesystem: list and extract files via the FST. No writes to the source image."""
import struct
from pathlib import Path


class GCDisc:
    def __init__(self, path):
        self.f = open(path, "rb")
        h = self._r(0, 0x440)
        self.game_id = h[:6].decode("ascii", "replace")
        self.title = h[0x20:0x60].split(b"\0")[0].decode("latin-1")
        fst_off, fst_size = struct.unpack(">II", self._r(0x424, 8))
        fst = self._r(fst_off, fst_size)
        n = struct.unpack_from(">I", fst, 8)[0]
        names = fst[n * 12:]
        self.files: dict[str, tuple[int, int]] = {}
        self.entries: dict[str, int] = {}                  # file -> disc offset of its FST entry (size at +8)
        # walk directory entries: (is_dir, name_off, offset/parent, size/next)
        stack = [("", n)]
        i = 1
        while i < n:
            while stack and i >= stack[-1][1]:
                stack.pop()
            flags_name, a, b = struct.unpack_from(">III", fst, i * 12)
            is_dir, name_off = flags_name >> 24, flags_name & 0xFFFFFF
            name = names[name_off:names.index(b"\0", name_off)].decode("latin-1")
            prefix = stack[-1][0] if stack else ""
            if is_dir:
                stack.append((f"{prefix}{name}/", b))
            else:
                self.files[f"{prefix}{name}"] = (a, b)
                self.entries[f"{prefix}{name}"] = fst_off + i * 12
            i += 1

    def _r(self, off, n):
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


if __name__ == "__main__":
    import sys
    d = GCDisc(sys.argv[1])
    print(d.game_id, d.title, len(d.files), "files")
    for k, (o, s) in sorted(d.files.items()):
        if len(sys.argv) < 3 or sys.argv[2].lower() in k.lower():
            print(f"{s:10d}  {k}")
