"""gbox.citra_memory: FCRAM + page-table discovery and guest reads on a fake RetroArch process (no emulator)."""
import struct

import pytest

from gbox import citra_memory as CM

SIG = bytes(range(64))


class FakeProc:
    """Host memory: FCRAM at 0x7f0000000000 (256 MiB + a malloc header page), a 12 MiB heap row holding the page table,
    and another big row that only looks like guest memory."""

    def __init__(self, table_off=0x30, code_phys=0x5000, heap_phys=0x40000):
        self.fc = 0x7F0000000000
        self.fc_end = self.fc + CM.FCRAM_SIZE + 0x1000
        self.fc_base = self.fc + 0x10                         # glibc's mmap chunk header before the user pointer
        self.heap = 0x5500000000
        self.heap_end = self.heap + (12 << 20)
        self.table = self.heap + table_off
        self.mem = {}                                         # sparse: host page -> bytearray(4096)
        self.map_page(0x100000, self.fc_base + code_phys)     # code page 0x100000 -> FCRAM + code_phys
        self.map_page(0x101000, self.fc_base + code_phys + 0x1000)
        self.map_page(0x08000000, self.fc_base + heap_phys)
        self.poke(self.fc_base + code_phys, SIG)
        self.poke(self.fc_base + heap_phys + 0x10, struct.pack("<I", 1234))
        self.decoy = 0x6600000000                             # same pointer value in a region too small to be the table
        self.poke(self.decoy + 0x800, struct.pack("<Q", self.fc_base + code_phys))

    def map_page(self, va, host):
        self.poke(self.table + (va >> 12) * 8, struct.pack("<Q", host))

    def poke(self, host, data):
        for i, b in enumerate(data):
            pg, off = divmod(host + i, 4096)
            self.mem.setdefault(pg, bytearray(4096))[off] = b

    def read(self, host, n):
        if not any(a <= host and host + n <= b for a, b, *_ in self.regions()):
            raise OSError("unmapped")
        out = bytearray(n)
        for pg, page in self.mem.items():
            lo, hi = max(host, pg * 4096), min(host + n, pg * 4096 + 4096)
            if lo < hi:
                out[lo - host:hi - host] = page[lo - pg * 4096:hi - pg * 4096]
        return bytes(out)

    def regions(self):
        return [(self.decoy, self.decoy + 0x10000, True, True),
                (self.heap, self.heap_end, True, True),
                (self.fc, self.fc_end, True, True)]


@pytest.fixture
def proc(monkeypatch):
    monkeypatch.setattr(CM, "SCAN_STEP", 0x400000)
    return FakeProc()


def test_locate_finds_fcram_code_page_and_table(proc):
    where = CM.locate(proc.regions(), proc.read, SIG)
    assert where["fcram"] == (proc.fc, proc.fc_end)
    assert where["code_host"] == proc.fc_base + 0x5000
    assert where["table"] == proc.table


def test_reads_go_through_the_page_table(proc):
    m = CM.CitraMemory(proc.read, proc.regions, SIG)
    assert m.rd(0x100000, 64) == SIG
    assert struct.unpack("<I", m.rd(0x08000010, 4))[0] == 1234
    with pytest.raises(ValueError, match="not mapped"):
        m.rd(0x09000000, 4)


def test_reads_cross_pages(proc):
    m = CM.CitraMemory(proc.read, proc.regions, SIG)
    proc.poke(proc.fc_base + 0x5000 + 0xFFE, b"\xAA\xBB")
    proc.poke(proc.fc_base + 0x6000, b"\xCC\xDD")
    assert m.rd(0x100FFE, 4) == b"\xAA\xBB\xCC\xDD"


def test_a_page_outside_fcram_is_refused(proc):
    proc.map_page(0x1F000000, 0x1234000)                    # VRAM-like: not FCRAM
    m = CM.CitraMemory(proc.read, proc.regions, SIG)
    with pytest.raises(ValueError, match="not in FCRAM"):
        m.rd(0x1F000000, 4)


def test_writes_need_a_writer(proc):
    m = CM.CitraMemory(proc.read, proc.regions, SIG)
    with pytest.raises(PermissionError):
        m.wr(0x08000010, b"\0\0\0\0")
    m2 = CM.CitraMemory(proc.read, proc.regions, SIG, write=proc.poke)
    assert m2.wr(0x08000010, struct.pack("<I", 99)) == 4
    assert struct.unpack("<I", m2.rd(0x08000010, 4))[0] == 99


def test_not_booted_yet(proc):
    with pytest.raises(ValueError, match="no FCRAM page"):
        CM.locate(proc.regions(), proc.read, bytes(range(1, 65)))


def test_signature_must_be_specific():
    with pytest.raises(ValueError):
        CM.locate([], lambda a, n: b"", b"short")


