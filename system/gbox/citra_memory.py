"""Citra's guest memory seen from the host: a 3DS game's RAM inside RetroArch's citra_libretro core (Linux and Windows).

The citra core gives RetroArch no libretro memory map, so READ_CORE_MEMORY / READ_CORE_RAM fail for 3DS sessions. Its
guest memory is still plain host memory in the emulator process (Citra's src/core/memory.cpp, read 2026-10-27):

  * FCRAM is one std::make_unique<u8[]>(FCRAM_N3DS_SIZE) block: 256 MiB of private read-write memory, an anonymous
    mapping on Linux, one VirtualAlloc'd heap block on Windows. Every page the emulated kernel maps for the game (its
    code set, heap and linear heap) is a page of that block.
  * The process's PageTable starts with pointers.raw[1 << 20]: one host pointer per 4 KiB guest page (null when the page
    is unmapped or is I/O). Guest address -> host address is raw[va >> 12] + (va & 0xFFF).

locate() finds both from a signature the title knows: the first bytes of its own .code, which the loader copies to guest
0x00100000 (every 3DS application's code start). The page of FCRAM that holds them gives the host address that
raw[0x100] must contain; the table is the 8-byte-aligned slot holding that value with raw[0] null and raw[0x101] in
FCRAM too. A read or write goes through the table every time a page is first touched, then from a per-page cache that
refresh() clears; nothing outside a page the table names is ever read or written, so a wrong table can't hand back
another mapping's bytes.
"""
from __future__ import annotations

import os
import struct
import sys

PAGE = 0x1000
CODE_START = 0x00100000
N_ENTRIES = 1 << 20
FCRAM_SIZE = 0x10000000                       # FCRAM_N3DS_SIZE: Citra always allocates the New 3DS size
TABLE_MIN = N_ENTRIES * 8                     # the raw pointer array alone is 8 MiB
TABLE_MAX = 0x4000000                         # Citra's PageTable (raw pointers + refs + attributes) is about 41 MiB
FCRAM_SLACK = 0x400000                        # the allocator's header / a small neighbour merged into the same row
SCAN_STEP = 0x1000000


def _table_for(page: int, fcram: tuple[int, int], rw, read) -> int | None:
    """The page table whose entry 0x100 holds `page` (entry 0 null, entry 0x101 in FCRAM too), or None."""
    want = struct.pack("<Q", page)
    sized = [r for r in rw if TABLE_MIN <= r[1] - r[0] <= TABLE_MAX and r != fcram]
    larger = [r for r in rw if r[1] - r[0] > TABLE_MAX and r != fcram]
    for a, b in sized + larger:                    # the table's own allocation first: a few reads, not the whole heap
        for off in range(0, b - a, SCAN_STEP):
            try:
                blk = read(a + off, min(SCAN_STEP, b - a - off))
            except OSError:
                continue
            i = blk.find(want)
            while i >= 0:
                slot = a + off + i
                table = slot - (CODE_START >> 12) * 8
                if (slot & 7) == 0 and table >= a:
                    try:
                        first, = struct.unpack("<Q", read(table, 8))
                        nxt, = struct.unpack("<Q", read(slot + 8, 8))
                    except (OSError, struct.error):
                        first, nxt = 1, 0
                    if first == 0 and fcram[0] <= nxt < fcram[1]:
                        return table
                i = blk.find(want, i + 1)
    return None


