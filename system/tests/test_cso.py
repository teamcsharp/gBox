"""Tests for the CISO (Compound ISO / .cso) reader/writer."""
import struct
import pytest
import zlib
from pathlib import Path

from gbox.formats.cso import CISO_MAGIC, BLOCK_UNIT, Cso, CsoError, _split_width


def make_cso(path: Path, data: bytes, block_size: int = 2048, version: int = 1,
             force_stored: tuple = ()) -> list[int]:
    """Synthetic CISOv2-style writer matching the real image layout.

    Header (24 bytes, little-endian): magic b"CISO" | u32 version | u32 image_size
    | u32 block_size | u32 index (0) | 4 zero bytes.  The TOC holds n_blocks + 1
    u64 entries (the last is the end sentinel) starting right after the header;
    block data starts at the first 2048-aligned boundary after the TOC.  Each
    entry packs a 3-bit mode in the top 3 bits and a 61-bit offset counted in
    2048-byte units; offsets accumulate (stored blocks advance one unit,
    compressed blocks advance by their packed payload).
    """
    n_blocks = (len(data) + block_size - 1) // block_size
    units_per_block = (block_size + BLOCK_UNIT - 1) // BLOCK_UNIT
    header = struct.pack("<4sIIII4s", b"CISO", version, len(data), block_size, 0, b"\x00" * 4)
    toc_bytes = 8 * (n_blocks + 1)
    
    # Data starts after header + TOC, rounded up to next 2048-byte unit boundary
    data_start = ((len(header) + toc_bytes + BLOCK_UNIT - 1) // BLOCK_UNIT) * BLOCK_UNIT
    
    toc: list[int] = []
    cursor_units = data_start // BLOCK_UNIT
    modes = []
    
    for i in range(n_blocks):
        chunk = data[i * block_size:(i + 1) * block_size].ljust(block_size, b"\x00")  # real writers zero-pad the tail block
        if i in force_stored:
            payload = chunk + b"\x00" * (block_size - len(chunk))
            mode = 0
        else:
            c = zlib.compressobj(9, zlib.DEFLATED, -15)
            payload = c.compress(chunk) + c.flush()
            mode = 1
        if len(payload) >= len(chunk) and mode == 1:  # incompressible -> stored
            payload = chunk + b"\x00" * (block_size - len(chunk))
            mode = 0
        toc.append((mode << 61) | cursor_units)
        if mode == 0:
            # Stored blocks always occupy exactly one block_size unit
            cursor_units += units_per_block
        else:
            # Compressed blocks advance by their payload size in units (rounded up)
            payload_units = (len(payload) + BLOCK_UNIT - 1) // BLOCK_UNIT
            cursor_units += payload_units
        modes.append(mode)
    
    # Sentinel entry marks end of last payload unit
    sentinel_offset = cursor_units
    toc.append((1 << 61) | sentinel_offset)
    
    # Build body: payloads placed contiguously at their TOC unit offsets,
    # each compressed payload unit-aligned (padded) so the next entry's
    # start unit is an exact multiple boundary.
    toc_end = len(header) + toc_bytes
    toc_padding = b"\x00" * (data_start - toc_end)
    body = bytearray(b"\x00" * (sentinel_offset * BLOCK_UNIT - data_start))

    for i in range(n_blocks):
        chunk = data[i * block_size:(i + 1) * block_size].ljust(block_size, b"\x00")  # real writers zero-pad the tail block
        if i in force_stored or modes[i] == 0:
            payload = chunk + b"\x00" * (block_size - len(chunk))
        else:
            c = zlib.compressobj(9, zlib.DEFLATED, -15)
            payload = c.compress(chunk) + c.flush()
            if len(payload) >= len(chunk):
                payload = chunk + b"\x00" * (block_size - len(chunk))
        start_unit = toc[i] & ((1 << 61) - 1)
        body_offset = start_unit * BLOCK_UNIT - data_start
        body[body_offset:body_offset + len(payload)] = payload

    path.write_bytes(header + struct.pack(f"<{n_blocks + 1}Q", *toc) + toc_padding + body)
    return modes


def make_cso_v1(path: Path, data: bytes, block_size: int = 16384, align: int = 2,
                force_stored: tuple = ()) -> list[int]:
    """Synthetic CISO v1 writer matching the real PSP/PS3 image layout.

    Header (24 bytes, little-endian): magic b"CISO" | u32 header_size (24)
    | u64 total_bytes | u32 block_size | u8 ver (1) | u8 align | u16 rsv (0).
    TOC: n_blocks + 1 u32 entries starting at offset 24.
    Each entry is a plain offset in (2^align)-byte units (2048 by default).
    Offsets are monotone non-decreasing; the last entry is the end sentinel.
    """
    import zlib
    n_blocks = (len(data) + block_size - 1) // block_size
    unit = 1 << align  # offset unit in bytes (2048 for align=2)
    toc_bytes = 4 * (n_blocks + 1)
    data_start = ((24 + toc_bytes + BLOCK_UNIT - 1) // BLOCK_UNIT) * BLOCK_UNIT

    toc: list[int] = []
    cursor_units = data_start // unit

    for i in range(n_blocks):
        chunk = data[i * block_size:(i + 1) * block_size].ljust(block_size, b"\x00")
        if i in force_stored:
            mode = 0
            payload = chunk
            payload_units = block_size // unit
        else:
            c = zlib.compressobj(9, zlib.DEFLATED, -15)
            payload = c.compress(chunk) + c.flush()
            mode = 1
            payload_units = (len(payload) + unit - 1) // unit
            if len(payload) >= len(chunk):
                mode = 0
                payload = chunk
                payload_units = block_size // unit
        # Pack mode in top 3 bits, offset in low 29 bits
        toc.append((mode << 29) | cursor_units)
        cursor_units += payload_units

    # Sentinel: mode 1, offset at cursor
    toc.append((1 << 29) | cursor_units)

    # Build body
    toc_end = 24 + toc_bytes
    toc_padding = b"\x00" * (data_start - toc_end)
    sentinel_units = toc[-1] & 0x1FFFFFFF
    body = bytearray(b"\x00" * (sentinel_units * unit - data_start))

    for i in range(n_blocks):
        chunk = data[i * block_size:(i + 1) * block_size].ljust(block_size, b"\x00")
        if i in force_stored or (toc[i] >> 29) == 0:
            payload = chunk
        else:
            c = zlib.compressobj(9, zlib.DEFLATED, -15)
            payload = c.compress(chunk) + c.flush()
            if len(payload) >= len(chunk):
                payload = chunk
        start_unit = toc[i] & 0x1FFFFFFF
        body_offset = start_unit * unit - data_start
        body[body_offset:body_offset + len(payload)] = payload

    header = struct.pack("<4sIQIBBH", b"CISO", 24, len(data), block_size, 1, align, 0)
    path.write_bytes(header + struct.pack(f"<{n_blocks + 1}I", *toc) + toc_padding + body)
    return [toc[i] >> 29 for i in range(n_blocks)]


def make_cso_file_v1(path: Path, data: bytes, block_size: int = 16384, align: int = 2,
                     force_stored: tuple = ()) -> Cso:
    """Write a synthetic CISO v1 file and return a Cso reader for it."""
    make_cso_v1(path, data, block_size, align, force_stored)
    return Cso(path)


def make_cso_file(path: Path, data: bytes, block_size: int = 2048, version: int = 1,
                  force_stored: tuple = ()) -> Cso:
    """Write a synthetic CISO file and return a Cso reader for it."""
    make_cso(path, data, block_size, version, force_stored)
    return Cso(path)


def _split_v2(entry: int, shift: int) -> tuple[int, int]:
    """Mirror of the reader's v2 entry split: mode in the top bits, offset in the rest."""
    mask = ~((1 << shift) - 1)
    return (entry & mask) >> shift, entry & ~mask


class TestSplit:
    """Test the v2 mode-field split (top-3-bit and top-2-bit layouts)."""

    def test_mode_in_top_3_bits(self):
        """Mode 1 with offset 100 in top 3 bits."""
        entry = (1 << 61) | 100
        mode, offset = _split_v2(entry, 61)
        assert mode == 1
        assert offset == 100

    def test_mode_in_top_2_bits(self):
        """Mode 2 with offset in top 2 bits layout."""
        entry = (2 << 62) | 200
        mode, offset = _split_v2(entry, 62)
        assert mode == 2
        assert offset == 200


class TestSplitWidth:
    """Test mode-field width detection from a TOC table."""

    def test_sniffs_top_3_bits(self):
        """Detection picks top-3-bit layout when valid."""
        table = [(1 << 61) | 10, (0 << 61) | 20, (2 << 61) | 30]
        shift = _split_width(table)
        assert shift == 61

    def test_sniffs_top_2_bits(self):
        """Detection picks top-2-bit layout when top-3-bit would overflow."""
        table = [(1 << 62) | 10, (0 << 62) | 20, (2 << 62) | 30]
        shift = _split_width(table)
        assert shift == 62


class TestCsoReader:
    """Tests for the Cso reader."""

    def test_roundtrip(self, tmp_path: Path):
        """Create and read back a synthetic CISO file."""
        data = b"X" * 5000  # More than one block
        path = tmp_path / "test.cso"
        cso = make_cso_file(path, data)
        assert cso.read_block(0) == data[:2048]
        assert cso.read(0, 5000) == data[:5000]

    def test_stored_and_mixed_blocks(self, tmp_path: Path):
        """Test a mix of stored and compressed blocks."""
        # Use a compressible pattern
        data = b"A" * 1024 + b"B" * 1024 + b"C" * 1024 + b"D" * 1024
        path = tmp_path / "mixed.cso"
        # Force first block to stored, others compressed
        cso = make_cso_file(path, data, force_stored=(0,))
        assert cso.read(0, len(data)) == data

    def test_block_size_8192(self, tmp_path: Path):
        """Test with a non-default block size of 8192 bytes."""
        data = b"Y" * 20000
        path = tmp_path / "bs8k.cso"
        cso = make_cso_file(path, data, block_size=8192)
        assert cso.block_size == 8192
        assert cso.read(0, len(data)) == data

    def test_zero_version_accepted(self, tmp_path: Path):
        """Version 0 (PPSSPP-style) should be accepted."""
        data = b"Z" * 3000
        path = tmp_path / "v0.cso"
        cso = make_cso_file(path, data, version=0)
        assert cso.version == 0
        assert cso.read(0, len(data)) == data


class TestValidation:
    """Tests for validation errors."""

    def test_invalid_magic(self, tmp_path: Path):
        """Reject file with wrong magic."""
        path = tmp_path / "bad_magic.cso"
        header = struct.pack("<4sIIII4s", b"BAD!", 1, 2048, 2048, 0, b"\x00" * 4)
        path.write_bytes(header)
        with pytest.raises(CsoError, match="no 'CISO' magic"):
            Cso(path)

    def test_invalid_block_size(self, tmp_path: Path):
        """Reject non-power-of-two or non-2048-multiple block size."""
        path = tmp_path / "bad_block.cso"
        header = struct.pack("<4sIIII4s", b"CISO", 1, 2048, 1024, 0, b"\x00" * 4)
        path.write_bytes(header)
        with pytest.raises(CsoError, match="invalid block size"):
            Cso(path)


class TestCisoV1:
    """Tests for the CISO v1 layout (u32-per-block TOC, u64 total_bytes)."""

    def test_roundtrip_v1(self, tmp_path: Path):
        """Create and read back a synthetic CISO v1 file."""
        data = b"X" * 50000  # several 16384-byte blocks
        path = tmp_path / "test_v1.cso"
        cso = make_cso_file_v1(path, data)
        assert cso.version == 1
        assert cso.block_size == 16384
        assert cso.image_size == len(data)
        assert cso.read(0, len(data)) == data

    def test_v1_stored_and_mixed_blocks(self, tmp_path: Path):
        """A mix of stored (mode 0) and compressed (mode 1) blocks in v1."""
        data = (b"A" * 16384) + (b"B" * 16384) + (b"C" * 16384)
        path = tmp_path / "v1mixed.cso"
        cso = make_cso_file_v1(path, data, force_stored=(0,))
        assert cso.read(0, len(data)) == data

    def test_v1_observed_header_fields(self, tmp_path: Path):
        """Lock the exact field layout seen on the real owned RE4 CSO: u64
        total_bytes, u32 block_size=16384, ver=1, align=2, u32 TOC entries
        with the offset in low 29 bits."""
        data = b"\x00" * (3 * 16384)
        path = tmp_path / "v1fields.cso"
        make_cso_v1(path, data)
        raw = path.read_bytes()
        magic, header_size = raw[:4], struct.unpack_from("<I", raw, 4)[0]
        total_bytes = struct.unpack_from("<Q", raw, 8)[0]
        block_size = struct.unpack_from("<I", raw, 16)[0]
        ver, align = raw[20], raw[21]  # ver u8 @20, align u8 @21, rsv u16 @22
        assert magic == b"CISO"
        assert header_size == 24
        assert total_bytes == len(data)
        assert block_size == 16384
        assert ver == 1
        assert align == 2


class TestRealRe4HeaderFixture:
    """Validate the parser against the observed real RE4 CSO header bytes."""

    def test_parses_real_header(self):
        """The real 24-byte header (PS3 RE4 CSO) must decode as CISO v1."""
        fixture = Path(__file__).parent / "fixtures" / "re4_cso_header.bin"
        raw = fixture.read_bytes()
        assert raw[:4] == b"CISO"
        header_size = struct.unpack_from("<I", raw, 4)[0]
        total_bytes = struct.unpack_from("<Q", raw, 8)[0]
        block_size = struct.unpack_from("<I", raw, 16)[0]
        ver, align = raw[20], raw[21]  # ver u8 @20, align u8 @21, rsv u16 @22
        assert header_size == 24
        assert total_bytes == 0x108658000  # 4,435,836,928
        assert block_size == 0x4000        # 16384
        assert ver == 1
        assert align == 2
        # First TOC entries are u32 offsets in 2048-byte units, low 29 bits.
        n_blocks = total_bytes // block_size
        assert n_blocks == 270742
        idx = [struct.unpack_from("<I", raw, 24 + i * 4)[0] for i in range(16)]
        assert idx[0] == 0x04219D  # 270,749 (sentinel-sized literal from real bytes)
        # every entry's low 29-bit offset is a sane number of 2048-byte units
        for e in idx:
            assert (e >> 29) <= 3
            assert (e & 0x1FFFFFFF) < (1 << 42)


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
