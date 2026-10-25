import pytest

from gbox import debug, ram_map
from gbox.ram_inspector import Inspector


class Adapter:
    def __init__(self):
        self.calls = []

    def read_memory(self, address, length):
        self.calls.append(("read", address, length))
        return b"\x48\x89\xe5\xc3" + bytes(max(0, length - 4))

    def write_memory(self, address, data):
        self.calls.append(("write", address, data))


def test_debugger_preserves_64_bit_addresses_and_uses_x64_disassembly():
    pytest.importorskip("capstone")
    adapter = Adapter()
    debugger = debug.ShadPS4ProcMem(adapter)
    result = debugger.disasm(0x900000000, 2)
    assert result[0]["operands"] == "rbp, rsp"
    assert result[0]["addr"] == 0x900000000
    assert adapter.calls[0][1] == 0x900000000
    assert debugger.info()["scope"] == "process_virtual"
    assert set(debugger.info()["features"]) == {"memory", "disasm"}
    debugger.write(0x900000001, b"\x90")
    assert adapter.calls[-1] == ("write", 0x900000001, b"\x90")
    with pytest.raises(debug.Unavailable):
        debugger.regs()
    with pytest.raises(debug.Unavailable):
        debugger.set_breakpoint(0x900000000)


def test_ps4_map_pointer_width_defaults_to_64_bit():
    spec = {"id": "test", "platform": "ps4", "fields": {}}
    mapped = ram_map.RamMap(spec)
    assert mapped.pointer_size == 8 and mapped.endian_name == "little"
    assert ram_map.RamMap(spec | {"pointer_size": 4}).pointer_size == 4


def test_hex_pointer_chain_reads_all_64_bits_without_a_map():
    calls = []
    class Reader:
        def read(self, addr, size, **kwargs):
            calls.append((addr, size))
            return (0x900000000).to_bytes(8, "little") if addr == 0x100000000 else b"\x7f"
    inspector = object.__new__(Inspector)
    inspector.map, inspector.platform, inspector.reader = None, "ps4", Reader()
    inspector.clock = lambda: 0.0
    result = inspector.hex(0, 1, pointer=[0x100000000, 4])
    assert calls == [(0x100000000, 8), (0x900000004, 1)]
    assert result["address"] == 0x900000004 and result["hex"] == "7f"