def locate(regions, read, signature: bytes, wide_ok: bool = True) -> dict:
    """{fcram: (lo, hi), code_host, table}: regions [(start, end, writable, private)] of the host process, read(host,
    n) -> bytes (or raises OSError). ValueError when the game isn't loaded yet (no FCRAM page holds the signature).

    Every big block holding the signature is a candidate, smallest first: RetroArch's save-state buffer is a second
    copy of FCRAM (live 2026-10-27: after SAVE_STATE the first hit was in it, at an address no page table names), so a
    hit counts only when a page table points at it."""
    if len(signature) < 32:
        raise ValueError("a code signature of at least 32 bytes is needed")
    rw = [(a, b) for a, b, writable, private in regions if writable and private]
    hits = 0
    # FCRAM-sized rows first (the block itself, or a save-state copy), then any bigger row (a merged neighbour): an
    # attach while the game boots reads one or two 256 MiB rows, not every big row of RetroArch's heap (2026-10-27: the
    # i9 worker stopped answering the Spark 50 s into the first Merc3D boot)
    exact = sorted((r for r in rw if FCRAM_SIZE <= r[1] - r[0] <= FCRAM_SIZE + FCRAM_SLACK), key=lambda r: r[1] - r[0])
    wide = sorted((r for r in rw if r[1] - r[0] > FCRAM_SIZE + FCRAM_SLACK), key=lambda r: r[1] - r[0])
    for a, b in exact + (wide if wide_ok else []):
        for off in range(0, b - a, SCAN_STEP):
            try:
                blk = read(a + off, min(SCAN_STEP + len(signature), b - a - off))
            except OSError:
                continue
            i = blk.find(signature)
            while i >= 0:
                hits += 1
                code_host = a + off + i
                table = _table_for(code_host - (CODE_START & (PAGE - 1)), (a, b), rw, read)
                if table is not None:
                    return {"fcram": (a, b), "code_host": code_host, "table": table}
                i = blk.find(signature, i + 1)
    if not hits:
        raise ValueError("no FCRAM page holds the game's code yet (still booting, or another game)")
    raise ValueError(f"Citra's page table was not found ({hits} copies of the game's code, none mapped)")


class CitraMemory:
    """rd(va, n) / wr(va, data) on a 3DS guest's virtual addresses through Citra's page table. `read(host, n)` and
    `write(host, data)` reach the emulator process; `regions()` lists its memory for locate()."""

    def __init__(self, read, regions, signature: bytes, write=None, wide_ok: bool = True):
        self._read, self._write, self._regions, self.signature = read, write, regions, signature
        self.where = locate(regions(), read, signature, wide_ok=wide_ok)
        self._pages: dict[int, int] = {}

    def refresh(self) -> None:
        self._pages.clear()

    def host(self, va: int) -> int:
        pg = (va & 0xFFFFFFFF) >> 12
        h = self._pages.get(pg)
        if h is None:
            h, = struct.unpack("<Q", self._read(self.where["table"] + pg * 8, 8))
            lo, hi = self.where["fcram"]
            if not h:
                raise ValueError(f"3DS address {va:#x} is not mapped")
            if not lo <= h < hi:                          # VRAM / DSP pages live elsewhere: never guessed at
                raise ValueError(f"3DS address {va:#x} is not in FCRAM")
            self._pages[pg] = h
        return h + (va & (PAGE - 1))

    def rd(self, va: int, n: int) -> bytes:
        out = bytearray()
        while n > 0:
            k = min(n, PAGE - (va & (PAGE - 1)))
            got = self._read(self.host(va), k)
            if len(got) != k:
                raise ValueError(f"3DS address {va:#x} could not be read")
            out += got
            va, n = va + k, n - k
        return bytes(out)

    read_memory = rd

    def wr(self, va: int, data: bytes) -> int:
        if self._write is None:
            raise PermissionError("this Citra memory view is read-only")
        done = 0
        while done < len(data):
            k = min(len(data) - done, PAGE - (va & (PAGE - 1)))
            self._write(self.host(va), data[done:done + k])
            va, done = va + k, done + k
        return done

    def mapped(self) -> list[tuple[int, int]]:
        """[(va, size)] runs of guest pages the table maps (reads the whole 8 MiB table)."""
        ents = struct.unpack(f"<{N_ENTRIES}Q", self._read(self.where["table"], N_ENTRIES * 8))
        runs, start = [], None
        for i, e in enumerate(ents + (0,)):
            if e and start is None:
                start = i
            elif not e and start is not None:
                runs.append((start << 12, (i - start) << 12))
                start = None
        return runs


# --- the emulator process --------------------------------------------------------------------------------------------
def _linux(pid: int, writable: bool):
    f = open(f"/proc/{pid}/mem", "rb+" if writable else "rb", 0)

    def read(host, n):
        f.seek(host)
        return f.read(n)

    def write(host, data):
        f.seek(host)
        f.write(data)

    def regions():
        out = []
        with open(f"/proc/{pid}/maps") as m:
            for ln in m:
                p = ln.split(None, 5)
                a, b = (int(x, 16) for x in p[0].split("-"))
                path = p[5].strip() if len(p) > 5 else ""
                out.append((a, b, p[1][:2] == "rw", path in ("", "[heap]")))
        return out

    return read, (write if writable else None), regions


