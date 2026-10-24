"""CISO (Compound ISO / .cso) compressed disc images, the format every PSP .cso on the shelf uses.

Layout (all little-endian):

  header (24 bytes): magic b"CISO" | u32 version | u32 image_size | u32 block_size
  (power of two, multiple of 2048) | u32 index (0) | 4 zero bytes.  PPSSPP-style
  writers leave the version field zeroed; magic + geometry sniff is the real gate.

  TOC: total_blocks + 1 u64 entries starting at offset 24 (the last entry is the
  end sentinel marking where the payload ends). Each entry packs a 3-bit mode in
  the top bits and an offset counted in units of 2048 bytes. The offset field
  accumulates across the table: uncompressed blocks advance by exactly one unit,
  compressed blocks advance by however many units their packed payload occupies.
  Block data starts at the first 2048-aligned boundary after the TOC.

  modes: 0 = stored verbatim (reads span [offset, offset+block_size)),
         1..3 = deflate payload read from [offset, next_entry_offset) and inflated
                to one block; mode 3 adds a zlib header, modes 1/2 are raw deflate.

Reading never trusts a raw offset: the reader validates the header, the monotone
accumulation of the TOC and that every block stays inside the file.
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

CISO_MAGIC = b"CISO"
HEADER_SIZE = 24
TOC_ENTRY_SIZE = 8
MODE_MASK = 0xC000000000000000
OFFSET_MASK = ~MODE_MASK
BLOCK_UNIT = 2048  # TOC offsets are counted in 2048-byte units regardless of block_size


class CsoError(ValueError):
    """Raised for a file that is not a structurally valid CISO image."""


def _split(entry: int, shift: int) -> tuple[int, int]:
    """Unpack one TOC entry into (mode, offset_in_2048_units) given the mode-field shift."""
    mask = ~((1 << shift) - 1)
    return (entry & mask) >> shift, entry & ~mask


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
    # Try shifts from 62 (top 2 bits) down to 59 (top 5 bits) to find the mode field
    for shift in (62, 61, 60, 59):
        mask = ~((1 << shift) - 1)
        if all((e & mask) >> shift <= 3 and (e & ~mask) < (1 << 42) for e in table):
            return shift
    raise CsoError("no TOC mode-field width in the top 1..3 bits decodes every entry")


def _mode_shift(table: list[int]) -> int:
    """Public helper kept for tests: the shift chosen for a table (same sniff as the reader)."""
    return _split_width(table)


class Cso:
    """Read-only view of a .cso file. Originals are never written."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        with open(self.path, "rb") as fh:
            hdr = fh.read(HEADER_SIZE)
            if len(hdr) < HEADER_SIZE:
                raise CsoError(f"{self.path.name}: too small for a CISO header ({len(hdr)} bytes)")
            magic, version, image_size, block_size, index = struct.unpack("<4sIIII", hdr[:20])
            if magic != CISO_MAGIC:
                raise CsoError(f"{self.path.name}: file has no 'CISO' magic (got {magic!r})")
            if version > 3:
                raise CsoError(f"{self.path.name}: unsupported CISO version {version}")
            # PPSSPP-style writers leave the version field zeroed; magic + geometry sniff is the real gate.
            if block_size < BLOCK_UNIT or block_size & (block_size - 1):
                raise CsoError(f"{self.path.name}: invalid block size {block_size}: not a power of "
                               f"two that is a multiple of {BLOCK_UNIT}")
            if image_size == 0:
                raise CsoError(f"{self.path.name}: empty image size")
            self.version = version
            self.block_size = block_size
            self.image_size = image_size
            self.index = index
            self.total_blocks = (image_size + block_size - 1) // block_size
            fh.seek(0, 2)
            self.file_size = fh.tell()
            toc_bytes = TOC_ENTRY_SIZE * (self.total_blocks + 1)  # + 1 end sentinel
            self.toc_start = HEADER_SIZE
            self.data_start = (self.toc_start + toc_bytes + BLOCK_UNIT - 1) // BLOCK_UNIT * BLOCK_UNIT
            if self.file_size < self.toc_start + toc_bytes:
                raise CsoError(f"{self.path.name}: truncated TOC ({self.file_size - self.toc_start} of "
                               f"{toc_bytes} bytes)")
            fh.seek(self.toc_start)
            raw = fh.read(toc_bytes)
        self._shift = _split_width([struct.unpack_from("<Q", raw, i * TOC_ENTRY_SIZE)[0]
                                    for i in range(self.total_blocks + 1)])
        self.toc = [struct.unpack_from("<Q", raw, i * TOC_ENTRY_SIZE)[0]
                    for i in range(self.total_blocks + 1)]
        self._validate_toc()

    def _split(self, entry: int) -> tuple[int, int]:
        mask = ~((1 << self._shift) - 1)
        return (entry & mask) >> self._shift, entry & ~mask

    def _validate_toc(self) -> None:
        """TOC offsets accumulate in 2048-byte units and must stay non-decreasing inside the file."""
        prev_boundary = (self.data_start + BLOCK_UNIT - 1) // BLOCK_UNIT  # first payload unit
        for i, entry in enumerate(self.toc):
            mode, start_units = self._split(entry)
            if mode > 3:
                raise CsoError(f"block {i}: mode {mode} out of range")
            if start_units < prev_boundary:
                raise CsoError(f"block {i}: offset {start_units} rewinds before the running boundary "
                               f"{prev_boundary}")
            # The sentinel (last entry) marks the end of the last block and may point past the file.
            # Real block starts must point inside the file (proved by read()).
            if i < self.total_blocks and start_units * BLOCK_UNIT >= self.file_size:
                raise CsoError(f"block {i}: offset {start_units} * {BLOCK_UNIT} past end of file "
                               f"({self.file_size} bytes)")
            prev_boundary = start_units

    def _block_bounds(self, i: int) -> tuple[int, int, int]:
        """Return (mode, start_bytes, end_bytes) for block i. The payload end comes from the
        next distinct TOC offset (the end sentinel closes the last block); stored blocks
        always span exactly one block_size."""
        mode, start_units = self._split(self.toc[i])
        start = start_units * BLOCK_UNIT
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
                nxt = (self.file_size + BLOCK_UNIT - 1) // BLOCK_UNIT
            end = min(nxt * BLOCK_UNIT, self.file_size)
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
