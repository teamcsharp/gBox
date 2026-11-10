"""BKTR tables: the relocation and subsection blocks of an NCA RomFS section (crypt type 4).

Verified against the RE6 update NCA (01002A000CD48800 v131072, RomFS section 0x4000..0x4790200): both blocks decrypt
with the section's own CTR (IV = reversed(section_ctr)[0:4] || (subsection ctr_val big-endian) || (offset >> 4)), and
their layout is a 0x4000 block header followed by a 0x4000 bucket:

* relocation block: {u32 _0; u32 num_buckets; u64 total_size} at 0, bucket at 0x4000:
  {u32 _0; u32 num_entries; u64 virtual_end; entries[]} with each entry **packed at 0x14 bytes**
  (u64 virt_offset, u64 phys_offset, u32 is_patch) — 126 entries = 52 patch regions in that title.
* subsection block: same shape, entries packed at 0x10 (u64 offset, u32 _0x8, u32 ctr_val).

The patch *payload* is a separate question (its bytes do not decrypt with the same CTR as the tables and are not
plaintext), so this module deliberately stops at the mapping: regions + subsections, which is what any BKTR reader
needs before it touches data.
"""
import struct

RELOCATION_BLOCK = 0x4000
RELOCATION_ENTRY = 0x14
SUBSECTION_ENTRY = 0x10


def superblock_offsets(header: bytes, section_index: int) -> dict:
    """The relocation/subsection header offsets of a BKTR RomFS section (fs header + 0xE0 + 0x18/+0x20)."""
    base = 0x400 + section_index * 0x200 + 8
    reloc_offset, reloc_size, reloc_magic, _reloc_v, reloc_count, _r = struct.unpack_from(
        "<QQIIII", header, base + 0xE0 + 0x18)
    sub_offset, sub_size, sub_magic, _sub_v, sub_count, _r2 = struct.unpack_from(
        "<QQIIII", header, base + 0xE0 + 0x18 + 0x20)
    return {"relocation": {"offset": reloc_offset, "size": reloc_size, "magic": reloc_magic, "count": reloc_count},
            "subsection": {"offset": sub_offset, "size": sub_size, "magic": sub_magic, "count": sub_count}}


def parse_relocation(block: bytes) -> list[dict]:
    """The relocation entries of every bucket: [{virt, phys, is_patch}] in virtual order."""
    _zero, buckets, _total = struct.unpack_from("<IIQ", block, 0)
    out = []
    for b in range(buckets):
        at = RELOCATION_BLOCK + b * RELOCATION_BLOCK
        _z, count, _vend = struct.unpack_from("<IIQ", block, at)
        for i in range(count):
            virt, phys, is_patch = struct.unpack_from("<QQI", block, at + 0x10 + i * RELOCATION_ENTRY)
            out.append({"virt": virt, "phys": phys, "is_patch": bool(is_patch)})
    return out


def parse_subsections(block: bytes) -> list[dict]:
    """The subsection entries: [{offset, ctr_val}] (the CTR value for each physical range)."""
    _zero, buckets, _total = struct.unpack_from("<IIQ", block, 0)
    out = []
    for b in range(buckets):
        at = RELOCATION_BLOCK + b * RELOCATION_BLOCK
        _z, count, _pend = struct.unpack_from("<IIQ", block, at)
        for i in range(count):
            offset, _x, ctr_val = struct.unpack_from("<QII", block, at + 0x10 + i * SUBSECTION_ENTRY)
            out.append({"offset": offset, "ctr_val": ctr_val})
    return out


def patch_regions(entries: list[dict], virtual_end: int | None = None) -> list[dict]:
    """The patched ranges: each is_patch entry runs until the next entry (or `virtual_end`)."""
    end = virtual_end if virtual_end is not None else (entries[-1]["virt"] + 1 if entries else 0)
    out = []
    for i, entry in enumerate(entries):
        if not entry["is_patch"]:
            continue
        nxt = entries[i + 1]["virt"] if i + 1 < len(entries) else end
        out.append({"virt": entry["virt"], "end": nxt, "phys": entry["phys"], "size": nxt - entry["virt"]})
    return out


def bktr_ctr(section_ctr: bytes, ctr_val: int, absolute_offset: int) -> bytes:
    """The BKTR AES-CTR IV: reversed(section_ctr)[0:4] then ctr_val big-endian then (offset >> 4) big-endian."""
    iv = bytearray(16)
    iv[0:4] = section_ctr[::-1][0:4]
    iv[4:8] = ctr_val.to_bytes(4, "big")
    iv[8:16] = (absolute_offset >> 4).to_bytes(8, "big")
    return bytes(iv)


def region_at(regions: list[dict], virtual: int) -> dict | None:
    for region in regions:
        if region["virt"] <= virtual < region["end"]:
            return region
    return None


def subsection_at(subsections: list[dict], physical: int) -> dict | None:
    current = None
    for sub in subsections:
        if sub["offset"] <= physical:
            current = sub
    return current
