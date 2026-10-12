"""CISO / CSO compressed disc images (PS2 and PSP collections ship them; #1321 Resident Evil 4 PS2).

Layout (CISO v0/v1, little-endian):

  0x00 "CISO"   0x04 u32 header size (0x18; some writers store 0)   0x08 u64 uncompressed size
  0x10 u32 block size (2048)   0x14 u8 version   0x15 u8 index shift (align)   0x16 2 reserved
  0x18 (size / block + 1) x u32 index: offset = (entry & 0x7FFFFFFF) << shift; bit 31 = block stored plain.
  A compressed block is raw deflate (zlib wbits=-15) of exactly one block; its length is next offset - offset.

ZSO ("ZISO", LZ4) is a different codec and is refused with a clear error rather than guessed.

`CSO(path)` is a read-only, seekable file object over the *uncompressed* image, so ISO9660 readers
(`romexport.iso_files`) work on it directly; `to_iso(src, dst)` writes the plain image once and returns its sha256
together with the sha256 of the compressed source, both computed in the same single pass over the source.
"""
from __future__ import annotations

import hashlib
import io
import os
import struct
import zlib
from pathlib import Path

MAGIC = b"CISO"
HEADER = 0x18


class CSOError(ValueError):
    pass


def parse_header(head: bytes) -> dict:
    if head[:4] == b"ZISO":
        raise CSOError("ZSO (LZ4) images aren't supported; convert it with maxcso --decompress first")
    if head[:4] != MAGIC or len(head) < HEADER:
        raise CSOError("not a CISO/CSO image (no 'CISO' magic)")
    hsize, total, block, ver, shift = struct.unpack_from("<IQIBB", head, 4)
    if block == 0 or block & (block - 1):
        raise CSOError(f"bad CSO block size {block}")
    if ver > 1:
        raise CSOError(f"CSO version {ver} isn't supported (v0/v1 only)")
    return {"header_size": hsize or HEADER, "total": total, "block": block, "version": ver, "shift": shift,
            "blocks": (total + block - 1) // block}


class CSO(io.RawIOBase):
    """Random-access reader over the uncompressed contents of a CSO image."""

    def __init__(self, path):
        super().__init__()
        self.path = Path(path)
        self._f = open(self.path, "rb")
        self.info = parse_header(self._f.read(HEADER))
        n = self.info["blocks"] + 1
        self._f.seek(HEADER)
        raw = self._f.read(4 * n)
        if len(raw) != 4 * n:
            raise CSOError("CSO index table is truncated")
        self.index = struct.unpack(f"<{n}I", raw)
        self.size = self.info["total"]
        self._pos = 0
        self._cache = (-1, b"")

    # -- io.RawIOBase ---------------------------------------------------------------------------------------------
    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self._pos

    def seek(self, off, whence=os.SEEK_SET):
        base = {os.SEEK_SET: 0, os.SEEK_CUR: self._pos, os.SEEK_END: self.size}[whence]
        self._pos = max(0, base + off)
        return self._pos

    def close(self):
        if not self.closed:
            self._f.close()
        super().close()

    def block(self, i: int) -> bytes:
        if self._cache[0] == i:
            return self._cache[1]
        bs, shift = self.info["block"], self.info["shift"]
        a, b = self.index[i], self.index[i + 1]
        start, end = (a & 0x7FFFFFFF) << shift, (b & 0x7FFFFFFF) << shift
        self._f.seek(start)
        if a & 0x80000000:
            data = self._f.read(bs)
        else:
            comp = self._f.read(end - start)
            try:
                data = zlib.decompressobj(-15).decompress(comp, bs)
            except zlib.error as e:
                raise CSOError(f"block {i} at 0x{start:x} doesn't inflate: {e}") from e
        want = min(bs, self.size - i * bs)
        if len(data) < want:
            raise CSOError(f"block {i} inflated to {len(data)} bytes, expected {want}")
        data = data[:want]
        self._cache = (i, data)
        return data

    def read(self, n=-1) -> bytes:
        if n is None or n < 0:
            n = self.size - self._pos
        n = max(0, min(n, self.size - self._pos))
        out = bytearray()
        bs = self.info["block"]
        while n > 0:
            i, o = divmod(self._pos, bs)
            chunk = self.block(i)[o:o + n]
            out += chunk
            self._pos += len(chunk)
            n -= len(chunk)
        return bytes(out)

    def readinto(self, b):
        data = self.read(len(b))
        b[:len(data)] = data
        return len(data)


def to_iso(src, dst, progress=None, chunk_blocks: int = 4096) -> dict:
    """Decompress `src` to `dst` (via dst.part). One sequential read of the source; returns both sha256s."""
    src, dst = Path(src), Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    part = dst.with_name(dst.name + ".part")
    hs, hi = hashlib.sha256(), hashlib.sha256()
    with open(src, "rb") as f:
        head = f.read(HEADER)
        info = parse_header(head)
        n = info["blocks"] + 1
        idx_raw = f.read(4 * n)
        index = struct.unpack(f"<{n}I", idx_raw)
        hs.update(head)
        hs.update(idx_raw)
        pos = HEADER + 4 * n
        bs, shift, total = info["block"], info["shift"], info["total"]
        with open(part, "wb") as o:
            for i in range(info["blocks"]):
                a, b = index[i], index[i + 1]
                start, end = (a & 0x7FFFFFFF) << shift, (b & 0x7FFFFFFF) << shift
                if start > pos:                                   # alignment padding between blocks
                    pad = f.read(start - pos)
                    hs.update(pad)
                    pos = start
                comp = f.read((bs if a & 0x80000000 else end - start))
                hs.update(comp)
                pos += len(comp)
                data = comp if a & 0x80000000 else zlib.decompressobj(-15).decompress(comp, bs)
                data = data[:min(bs, total - i * bs)]
                if len(data) != min(bs, total - i * bs):
                    raise CSOError(f"block {i} inflated to {len(data)} bytes")
                hi.update(data)
                o.write(data)
                if progress and i % (chunk_blocks * 64) == 0:
                    progress(i / info["blocks"], f"CSO block {i}/{info['blocks']}")
        while True:                                               # trailing bytes still belong to the source hash
            rest = f.read(1 << 20)
            if not rest:
                break
            hs.update(rest)
    part.replace(dst)
    return {"source_sha256": hs.hexdigest(), "iso_sha256": hi.hexdigest(), "iso_size": total, **info}


def write_cso(data: bytes, dst, block: int = 2048, shift: int = 0, plain_every: int = 0) -> Path:
    """Small CISO v1 writer (tests and fixtures). plain_every=k stores every k-th block uncompressed."""
    blocks = (len(data) + block - 1) // block
    body, index = bytearray(), []
    base = HEADER + 4 * (blocks + 1)
    for i in range(blocks):
        cur = base + len(body)
        cur += -cur % (1 << shift)
        body += b"\0" * (cur - base - len(body))
        raw = data[i * block:(i + 1) * block]
        plain = plain_every and i % plain_every == 0
        if plain:
            raw = raw + b"\0" * (block - len(raw))
            index.append((cur >> shift) | 0x80000000)
            body += raw
        else:
            c = zlib.compressobj(9, zlib.DEFLATED, -15)
            index.append(cur >> shift)
            body += c.compress(raw) + c.flush()
    cur = base + len(body)
    cur += -cur % (1 << shift)
    body += b"\0" * (cur - base - len(body))
    index.append(cur >> shift)
    out = struct.pack("<4sIQIBBxx", MAGIC, HEADER, len(data), block, 1, shift) + struct.pack(f"<{blocks + 1}I", *index)
    Path(dst).write_bytes(out + bytes(body))
    return Path(dst)


def cached_iso(rom, dst, progress=None) -> Path:
    """The plain ISO of a CSO for ISO9660/patching code, decompressed once next to a .sha256 receipt."""
    dst = Path(dst)
    if not dst.exists():
        r = to_iso(rom, dst, progress)
        dst.with_name(dst.name + ".json").write_text(__import__("json").dumps(r, indent=1))
    return dst


if __name__ == "__main__":
    import json
    import sys
    print(json.dumps(to_iso(sys.argv[1], sys.argv[2], lambda p, m: print(f"{p:.0%} {m}", flush=True)), indent=1))
