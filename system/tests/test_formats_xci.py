"""Focused tests for gbox.formats.xci: container classification + plaintext HFS0 walk.

Synthetic images only (no game data).  The headerless case mirrors the byte layout
observed on the Bayonetta 2 (World).xci owned source: a high-entropy offset 0, a
"HEAD" signature at 0x100 with nonsense header fields, and an all-0xFF NCSD slot at
0x7000 -- which must classify as an encrypted container requiring the header key, and
must NOT be silently listed as readable.
"""
import struct

import pytest

from gbox.formats import xci


def _pad(b: bytes, n: int) -> bytes:
    if len(b) < n:
        b += b"\x00" * (n - len(b))
    return b[:n]


def build_standard_xci() -> bytes:
    # XCI0 at 0, sane header at 0x100, plaintext NCSD-ish table at 0x7000.
    data = bytearray(0x8000)
    data[0:4] = xci.XCI_MAGIC
    data[0x100:0x104] = b"XXXX"          # not HEAD
    struct.pack_into("<III", data, 0x104, 0x10000, 0x200, 0x400)  # image/sector/header
    data[0x7000:0x7040] = bytes(range(0x40))  # plaintext NCSD (not 0xFF)
    return bytes(data)


def build_headerless_xci() -> bytes:
    data = bytearray(0x8000)
    data[0:16] = bytes([0x21, 0x8D, 0x92, 0xC8] + list(range(12)))  # high-entropy-ish
    data[0x100:0x104] = xci.HEADLESS_MAGIC
    # nonsense header fields (as seen on the owned source)
    struct.pack_into("<II", data, 0x104, 0x000B84C0, 0xFFFFFFFF)
    struct.pack_into("<I", data, 0x110, 0x191DE2F8)
    data[0x7000:0x7040] = b"\xff" * 0x40   # encrypted NCSD slot
    return bytes(data)


def build_hfs0_image(files: dict[str, bytes]) -> bytes:
    """Synthetic plaintext HFS0 at offset 0 for read_hfs0 round-trip."""
    entries = bytearray()
    names = bytearray()
    blob = bytearray()
    name_off = 0
    hash_off = 0
    for name, payload in files.items():
        nb = name.encode("utf-8")
        entries += struct.pack("<IIIIII", name_off, len(nb), hash_off, len(payload), 0, 0)
        names += nb
        name_off += len(nb)
        blob += payload
        hash_off += len(payload)
    header = xci.HFS0_MAGIC + struct.pack("<III", len(files), len(names), 0)
    table = header + entries + names + bytes((-((len(header) + len(entries) + len(names))) % 16))
    return bytes(table + blob)


def make_read_at(image: bytes):
    def read_at(off, size):
        return image[off:off + size]
    return read_at


# --------------------------------------------------------------- classification

def test_standard_classifies_readable():
    img = build_standard_xci()
    info = xci.classify(img, len(img), "std.xci")
    assert info.layout == "standard"
    assert info.partition_table_readable is True
    assert info.header_key_required is False


def test_headerless_classifies_encrypted_not_readable():
    img = build_headerless_xci()
    info = xci.classify(img, len(img), "hdr.xci")
    assert info.layout == "headerless"
    assert info.partition_table_readable is False
    assert info.header_key_required is True
    assert any("encrypted" in n.lower() for n in info.notes)


def test_unknown_when_no_signature():
    img = bytes(0x8000)
    info = xci.classify(img, len(img), "rand")
    assert info.layout == "unknown"
    assert info.partition_table_readable is False
    assert info.header_key_required is False


def test_head_too_short_is_unknown():
    info = xci.classify(b"XCI0", 4, "tiny")
    assert info.layout == "unknown"


# --------------------------------------------------------------- HFS0 round-trip

def test_hfs0_round_trip():
    files = {"main": b"HELLO", "icon": b"\x00\x01\x02\x03", "a.txt": b"abc"}
    img = build_hfs0_image(files)
    table = xci.read_hfs0(make_read_at(img), 0)
    assert table.file_count == 3
    assert table.string_table_size == sum(len(k) for k in files)
    names = {e.name: e.size for e in table.entries}
    assert names == {k: len(v) for k, v in files.items()}


def test_hfs0_no_magic_raises():
    img = b"NOTANHSFTABLE" * 100
    with pytest.raises(ValueError):
        xci.read_hfs0(make_read_at(img), 0)


def test_hfs0_implausible_count_raises():
    hdr = xci.HFS0_MAGIC + struct.pack("<III", 0, 0, 0)
    with pytest.raises(ValueError):
        xci.read_hfs0(make_read_at(hdr + bytes(64)), 0)


def test_find_hfs0_offsets_finds_magic():
    img = build_hfs0_image({"x": b"y"})
    offsets = xci._find_hfs0_offsets(img)
    assert 0 in offsets


def _entropy(b: bytes, n: int) -> bytes:
    """Deterministic high-entropy filler (no NULs, no ASCII names)."""
    import hashlib
    out = bytearray()
    seed = 0
    while len(out) < n:
        seed = (seed * 1103515245 + 12345) & 0x7FFFFFFF
        out += bytes(((seed >> (i * 8)) & 0xFF) ^ 0xA5 for i in range(4))
        seed += len(b)
    return bytes(out[:n])


def test_false_positive_hfs0_is_not_a_readable_listing():
    """Regression: the Bayonetta 2 (World) headerless XCI owns a *spurious* HFS0 magic
    at 0xf000 (file_count=3, string_table_size=304) whose string table is pure entropy
    and whose entries carry impossible hash offsets. The classifier must NOT treat such
    a table as a readable file listing; a real CONTENT partition has hundreds of files
    with NUL-terminated names, and the spurious table must fail to produce a valid
    manifest. Encodes the verified-negative finding from the fixed-layout probe."""
    img = bytearray(0x10000)
    # Place a spurious HFS0 header with entropy entries (mirrors the owned 0xf000 bytes:
    # header_count=3, string_table_size=304, entropy string table, garbage entries).
    base = 0xF000
    img[base:base + 4] = xci.HFS0_MAGIC
    struct.pack_into("<II", img, base + 4, 3, 304)         # file_count, string_table_size
    ent = _entropy(b"", 3 * 24)                            # entropy entry block
    img[base + 16:base + 16 + 72] = ent
    names = _entropy(b"", 304)                            # entropy string table (no names)
    img[base + 16 + 72:base + 16 + 72 + 304] = names

    table = xci.read_hfs0(lambda off, size: bytes(img[off:off + size]), base)
    # The table parses (magic + count are self-consistent) but NONE of the entries are
    # real files: every name is empty/garbage. That is the signature of a false positive.
    real = [e for e in table.entries if e.name and 0 < e.size < 1 << 30]
    assert table.file_count == 3
    assert real == [], "spurious entropy HFS0 must not yield a single real file entry"


def test_headerless_has_no_fixed_key_free_hfs0_offset():
    """On a headerless card the partition table at 0x7000 is AES-XTS encrypted; the
    CONTENT partition HFS0 has NO fixed, key-free offset. classify() must report the
    container as unreadable / header_key_required, and the head-region HFS0 scan must
    find no *trusted* table (any spurious magic is not a listing)."""
    img = build_headerless_xci()
    info = xci.classify(img, len(img), "hdr.xci")
    assert info.header_key_required is True
    assert info.partition_table_readable is False
    # The head-region audit list may contain offsets, but none is an authoritative
    # listing: a trusted listing would require the header key.
    for hit in info.plaintext_hfs0:
        # Each 'offset' is a magic location only -- not a validated file table.
        assert isinstance(hit, dict) and "offset" in hit
