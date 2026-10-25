"""PS4 analysis uses actual ELF64/SELF layout, never a fabricated guest RAM base."""
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

from gbox import ps4_executable as ps4
from gbox import re_lab_tool as lab


def executable(kind=0xFE10, base=0x900000000, data=b"\x48\x89\xe5\xc3"):
    ident = b"\x7fELF\x02\x01\x01\x09" + bytes(8)
    header = struct.pack("<16sHHIQQQIHHHHHH", ident, kind, 62, 1, base, 64, 0, 0, 64, 56, 1, 0, 0, 0)
    program = struct.pack("<II6Q", 1, 5, 0x100, base, base, len(data), len(data) + 64, 0x1000)
    return header + program + bytes(0x100 - len(header + program)) + data


def self_file(flags=0x800):
    elf = executable()
    header = bytearray(32)
    header[:10] = ps4.SELF_MAGIC + b"\x00\x01\x01\x12\x01\x01"
    struct.pack_into("<H", header, 0x18, 1)
    segment = struct.pack("<4Q", flags, 0x200, 4, 4)
    data = bytes(header) + segment + elf[:120]
    return data + bytes(0x200 - len(data)) + elf[0x100:]


def test_elf64_preserves_64_bit_entry_and_source():
    raw = executable()
    result, info = ps4.analysis_image(raw)
    assert info["entry"] == info["base"] == 0x900000000
    assert struct.unpack_from("<Q", result, 24)[0] == 0x900000000
    assert struct.unpack_from("<H", result, 16)[0] == 3
    assert struct.unpack_from("<H", raw, 16)[0] == 0xFE10
    assert result[0x100:] == raw[0x100:]


def test_self_segments_are_rebuilt_at_elf_offsets():
    result, info = ps4.analysis_image(self_file())
    assert result[:4] == b"\x7fELF" and result[0x100:] == b"\x48\x89\xe5\xc3"
    assert info["format"] == "PS4 decrypted SELF -> ELF64"
    assert info["entry"] == 0x900000000
    assert struct.unpack_from("<Q", result, 40)[0] == 0


@pytest.mark.parametrize("flags,message", [(0x802, "Encrypted"), (0x808, "Compressed"),
                                          (0x100800, "segment index"), (0, "no decrypted payload")])
def test_self_rejects_unsupported_or_missing_data(flags, message):
    with pytest.raises(ValueError, match=message):
        ps4.analysis_image(self_file(flags))


@pytest.mark.parametrize("mutate", [lambda b: b.__setitem__(4, 1), lambda b: b.__setitem__(5, 2),
                                    lambda b: struct.pack_into("<H", b, 18, 21),
                                    lambda b: struct.pack_into("<Q", b, 72, 2**60)])
def test_wrong_cpu_or_malformed_elf_is_refused(mutate):
    raw = bytearray(executable())
    mutate(raw)
    with pytest.raises(ValueError):
        ps4.analysis_image(bytes(raw))


def test_truncated_elf_and_self_payloads_are_refused():
    for raw in (executable()[:-1], self_file()[:-1], ps4.SELF_MAGIC):
        with pytest.raises(ValueError, match="Truncated"):
            ps4.analysis_image(raw)


def test_sce_relro_is_included_for_ghidra():
    raw = bytearray(executable())
    struct.pack_into("<I", raw, 64, ps4.PT_SCE_RELRO)
    result, _info = ps4.analysis_image(bytes(raw))
    assert struct.unpack_from("<I", result, 64)[0] == 1


def test_disc_reader_and_module_paths_are_ps4_specific(tmp_path):
    module = tmp_path / "libExample.sprx"
    module.write_bytes(self_file())
    result, source, info = lab.extract_from_disc(None, {"platform": "ps4"}, module)
    assert source == module.read_bytes() and result[:4] == b"\x7fELF"
    assert info["source_file"] == "libExample.sprx"
    assert lab.PLATFORM_CPU["ps4"] == ("x86_64", ps4.PROCESSOR, 62, False)


def test_ps4_process_memory_is_not_mislabeled_as_guest_ram():
    with pytest.raises(ValueError, match="guest-only"):
        lab.ram_to_image("ps4", bytes(32), 0x900000000)


def test_ps4_file_patches_and_model_assets_preserve_originals(tmp_path):
    from gbox import filemods
    game = tmp_path / "owned-game"
    game.mkdir()
    boot = game / "eboot.bin"
    boot.write_bytes(executable())
    (game / "model.bin").write_bytes(b"original model")
    cfg = SimpleNamespace(cache=tmp_path / "cache")
    result = filemods.build(cfg, "ps4-game", boot, "reviewed-assets", {
        "eboot.bin": {"patch": [{"offset": "0x100", "hex": "90"}]},
        "model.bin": {"bytes": b"replacement model"},
    })
    launched = filemods.launch_path(cfg, "ps4-game", boot, result["mod"])
    assert launched == Path(result["dir"]) / "eboot.bin"
    assert launched.read_bytes()[0x100] == 0x90
    assert (launched.parent / "model.bin").read_bytes() == b"replacement model"
    assert boot.read_bytes() == executable()
    assert (game / "model.bin").read_bytes() == b"original model"
