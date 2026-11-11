"""Nintendo Switch game-card images: XCI partition table, HFS0 file table, NCA header names.

This is a LISTING reader only -- it parses plaintext headers to enumerate what a card holds. It never decrypts
content: Hash0/HashIV/NAVI tables and NCA body sections (where asset data actually lives) are AES-encrypted with
titlekeys and out of scope here. It answers the assimilation question "what containers does this owned build
actually contain" for .xci files, which gbox.formats.disc refuses to list
("not a disc image, ROM, archive or folder gBox can list").

Layout facts used (plaintext regions):
  XCI0 (classic card): magic "XCI0" at 0; partition table at 0x1000: u64 LE image start offset, u64 LE image size,
        u16 LE header size, u8 header version, u8 flags, ASCII name padded with spaces to 16 ("HFS0PARTT").
  XCI HEAD variant (Switch cartridge image per `file`): "HEAD" magic at 0x100 (0..0xFF is an RSA signature), root HFS0 address at
        0x130 (u64 LE) pointing to a top-level HFS0 whose children are the real partitions (update/normal/secure).
        The secure partition contains the game's NCA files.
  HFS0: magic "HFS0" at 0; u32 LE file count (+4); u32 LE string pool size (+8);
        64-byte entries at +16 each: u64 LE data offset (relative to file-data start), u64 LE size,
        u32 LE name offset (into string pool), u32 LE header size, u64 LE ext; sha256 at +32.
        File data starts at base + 16 + count*64 + pool_size.
  NCA:  (NOTE: on retail cards NCA headers are AES-XTS encrypted, so header_names is usually empty.)
        magic "NCA3" at 0 with plaintext header-name strings at 0x200/0x220/0x240
        (main/program/control, e.g. "Qnv9CtUJy...").

Failure policy: truncated images and out-of-range offsets/counts raise ValueError; a non-XCI stream raises
ValueError, so callers never mistake a mislabelled file for a card.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import BinaryIO, Callable, List

XCI0_MAGIC = b"XCI0"
HEAD_MAGIC = b"HEAD"
HFS0_MAGIC = b"HFS0"
NCA3_MAGIC = b"NCA3"
XCI_PARTITION_TABLE_OFFSET = 0x1000
XCI_PARTITION_HEADER_SIZE = 0x20
# HEAD variant: root HFS0 address is a u64 LE at this offset
XCI_HEAD_MAGIC_OFFSET = 0x100
XCI_HEAD_ROOT_HFS0_OFFSET = 0x130
HFS0_ENTRY_SIZE = 64
HFS0_HEADER_SIZE = 16  # magic(4) + count(4) + pool_size(4) + pad(4)
# plaintext header-name slots inside an NCA header (main/program/control), fixed offsets
NCA_HEADER_NAME_SLOTS = (0x200, 0x220, 0x240)


@dataclass(frozen=True)
class XciPartition:
    name: str
    offset: int      # absolute byte offset of the partition image inside the .xci
    size: int
    version: int
    flags: int


@dataclass(frozen=True)
class Hfs0Entry:
    name: str
    offset: int      # absolute byte offset inside the .xci
    size: int
    sha256: str      # hex digest stored in the entry table (plaintext)


@dataclass
class XciInfo:
    partitions: List[XciPartition] = field(default_factory=list)
    hfs0: dict = field(default_factory=dict)          # partition name -> list[Hfs0Entry]
    ncas: List[dict] = field(default_factory=list)    # {partition, entry, offset, size, header_names}
    warnings: List[str] = field(default_factory=list)


def _read_at(read_at: Callable[[int, int], bytes], off: int, size: int) -> bytes:
    data = read_at(off, size)
    if len(data) != size:
        raise ValueError("truncated image reading %d bytes at offset 0x%x (got %d)" % (size, off, len(data)))
    return data


def _ascii(data: bytes) -> str:
    return data.split(b"\0", 1)[0].rstrip().decode("ascii", "replace")


def parse_xci_header(read_at: Callable[[int, int], bytes]) -> List[XciPartition]:
    """Parse the XCI partition table. Handles both classic XCI0 and HEAD variants."""
    magic = _read_at(read_at, 0, 4)
    parts: List[XciPartition] = []
    # Real cards: bytes 0..0xFF are an RSA signature; the "HEAD" magic sits at 0x100.
    if magic != XCI0_MAGIC and _read_at(read_at, XCI_HEAD_MAGIC_OFFSET, 4) == HEAD_MAGIC:
        magic = HEAD_MAGIC

    if magic == XCI0_MAGIC:
        # Classic XCI0: partition table at 0x1000
        off = XCI_PARTITION_TABLE_OFFSET
        while True:
            head = _read_at(read_at, off, XCI_PARTITION_HEADER_SIZE)
            start, size = struct.unpack_from("<QQ", head, 0)
            header_size, version, flags = struct.unpack_from("<HBB", head, 16)
            name = head[20:36].decode("ascii", "replace")
            if name.strip() == "HFS0PARTT":
                parts.append(XciPartition("HFS0PARTT", start, size, version, flags))
            if not flags & 1:  # bit 0 = more entries follow
                break
            off += max(header_size, XCI_PARTITION_HEADER_SIZE)
        if not parts:
            raise ValueError("XCI0 partition table has no HFS0PARTT entry")

    elif magic == HEAD_MAGIC:
        # HEAD variant: root HFS0 at offset stored at 0x130
        root_hfs0 = struct.unpack_from("<Q", _read_at(read_at, XCI_HEAD_ROOT_HFS0_OFFSET, 8), 0)[0]
        if root_hfs0 == 0:
            raise ValueError("HEAD variant: root HFS0 address is 0")
        # The root HFS0 contains sub-partitions (update, normal, secure).
        # Each is itself an HFS0 partition. We list them as XciPartition entries.
        entries = parse_hfs0(read_at, root_hfs0)
        for e in entries:
            parts.append(XciPartition(e.name, e.offset, e.size, 0, 0))
        if not parts:
            raise ValueError("HEAD variant: root HFS0 has no entries")

    else:
        raise ValueError("not an XCI image (magic %r at 0)" % magic)

    return parts


def parse_hfs0(read_at: Callable[[int, int], bytes], base: int) -> List[Hfs0Entry]:
    """HFS0 partition at absolute offset `base`: file table + string pool -> entries with absolute offsets.

    HFS0 layout:
      +0   magic "HFS0" (4 bytes)
      +4   u32 LE file count
      +8   u32 LE string pool size
      +12  u32 LE padding
      +16  64-byte file entries (count of them)
      +16 + count*64   string pool (pool_size bytes)
      +16 + count*64 + pool_size   file data
    """
    if _read_at(read_at, base, 4) != HFS0_MAGIC:
        raise ValueError("no HFS0 magic at 0x%x (found %r)" % (base, read_at(base, 4)))
    count, pool_size = struct.unpack_from("<II", _read_at(read_at, base + 4, 8), 0)
    if count == 0 and pool_size == 0:
        return []
    if pool_size > 1 << 28:
        raise ValueError("implausible HFS0 string pool size %d at 0x%x" % (pool_size, base))

    table_off = base + HFS0_HEADER_SIZE
    pool_off = table_off + count * HFS0_ENTRY_SIZE
    data_base = pool_off + pool_size
    pool = _read_at(read_at, pool_off, pool_size)

    entries = []
    for i in range(count):
        rec = _read_at(read_at, table_off + i * HFS0_ENTRY_SIZE, HFS0_ENTRY_SIZE)
        ext_off, size, name_off, _header_sz, _ext = struct.unpack_from("<QQIIQ", rec, 0)
        sha = rec[32:64].hex()
        if name_off >= pool_size:
            raise ValueError("HFS0 entry %d name offset %d outside pool (%d)" % (i, name_off, pool_size))
        end = pool.index(b"\0", name_off) if b"\0" in pool[name_off:] else pool_size
        entries.append(Hfs0Entry(
            pool[name_off:end].decode("ascii", "replace"),
            data_base + ext_off,
            size,
            sha,
        ))
    return entries


def read_nca_header_names(read_at: Callable[[int, int], bytes], nca_offset: int) -> List[str]:
    """Plaintext NCA3 header-name slots (main/program/control ids); [] if the member is not an NCA3."""
    if _read_at(read_at, nca_offset, 4) != NCA3_MAGIC:
        return []
    names = []
    for slot in NCA_HEADER_NAME_SLOTS:
        raw = _read_at(read_at, nca_offset + slot, 32)
        name = _ascii(raw)
        if name:
            names.append(name)
    return names


def _file_read_at(path: str) -> Callable[[int, int], bytes]:
    fh: BinaryIO = open(path, "rb")

    def read_at(off: int, size: int) -> bytes:
        fh.seek(off)
        return fh.read(size)

    read_at.close = fh.close  # type: ignore[attr-defined]
    return read_at


def list_xci(path: str) -> XciInfo:
    """Enumerate one owned .xci end-to-end: partitions, HFS0 file tables, NCA header names."""
    read_at = _file_read_at(path)
    try:
        return list_xci_from(read_at)
    finally:
        read_at.close()  # type: ignore[attr-defined]


def list_xci_from(read_at: Callable[[int, int], bytes]) -> XciInfo:
    info = XciInfo()
    info.partitions = parse_xci_header(read_at)
    for part in info.partitions:
        try:
            entries = parse_hfs0(read_at, part.offset)
        except ValueError as exc:  # encrypted/unreadable partition header: record, keep going
            info.warnings.append("partition %s: %s" % (part.name, exc))
            continue
        info.hfs0[part.name] = entries
        for e in entries:
            if e.size < 0x300:
                continue
            try:
                names = read_nca_header_names(read_at, e.offset)
            except ValueError:
                names = []
            if names:
                info.ncas.append({"partition": part.name, "entry": e.name, "offset": e.offset,
                                  "size": e.size, "sha256": e.sha256, "header_names": names})
    return info


def summarize(info: XciInfo) -> dict:
    return {"partitions": [{"name": p.name, "offset": p.offset, "size": p.size,
                            "version": p.version, "flags": p.flags} for p in info.partitions],
            "hfs0": {k: [{"name": e.name, "offset": e.offset, "size": e.size, "sha256": e.sha256}
                         for e in v] for k, v in info.hfs0.items()},
            "ncas": info.ncas,
            "warnings": info.warnings}


# --- NCA3 header decrypt + ExeFS (PFS0) reader (needs the owner's prod.keys; keys are never stored here) ---

def load_keys(path: str) -> dict:
    keys = {}
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if "=" in line:
                k, v = line.split("=", 1)
                try:
                    keys[k.strip()] = bytes.fromhex(v.strip())
                except ValueError:
                    pass
    return keys


def decrypt_nca_header(read_at: Callable[[int, int], bytes], nca_offset: int, header_key: bytes) -> bytes:
    """AES-128-XTS decrypt the 0xC00-byte NCA header; 0x200 sectors, tweak = big-endian sector number, sector 0 = NCA start."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    raw = _read_at(read_at, nca_offset, 0xC00)
    out = b""
    for i in range(6):
        c = Cipher(algorithms.AES(header_key), modes.XTS(i.to_bytes(16, "big"))).decryptor()
        out += c.update(raw[i * 0x200:(i + 1) * 0x200])
    if out[0x200:0x204] != NCA3_MAGIC:
        raise ValueError("NCA header did not decrypt to NCA3 (wrong header_key or not an NCA3)")
    return out


