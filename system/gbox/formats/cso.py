"""CISO (Compound ISO / .cso) compressed disc images.

Two header layouts exist in the wild:

  CISO v1 (PS3/PSP, the format the PSP .cso on the shelf uses):
    header (24 bytes): magic b"CISO" | u32 header_size (0x18)
      | u64 total_bytes | u32 block_size | u8 ver | u8 align | u16 rsv
    TOC: n_blocks + 1 u32 entries starting at offset 24.
    Each entry is a plain offset in (2^align)-byte units (usually 2048).
    Offsets are monotone non-decreasing; the last entry is the end sentinel.

  CISO v2 (PPSSPP-style, older):
    header (24 bytes): magic b"CISO" | u32 version | u32 image_size
      | u32 block_size | u32 index (0) | 4 zero bytes
    TOC: n_blocks + 1 u64 entries. Each entry packs a 3-bit mode in the
    top bits and an offset counted in 2048-byte units. The last entry
    is the end sentinel.

The reader auto-detects which layout by checking whether the header
decodes as v1 (header_size == 24, total_bytes < 2^64, block_size sane)
or falls through to v2.
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

CISO_MAGIC = b"CISO"
HEADER_SIZE = 24
BLOCK_UNIT = 2048  # TOC offsets are counted in 2048-byte units regardless of block_size


class CsoError(ValueError):
    """Raised for a file that is not a structurally valid CISO image."""


def _inflate(payload: bytes, mode: int, limit: int) -> bytes:
    if mode == 3:
        d = zlib.decompressobj(15)
    else:
        d = zlib.decompressobj(-15)
    out = d.decompress(payload, limit)
    return out + d.flush()


def _split_width(table: list[int]) -> int:
    """Sniff the mode-field width (top 3, 2 or 1 bits) once from the whole TOC (end
    sentinel included): a shift is only accepted when every entry decodes a mode <= 3
    AND leaves every offset a sane (non-negative, below the 2^42 block-unit space)
    number of 2048-byte units."""
    for shift in (62, 61, 60, 59):
        mask = ~((1 << shift) - 1)
        if all((e & mask) >> shift <= 3 and (e & ~mask) < (1 << 42) for e in table):
            return shift
    raise CsoError("no TOC mode-field width in the top 1..3 bits decodes every entry")


def _split_v2(table: list[int]) -> int:
    """Public helper kept for tests: the shift chosen for a v2 table (same sniff as the reader)."""
    return _split_width(table)


def _split_v1_entry(entry: int, align: int) -> tuple[int, int]:
    """For CISO v1: unpack one u32 TOC entry. The mode is in the top 3 bits,
    the offset is in (2^align)-byte units. Returns (mode, offset_in_align_units)."""
    mode = entry >> 29
    offset = entry & 0x1FFFFFFF
    return mode, offset


class Cso:
    """Read-only view of a .cso file. Originals are never written."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        with open(self.path, "rb") as fh:
            hdr = fh.read(HEADER_SIZE)
            if len(hdr) < HEADER_SIZE:
                raise CsoError(f"{self.path.name}: too small for a CISO header ({len(hdr)} bytes)")
            magic = hdr[:4]
            if magic != CISO_MAGIC:
                raise CsoError(f"{self.path.name}: file has no 'CISO' magic (got {magic!r})")

            # v1 header: <4s I Q I B B H> (header_size, total_bytes, block_size, ver, align, rsv)
            header_size = struct.unpack_from("<I", hdr, 4)[0]
            total_bytes = struct.unpack_from("<Q", hdr, 8)[0]
            block_size = struct.unpack_from("<I", hdr, 16)[0]
            ver = struct.unpack_from("<B", hdr, 20)[0]
            align = struct.unpack_from("<B", hdr, 21)[0]

            is_v1 = (
                header_size == 24
                and total_bytes > 0
                and total_bytes < (1 << 64)
                and block_size >= BLOCK_UNIT
                and (block_size & (block_size - 1)) == 0
                and align <= 8
            )

            if is_v1:
                self.version = 1
                self.block_size = block_size
                self.image_size = total_bytes
                self.toc_unit = 1 << align  # offset unit in bytes
                self.total_blocks = (self.image_size + self.block_size - 1) // self.block_size
                fh.seek(0, 2)
                self.file_size = fh.tell()
                toc_bytes = 4 * (self.total_blocks + 1)
                self.toc_start = HEADER_SIZE
                self.data_start = (self.toc_start + toc_bytes + BLOCK_UNIT - 1) // BLOCK_UNIT * BLOCK_UNIT
                if self.file_size < self.toc_start + toc_bytes:
                    raise CsoError(f"{self.path.name}: truncated TOC ({self.file_size - self.toc_start} of "
                                   f"{toc_bytes} bytes)")
                fh.seek(self.toc_start)
                raw = fh.read(toc_bytes)
                self.toc = [struct.unpack_from("<I", raw, i * 4)[0] for i in range(self.total_blocks + 1)]
                self._shift = None
                self._validate_toc_v1()
            else:
                # Fall back to v2: <4s I I I I 4s>
                version, image_size, block_size, index = struct.unpack_from("<IIII", hdr, 4)
                if version > 3:
                    raise CsoError(f"{self.path.name}: unsupported CISO version {version}")
                if block_size < BLOCK_UNIT or block_size & (block_size - 1):
                    raise CsoError(f"{self.path.name}: invalid block size {block_size}: not a power of "
                                   f"two that is a multiple of {BLOCK_UNIT}")
                if image_size == 0:
                    raise CsoError(f"{self.path.name}: empty image size")
                self.version = version
                self.block_size = block_size
                self.image_size = image_size
                self.index = index
                self.toc_unit = BLOCK_UNIT
                self.total_blocks = (image_size + block_size - 1) // block_size
                fh.seek(0, 2)
                self.file_size = fh.tell()
                toc_bytes = 8 * (self.total_blocks + 1)
                self.toc_start = HEADER_SIZE
                self.data_start = (self.toc_start + toc_bytes + BLOCK_UNIT - 1) // BLOCK_UNIT * BLOCK_UNIT
                if self.file_size < self.toc_start + toc_bytes:
                    raise CsoError(f"{self.path.name}: truncated TOC ({self.file_size - self.toc_start} of "
                                   f"{toc_bytes} bytes)")
                fh.seek(self.toc_start)
                raw = fh.read(toc_bytes)
                self.toc = [struct.unpack_from("<Q", raw, i * 8)[0] for i in range(self.total_blocks + 1)]
                self._shift = _split_width(self.toc)
                self._validate_toc()

    def _split(self, entry: int) -> tuple[int, int]:
        if self._shift is None:
            return _split_v1_entry(entry, 2)  # v1: align=2 default
        mask = ~((1 << self._shift) - 1)
        return (entry & mask) >> self._shift, entry & ~mask

    def _validate_toc_v1(self) -> None:
        """CISO v1: offsets are monotone non-decreasing in (2^align)-byte units."""
        prev = 0
        for i, entry in enumerate(self.toc):
            mode, start_units = _split_v1_entry(entry, 2)  # align=2 is the common case
            if mode > 3:
                raise CsoError(f"block {i}: mode {mode} out of range")
            if start_units < prev:
                raise CsoError(f"block {i}: offset {start_units} rewinds before the running boundary {prev}")
            prev = start_units

    def _validate_toc(self) -> None:
        """CISO v2: TOC offsets accumulate in 2048-byte units and must stay non-decreasing inside the file."""
        prev_boundary = (self.data_start + BLOCK_UNIT - 1) // BLOCK_UNIT
        for i, entry in enumerate(self.toc):
            mode, start_units = self._split(entry)
            if mode > 3:
                raise CsoError(f"block {i}: mode {mode} out of range")
            if start_units < prev_boundary:
                raise CsoError(f"block {i}: offset {start_units} rewinds before the running boundary "
                               f"{prev_boundary}")
            if i < self.total_blocks and start_units * BLOCK_UNIT >= self.file_size:
                raise CsoError(f"block {i}: offset {start_units} * {BLOCK_UNIT} past end of file "
                               f"({self.file_size} bytes)")
            prev_boundary = start_units

    def _block_bounds(self, i: int) -> tuple[int, int, int]:
        mode, start_units = self._split(self.toc[i])
        start = start_units * self.toc_unit
        if mode == 0:
            end = start + self.block_size
        else:
            nxt = None
            for j in range(i + 1, self.total_blocks + 1):
                cand = self._split(self.toc[j])[1]
                if cand > start_units:
                    nxt = cand
                    break
            if nxt is None:
                nxt = (self.file_size + self.toc_unit - 1) // self.toc_unit
            end = min(nxt * self.toc_unit, self.file_size)
        if start > end:
            raise CsoError(f"block {i}: bounds {start}..{end} inverted")
        return mode, start, end

    def read_block(self, i: int) -> bytes:
        if not 0 <= i < self.total_blocks:
            raise IndexError(f"block {i} outside 0..{self.total_blocks - 1}")
        mode, start, end = self._block_bounds(i)
        with open(self.path, "rb") as fh:
            fh.seek(start)
            payload = fh.read(end - start)
        if mode == 0:
            if len(payload) < self.block_size:
                raise CsoError(f"block {i}: stored block truncated ({len(payload)} < {self.block_size})")
            return payload[: self.block_size]
        out = _inflate(payload, mode, self.block_size)
        if len(out) != self.block_size:
            raise CsoError(f"block {i}: inflated to {len(out)} bytes, expected {self.block_size}")
        return out

    def read(self, offset: int, size: int) -> bytes:
        if offset < 0 or size < 0:
            raise ValueError("offset and size must be nonnegative")
        if offset >= self.image_size:
            return b""
        size = min(size, self.image_size - offset)
        out = bytearray()
        first = offset // self.block_size
        end_block = (offset + size + self.block_size - 1) // self.block_size
        for b in range(first, end_block):
            chunk = self.read_block(b)
            lo = offset - b * self.block_size if b == first else 0
            hi = offset + size - b * self.block_size if b == end_block - 1 else self.block_size
            out += chunk[lo:hi]
        return bytes(out[:size])
