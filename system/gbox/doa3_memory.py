"""Identity-checked guest RAM for the reviewed DOA3 native runner: reads, and read-back-verified writes outside the code."""
from __future__ import annotations

import hashlib
from pathlib import Path
import struct

from .registry import ToolUnavailable, Unsupported

RAM_SIZE = 0x04000000
ALIASES = (0, 0x80000000, 0xF0000000)
READ_ACCESS = 0x0400 | 0x0010  # PROCESS_QUERY_INFORMATION | PROCESS_VM_READ only.
WRITE_ACCESS = READ_ACCESS | 0x0020 | 0x0008  # + PROCESS_VM_WRITE | PROCESS_VM_OPERATION, for verified guest RAM writes
MAX_WRITE = 4096


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024**2), b""):
            digest.update(block)
    return digest.hexdigest()


def _anchor_digest(item, data):
    if item.get("mutable_dwords"):
        data = bytearray(data)
        for offset in item["mutable_dwords"]:
            data[offset:offset + 4] = b"\0" * 4
    return hashlib.sha256(data).hexdigest()


KERNEL_THUNK_KEYS = (0x5B6D40B6, 0xEFB1F152)  # retail, debug: the runner's XBE parser takes the one inside the image
# The kernel *data* exports the pinned runner (runner.cpp v0.2, kernelDataAddress / materializeKernelDataExports)
# writes into their thunk-table slots at boot, pointing them at its kernel data area (0x00F80000 + n): ExEventObjectType
# 16, HalDiskCachePartitionCount 40, KeTickCount 156, LaunchDataPage 164, PsThreadObjectType 259, XboxHardwareInfo 322,
# XboxHDKey 323, XboxKrnlVersion 324, XboxSignatureKey 325, XboxAlternateSignatureKeys 354, HalBootSMCVideoMode 356.
# Imported kernel functions keep their ordinals there (the runner dispatches them by ordinal), so they stay verified.
RUNNER_KERNEL_DATA_EXPORTS = frozenset({16, 40, 156, 164, 259, 322, 323, 324, 325, 354, 356})


def runner_thunk_slots(xbe: bytes) -> list[int]:
    """Guest addresses of the kernel thunk slots the runner overwrites: the data-export entries of the XBE's kernel
    thunk table (zero-terminated ordinals, the low 9 bits as the runner reads them)."""
    u32 = lambda offset: struct.unpack_from("<I", xbe, offset)[0]
    base, image, count, table = u32(0x104), u32(0x10C), u32(0x11C), u32(0x120) - u32(0x104)
    thunk = next((u32(0x158) ^ key for key in KERNEL_THUNK_KEYS if base <= u32(0x158) ^ key < base + image), None)
    if thunk is None:
        raise Unsupported("DOA3 XBE kernel thunk table lies outside its image")
    for index in range(count):
        _, guest, _, raw, size = struct.unpack_from("<IIIII", xbe, table + index * 56)
        if guest <= thunk < guest + size:
            offset = raw + thunk - guest
            break
    else:
        raise Unsupported("DOA3 XBE kernel thunk table is not in a loaded section")
    slots = []
    for index in range(4096):
        if offset + index * 4 + 4 > len(xbe):
            raise Unsupported("DOA3 XBE kernel thunk table has no terminator")
        value = u32(offset + index * 4)
        if not value:
            return slots
        if value & 0x1FF in RUNNER_KERNEL_DATA_EXPORTS:
            slots.append(thunk + index * 4)
    raise Unsupported("DOA3 XBE kernel thunk table has no terminator")