def nca_sections(h: bytes) -> List[dict]:
    secs = []
    for i in range(4):
        s, e = struct.unpack_from("<II", h, 0x240 + i * 16)
        if e <= s:
            continue
        fh = h[0x400 + i * 0x200:0x600 + i * 0x200]
        secs.append({"index": i, "start": s * 0x200, "end": e * 0x200, "fs_type": fh[2], "hash_type": fh[3],
                     "enc_type": fh[4], "ctr": fh[0x140:0x148]})
    return secs


def read_nca_section(read_at, nca_offset: int, h: bytes, keys: dict, sec: dict, rel: int, size: int) -> bytes:
    """Read `size` bytes at section-relative `rel`, decrypting AES-CTR (enc_type 3) with the key-area CTR key (key-area rights only)."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    off = sec["start"] + rel
    data = _read_at(read_at, nca_offset + off, size)
    if sec["enc_type"] == 1:
        return data
    if sec["enc_type"] != 3:
        raise ValueError("unsupported section encryption %d" % sec["enc_type"])
    if h[0x230:0x240] != bytes(16):
        raise ValueError("rights_id set: titlekey crypto not implemented here")
    gen = max(h[0x206], h[0x220]); gen = gen - 1 if gen > 0 else 0
    kek = keys["key_area_key_application_%02x" % gen]
    ka = Cipher(algorithms.AES(kek), modes.ECB()).decryptor().update(h[0x300:0x340])
    ctr_key = ka[0x10 * 2:0x10 * 3]
    base = off & ~0xF
    pad = off - base
    iv = sec["ctr"][::-1] + (base >> 4).to_bytes(8, "big")
    d = Cipher(algorithms.AES(ctr_key), modes.CTR(iv)).decryptor()
    return d.update(b"\0" * pad + data)[pad:]


def list_exefs(read_at, nca_offset: int, keys: dict) -> List[dict]:
    """ExeFS PFS0 members (name, section-relative offset, size) of a Program NCA whose first section is HierarchicalSha256 PFS0."""
    h = decrypt_nca_header(read_at, nca_offset, keys["header_key"])
    sec = nca_sections(h)[0]
    fh = h[0x400:0x600]
    bs, lc = struct.unpack_from("<II", fh, 0x28)
    doff, dsz = struct.unpack_from("<QQ", fh, 0x30 + (lc - 1) * 16)
    head = read_nca_section(read_at, nca_offset, h, keys, sec, doff, 0x4000)
    if head[:4] != b"PFS0":
        raise ValueError("section 0 data layer is not PFS0")
    cnt, strsz = struct.unpack_from("<II", head, 4)
    pool = 16 + cnt * 24
    names = head[pool:pool + strsz]
    out = []
    for i in range(cnt):
        o, sz, no = struct.unpack_from("<QQI", head, 16 + i * 24)
        out.append({"name": names[no:names.index(b"\0", no)].decode(), "offset": doff + pool + strsz + o, "size": sz})
    return out


def lz4_block_decompress(src: bytes, out_size: int) -> bytes:
    """Pure-python LZ4 block decoder (no frame header), as used by NSO segments."""
    out = bytearray()
    i, n = 0, len(src)
    while i < n:
        tok = src[i]; i += 1
        lit = tok >> 4
        if lit == 15:
            while True:
                b = src[i]; i += 1; lit += b
                if b != 255:
                    break
        out += src[i:i + lit]; i += lit
        if i >= n:
            break
        off = src[i] | (src[i + 1] << 8); i += 2
        if off == 0 or off > len(out):
            raise ValueError("bad LZ4 match offset")
        ml = tok & 15
        if ml == 15:
            while True:
                b = src[i]; i += 1; ml += b
                if b != 255:
                    break
        ml += 4
        s = len(out) - off
        for k in range(ml):
            out.append(out[s + k])
    if len(out) != out_size:
        raise ValueError("LZ4 size mismatch %d != %d" % (len(out), out_size))
    return bytes(out)


def parse_nso(data: bytes) -> dict:
    """Decompress an NSO0 image: returns segments {text,ro,data} (bytes + memory offset) and bss size.
    Verifies each segment against the SHA-256 in the header when the hash flag is set."""
    import hashlib
    if data[:4] != b"NSO0":
        raise ValueError("not NSO0")
    flags = struct.unpack_from("<I", data, 0xC)[0]
    segs = {}
    for idx, name in enumerate(("text", "ro", "data")):
        foff, moff, dsz = struct.unpack_from("<III", data, 0x10 + idx * 0x10)
        csz = struct.unpack_from("<I", data, 0x60 + idx * 4)[0]
        raw = data[foff:foff + (csz if flags & (1 << idx) else dsz)]
        seg = lz4_block_decompress(raw, dsz) if flags & (1 << idx) else raw
        if flags & (1 << (3 + idx)):
            if hashlib.sha256(seg).digest() != data[0xA0 + idx * 0x20:0xC0 + idx * 0x20]:
                raise ValueError("%s segment hash mismatch" % name)
        segs[name] = {"mem_offset": moff, "size": dsz, "data": seg}
    return {"segments": segs, "bss_size": struct.unpack_from("<I", data, 0x3C)[0], "build_id": data[0x40:0x60].hex()}


def read_exefs_member(read_at, nca_offset: int, keys: dict, name: str) -> bytes:
    h = decrypt_nca_header(read_at, nca_offset, keys["header_key"])
    sec = nca_sections(h)[0]
    f = next(x for x in list_exefs(read_at, nca_offset, keys) if x["name"] == name)
    return read_nca_section(read_at, nca_offset, h, keys, sec, f["offset"], f["size"])


# --- RomFS (IVFC) walker for key-area-crypto NCA sections ---

def parse_romfs_tables(dir_meta: bytes, file_meta: bytes) -> List[dict]:
    """Walk RomFS directory/file metadata tables; returns [{path, offset, size}] (offset relative to RomFS data area)."""
    out: List[dict] = []
    seen = set()

    def walk(doff: int, prefix: str) -> None:
        if doff == 0xFFFFFFFF or doff in seen or doff + 24 > len(dir_meta):
            return
        seen.add(doff)
        _par, sib, child_dir, child_file, _hash, nlen = struct.unpack_from("<IIIIII", dir_meta, doff)
        name = dir_meta[doff + 24:doff + 24 + nlen].decode("utf-8", "replace")
        here = prefix if doff == 0 else prefix + name + "/"
        fo = child_file
        while fo != 0xFFFFFFFF and fo + 32 <= len(file_meta):
            _p, fsib, off, size, _h, fnl = struct.unpack_from("<IIQQII", file_meta, fo)
            out.append({"path": here + file_meta[fo + 32:fo + 32 + fnl].decode("utf-8", "replace"), "offset": off, "size": size})
            fo = fsib
        walk(child_dir, here)
        walk(sib, prefix)

    walk(0, "/")
    return out


def list_romfs(read_at, nca_offset: int, keys: dict, section_index: int = 1) -> dict:
    """List files of a RomFS section (fs_type 0, IVFC hash_type 3). Returns {data_start, files:[{path, offset, size}]};
    file offset is section-relative (readable with read_nca_section)."""
    h = decrypt_nca_header(read_at, nca_offset, keys["header_key"])
    sec = next((s for s in nca_sections(h) if s["index"] == section_index), None)
    if sec is None:
        raise ValueError("no section %d" % section_index)
    fh = h[0x400 + section_index * 0x200:0x600 + section_index * 0x200]
    if fh[2] != 0 or fh[8:12] != b"IVFC":
        raise ValueError("section %d is not RomFS/IVFC" % section_index)
    nlev = struct.unpack_from("<I", fh, 0x14)[0]
    lo, _ls = struct.unpack_from("<QQ", fh, 0x18 + (nlev - 2) * 24)  # last level = data (levels listed excl. master hash)
    hdr = read_nca_section(read_at, nca_offset, h, keys, sec, lo, 0x50)
    dho, dhs, dmo, dms, fho, fhs, fmo, fms, dao = struct.unpack_from("<9Q", hdr, 8)
    dir_meta = read_nca_section(read_at, nca_offset, h, keys, sec, lo + dmo, dms)
    file_meta = read_nca_section(read_at, nca_offset, h, keys, sec, lo + fmo, fms)
    files = parse_romfs_tables(dir_meta, file_meta)
    for f in files:
        f["offset"] += lo + dao
    return {"data_start": lo + dao, "files": files}


def read_romfs_file(read_at, nca_offset: int, keys: dict, entry: dict, section_index: int = 1) -> bytes:
    """Read one list_romfs() file entry (decrypted, still zstd-compressed for *.zs)."""
    h = decrypt_nca_header(read_at, nca_offset, keys["header_key"])
    sec = next(s for s in nca_sections(h) if s["index"] == section_index)
    return read_nca_section(read_at, nca_offset, h, keys, sec, entry["offset"], entry["size"])


def sarc_members(data: bytes) -> List[dict]:
    """Parse a SARC archive (little-endian) into [{name, offset, size}]; offsets absolute within `data`."""
    if data[:4] != b"SARC":
        raise ValueError("not SARC")
    hdr_sz, bom, _fsz, data_off = struct.unpack_from("<HHII", data, 4)
    if bom != 0xFEFF:
        raise ValueError("big-endian SARC unsupported")
    cnt = struct.unpack_from("<H", data, 0x14 + 6)[0]
    sfat = 0x14
    sfnt = sfat + 12 + cnt * 16
    names_off = sfnt + 8
    out = []
    for i in range(cnt):
        _hash, attr, s, e = struct.unpack_from("<IIII", data, sfat + 12 + i * 16)
        no = (attr & 0xFFFFFF) * 4 if (attr >> 24) & 1 else 0
        n = data[names_off + no:data.index(b"\0", names_off + no)].decode() if (attr >> 24) & 1 else ""
        out.append({"name": n, "offset": data_off + s, "size": e - s})
    return out


def parse_bfres_header(data: bytes) -> dict:
    """Parse the Switch BFRES (FRES) container header (little-endian, v9-style layout).

    Offsets verified on the owned AC:NH NpcNmlAnt00 model: 0x08 version, 0x0C BOM(0xFEFF)+align shift,
    0x10 name offset, 0x14 flags/block offset, 0x18 relocation-table offset, 0x1C file size,
    0x28 first FMDL offset. Bounds-checked against len(data).
    """
    if len(data) < 0x30 or data[:8] != b"FRES    ":
        raise ValueError("not a Switch BFRES")
    ver = struct.unpack_from("<I", data, 8)[0]
    bom, align_shift, addr_sz = struct.unpack_from("<HBB", data, 0x0C)
    if bom != 0xFEFF:
        raise ValueError("big-endian BFRES unsupported")
    name_off, flags, block_off, rlt_off, fsize = struct.unpack_from("<IHHII", data, 0x10)
    if fsize != len(data):
        raise ValueError("BFRES size mismatch: header %d vs %d" % (fsize, len(data)))
    if not (0 < name_off < fsize - 2) or not (0 < rlt_off <= fsize - 4):
        raise ValueError("BFRES offsets out of range")
    nlen = struct.unpack_from("<H", data, name_off - 2)[0]
    if name_off + nlen > fsize:
        raise ValueError("BFRES name out of range")
    fmdl_off = struct.unpack_from("<Q", data, 0x28)[0]
    if not (0 < fmdl_off <= fsize - 4) or data[fmdl_off:fmdl_off + 4] != b"FMDL":
        raise ValueError("FMDL not at declared offset")
    if data[rlt_off:rlt_off + 4] != b"_RLT":
        raise ValueError("relocation table magic missing")
    counts = {t.decode(): data.count(t) for t in (b"FMDL", b"FSKL", b"FMAT", b"FSHP", b"FVTX", b"BNTX")}
    return {"version": ver, "align_shift": align_shift, "addr_size": addr_sz, "name": data[name_off:name_off + nlen].decode("ascii", "replace"),
            "rlt_offset": rlt_off, "file_size": fsize, "fmdl_offset": fmdl_off, "magic_counts": counts,
            "bntx_offset": data.find(b"BNTX")}


def _bf_str(data: bytes, off: int) -> str:
    if not (2 <= off < len(data) - 2):
        raise ValueError("BFRES string offset out of range")
    n = struct.unpack_from("<H", data, off)[0]
    if off + 2 + n > len(data):
        raise ValueError("BFRES string overruns file")
    return data[off + 2:off + 2 + n].decode("ascii", "replace")


def _bf_ptr(data: bytes, off: int) -> int:
    v = struct.unpack_from("<Q", data, off)[0]
    if v >= len(data):
        raise ValueError("BFRES pointer 0x%X out of range at 0x%X" % (v, off))
    return v


def bfres_rlt_sections(data: bytes) -> List[dict]:
    """Relocation-table sections (_RLT): 0=header/structs, 1=index buffers (= buffer pool base), 2=vertex buffers, 3=memory pool, 4=embedded BNTX."""
    h = parse_bfres_header(data)
    o = h["rlt_offset"]
    n = struct.unpack_from("<I", data, o + 8)[0]
    if n > 64 or o + 0x10 + n * 0x18 > len(data):
        raise ValueError("bad RLT section count")
    out = []
    for i in range(n):
        _ptr, pos, size, idx, cnt = struct.unpack_from("<QIIII", data, o + 0x10 + i * 0x18)
        if pos + size > len(data):
            raise ValueError("RLT section %d out of file" % i)
        out.append({"pos": pos, "size": size, "entry_index": idx, "entry_count": cnt})
    return out


def parse_bfres_model(data: bytes) -> dict:
    """Parse the first FMDL of a Switch BFRES v9 file: skeleton bones, FVTX attribute layouts, FSHP shapes + LOD0 index info.

    Layouts empirically verified on AC:NH NpcNmlAnt00 (Body__mBody 2284 verts / 11160 u16 indices; 44 bones).
    All pointers are bounds-checked; buffer data base is RLT section 1 (the pool base); face/vertex offsets are pool-relative.
    """
    h = parse_bfres_header(data)
    f = h["fmdl_offset"]
    if len(data) < f + 0x78:
        raise ValueError("FMDL truncated")
    skl, vtx, shp, mat = (_bf_ptr(data, f + k) for k in (0x18, 0x20, 0x28, 0x38))
    nvtx, nshp, nmat = struct.unpack_from("<HHH", data, f + 0x68)
    if not (0 < nshp <= 256 and 0 < nvtx <= 256 and nmat <= 256):
        raise ValueError("implausible FMDL counts")
    secs = bfres_rlt_sections(data)
    if len(secs) < 3:
        raise ValueError("RLT lacks buffer sections")
    pool = secs[1]["pos"]
    # skeleton
    if data[skl:skl + 4] != b"FSKL":
        raise ValueError("FSKL magic missing")
    bone_arr = _bf_ptr(data, skl + 0x10)
    nbones = struct.unpack_from("<H", data, skl + 0x38)[0]
    if bone_arr + nbones * 0x60 > len(data):
        raise ValueError("bone array out of range")
    bones = []
    for i in range(nbones):
        o = bone_arr + i * 0x60
        idx, parent = struct.unpack_from("<Hh", data, o + 0x28)
        floats = struct.unpack_from("<3f4f3f", data, o + 0x38)
        bones.append({"name": _bf_str(data, _bf_ptr(data, o)), "index": idx, "parent": parent,
                      "scale": floats[0:3], "rot": floats[3:7], "pos": floats[7:10]})
    # vertex buffers
    fvtx = []
    for i in range(nvtx):
        o = vtx + i * 0x58
        if data[o:o + 4] != b"FVTX":
            raise ValueError("FVTX %d magic missing" % i)
        attr_arr, binfo, bstride = _bf_ptr(data, o + 8), _bf_ptr(data, o + 0x30), _bf_ptr(data, o + 0x38)
        buf_off = struct.unpack_from("<I", data, o + 0x48)[0]
        nattr, nbuf = data[o + 0x4C], data[o + 0x4D]
        vcount = struct.unpack_from("<I", data, o + 0x50)[0]
        attrs = []
        for j in range(nattr):
            a = attr_arr + j * 0x10
            fmt = struct.unpack_from(">H", data, a + 8)[0]
            aoff, abuf = struct.unpack_from("<HH", data, a + 0xC)
            attrs.append({"name": _bf_str(data, _bf_ptr(data, a)), "format": fmt, "offset": aoff, "buffer": abuf})
        bufs = []
        pos = buf_off
        for j in range(nbuf):
            size = struct.unpack_from("<I", data, binfo + j * 0x10)[0]
            stride = struct.unpack_from("<I", data, bstride + j * 0x10)[0]
            bufs.append({"size": size, "stride": stride, "pool_offset": pos})
            pos += (size + 7) & ~7  # 8-byte packed (verified: 0x6B10 then 0x23B0 buffers)
        fvtx.append({"vertex_count": vcount, "attrs": attrs, "buffers": bufs})
    # shapes
    shapes = []
    for i in range(nshp):
        o = shp + i * 0x60
        if data[o:o + 4] != b"FSHP":
            raise ValueError("FSHP %d magic missing" % i)
        mesh = _bf_ptr(data, o + 0x18)
        skin_list = _bf_ptr(data, o + 0x20)
        sidx, midx, bidx, vidx, nskin = struct.unpack_from("<5H", data, o + 0x50)
        # 0x50 shape index, 0x52 material index, 0x54 bone index, 0x56 FVTX index, 0x58 skin-bone count
        vskin, nlod = data[o + 0x5A], data[o + 0x5B]
        if skin_list + nskin * 2 > len(data) or vidx >= len(fvtx) or nlod < 1:
            raise ValueError("FSHP %d fields out of range" % i)
        face_off, prim, ifmt, icount, first_v = struct.unpack_from("<5I", data, mesh + 0x20)
        if ifmt not in (0, 1, 2):
            raise ValueError("unknown index format %d" % ifmt)
        shapes.append({"name": _bf_str(data, _bf_ptr(data, o + 8)), "index": sidx, "material": midx, "bone": bidx, "fvtx": vidx,
                       "skin_bones": list(struct.unpack_from("<%dH" % nskin, data, skin_list)), "vertex_skin_count": vskin, "lod_count": nlod,
                       "lod0": {"face_pool_offset": face_off, "primitive": prim, "index_format": ifmt, "index_count": icount, "first_vertex": first_v}})
    return {"name": _bf_str(data, _bf_ptr(data, f + 8)), "pool_base": pool, "bones": bones, "fvtx": fvtx, "shapes": shapes,
            "material_count": nmat}


def bfres_read_indices(data: bytes, model: dict, shape: dict) -> List[int]:
    lod = shape["lod0"]
    width = {0: 1, 1: 2, 2: 4}[lod["index_format"]]
    start = model["pool_base"] + lod["face_pool_offset"]
    n = lod["index_count"]
    if start + n * width > len(data):
        raise ValueError("index buffer out of range")
    return list(struct.unpack_from("<%d%s" % (n, {1: "B", 2: "H", 4: "I"}[width]), data, start))


def bfres_read_positions(data: bytes, model: dict, shape: dict) -> List[tuple]:
    """Decode the _p0 (float32x3, format 0x0518) attribute of a shape's FVTX."""
    fv = model["fvtx"][shape["fvtx"]]
    a = next((x for x in fv["attrs"] if x["name"] == "_p0"), None)
    if a is None or a["format"] != 0x0518:
        raise ValueError("_p0 is not float32x3")
    b = fv["buffers"][a["buffer"]]
    start = model["pool_base"] + b["pool_offset"] + a["offset"]
    n = fv["vertex_count"]
    if start + (n - 1) * b["stride"] + 12 > len(data):
        raise ValueError("position buffer out of range")
    return [struct.unpack_from("<3f", data, start + i * b["stride"]) for i in range(n)]
