"""Dolphin GCZ (CompressedBlob) reader for GameCube disc images.

GCZ is Dolphin's scrubbed/compressed disc-image container.  Layout
(after Dolphin 5.0 Source/Core/DiscIO/CompressedBlob.h):

  header (32 bytes)
      u32 magic           0xB10BC001
      u32 sub_type        0 = full image, 1 = scrubbed
      u64 compressed_data_size
      u64 data_size
      u32 block_size       (0x4000 here)
      u32 num_blocks
  u64 block_pointer[num_blocks]
      top bit (1<<63) set  -> block stored uncompressed (raw)
      low bits             -> offset of the block inside the compressed
                              data region, relative to data_offset
  u32 block_hash[num_blocks]   (Adler32 of the STORED bytes)
  compressed data
      block i spans [ptr[i], ptr[i+1]) ; the last block spans
      [ptr[n-1], compressed_data_size)

This module reads arbitrary byte ranges out of a GCZ without
decompressing more than the touched 16 KiB blocks.
"""

from __future__ import annotations

import os
import struct
import zlib

GCZ_MAGIC = 0xB10BC001


class GCZError(Exception):
    pass


class GCZ:
    """Random-access reader over a Dolphin GCZ container."""

    def __init__(self, path: str, verify_hashes: bool = False):
        self.path = path
        self._f = open(path, "rb")
        hdr = self._f.read(32)
        if len(hdr) < 32:
            raise GCZError(f"{path}: truncated GCZ header")
        (self.magic, self.sub_type, self.compressed_data_size,
         self.data_size, self.block_size, self.num_blocks) = struct.unpack(
            "<IIQQII", hdr)
        if self.magic != GCZ_MAGIC:
            raise GCZError(f"{path}: bad GCZ magic 0x{self.magic:08x}")
        if self.block_size == 0 or self.num_blocks == 0:
            raise GCZError(f"{path}: empty GCZ image")
        self._f.seek(32)
        self._ptrs = struct.unpack(
            f"<{self.num_blocks}Q", self._f.read(8 * self.num_blocks))
        self._hashes = None
        if verify_hashes:
            self._f.seek(32 + 8 * self.num_blocks)
            self._hashes = struct.unpack(
                f"<{self.num_blocks}I", self._f.read(4 * self.num_blocks))
        self._data_offset = 32 + 12 * self.num_blocks
        self._cache = {}

    def close(self):
        self._f.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    @property
    def file_size(self) -> int:
        return os.path.getsize(self.path)

    def _block_extent(self, i: int):
        p = self._ptrs[i]
        raw = bool(p & (1 << 63))
        off = p & ~(1 << 63)
        nxt = (self._ptrs[i + 1] & ~(1 << 63)
               if i + 1 < self.num_blocks else self.compressed_data_size)
        return raw, off, nxt - off

    def read_block(self, i: int) -> bytes:
        if i >= self.num_blocks:
            raise GCZError(f"block {i} out of range")
        if i in self._cache:
            return self._cache[i]
        raw, off, csize = self._block_extent(i)
        self._f.seek(self._data_offset + off)
        blob = self._f.read(csize)
        if len(blob) != csize:
            raise GCZError(f"{self.path}: truncated block {i}")
        if self._hashes is not None:
            h = zlib.adler32(blob) & 0xFFFFFFFF
            if h != self._hashes[i]:
                raise GCZError(
                    f"{self.path}: block {i} Adler32 mismatch "
                    f"{h:08x} != {self._hashes[i]:08x}")
        if raw:
            if csize != self.block_size:
                raise GCZError(f"{self.path}: raw block {i} has size {csize}")
            out = blob
        else:
            out = zlib.decompress(blob)
            if len(out) != self.block_size:
                raise GCZError(
                    f"{self.path}: block {i} decompressed to {len(out)}")
        self._cache[i] = out
        return out

    def read(self, offset: int, size: int) -> bytes:
        if offset < 0 or size < 0 or offset + size > self.data_size:
            raise GCZError(
                f"{self.path}: read [{offset}, {offset + size}) outside "
                f"image ({self.data_size} bytes)")
        out = bytearray()
        while size:
            i, bo = divmod(offset, self.block_size)
            take = min(size, self.block_size - bo)
            out += self.read_block(i)[bo:bo + take]
            offset += take
            size -= take
        return bytes(out)

    def sha256_range(self, offset: int, size: int) -> str:
        import hashlib
        h = hashlib.sha256()
        remaining = size
        pos = offset
        while remaining:
            i, bo = divmod(pos, self.block_size)
            take = min(remaining, self.block_size - bo)
            h.update(self.read_block(i)[bo:bo + take])
            pos += take
            remaining -= take
        return h.hexdigest()
