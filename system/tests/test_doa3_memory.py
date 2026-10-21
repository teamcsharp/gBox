"""A native RAM address is usable only after exact owned-process/source proof."""
import hashlib
import ctypes
from pathlib import Path
import struct
from types import SimpleNamespace

import psutil
import pytest

from gbox import doa3_memory as memory
from gbox import doa3_native as native
from gbox.config import Config
from gbox.registry import Unsupported


THUNKS = 0x13100                  # the kernel thunk table, inside the last immutable section (DOA3: .rdata 0x1ED0E0)
# KeTickCount (data), ordinal 1 (a function), XboxHardwareInfo (data), terminator
THUNK_ENTRIES = (0x80000000 | 156, 0x80000000 | 1, 0x80000000 | 322, 0)


def xbe_bytes(*, writable=False, thunk_key=0x5B6D40B6, thunks=THUNK_ENTRIES):
    image = bytearray(0x2000)
    image[:4] = b"XBEH"
    struct.pack_into("<II", image, 0x104, 0x10000, 0x400)
    struct.pack_into("<I", image, 0x10C, 0x4000)
    struct.pack_into("<II", image, 0x11C, 3, 0x10180)
    struct.pack_into("<I", image, 0x128, 0x11000 ^ 0xA8FC57AB)
    struct.pack_into("<I", image, 0x158, THUNKS ^ thunk_key)
    rdata = bytearray(b"another code section" * 20)
    struct.pack_into(f"<{len(thunks)}I", rdata, THUNKS - 0x13000, *thunks)
    # Two immutable executable sections and one mutable executable section.
    for index, (flags, guest, raw, data) in enumerate([
        (5 if writable else 4, 0x11000, 0x400, b"immutable code" * 20),
        (5, 0x12000, 0x800, b"mutable imports" * 20),
        (5 if writable else 4, 0x13000, 0xC00, bytes(rdata)),
    ]):
        struct.pack_into("<IIIII", image, 0x180 + index * 56, flags, guest, len(data), raw, len(data))
        image[raw:raw + len(data)] = data
    return bytes(image)


def source_anchors(image=None):
    image = xbe_bytes() if image is None else image
    return memory.anchors(image, hashlib.sha256(image).hexdigest())


class Reader:
    def __init__(self, expected, bases=(0x100000000,), prefix=0):
        self.mapping = [{"base": base, "size": memory.RAM_SIZE + prefix,
                         "state": 0x1000, "type": 0x20000, "protect": 4} for base in bases]
        self.data = {base + prefix + item["guest"]: item["data"] for base in bases for item in expected}
        self.reads = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def regions(self):
        yield from self.mapping

    def region(self, address):
        return next(row for row in self.mapping if row["base"] <= address < row["base"] + row["size"])

    def write(self, address, data):
        self.writes = getattr(self, "writes", []) + [(address, bytes(data))]
        self.data[address] = bytes(data)

    def read(self, address, size):
        self.reads.append((address, size))
        output = bytearray(size)
        for start, data in self.data.items():
            left, right = max(start, address), min(start + len(data), address + size)
            if left < right:
                output[left - address:right - address] = data[left - start:right - start]
        return bytes(output)


def test_exact_xbe_full_header_and_every_immutable_text_are_anchors():
    expected = source_anchors()
    assert [item["guest"] for item in expected] == [0x10000, 0x11000, 0x13000]
    assert expected[0]["data"] == xbe_bytes()[:0x400]
    assert all(memory._anchor_digest(row, row["data"]) == row["sha256"] for row in expected)
    assert expected[0]["mutable_dwords"] == [0x198, 0x1D0, 0x208]
    assert not expected[1].get("mutable_dwords")
    assert expected[2]["mutable_dwords"] == [0x100, 0x108]      # only the runner's kernel data-export thunk slots
    with pytest.raises(Unsupported, match="exact reviewed"):
        memory.anchors(xbe_bytes() + b"modified", hashlib.sha256(xbe_bytes()).hexdigest())
    with pytest.raises(Unsupported, match="exact reviewed"):
        memory.anchors(b"XBEH", hashlib.sha256(b"XBEH").hexdigest())


