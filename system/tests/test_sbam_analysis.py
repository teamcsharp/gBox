import os
import struct

import pytest

from gbox import sbam_analysis as A
from gbox.sbam_inventory import Iso9660, cmp3_decompress, parse_ra

CACHE = os.path.expanduser("~/gbox-cache/ps2/6cd93f2e36885f31")
ISO = os.path.join(CACHE, "disc.iso")
ELF = os.path.join(CACHE, "inventory", "SLUS_201.15")

needs_data = pytest.mark.skipif(
    not (os.path.exists(ISO) and os.path.exists(ELF)),
    reason="owned PS2 build not cached on this host",
)


def test_vaddr_file_roundtrip():
    assert A.file_to_vaddr(A.vaddr_to_file(A.DAT_INDEX_TABLE)) == A.DAT_INDEX_TABLE
    assert A.vaddr_to_file(0x56D780) == 0x46E780
    assert A.file_to_vaddr(0x46E780) == 0x56D780


def _synthetic_elf_with_index_table():
    """A minimal ELF blob with the 153-entry index table placed at its real
    file offset, so dat_index_table works without the full 4.6 MB image."""
    size = 0x46E780 + A.DAT_INDEX_COUNT * A.DAT_INDEX_STRIDE
    elf = bytearray(size)
    names = ["\\DATA\\DATA%02X\\DATA%02X.DAT;1" % (a // 30, a % 30)
             for a in range(A.DAT_INDEX_COUNT - 1, -1, -1)]
    f = A.vaddr_to_file(A.DAT_INDEX_TABLE)
    for i, name in enumerate(names):
        rec = name.encode("ascii") + b"\x00" * (A.DAT_INDEX_STRIDE - len(name))
        elf[f + i * A.DAT_INDEX_STRIDE: f + (i + 1) * A.DAT_INDEX_STRIDE] = rec
    return bytes(elf), names


def test_dat_index_table_parse():
    elf, names = _synthetic_elf_with_index_table()
    rows = A.dat_index_table(elf)
    assert len(rows) == A.DAT_INDEX_COUNT
    assert rows[0] == "DATA/DATA05/DATA02.DAT"      # descending order
    assert rows[-1] == "DATA/DATA00/DATA00.DAT"
    assert rows[0] > rows[-1]
    assert A.dat_index(elf)["DATA/DATA05/DATA02.DAT"] == 0


@needs_data
def test_dat_index_table_real_elf():
    elf = open(ELF, "rb").read()
    rows = A.dat_index_table(elf)
    assert len(rows) == A.DAT_INDEX_COUNT
    assert rows[0] == "DATA/DATA05/DATA02.DAT"
    assert rows[-1] == "DATA/DATA00/DATA00.DAT"
    # every row is a distinct DAT path
    assert len(set(rows)) == A.DAT_INDEX_COUNT


@needs_data
def test_cmp3_decoder_constants_pinned():
    elf = open(ELF, "rb").read()
    c = A.cmp3_decoder_constant_words(elf)
    assert c["zero_fill_bound_imm"] == 0xFEE
    assert c["cursor_init_imm"] == 0xFEE


@needs_data
def test_tim2_library_strings_present():
    elf = open(ELF, "rb").read()
    marks = A.tim2_library_strings(elf)
    assert marks["Tim2CheckFileHeader"] is not None
    assert marks["Tim2GetPictureHeader"] is not None


def test_raw_entry_marker_convention():
    # raw entries begin with 4 zero bytes; CMP3 entries begin with "CMP3"
    assert A.RAW_ENTRY_MARKER == b"\x00\x00\x00\x00"
    assert A.CMP3_MAGIC == b"CMP3"
    assert A.CMP3_MAGIC != A.RAW_ENTRY_MARKER[:4]


def test_format_constraints_consistent():
    assert A.FORMAT_CONSTRAINTS["transparent_index"] == 0
    assert A.FORMAT_CONSTRAINTS["image_types"][4].startswith("4bpp")


@needs_data
def _read_tim2_payload(dat_path, entry_index=0):
    with Iso9660(ISO) as iso:
        buf = iso.read(dat_path)
    for e in parse_ra(buf):
        if e.codec == "cmp3":
            pay = cmp3_decompress(buf, e.offset, e.offset + e.size)
            if pay[:4] == b"TIM2":
                return pay
    raise AssertionError("no TIM2 payload in " + dat_path)


@needs_data
def test_decode_4bpp_sprite_frame():
    pay = _read_tim2_payload("DATA/DATA00/DATA01.DAT")
    meta = A.tim2_picture_meta(pay)
    pic4 = next(m for m in meta if m["bpp"] == 4)
    idx = meta.index(pic4)
    w, h, rgba = A.tim2_picture_rgba(pay, idx)
    assert (w, h) == (pic4["width"], pic4["height"])
    assert len(rgba) == w * h * 4
    assert pic4["clut_colors"] == 16
    assert pic4["clut_size"] == 16 * 4          # RGBA8888 CLUT
    # CLUT[0] is the transparent colour (alpha 0)
    assert rgba[3] == 0
    # image is packed 4bpp: image_size == w*h/2
    assert pic4["image_size"] == w * h // 2


@needs_data
def test_decode_8bpp_texture():
    pay = _read_tim2_payload("DATA/DATA00/DATA0F.DAT")
    meta = A.tim2_picture_meta(pay)
    pic8 = next(m for m in meta if m["bpp"] == 8)
    idx = meta.index(pic8)
    w, h, rgba = A.tim2_picture_rgba(pay, idx)
    assert (w, h) == (pic8["width"], pic8["height"])
    assert len(rgba) == w * h * 4
    assert pic8["clut_colors"] == 256
    assert pic8["clut_size"] == 256 * 4


@needs_data
def test_cmp3_roundtrip_matches_decoder_semantics():
    # the game's decoder reads "CMP3"+u32 size then LZSS; the inventory's
    # all-literal encoder must round-trip through cmp3_decompress exactly.
    from gbox.sbam_inventory import cmp3_compress_literal
    data = bytes(range(256)) * 3 + b"\x00\xff" * 100
    blob = cmp3_compress_literal(data)
    assert blob[:4] == b"CMP3"
    assert cmp3_decompress(blob) == data
