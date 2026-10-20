import os
import struct
import hashlib
from pathlib import Path

import pytest

from gbox import sbam_analysis as A
from gbox.sbam_inventory import Iso9660, cmp3_decompress, parse_ra

CACHE = os.path.expanduser("~/gBox_alt/gbox-cache/ps2/6cd93f2e36885f31")
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


@pytest.mark.parametrize("helper", [A.dat_index_table, A.dat_index,
    A.cmp3_decoder_constant_words, A.tim2_library_strings, A.loader_marker])
def test_pinned_helpers_reject_unknown_elf(helper):
    for blob in (b"", b"\x7fELF" + bytes(A.BOOT_ELF_BYTES - 4)):
        with pytest.raises(ValueError, match="exact SLUS"):
            helper(blob)


@needs_data
def test_dat_index_table_real_elf():
    elf = Path(ELF).read_bytes()
    rows = A.dat_index_table(elf)
    assert len(rows) == A.DAT_INDEX_COUNT
    assert rows[0] == "DATA/DATA05/DATA02.DAT"
    assert rows[-1] == "DATA/DATA00/DATA00.DAT"
    # every row is a distinct DAT path
    assert len(set(rows)) == A.DAT_INDEX_COUNT


@needs_data
def test_cmp3_decoder_constants_pinned():
    elf = Path(ELF).read_bytes()
    c = A.cmp3_decoder_constant_words(elf)
    assert c["zero_fill_bound_word"] == 0x28430FEE  # slti v1,v0,0xFEE
    assert c["cursor_init_word"] == 0x24020FEE  # addiu v0,zero,0xFEE
    assert c["zero_fill_bound_imm"] == 0xFEE
    assert c["cursor_init_imm"] == 0xFEE


@needs_data
def test_tim2_library_strings_present():
    elf = Path(ELF).read_bytes()
    marks = A.tim2_library_strings(elf)
    assert marks["Tim2CheckFileHeader"] is not None
    assert marks["Tim2GetPictureHeader"] is not None


@needs_data
def test_loader_marker_and_identity():
    elf = Path(ELF).read_bytes()
    assert A.loader_marker(elf) == b"NOCM"
    modified = elf[:-1] + bytes([elf[-1] ^ 1])
    with pytest.raises(ValueError, match="exact SLUS"):
        A.loader_marker(modified)


def _read_tim2_payload(dat_path):
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