@pytest.mark.parametrize("field,value", [(0x104, 0x20000), (0x108, 0xFFFFF), (0x11C, 129),
                                        (0x120, 0x103F0), (0x184, memory.RAM_SIZE), (0x18C, 0xFFFF)])
def test_malformed_source_ranges_are_rejected(field, value):
    image = bytearray(xbe_bytes())
    struct.pack_into("<I", image, field, value)
    with pytest.raises(Unsupported):
        source_anchors(bytes(image))


def test_source_without_immutable_code_is_not_a_mapping_proof():
    with pytest.raises(Unsupported, match="no immutable"):
        source_anchors(xbe_bytes(writable=True))


def test_initial_image_analysis_range_and_entry_are_derived_from_reviewed_header():
    layout = memory.image_layout(xbe_bytes())
    assert layout["analysis_range"] == {"address": 0x10000, "size": 0x4000}
    assert layout["entry_point"] == 0x11000
    assert layout["sections"][1]["writable"] is True


@pytest.mark.parametrize("field,value", [(0x10C, 0), (0x10C, memory.RAM_SIZE), (0x10C, 0x1000),
                                        (0x128, 0x50000 ^ 0xA8FC57AB)])
def test_analysis_range_or_entry_outside_verified_image_is_rejected(field, value):
    source = bytearray(xbe_bytes())
    struct.pack_into("<I", source, field, value)
    with pytest.raises(Unsupported):
        memory.image_layout(source)


@pytest.mark.parametrize("prefix", [0, 16, 65536])
def test_unique_allocation_is_located_with_heap_prefix(prefix):
    expected = source_anchors()
    reader = Reader(expected, prefix=prefix)
    assert memory.discover(reader, expected) == 0x100000000 + prefix


def test_magic_without_all_code_sections_does_not_qualify():
    expected = source_anchors()
    reader = Reader(expected)
    reader.data[0x100000000 + 0x13000] = b"changed code"
    with pytest.raises(Unsupported, match="found 0"):
        memory.discover(reader, expected)


def test_only_upstream_section_reference_counters_are_normalized():
    expected = source_anchors()
    reader = Reader(expected)
    address = 0x100000000 + expected[0]["guest"]
    header = bytearray(reader.data[address])
    for offset in expected[0]["mutable_dwords"]:
        struct.pack_into("<I", header, offset, 7)
    reader.data[address] = bytes(header)
    assert memory.discover(reader, expected) == 0x100000000
    header[0x197] ^= 1  # Adjacent section metadata is still immutable.
    reader.data[address] = bytes(header)
    with pytest.raises(Unsupported, match="validation changed"):
        memory.validate(reader, 0x100000000, expected)


def runner_mapped(expected, base=0x100000000):
    """Guest RAM as the pinned runner leaves it after boot (runner.cpp v0.2 materializeKernelDataExports): the
    kernel data-export thunk slots point at its kernel data area."""
    reader = Reader(expected, bases=(base,))
    reader.data[base + THUNKS] = struct.pack("<I", 0x00F80040)            # KeTickCount
    reader.data[base + THUNKS + 8] = struct.pack("<I", 0x00F80000)        # XboxHardwareInfo
    return reader


def test_runner_written_kernel_data_slots_are_the_only_normalized_section_bytes():
    """Live 2026-10-20 on the i9-NUC every DOA3 read failed 'no unique verified allocation (found 0)': the runner fills
    the data-export slots of the kernel thunk table (DOA3: .rdata 0x1ED0E0, an immutable section) at boot."""
    expected = source_anchors()
    unnormalized = [dict(item) for item in expected]
    for item in unnormalized[1:]:
        item.pop("mutable_dwords", None)
        item["sha256"] = memory._anchor_digest(item, item["data"])
    with pytest.raises(Unsupported, match="validation changed"):
        memory.validate(runner_mapped(expected), 0x100000000, unnormalized)   # today's mapping, without the fix
    with pytest.raises(Unsupported, match="found 0"):
        memory.discover(runner_mapped(expected), unnormalized)
    memory.validate(runner_mapped(expected), 0x100000000, expected)           # with it
    assert memory.discover(runner_mapped(expected), expected) == 0x100000000
    for address, data in ((THUNKS + 4, b"\x00\x00\xF8\x00"),                 # an imported function's slot
                          (THUNKS - 4, b"!"), (THUNKS + 12, b"!"),            # bytes around the table, the terminator
                          (0x13000, b"x"), (0x11000, b"x")):                  # other code
        reader = runner_mapped(expected)
        reader.data[0x100000000 + address] = data
        with pytest.raises(Unsupported, match="validation changed"):
            memory.validate(reader, 0x100000000, expected)