def test_a_copy_of_fcram_without_a_page_table_is_skipped(proc):
    """RetroArch's save-state buffer holds FCRAM again: a hit there is not the guest's memory."""
    decoy = 0x7E0000000000
    proc.poke(decoy + 0x9010, SIG)                          # scanned first (the smaller block), never mapped
    regions = proc.regions

    def with_decoy():
        return [(decoy, decoy + CM.FCRAM_SIZE + 0x800, True, True)] + regions()

    proc.regions = with_decoy
    where = CM.locate(proc.regions(), proc.read, SIG)
    assert where["code_host"] == proc.fc_base + 0x5000 and where["table"] == proc.table


def test_copies_without_any_table_say_so(proc):
    proc.poke(proc.table + 0x100 * 8, b"\0" * 8)            # the page table no longer names the code page
    with pytest.raises(ValueError, match="none mapped"):
        CM.locate(proc.regions(), proc.read, SIG)


# --- RetroArchAdapter: 3DS sessions read and write through the page table ------------------------------------------
class _Proc:
    pid = 4242

    def poll(self):
        return None


class _Mem:
    def __init__(self):
        self.bytes = {}

    def rd(self, va, n):
        return bytes(self.bytes.get(va + i, 0) for i in range(n))

    def wr(self, va, data):
        for i, b in enumerate(data):
            self.bytes[va + i] = b
        return len(data)


def _adapter(monkeypatch, platform="3ds"):
    from gbox import adapters
    from gbox.config import EmulatorConfig
    ad = adapters.RetroArchAdapter(EmulatorConfig(adapter="retroarch", executable="x", core="citra_libretro"),
                                   platform=platform)
    ad.proc, ad.content_path = _Proc(), "game.3ds"
    mem, attached = _Mem(), []

    def attach(pid, signature, writable=False, wide_ok=True):
        attached.append((pid, signature, writable))
        return mem

    monkeypatch.setattr(CM, "attach", attach)
    monkeypatch.setattr(CM, "code_signature", lambda path, n=64: b"S" * 64)
    return ad, mem, attached


def test_retroarch_3ds_reads_go_to_citra(monkeypatch):
    ad, mem, attached = _adapter(monkeypatch)
    mem.wr(0x8D58D0, b"\x90\x24\x30\x08")
    assert ad.read_memory(0x8D58D0, 4) == b"\x90\x24\x30\x08"
    assert ad.read_memory(0x8D58D0, 4) == b"\x90\x24\x30\x08"
    assert attached == [(4242, b"S" * 64, True)]            # attached once per process


def test_retroarch_3ds_writes_are_read_back(monkeypatch):
    ad, mem, _ = _adapter(monkeypatch)
    assert ad.write_memory(0x8303C00, b"\x03\x03") == {"written": 2, "via": "citra_page_table", "verified": True}
    assert mem.rd(0x8303C00, 2) == b"\x03\x03"


def test_other_cores_keep_the_network_commands(monkeypatch):
    ad, _, attached = _adapter(monkeypatch, platform="snes")
    ad.cfg.core = "snes9x"
    assert ad.citra_memory() is None and not attached


def test_boot_retries_are_rate_limited_and_cheap(monkeypatch):
    from gbox import adapters
    ad, _, _ = _adapter(monkeypatch)
    calls = []
    now = [1000.0]
    monkeypatch.setattr(adapters.time, "monotonic", lambda: now[0])

    def attach(pid, signature, writable=False, wide_ok=True):
        calls.append(wide_ok)
        raise ValueError("no FCRAM page holds the game's code yet")

    monkeypatch.setattr(CM, "attach", attach)
    for _ in range(3):
        with pytest.raises(RuntimeError, match="not found yet"):
            ad.read_memory(0x100000, 4)
    assert calls == [False]                                 # one cheap attempt per CITRA_RETRY_S
    for _ in range(4):
        now[0] += adapters.CITRA_RETRY_S
        with pytest.raises(RuntimeError):
            ad.read_memory(0x100000, 4)
    assert calls == [False] * 5                             # never the wide scan (2026-10-28: it starved the i9's worker)


def test_locate_reads_fcram_sized_rows_first_and_skips_wide_ones_when_told(proc):
    """A booting game: the cheap attach never reads a big row of the heap (only FCRAM-sized ones)."""
    big = 0x6000000000
    read_rows = []
    real_read = proc.read
    regions = proc.regions

    def read(host, n):
        if big <= host < big + 0x40000000:
            read_rows.append(host)
        return real_read(host, n)

    proc.regions = lambda: regions() + [(big, big + 0x40000000, True, True)]
    proc.read = read
    where = CM.locate(proc.regions(), proc.read, SIG, wide_ok=False)
    assert where["table"] == proc.table and not read_rows