def anchors(xbe: bytes, expected_sha256: str) -> list[dict]:
    """Check the mapped header and every immutable executable section.

    Upstream kernel_memory.c's load/unload-section routines change only each
    section header's reference-count DWORD (+0x18). Normalize those explicit
    counters; every other mapped header byte must still match the reviewed XBE.
    The runner also fills the kernel data-export slots of the thunk table (in
    DOA3's .rdata, an immutable section) at boot: those DWORDs are normalized
    too (runner_thunk_slots), every other section byte stays verified.
    """
    if len(xbe) < 0x178 or hashlib.sha256(xbe).hexdigest() != expected_sha256 or xbe[:4] != b"XBEH":
        raise Unsupported("DOA3 live memory needs the exact reviewed USA XBE")
    u32 = lambda offset: struct.unpack_from("<I", xbe, offset)[0]
    base, header_size, count = u32(0x104), u32(0x108), u32(0x11C)
    table = u32(0x120) - base
    if base != 0x10000 or not 0x178 <= header_size <= 65536 or header_size > len(xbe) or not 1 <= count <= 128 or table < 0x178 or table + count * 56 > header_size:
        raise Unsupported("DOA3 XBE has an unsupported mapped header layout")
    result = [{"guest": base, "data": xbe[:header_size], "kind": "xbe_header",
               "mutable_dwords": [table + index * 56 + 0x18 for index in range(count)]}]
    slots = runner_thunk_slots(xbe)
    for index in range(count):
        offset = table + index * 56
        flags, guest, virtual_size, raw, size = struct.unpack_from("<IIIII", xbe, offset)
        if flags & 4 and not flags & 1 and size:
            if guest < base + header_size or guest + max(virtual_size, size) > RAM_SIZE or raw + size > len(xbe):
                raise Unsupported("DOA3 immutable text section leaves its expected bounds")
            item = {"guest": guest, "data": xbe[raw:raw + size], "kind": "immutable_text"}
            mutable = [slot - guest for slot in slots if guest <= slot and slot + 4 <= guest + size]
            if mutable:
                item["mutable_dwords"] = mutable
            result.append(item)
    if len(result) < 2:
        raise Unsupported("DOA3 XBE has no immutable executable section anchors")
    for item in result:
        item["sha256"] = _anchor_digest(item, item["data"])
    return result


def image_layout(xbe: bytes) -> dict:
    """A bounded initial analysis span from the already hash-verified XBE."""
    base, image_size = struct.unpack_from("<I", xbe, 0x104)[0], struct.unpack_from("<I", xbe, 0x10C)[0]
    count, table = struct.unpack_from("<II", xbe, 0x11C)
    table -= base
    entry = struct.unpack_from("<I", xbe, 0x128)[0] ^ 0xA8FC57AB  # Upstream ENTRY_RETAIL_XOR.
    end, sections = base + image_size, []
    if not 0 < image_size or end > RAM_SIZE:
        raise Unsupported("DOA3 XBE analysis image leaves guest RAM")
    for index in range(count):
        flags, guest, virtual_size, _, raw_size = struct.unpack_from("<IIIII", xbe, table + index * 56)
        size = max(virtual_size, raw_size)
        if guest < base or guest + size > end:
            raise Unsupported("DOA3 XBE section leaves its declared image span")
        sections.append({"address": guest, "size": size, "executable": bool(flags & 4), "writable": bool(flags & 1)})
    if not any(row["executable"] and row["address"] <= entry < row["address"] + row["size"] for row in sections):
        raise Unsupported("DOA3 retail entry point does not lie in its reviewed executable sections")
    return {"analysis_range": {"address": base, "size": image_size}, "entry_point": entry, "sections": sections}


def _readable(region):
    return (region["state"] == 0x1000 and region["type"] == 0x20000
            and not region["protect"] & 0x100 and region["protect"] & 0xFF in (4, 8))


def validate(reader, base: int, expected: list[dict]):
    region = reader.region(base)
    if not _readable(region) or not region["base"] <= base or base + RAM_SIZE > region["base"] + region["size"]:
        raise Unsupported("DOA3 guest allocation is no longer one readable private RAM span")
    for item in expected:
        data = reader.read(base + item["guest"], len(item["data"]))
        if _anchor_digest(item, data) != item["sha256"]:
            raise Unsupported("DOA3 guest RAM header/text validation changed")


