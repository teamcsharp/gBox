"""Read-only Switch XCI / NCA / ExeFS / NSO helpers (stdlib + cryptography).

Used to resolve the executable identity of an owned XCI so it can be hashed and
opened in REA/Ghidra. Never writes to the source image; keys are read from a
caller-supplied prod.keys path and never returned or logged.
"""
from __future__ import annotations

import hashlib
import struct
from pathlib import Path

XCI_HFS0_OFFSET_FIELD = 0x130


def load_keys(path) -> dict[str, bytes]:
    keys: dict[str, bytes] = {}
    for line in Path(path).read_text(errors="ignore").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            try:
                keys[k.strip()] = bytes.fromhex(v.strip())
            except ValueError:
                pass
    return keys


def read_hfs0(f, base: int) -> list[tuple[str, int, int]]:
    """Return [(name, absolute_offset, size)] for an HFS0 at ``base``."""
    f.seek(base)
    magic, n, strsz, _ = struct.unpack("<4sIII", f.read(16))
    if magic != b"HFS0":
        raise ValueError(f"not HFS0 at {base:#x}: {magic!r}")
    ents = [struct.unpack("<QQI", f.read(0x40)[:20]) for _ in range(n)]
    strtab = f.read(strsz)
    data = base + 16 + 0x40 * n + strsz
    out = []
    for off, size, noff in ents:
        name = strtab[noff:strtab.index(b"\0", noff)].decode("ascii", "replace")
        out.append((name, data + off, size))
    return out


def classify(path) -> dict:
    """Classify an XCI: container layout and partition/NCA inventory."""
    with open(path, "rb") as f:
        head = f.read(0x200)
        info = {"magic": head[0x100:0x104].decode("ascii", "replace"), "partitions": {}}
        root_off = struct.unpack("<Q", head[XCI_HFS0_OFFSET_FIELD:XCI_HFS0_OFFSET_FIELD + 8])[0]
        info["root_hfs0_offset"] = root_off
        try:
            root = read_hfs0(f, root_off)
        except ValueError as exc:
            info.update(layout="unknown", error=str(exc))
            return info
        info["layout"] = "standard"
        for name, off, size in root:
            try:
                info["partitions"][name] = [
                    {"name": n, "offset": o, "size": s} for n, o, s in read_hfs0(f, off)
                ]
            except ValueError:
                info["partitions"][name] = []
    return info


def _xts_dec(data: bytes, key: bytes, sector=0, ss=0x200) -> bytes:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    out = bytearray()
    for i in range(0, len(data), ss):
        tweak = (sector + i // ss).to_bytes(16, "big")
        out += Cipher(algorithms.AES(key), modes.XTS(tweak)).decryptor().update(data[i:i + ss])
    return bytes(out)


def _ctr_dec(key: bytes, hi: bytes, off: int, data: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    base = off - off % 16
    dec = Cipher(algorithms.AES(key), modes.CTR(hi + (base >> 4).to_bytes(8, "big"))).decryptor()
    dec.update(b"\0" * (off % 16))
    return dec.update(data)


def read_nca_header(f, off: int, keys: dict) -> bytes:
    f.seek(off)
    h = _xts_dec(f.read(0xC00), keys["header_key"])
    if h[0x200:0x204] not in (b"NCA3", b"NCA2"):
        raise ValueError("NCA header did not decrypt (wrong header_key?)")
    return h


def extract_exefs(f, nca_off: int, keys: dict) -> dict[str, bytes]:
    """Decrypt the ExeFS PFS0 of a Program NCA (HierarchicalSha256 + AES-CTR)."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    h = read_nca_header(f, nca_off, keys)
    gen = max(h[0x206], h[0x220])
    gen = gen - 1 if gen else 0
    kak = keys[f"key_area_key_application_{gen:02x}"]
    ctrkey = Cipher(algorithms.AES(kak), modes.ECB()).decryptor().update(h[0x300:0x340])[0x20:0x30]
    for i in range(4):
        start, end = struct.unpack("<II", h[0x240 + 16 * i:0x248 + 16 * i])
        fh = h[0x400 + 0x200 * i:0x600 + 0x200 * i]
        if end == 0 or fh[2] != 1 or fh[4] != 3 or fh[3] != 2:
            continue
        sb = fh[8:]
        layers = struct.unpack("<I", sb[0x24:0x28])[0]
        lo, ls = struct.unpack("<QQ", sb[0x28 + 16 * (layers - 1):0x38 + 16 * (layers - 1)])
        off = start * 0x200 + lo
        f.seek(nca_off + off)
        d = _ctr_dec(ctrkey, fh[0x140:0x148][::-1], off, f.read(ls))
        return parse_pfs0(d)
    raise ValueError("no ExeFS section found")


def parse_pfs0(d: bytes) -> dict[str, bytes]:
    magic, n, strsz, _ = struct.unpack("<4sIII", d[:16])
    if magic != b"PFS0":
        raise ValueError("not PFS0")
    strtab = d[16 + 24 * n:16 + 24 * n + strsz]
    data = 16 + 24 * n + strsz
    out = {}
    for j in range(n):
        off, size, noff = struct.unpack("<QQI", d[16 + 24 * j:16 + 24 * j + 20])
        out[strtab[noff:strtab.index(b"\0", noff)].decode()] = d[data + off:data + off + size]
    return out


def lz4_block(src: bytes, size: int) -> bytes:
    out = bytearray()
    i = 0
    while i < len(src):
        tok = src[i]; i += 1
        ln = tok >> 4
        if ln == 15:
            while True:
                x = src[i]; i += 1; ln += x
                if x != 255:
                    break
        out += src[i:i + ln]; i += ln
        if i >= len(src):
            break
        off = src[i] | src[i + 1] << 8; i += 2
        ml = tok & 15
        if ml == 15:
            while True:
                x = src[i]; i += 1; ml += x
                if x != 255:
                    break
        ml += 4
        s = len(out) - off
        for k in range(ml):
            out.append(out[s + k])
    if len(out) != size:
        raise ValueError(f"lz4 size mismatch {len(out)} != {size}")
    return bytes(out)


def nso_segments(nso: bytes) -> dict[str, tuple[int, bytes]]:
    """Return {'text'|'rodata'|'data': (memory_offset, decompressed bytes)}."""
    if nso[:4] != b"NSO0":
        raise ValueError("not NSO0")
    flags = struct.unpack("<I", nso[0xC:0x10])[0]
    csz = struct.unpack("<III", nso[0x60:0x6C])
    segs = {}
    for i, name in enumerate(("text", "rodata", "data")):
        fo, mo, sz = struct.unpack("<III", nso[0x10 + 16 * i:0x1C + 16 * i])
        raw = nso[fo:fo + csz[i]]
        segs[name] = (mo, lz4_block(raw, sz) if flags & (1 << i) else raw)
    return segs


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()