def _windows(pid: int, writable: bool):
    import ctypes
    import ctypes.wintypes as w
    k32 = ctypes.windll.kernel32
    k32.OpenProcess.restype = ctypes.c_void_p
    access = 0x0400 | 0x0010 | ((0x0020 | 0x0008) if writable else 0)   # QUERY_INFORMATION | VM_READ (| WRITE | OPERATION)
    handle = k32.OpenProcess(access, False, pid)
    if not handle:
        raise PermissionError(f"cannot open process {pid}")

    class MBI(ctypes.Structure):
        _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p), ("AllocationProtect", w.DWORD),
                    ("PartitionId", w.WORD), ("RegionSize", ctypes.c_size_t), ("State", w.DWORD), ("Protect", w.DWORD),
                    ("Type", w.DWORD)]

    def read(host, n):
        buf, got = ctypes.create_string_buffer(n), ctypes.c_size_t()
        if not k32.ReadProcessMemory(ctypes.c_void_p(handle), ctypes.c_void_p(host), buf, n, ctypes.byref(got)):
            raise OSError(f"ReadProcessMemory {host:#x} failed")
        return buf.raw[:got.value]

    def write(host, data):
        n = ctypes.c_size_t()
        if not k32.WriteProcessMemory(ctypes.c_void_p(handle), ctypes.c_void_p(host), data, len(data), ctypes.byref(n)):
            raise OSError(f"WriteProcessMemory {host:#x} failed")

    def regions():
        out, a, m = [], 0, MBI()
        while a < 1 << 47 and k32.VirtualQueryEx(ctypes.c_void_p(handle), ctypes.c_void_p(a), ctypes.byref(m),
                                                 ctypes.sizeof(m)):
            size = m.RegionSize
            if m.State == 0x1000 and not m.Protect & 0x101:                 # MEM_COMMIT, not NOACCESS / GUARD
                out.append((a, a + size, bool(m.Protect & 0x44), m.Type == 0x20000,   # READWRITE|EXECUTE_READWRITE, MEM_PRIVATE
                            m.AllocationBase or 0))
            a = (m.BaseAddress or 0) + size
        merged = []
        for r in out:                                       # one VirtualAlloc block can come back as several rows; two
            if merged and merged[-1][1] == r[0] and merged[-1][2:] == r[2:]:     # allocations never merge (sizes matter)
                merged[-1] = (merged[-1][0], r[1], *r[2:])
            else:
                merged.append(r)
        return [r[:4] for r in merged]

    return read, (write if writable else None), regions


def attach(pid: int, signature: bytes, writable: bool = False, wide_ok: bool = True) -> CitraMemory:
    """The 3DS guest of the RetroArch (citra_libretro) process `pid` on this host. wide_ok False: FCRAM-sized rows only
    (the cheap attach the adapter retries while the game boots)."""
    read, write, regions = (_windows if sys.platform == "win32" else _linux)(pid, writable)
    return CitraMemory(read, regions, signature, write=write, wide_ok=wide_ok)


_SIGNATURES: dict[tuple, bytes] = {}


def code_signature(path, n: int = 64) -> bytes:
    """The first n bytes of a decrypted 3DS image's code (its ExeFS .code, BLZ-decompressed when the exheader says so):
    what the loader puts at guest 0x00100000. Cached per file (path, size, mtime)."""
    if not path:
        raise ValueError("the session's 3DS content path is unknown")
    st = os.stat(path)
    key = (str(path), st.st_size, st.st_mtime_ns, n)
    if key not in _SIGNATURES:
        from .ctr_romfs import CtrImage, blz_decompress
        with CtrImage(path) as img:
            code = img.exefs_file(".code")
            if img.exheader().get("code_compressed"):
                code = blz_decompress(code)
        _SIGNATURES[key] = bytes(code[:n])
    return _SIGNATURES[key]


def is_citra(ad) -> bool:
    """A RetroArch session running the citra core (its -L argument), on any host."""
    core = str(getattr(ad, "core_path", "") or getattr(getattr(ad, "cfg", None), "core", "") or "")
    return getattr(ad, "platform", None) == "3ds" or "citra" in os.path.basename(core).lower()