def discover(reader, expected: list[dict]) -> int:
    """A unique allocation must match all source anchors, never just XBEH."""
    header = expected[0]
    matches, candidates = set(), 0
    for region in reader.regions():
        if not _readable(region) or not RAM_SIZE <= region["size"] <= RAM_SIZE + 1024**2:
            continue
        candidates += 1
        if candidates > 128:
            raise Unsupported("Too many candidate native RAM allocations to identify safely")
        start = region["base"] + header["guest"]
        probe = reader.read(start, 65536 + len(header["data"]))
        position = probe.find(b"XBEH")
        while position >= 0:
            base = start + position - header["guest"]
            try:
                validate(reader, base, expected)
            except Unsupported:
                pass
            else:
                matches.add(base)
            position = probe.find(b"XBEH", position + 1)
    if len(matches) != 1:
        raise Unsupported(f"DOA3 guest RAM has no unique verified allocation (found {len(matches)})")
    return matches.pop()


class _WindowsReader:
    """A scoped process handle: read/query only by default; WRITE_ACCESS adds VM write for a verified guest RAM write."""
    def __init__(self, pid, born, access=READ_ACCESS):
        import ctypes
        from ctypes import wintypes as w
        if ctypes.sizeof(ctypes.c_void_p) != 8:
            raise Unsupported("DOA3 native RAM requires a 64-bit Windows worker")
        self.ctypes, self.w = ctypes, w
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        self.kernel.OpenProcess.restype = w.HANDLE
        self.kernel.CloseHandle.argtypes = [w.HANDLE]
        self.kernel.GetProcessTimes.argtypes = [w.HANDLE] + [ctypes.POINTER(w.FILETIME)] * 4
        self.kernel.GetProcessTimes.restype = w.BOOL
        self.kernel.ReadProcessMemory.argtypes = [w.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
        self.kernel.ReadProcessMemory.restype = w.BOOL
        class MBI(ctypes.Structure):
            _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                        ("AllocationProtect", w.DWORD), ("RegionSize", ctypes.c_size_t),
                        ("State", w.DWORD), ("Protect", w.DWORD), ("Type", w.DWORD)]
        self.MBI = MBI
        self.kernel.VirtualQueryEx.argtypes = [w.HANDLE, ctypes.c_void_p, ctypes.POINTER(MBI), ctypes.c_size_t]
        self.kernel.VirtualQueryEx.restype = ctypes.c_size_t
        class SystemInfo(ctypes.Structure):
            _fields_ = [("architecture", w.DWORD), ("page_size", w.DWORD), ("minimum", ctypes.c_void_p),
                        ("maximum", ctypes.c_void_p), ("processor_mask", ctypes.c_size_t),
                        ("processors", w.DWORD), ("processor_type", w.DWORD), ("granularity", w.DWORD),
                        ("processor_level", w.WORD), ("processor_revision", w.WORD)]
        self.kernel.GetNativeSystemInfo.argtypes = [ctypes.POINTER(SystemInfo)]
        info = SystemInfo()
        self.kernel.GetNativeSystemInfo(ctypes.byref(info))
        self.maximum_address = int(info.maximum or 0)
        if not 0 < self.maximum_address <= 0x7FFFFFFFFFFF:
            raise Unsupported("Native Windows address-space bounds could not be verified")
        self.handle = self.kernel.OpenProcess(access, False, pid)
        if not self.handle:
            raise Unsupported("Cannot open the owned native DOA3 process for "
                              + ("read-only inspection" if access == READ_ACCESS else "a guest RAM write"))
        try:
            created, exited, kernel, user = (w.FILETIME() for _ in range(4))
            if not self.kernel.GetProcessTimes(self.handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel), ctypes.byref(user)):
                raise Unsupported("Cannot verify the owned native process creation time")
            actual = ((created.dwHighDateTime << 32) | created.dwLowDateTime) / 1e7 - 11644473600
            if abs(actual - born) > 0.01:
                raise Unsupported("Native DOA3 process handle belongs to a different process identity")
        except Exception:
            self.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None

    def region(self, address):
        info = self.MBI()
        if self.kernel.VirtualQueryEx(self.handle, self.ctypes.c_void_p(address), self.ctypes.byref(info), self.ctypes.sizeof(info)) != self.ctypes.sizeof(info):
            raise Unsupported("Cannot verify a native DOA3 memory region")
        return {"base": int(info.BaseAddress or 0), "size": info.RegionSize, "state": info.State,
                "protect": info.Protect, "type": info.Type}

    def regions(self):
        address = 0
        for _ in range(100000):
            if address > self.maximum_address:
                break
            region = self.region(address)  # Any incomplete walk fails closed.
            yield region
            end = region["base"] + region["size"]
            if end <= address:
                raise Unsupported("Native memory map has a nonadvancing region")
            address = end
        else:
            raise Unsupported("Native memory map exceeded its bounded region count")

    def read(self, address, size):
        if not 0 <= address <= 0x7FFFFFFFFFFF or not 0 < size <= RAM_SIZE:
            raise Unsupported("Native memory read is outside its supported bounds")
        buffer, got = self.ctypes.create_string_buffer(size), self.ctypes.c_size_t()
        if not self.kernel.ReadProcessMemory(self.handle, self.ctypes.c_void_p(address), buffer, size, self.ctypes.byref(got)) or got.value != size:
            raise Unsupported("Owned native DOA3 memory could not be read completely")
        return buffer.raw

    def write(self, address, data: bytes):
        if not 0 <= address <= 0x7FFFFFFFFFFF or not 0 < len(data) <= MAX_WRITE:
            raise Unsupported("Native memory write is outside its supported bounds")
        w, ctypes = self.w, self.ctypes
        self.kernel.WriteProcessMemory.argtypes = [w.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
        self.kernel.WriteProcessMemory.restype = w.BOOL
        buffer, put = self.ctypes.create_string_buffer(bytes(data), len(data)), self.ctypes.c_size_t()
        if not self.kernel.WriteProcessMemory(self.handle, self.ctypes.c_void_p(address), buffer, len(data), self.ctypes.byref(put)) or put.value != len(data):
            raise Unsupported("Owned native DOA3 memory could not be written completely")


def _overlaps_anchor(expected, offset, length) -> bool:
    """True when [offset, offset+length) touches the mapped XBE header or an immutable code section."""
    return any(item["guest"] < offset + length and offset < item["guest"] + len(item["data"]) for item in expected)


class GuestMemory:
    def __init__(self, owner, exe: Path, xbe: Path, runner_sha256: str, xbe_sha256: str):
        self.owner, self.exe, self.xbe = owner, Path(exe).absolute(), Path(xbe).absolute()
        self.pid = owner.render_pid
        self.born = owner._owned.get(self.pid)
        self.runner_sha256, self.xbe_sha256 = runner_sha256, xbe_sha256
        self.base = None
        self._identity()
        source = self.xbe.read_bytes()
        self.expected = anchors(source, xbe_sha256)
        self.layout = image_layout(source)

    def _owner_check(self):
        if not self.owner.ready or self.owner.render_pid != self.pid or self.born is None or self.owner._owned.get(self.pid) != self.born:
            raise Unsupported("Native memory is restricted to this adapter's owned running process")

    def _identity(self, hashes: bool = True):
        """The owned process (birth, path, alive) and, with hashes, the pinned runner and XBE files."""
        import psutil
        from .doa3_native import _plain_path
        self._owner_check()
        try:
            process = psutil.Process(self.pid)
            if abs(process.create_time() - self.born) > 0.01 or not process.is_running() or process.status() == psutil.STATUS_ZOMBIE or Path(process.exe()).absolute() != self.exe:
                raise Unsupported("Native DOA3 process identity changed")
            if hashes:
                _plain_path(self.exe)
                _plain_path(self.xbe)
                if _sha(self.exe) != self.runner_sha256 or _sha(self.xbe) != self.xbe_sha256:
                    raise Unsupported("Native DOA3 executable/source checksum differs from the reviewed build")
        except (psutil.Error, OSError, ToolUnavailable) as error:
            raise Unsupported("Cannot verify the owned native DOA3 process and source") from error

    def _verified(self, reader):
        # Each caller already verified identity before opening this scoped,
        # creation-time-checked handle. Avoid rehashing both files redundantly.
        if self.base is None:
            self.base = discover(reader, self.expected)
        validate(reader, self.base, self.expected)

    def memory_map(self):
        self._identity()
        with _WindowsReader(self.pid, self.born) as reader:
            self._verified(reader)
            self._identity()
        return {"verified": True, "address_space": "guest", "platform": "xbox", "processor": "x86:LE:32:default",
                "endianness": "little", "bits": 32, "pid": self.pid, "process_created": self.born,
                "host_base": hex(self.base), "regions": [{"address": 0, "size": RAM_SIZE, "kind": "ram", "readable": True, "writable": True}],
                "aliases": list(ALIASES), "runner_sha256": self.runner_sha256, "xbe_sha256": self.xbe_sha256, **self.layout,
                "anchors": [{"address": item["guest"], "length": len(item["data"]), "sha256": item["sha256"], "kind": item["kind"],
                             "mutable_dwords": [item["guest"] + offset for offset in item.get("mutable_dwords", [])]} for item in self.expected],
                "validation": "Owned process creation time, pinned binary/XBE, mapped header except section reference counters and all immutable text revalidated"}

    def read(self, address, length):
        if type(address) is not int or type(length) is not int or not 0 < length <= RAM_SIZE:
            raise ValueError("DOA3 memory reads require an integer address and 1..64MiB length")
        window, offset = address & ~0x03FFFFFF, address & 0x03FFFFFF
        if address < 0 or window not in ALIASES or offset + length > RAM_SIZE:
            raise ValueError("DOA3 memory read leaves verified guest RAM")
        self._identity()
        with _WindowsReader(self.pid, self.born) as reader:
            self._verified(reader)
            data = reader.read(self.base + offset, length)
            validate(reader, self.base, self.expected)
            self._identity()
            return data

    def write(self, address, data: bytes) -> dict:
        """Write guest RAM of the owned, identity-checked runner (unlock-on-load holds, cheats). The mapped XBE header
        and immutable code sections are refused, and every write is read back."""
        data = bytes(data)
        if type(address) is not int or not 0 < len(data) <= MAX_WRITE:
            raise ValueError("DOA3 memory writes require an integer address and 1..4096 bytes")
        window, offset = address & ~0x03FFFFFF, address & 0x03FFFFFF
        if address < 0 or window not in ALIASES or offset + len(data) > RAM_SIZE:
            raise ValueError("DOA3 memory write leaves verified guest RAM")
        if _overlaps_anchor(self.expected, offset, len(data)):
            raise ValueError("DOA3 memory write would touch the XBE header or immutable code")
        self._identity()
        with _WindowsReader(self.pid, self.born, WRITE_ACCESS) as handle:
            self._verified(handle)
            handle.write(self.base + offset, data)
            back = handle.read(self.base + offset, len(data))
            validate(handle, self.base, self.expected)
            self._identity()
        if back != data:
            raise RuntimeError(f"DOA3 memory write at {address:#x} did not read back")
        return {"written": len(data), "via": "native_guest_ram", "verified": True}

    def channel(self, writable=()) -> "Channel":
        """A Channel for per-frame reads (and writes to `writable` only): see Channel."""
        return Channel(self, writable)


def _guest_offset(address, length) -> int:
    if type(address) is not int or type(length) is not int or not 0 < length <= RAM_SIZE:
        raise ValueError("DOA3 memory access requires an integer address and a positive length")
    window, offset = address & ~0x03FFFFFF, address & 0x03FFFFFF
    if address < 0 or window not in ALIASES or offset + length > RAM_SIZE:
        raise ValueError("DOA3 memory access leaves verified guest RAM")
    return offset


class Channel:
    """A bot's per-frame link to the owned runner (Doa3NativeAdapter.channel). GuestMemory proves everything on every
    call, which hashes the runner and the XBE each time (tens of ms: a 60 fps bot can't). A Channel makes the same
    proof once (owned PID and birth, pinned runner / XBE hashes, the unique verified allocation) and keeps one
    creation-time-checked process handle: that handle can't follow its PID to another process. Then
      * every call: the adapter still owns that process (ready, same PID and birth);
      * every REVALIDATE_S: the process (birth, path, alive) and the anchors (mapped header + immutable code);
      * every IDENTITY_S: the full proof again, hashes included;
    a failed check closes the channel for good (the caller makes a new one). Writes go only to the `writable` ranges
    (the virtual pad's block: doa3_pad.BLOCK), never to the header or code, and each is read back."""
    REVALIDATE_S = 2.0
    IDENTITY_S = 30.0

    def __init__(self, guest: "GuestMemory", writable=(), clock=None):
        import threading
        import time
        self.guest, self.clock = guest, clock or time.monotonic
        self.writable = tuple((_guest_offset(int(a), int(n)), int(n)) for a, n in writable)
        if any(n > MAX_WRITE or _overlaps_anchor(guest.expected, a, n) for a, n in self.writable):
            raise ValueError("A DOA3 channel can't write the XBE header, immutable code or more than 4 KiB at once")
        self.lock = threading.Lock()
        self.broken = None
        guest._identity()
        self.handle = _WindowsReader(guest.pid, guest.born, WRITE_ACCESS if self.writable else READ_ACCESS)
        try:
            guest._verified(self.handle)
            guest._identity()
        except Exception:
            self.handle.close()
            raise
        self.base = guest.base
        self.checked = self.identified = self.clock()
        self.reads = self.writes = 0

    def _check(self):
        if self.broken:
            raise Unsupported(self.broken)
        try:
            self.guest._owner_check()
            now = self.clock()
            if now - self.identified >= self.IDENTITY_S:
                self.guest._identity()
                validate(self.handle, self.base, self.guest.expected)
                self.identified = self.checked = now
            elif now - self.checked >= self.REVALIDATE_S:
                self.guest._identity(hashes=False)
                validate(self.handle, self.base, self.guest.expected)
                self.checked = now
        except Exception as error:
            self.close(f"DOA3 channel closed: {error}")
            raise

    def read(self, address, length) -> bytes:
        offset = _guest_offset(address, length)
        with self.lock:
            self._check()
            self.reads += 1
            return self.handle.read(self.base + offset, length)

    def read_many(self, ranges) -> list:
        """[(address, n)] -> bytes per range (or that range's exception); a failed identity check raises."""
        out = []
        for a, n in ranges:
            try:
                out.append(self.read(a, n))
            except Unsupported:
                raise
            except Exception as error:                 # noqa: BLE001 - a bad range fails alone
                out.append(error)
        return out

    def write(self, address, data) -> dict:
        data = bytes(data)
        offset = _guest_offset(address, len(data))
        if not any(lo <= offset and offset + len(data) <= lo + n for lo, n in self.writable):
            raise ValueError(f"DOA3 channel writes only its own block, not {address:#x}+{len(data)}")
        with self.lock:
            self._check()
            self.handle.write(self.base + offset, data)
            if self.handle.read(self.base + offset, len(data)) != data:
                raise RuntimeError(f"DOA3 channel write at {address:#x} did not read back")
            self.writes += 1
        return {"written": len(data), "via": "native_guest_ram_channel", "verified": True}

    def close(self, why: str = "DOA3 channel closed"):
        self.broken = self.broken or why
        handle, self.handle = getattr(self, "handle", None), None
        if handle is not None:
            handle.close()