def texture(bpp=4, width=2, height=1, pixels=None, colors=None, header_size=48,
            alignment=0, count=1):
    image_type = {4: 4, 8: 5, 32: 3}[bpp]
    if pixels is None:
        pixels = bytes(width * height * bpp // 8)
    if colors is None:
        colors = (b"\x0a\x14\x1e\x80" * (16 if bpp == 4 else 256)) if bpp != 32 else b""
    header = bytearray(header_size)
    struct.pack_into("<IIIHH4BHHQ", header, 0,
        header_size + len(pixels) + len(colors), len(colors), len(pixels),
        header_size, len(colors) // 4, 0, 1, 3 if colors else 0, image_type,
        width, height, {4: 20, 8: 19, 32: 0}[bpp] << 20)
    top = bytearray(128 if alignment else 16)
    struct.pack_into("<4sBBH", top, 0, b"TIM2", 4, alignment, count)
    return bytes(top + header + pixels + colors)


def replace(blob, offset, fmt, value):
    out = bytearray(blob)
    struct.pack_into(fmt, out, offset, value)
    return bytes(out)


def test_4bpp_low_nibble_first_and_alpha_not_fixed_index():
    colors = b"\x01\x02\x03\x80" + b"\x05\x06\x07\x00" + bytes(56)
    source = texture(pixels=b"\x10", colors=colors)
    before = hashlib.sha256(source).hexdigest()
    assert A.tim2_picture_rgba(source) == (2, 1, b"\x01\x02\x03\xff\x05\x06\x07\x00")
    assert hashlib.sha256(source).hexdigest() == before


def test_8bpp_csm1_swaps_palette_blocks_and_scales_alpha():
    colors = b"".join(bytes((i, 255-i, 13, 64)) for i in range(256))
    _, _, rgba = A.tim2_picture_rgba(texture(8, width=256, pixels=bytes(range(256)), colors=colors))
    # Explicit independent expected order for the first two CSM1 groups.
    order = list(range(8)) + list(range(16,24)) + list(range(8,16)) + list(range(24,40)) + list(range(48,56)) + list(range(40,48)) + list(range(56,64))
    assert list(rgba[:64*4:4]) == order
    assert set(rgba[3::4]) == {128}
    assert len(rgba) == 1024


def test_direct_alpha_saturates_and_rgb_is_unchanged():
    source = b"".join(bytes((1, 2, 3, a)) for a in (0, 1, 64, 127, 128, 255))
    _, _, rgba = A.tim2_picture_rgba(texture(32, width=6, pixels=source))
    assert list(rgba[3::4]) == [0, 2, 128, 254, 255, 255]
    assert rgba[::4] == bytes([1]*6)


@pytest.mark.parametrize("offset,fmt,value", [
    (4,"B",3), (5,"B",2), (6,"H",0), (6,"H",65),
    (16,"I",0), (16,"I",0xffffffff), (28,"H",47),
    (32,"B",1), (33,"B",2), (35,"B",255),
    (36,"H",0), (38,"H",0), (36,"H",3),
    (20,"I",63), (24,"I",0), (30,"H",15),
])
def test_malformed_header_rejected(offset, fmt, value):
    with pytest.raises(ValueError):
        A.tim2_picture_rgba(replace(texture(), offset, fmt, value))


@pytest.mark.parametrize("cut", [0, 4, 15, 16, 47, 63, 64, 65, 128])
def test_truncation_never_returns_short_rgba(cut):
    with pytest.raises(ValueError):
        A.tim2_picture_rgba(texture()[:cut])


def test_truncated_direct_data_rejected():
    with pytest.raises(ValueError):
        A.tim2_picture_rgba(texture(32)[:-1])


def test_huge_dimensions_rejected_before_rgba_allocation(monkeypatch):
    payload = replace(replace(texture(), 36, "H", 65534), 38, "H", 65535)
    def forbidden(*args, **kwargs):
        raise AssertionError("allocation must not happen for malformed input")
    monkeypatch.setattr(A, "bytearray", forbidden, raising=False)
    with pytest.raises(ValueError, match="pixel limit"):
        A.tim2_picture_rgba(payload)


@pytest.mark.parametrize("index", [-1, 1, True, 0.0, "0"])
def test_picture_index_rejected(index):
    with pytest.raises(ValueError):
        A.tim2_picture_rgba(texture(), index)


@pytest.mark.parametrize("v", [None, True, 1.0, "100000", -1, 0x7fffffff])
def test_address_types_and_bounds(v):
    with pytest.raises(ValueError):
        A.vaddr_to_file(v)
    with pytest.raises(ValueError):
        A.file_to_vaddr(v)


def test_all_pictures_validated_before_selected_decode():
    first = texture(count=2)
    second = texture()[16:]
    good = first + second
    assert A.tim2_picture_rgba(good, 1)[:2] == (2, 1)
    bad = replace(good, len(first), "I", 0)
    with pytest.raises(ValueError):
        A.tim2_picture_rgba(bad, 0)


def test_alignment_and_extended_header():
    assert A.tim2_picture_rgba(texture(alignment=1, header_size=128))[:2] == (2, 1)


@pytest.mark.parametrize("change", ["many_palettes", "csm2", "csa", "cpsm", "psm", "clut_storage"])
def test_unverified_layout_is_not_silently_decoded(change):
    source = texture(colors=bytes(128)) if change == "many_palettes" else texture()
    if change in ("csm2", "csa", "cpsm", "psm"):
        bit = {"csm2":55,"csa":56,"cpsm":51,"psm":20}[change]
        source = replace(source, 40, "Q", (20 << 20) ^ (1 << bit))
    elif change == "clut_storage":
        source = replace(source, 34, "B", 0x83)
    with pytest.raises(ValueError):
        A.tim2_picture_rgba(source)


def test_trailing_bytes_rejected():
    with pytest.raises(ValueError, match="trailing"):
        A.tim2_picture_meta(texture() + b"X")


def test_payload_bound(monkeypatch):
    monkeypatch.setattr(A, "MAX_PAYLOAD_BYTES", 64)
    with pytest.raises(ValueError, match="limit"):
        A.tim2_picture_rgba(texture())


def test_aggregate_picture_limit(monkeypatch):
    monkeypatch.setattr(A, "MAX_PIXELS", 3)
    with pytest.raises(ValueError, match="aggregate"):
        A.tim2_picture_rgba(texture(count=2) + texture()[16:])


def test_zero_tail_alignment_is_bounded_and_not_decoded():
    source = texture(32, width=1, pixels=b"\x01\x02\x03\x80" + bytes(12))
    assert A.tim2_picture_rgba(source) == (1, 1, b"\x01\x02\x03\xff")
    with pytest.raises(ValueError, match="alignment"):
        A.tim2_picture_rgba(source[:-1] + b"X")
    with pytest.raises(ValueError, match="dimensions"):
        A.tim2_picture_rgba(texture(32, width=1, pixels=bytes(32)))