def test_kernel_thunk_slots_follow_the_runner_parser():
    assert memory.runner_thunk_slots(xbe_bytes()) == [THUNKS, THUNKS + 8]
    assert memory.runner_thunk_slots(xbe_bytes(thunk_key=0xEFB1F152)) == [THUNKS, THUNKS + 8]   # a debug-keyed XBE
    assert memory.runner_thunk_slots(xbe_bytes(thunks=(0x80000000 | 1, 0))) == []
    with pytest.raises(Unsupported, match="outside its image"):
        source_anchors(xbe_bytes(thunk_key=0x12345678))
    endless = bytearray(xbe_bytes())
    start = 0xC00 + THUNKS - 0x13000                                       # the table's file offset to the end of file
    struct.pack_into(f"<{(len(endless) - start) // 4}I", endless, start, *[0x80000000 | 156] * ((len(endless) - start) // 4))
    with pytest.raises(Unsupported, match="terminator"):
        memory.runner_thunk_slots(bytes(endless))


def test_two_fully_matching_allocations_are_ambiguous():
    expected = source_anchors()
    with pytest.raises(Unsupported, match="found 2"):
        memory.discover(Reader(expected, bases=(0x100000000, 0x200000000)), expected)


@pytest.mark.parametrize("change", [{"protect": 0x104}, {"type": 0x40000}, {"state": 0x2000},
                                    {"size": memory.RAM_SIZE - 1}, {"size": memory.RAM_SIZE + 1024**2 + 1}])
def test_unsupported_regions_are_not_scanned(change):
    expected = source_anchors()
    reader = Reader(expected)
    reader.mapping[0].update(change)
    with pytest.raises(Unsupported, match="found 0"):
        memory.discover(reader, expected)
    assert reader.reads == []


def test_candidate_count_is_bounded():
    expected = source_anchors()
    reader = Reader(expected, bases=())
    reader.mapping = [{"base": index * 0x10000000, "size": memory.RAM_SIZE,
                       "state": 0x1000, "type": 0x20000, "protect": 4} for index in range(129)]
    with pytest.raises(Unsupported, match="Too many"):
        memory.discover(reader, expected)


def provider(tmp_path, monkeypatch):
    exe, xbe = tmp_path / "runner.exe", tmp_path / "default.xbe"
    exe.write_bytes(b"reviewed runner")
    xbe.write_bytes(xbe_bytes())
    owner = SimpleNamespace(ready=True, render_pid=123, _owned={123: 100.25})
    process = SimpleNamespace(create_time=lambda: 100.25, is_running=lambda: True,
                              status=lambda: "running", exe=lambda: str(exe))
    monkeypatch.setattr(psutil, "Process", lambda pid: process)
    result = memory.GuestMemory(owner, exe, xbe, hashlib.sha256(exe.read_bytes()).hexdigest(),
                                hashlib.sha256(xbe.read_bytes()).hexdigest())
    reader = Reader(result.expected)
    monkeypatch.setattr(memory, "_WindowsReader", lambda pid, born, access=memory.READ_ACCESS: reader.__setattr__("access", access) or reader)
    return result, reader, process


def test_mapping_contract_and_alias_reads(tmp_path, monkeypatch):
    result, reader, _ = provider(tmp_path, monkeypatch)
    mapping = result.memory_map()
    assert mapping["verified"] and mapping["processor"] == "x86:LE:32:default"
    assert mapping["regions"] == [{"address": 0, "size": memory.RAM_SIZE, "kind": "ram", "readable": True, "writable": True}]
    assert mapping["pid"] == 123 and mapping["process_created"] == 100.25
    assert mapping["analysis_range"] == {"address": 0x10000, "size": 0x4000}
    assert mapping["entry_point"] == 0x11000
    assert mapping["anchors"][0]["mutable_dwords"] == [0x10198, 0x101D0, 0x10208]
    assert mapping["anchors"][2]["mutable_dwords"] == [THUNKS, THUNKS + 8]
    assert [result.read(alias + 0x11000, 12) for alias in memory.ALIASES] == [b"immutable co"] * 3
    assert memory.READ_ACCESS == 0x410  # Reads never open VM_WRITE/VM_OPERATION.
    assert memory.WRITE_ACCESS == 0x438
    assert reader.access == memory.READ_ACCESS


def test_writes_go_to_guest_ram_only_and_read_back(tmp_path, monkeypatch):
    """Unlock-on-load holds (2026-10-19): verified writes into data RAM; the XBE header and code are refused."""
    result, reader, _ = provider(tmp_path, monkeypatch)
    result.memory_map()
    assert result.write(0x80300000, b"\x01\x02") == {"written": 2, "via": "native_guest_ram", "verified": True}
    assert reader.access == memory.WRITE_ACCESS and reader.writes == [(result.base + 0x300000, b"\x01\x02")]
    assert result.read(0x300000, 2) == b"\x01\x02"
    for address, data in ((0x10000, b"x"), (0x11000, b"x"), (0x3FFFFFF, b"xx"), (0xC0000000, b"x"), (0, b""),
                          (0x300000, b"x" * (memory.MAX_WRITE + 1))):
        with pytest.raises(ValueError):
            result.write(address, data)
    original = reader.write
    reader.write = lambda address, data: original(address, b"\x00" * len(data))
    with pytest.raises(RuntimeError, match="did not read back"):
        result.write(0x300010, b"\x05")


@pytest.mark.parametrize("address,length", [(-1, 1), (0x4000000, 1), (0xC0000000, 1),
    (0xFFFFFFFF, 2), (0x3FFFFFF, 2), (0, 0), (0, memory.RAM_SIZE + 1), (True, 1), (0, False)])
def test_invalid_read_ranges_fail_before_opening_process(tmp_path, monkeypatch, address, length):
    result, _, _ = provider(tmp_path, monkeypatch)
    monkeypatch.setattr(memory, "_WindowsReader", lambda *args: pytest.fail("Invalid bounds opened a process"))
    with pytest.raises(ValueError):
        result.read(address, length)


@pytest.mark.parametrize("change", ["owner_pid", "owner_born", "ready", "process_born", "process_path", "stopped", "exe", "xbe"])
def test_every_read_revalidates_owned_process_and_pinned_sources(tmp_path, monkeypatch, change):
    result, _, process = provider(tmp_path, monkeypatch)
    result.memory_map()
    if change == "owner_pid": result.owner.render_pid = 124
    elif change == "owner_born": result.owner._owned[123] = 200
    elif change == "ready": result.owner.ready = False
    elif change == "process_born": process.create_time = lambda: 200
    elif change == "process_path": process.exe = lambda: str(tmp_path / "other.exe")
    elif change == "stopped": process.is_running = lambda: False
    elif change == "exe": result.exe.write_bytes(b"changed runner")
    elif change == "xbe": result.xbe.write_bytes(b"changed source")
    monkeypatch.setattr(memory, "_WindowsReader", lambda *args: pytest.fail("Failed identity opened a process"))
    with pytest.raises(Unsupported):
        result.read(0, 1)


def test_cached_address_does_not_skip_text_or_region_revalidation(tmp_path, monkeypatch):
    result, reader, _ = provider(tmp_path, monkeypatch)
    result.memory_map()
    reader.data[result.base + 0x13000] = b"modified immutable code"
    with pytest.raises(Unsupported, match="validation changed"):
        result.read(0, 1)
    reader.data[result.base + 0x13000] = result.expected[-1]["data"]
    reader.mapping[0]["protect"] = 0x104
    with pytest.raises(Unsupported, match="no longer"):
        result.read(0, 1)


def test_changed_text_during_sample_is_rejected_before_return(tmp_path, monkeypatch):
    result, reader, _ = provider(tmp_path, monkeypatch)
    result.memory_map()
    original = reader.read
    def changed(address, size):
        data = original(address, size)
        if address == result.base and size == 8:
            reader.data[result.base + 0x13000] = b"code changed during read"
        return data
    reader.read = changed
    with pytest.raises(Unsupported, match="validation changed"):
        result.read(0, 8)


def test_adapter_exposes_verified_reads_and_writes_without_input(monkeypatch, tmp_path):
    ad = native.Doa3NativeAdapter(Config(data_dir=tmp_path / "data", cache_dir=tmp_path / "cache"), {})
    assert {"read_memory", "write_memory", "query_memory_map"} <= ad.supported
    assert "send_input" not in ad.supported
    with pytest.raises(Unsupported, match="verified running"):
        ad.query_memory_map()
    monkeypatch.setattr(ad, "_running", lambda: True)
    monkeypatch.setattr(ad, "_live", lambda: {123})
    ad.ready, ad.render_pid = True, 123
    assert ad.query_runtime()["guest_memory"]["verified"] is False
    proof = {"verified": True, "regions": [{"address": 0, "size": memory.RAM_SIZE}]}
    ad._memory_source = Path("expected-source")
    ad._guest_memory = SimpleNamespace(memory_map=lambda: proof, read=lambda address, length: b"verified",
                                       write=lambda address, data: {"written": len(data)})
    assert ad.query_runtime()["guest_memory"] == proof
    assert ad.regions() == [(0, memory.RAM_SIZE)]
    assert ad.read_memory(0, 8) == b"verified"
    assert ad.write_memory(0x300000, b"ab") == {"written": 2}


def fake_kernel(monkeypatch, *, born=100.25, complete=True):
    calls = []
    class Function:
        def __init__(self, callback): self.callback = callback
        def __call__(self, *args): return self.callback(*args)
    def info(pointer): pointer._obj.maximum = 0x7FFFFFFEFFFF
    def times(handle, created, *rest):
        value = int((born + 11644473600) * 1e7)
        created._obj.dwLowDateTime, created._obj.dwHighDateTime = value & 0xFFFFFFFF, value >> 32
        return True
    def read(handle, address, buffer, length, got):
        ctypes.memmove(buffer, b"x" * length, length)
        got._obj.value = length if complete else length - 1
        return True
    def region(handle, address, pointer, size):
        obj = pointer._obj
        obj.BaseAddress, obj.RegionSize, obj.State, obj.Protect, obj.Type = 0x100000000, memory.RAM_SIZE, 0x1000, 4, 0x20000
        return size
    kernel = SimpleNamespace(
        OpenProcess=Function(lambda rights, inherit, pid: calls.append((rights, inherit, pid)) or 1234),
        CloseHandle=Function(lambda handle: calls.append(("close", handle))),
        GetProcessTimes=Function(times), GetNativeSystemInfo=Function(info),
        ReadProcessMemory=Function(read), VirtualQueryEx=Function(region))
    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: kernel, raising=False)
    return calls


def test_windows_handle_requests_read_only_rights_and_checks_birth(monkeypatch):
    calls = fake_kernel(monkeypatch)
    with memory._WindowsReader(123, 100.25) as reader:
        assert reader.read(0x100000000, 3) == b"xxx"
        assert reader.region(0x100000000)["size"] == memory.RAM_SIZE
        assert calls == [(0x410, False, 123)]
    assert calls[-1] == ("close", 1234)
    calls = fake_kernel(monkeypatch, born=200)
    with pytest.raises(Unsupported, match="different process identity"):
        memory._WindowsReader(123, 100.25)
    assert calls[-1] == ("close", 1234)


def test_partial_windows_read_is_never_returned(monkeypatch):
    fake_kernel(monkeypatch, complete=False)
    with memory._WindowsReader(123, 100.25) as reader:
        with pytest.raises(Unsupported, match="completely"):
            reader.read(0x100000000, 3)
