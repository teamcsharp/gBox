"""The RE4 Switch cave verifier (checkpoint E1): a synthetic NSO image exercises every check.

No game file is needed: the image builder writes the NSO0 header the verifier reads, so each test controls the
section layout, the tail padding and the one reference it plants. The measured RE4 layout (the operator's extracted
`main-82C2A04A....nso`) is a separate case: it pins the cave this lane will install into.
"""
import importlib.util
import struct
from pathlib import Path

import pytest

from gbox import nso_elf

SHIFT = 0x100


def _load_tool():
    path = Path(__file__).resolve().parents[1] / "scripts" / "verify_re4_caves.py"
    spec = importlib.util.spec_from_file_location("verify_re4_caves", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V = _load_tool()


def nso_image(*, text_size=0x820, rodata_memory=0x1000, rodata_size=0x100, data_memory=0x1100, data_size=0x100,
              bss_size=0x100, text=b"", rodata=b"", data=b"", truncate=0):
    """An NSO0 image laid out exactly as `hactool --uncompressed` writes one: section vaddr + 0x100."""
    end = max(rodata_memory + rodata_size, data_memory + data_size, len(text))
    image = bytearray(SHIFT + end - truncate)
    struct.pack_into("<4s", image, 0, b"NSO0")
    struct.pack_into("<I", image, 0x0C, 0)                       # flags
    struct.pack_into("<I", image, 0x10, SHIFT)                   # text_file
    struct.pack_into("<I", image, 0x14, 0)                       # text_memory
    struct.pack_into("<I", image, 0x18, text_size)               # text_size
    struct.pack_into("<I", image, 0x1C, 0)                       # module name offset
    struct.pack_into("<I", image, 0x20, SHIFT + rodata_memory)   # rodata_file
    struct.pack_into("<I", image, 0x24, rodata_memory)           # rodata_memory
    struct.pack_into("<I", image, 0x28, rodata_size)             # rodata_size
    struct.pack_into("<I", image, 0x30, SHIFT + data_memory)     # data_file
    struct.pack_into("<I", image, 0x34, data_memory)             # data_memory
    struct.pack_into("<I", image, 0x38, data_size)               # data_size
    struct.pack_into("<I", image, 0x3C, bss_size)                # bss_size
    image[SHIFT:SHIFT + len(text)] = text
    image[SHIFT + rodata_memory:SHIFT + rodata_memory + len(rodata)] = rodata
    image[SHIFT + data_memory:SHIFT + data_memory + len(data)] = data
    return bytes(image)


def put(image, vaddr, blob):
    image = bytearray(image)
    image[SHIFT + vaddr:SHIFT + vaddr + len(blob)] = blob
    return bytes(image)


def branch(pc, target):
    return struct.pack("<I", 0x14000000 | (((target - pc) >> 2) & 0x3FFFFFF))


def adrp_add(pc, rd, target):
    page = (pc & ~0xFFF)
    delta = target - page
    imm = delta >> 12
    immlo, immhi = imm & 3, (imm >> 2) & 0x7FFFF
    adrp = 0x90000000 | (immlo << 29) | (immhi << 5) | rd
    add = 0x91000000 | ((target - (page + (imm << 12))) & 0xFFF) << 10 | (rd << 5) | rd
    return struct.pack("<II", adrp, add)


def test_a_clean_image_yields_the_aligned_tail_cave():
    report = V.evaluate(nso_image())
    assert report["usable"] is True
    assert report["cave"]["at"] == hex(0x840) and report["cave"]["size"] == 0x7C0
    assert report["holes"] == {"re4_cave": True}
    assert report["aligned"] == {"re4_cave": True} and report["in_mapping"] == {"re4_cave": True}
    assert report["references"] == []


def test_a_branch_into_the_cave_is_found():
    image = put(nso_image(), 0, branch(0, 0x860))
    report = V.evaluate(image)
    assert report["usable"] is False and report["reason"] == "code or a literal points into the cave"
    assert [(r["kind"], r["target"]) for r in report["references"]] == [("instruction", hex(0x860))]


def test_an_adrp_add_pair_into_the_cave_is_found():
    image = put(nso_image(), 0x100, adrp_add(0x100, 0, 0x880))
    report = V.evaluate(image)
    assert any(r["kind"] == "instruction" and r["target"] == hex(0x880) for r in report["references"])
    assert report["usable"] is False


def test_a_literal_pointer_into_the_cave_is_found():
    image = put(nso_image(), 0x1000, struct.pack("<Q", 0x890))       # in .rodata
    report = V.evaluate(image)
    assert report["references"] == [{"cave": "re4_cave", "at": hex(0x1000), "kind": "literal-64",
                                     "target": hex(0x890)}]
    assert report["usable"] is False


def test_a_nonzero_byte_makes_the_range_not_a_hole():
    image = put(nso_image(), 0x900, b"\x01")
    report = V.evaluate(image)
    assert report["holes"] == {"re4_cave": False}
    assert report["usable"] is False and report["reason"] == "the cave range is not all zero"


def test_a_page_aligned_text_leaves_no_cave():
    image = nso_image(text_size=0x1000, rodata_memory=0x1000)
    report = V.evaluate(image)
    assert report["cave"]["size"] == 0 and report["usable"] is False
    assert "no tail padding" in report["reason"]


def test_a_truncated_or_foreign_image_is_refused():
    with pytest.raises(nso_elf.NsoError):
        V.evaluate(b"\x00" * 0x200)
    with pytest.raises(nso_elf.NsoError):
        V.evaluate(nso_image(data_memory=0x1100, data_size=0x100, truncate=0x80))


def test_the_measured_re4_layout_yields_the_pinned_cave():
    """The operator's extracted RE4 main: .text ends 0x655850; the RX page ends 0x656000; the cave is 0x655880."""
    image = nso_image(text_size=0x655850, rodata_memory=0x656000, rodata_size=0x48BBCC,
                      data_memory=0xAE2000, data_size=0x4A738, bss_size=0x11938C8)
    report = V.evaluate(image)
    assert report["cave"]["at"] == hex(0x655880) and report["cave"]["size"] == 0x780
    assert report["usable"] is True


def test_the_cli_reports_pass_and_fail(tmp_path, capsys):
    good = tmp_path / "main.bin"
    good.write_bytes(nso_image())
    assert V.main(["verify_re4_caves.py", str(good)]) == 0
    assert "PASS" in capsys.readouterr().out
    bad = tmp_path / "bad.bin"
    bad.write_bytes(put(nso_image(), 0, branch(0, 0x860)))
    assert V.main(["verify_re4_caves.py", str(bad)]) == 1
    assert "FAIL" in capsys.readouterr().out


def test_a_cave_given_on_the_command_line_is_vetted_too(tmp_path, capsys):
    image = put(nso_image(), 0x900, b"\x01")
    path = tmp_path / "main.bin"
    path.write_bytes(image)
    assert V.main(["verify_re4_caves.py", str(path), "--at", "0x900", "--size", "0x40"]) == 1
    assert "not all zero" in capsys.readouterr().out
