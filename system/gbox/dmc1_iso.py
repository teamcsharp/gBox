"""Devil May Cry (USA) SLUS_202.16 (PS2) ISO-9660 inventory (#1856).

Read-only.  The authoritative owned source is the ISO-9660 image

    /home/ehm_eckx/gBox_alt/gbox-cache/modbase/d460ea70167416a2/Devil May Cry (USA).iso
    sha256 = 9e4d87fa0bae06e7282c085bb58693f83cf857bede9803f4bd235e3dfcfe0726
    (stream-hashed on lilspark2 2026-11-06; 4,698,767,360 B = 2,294,320
    MODE1/2048 sectors, byte-identical to the earlier chdman-extracted raw
    dmc1_usa.bin).  The prior checkpoint's CHD reference
    (1e6d865218bfb4abf1f6e35cbcc244fbd4fcc68aef558ae2403e3d4944693a60) is stale:
    that CHD is absent on this host; the owned ISO is the canonical source.

Disc layout (verified against the raw bytes):
    SYSTEM.CNF        -> BOOT2 = cdrom0:\\SLUS_202.16;1 / VER = 1.10 / VMODE = NTSC
    SLUS_202.16       ELF32 little-endian MIPS (32-bit PS2 EE), sha256
                       ac1a1e72845f04e6683d8ecd9e223f5297200bf2133709d5391925ad98e7be68
    DATA/EMD          178 files (enemy/player models .EMD, TIM2 textures .TM2/.T32)
    DATA/PLD          80 files (player containers .PLD/.PWS/.PWD)
    DATA/ETC|FSD|MODULES|ADS|STATUS|STATUS_U  (609 further files)

Player container format (.PLD):
    Standard header: u32 child_count at offset 0, followed by child_count u32
    offsets (relative to container start, first child at offset 48 = 4 + 4*count).
    Each child runs to the next larger offset (or EOF).
    
    Variant header (PL01-PL04/PL06): child_count=0 at offset 0, embedded children
    at offset 32 as (offset, size) u32 pairs.
    
    Child6 (1,042,640 B, identical size in PL00/PL05): u32 count (0xd7 = 215)
    then 215 u32 offsets relative to child6 start (table ends at 0x360; entry 0
    points at the table itself).  Verified on the real image: all 215 offsets
    < child6 size; even-indexed entries (108) strictly increasing; odd-indexed
    entries (107) repeat (shared sections).  Pinned section header layout
    (hex census 2026-11-09): 8-byte LE u64 ``lo`` with nloop = lo & 0xFFFF
    and prim = (lo >> 47) & 0xF (data sections carry prim in
    {0, 2, 6, 8, 10, 12, 14}; all 107 palette sections carry prim == 4;
    EOP/PRE/FLG/NREG observed zero everywhere), then
    four LE u32 register words, reg = word & 0xFFFF, value = word >> 16.
    Data sections carry bare register ids (0x2888: 0x40 XYZ2 / 0x80 RGBAQ /
    0xc0 FOG / 0x100) or packed (value << 16 | reg) pairs (0xa1c4: all value
    0x40); palette sections carry an ascending byte run 0x04..0x13, (index,
    size) byte pairs and a trailing u32.  The earlier 'GS GIF tag + CSM1
    palette' classification was refuted (no bit-field placement decodes
    both parity classes) and is withdrawn; see child6_section_header().

    Child0 (228,144 B) begins 13 20 03 01 e0 78 03 00 01 00 be 00 40 01 00 00;
    header is {u32 span/flags 0x1032013, u32 size 0x378e0 (227552 = body size)}
    then a body whose tail closes with float vertices (e.g. `1d f6 55 c1 ..`).
    The body mixes packed vertex/index data and per-entry tables; a clean
    (flags, offset) record decode is NOT yet established (near-uniform byte
    entropy in the first u32 field, monotonic offsets in the second).  Earlier
    'mesh -> child6 pointer' claim was unsupported and is withdrawn.

fingerprint suggestion gbox.dmc3_mod does NOT apply to this build:
    gbox.dmc3_mod uses PAC/AFS layout which is incompatible with DMC1 .PLD format.
    Native DMC1 .PLD reader required.

Target slot for the eventual native replacement:
    DATA/PLD/PL00.PLD  (Dante default) LBA 1043291 size 1,547,616
    sha256 = 450f16f7d23e827ca8213d187e093e489c086e9c5bf497a0c943e252307378ea
    (PL05.PLD alt-costume: 6bdddd0666959d7d9abb47914b753df114642e7b48f4973db6f0bd0a85f62847;
     EM00.EMD first enemy model: 4cb173e7907b20f1345e28a1dc4285484528ab294983c5142d7b2395a1ee4d9f)

Usage:  python -m gbox.dmc1_iso <raw.bin> --out manifest.json
"""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

SECTOR = 2048
PVD_LBA = 16
ROOT_DIR_LBA = 261
DATA_DIR_LBA = 262
GROUP_LBAS = {
    "EMD": (264, 3498), "ETC": (266, 3882), "FSD": (268, 6318),
    "MODULES": (272, 818), "ADS": (273, 214), "PLD": (274, 1082),
    "STATUS": (275, 3192), "STATUS_U": (277, 840),
}
SOURCE_ISO_PATH = "/home/ehm_eckx/gBox_alt/gbox-cache/modbase/d460ea70167416a2/Devil May Cry (USA).iso"
SOURCE_ISO_SHA256 = "9e4d87fa0bae06e7282c085bb58693f83cf857bede9803f4bd235e3dfcfe0726"
# Stale CHD reference from an earlier host (absent on lilspark2; kept for traceability)
SOURCE_CHD_SHA256 = "1e6d865218bfb4abf1f6e35cbcc244fbd4fcc68aef558ae2403e3d4944693a60"
RAW_BIN_SHA256 = "9e4d87fa0bae06e7282c085bb58693f83cf857bede9803f4bd235e3dfcfe0726"
ELF_SHA256 = "ac1a1e72845f04e6683d8ecd9e223f5297200bf2133709d5391925ad98e7be68"
TARGET_PL00_SHA256 = "450f16f7d23e827ca8213d187e093e489c086e9c5bf497a0c943e252307378ea"


def walk_dir(f, lba: int, nbytes: int) -> list[tuple[str, int, bool, int]]:
    """ISO-9660 directory records at ``lba`` spanning ``nbytes``."""
    f.seek(lba * SECTOR)
    d = f.read(nbytes + 8192)
    i, files = 0, []
    while i + 34 <= len(d):
        ln = d[i]
        if ln == 0:
            nxt = (i // SECTOR + 1) * SECTOR
            if nxt <= i:
                break
            i = nxt
            continue
        if ln < 33:
            i += 1
            continue
        size = struct.unpack_from("<I", d, i + 10)[0]
        flags = d[i + 25]
        fnlen = d[i + 32]
        name = d[i + 33:i + 33 + fnlen].decode("latin1").split(";")[0]
        ext = struct.unpack_from("<I", d, i + 2)[0]
        if name not in ("\x00", "\x01", ".", ".."):
            files.append((name, size, bool(flags & 2), ext))
        i += ln
    return files


def parse_pld_children(f, lba: int, size: int) -> tuple[int, list[tuple[int, int]]]:
    """(child_count, [(offset, length)]) for a .PLD container header.
    
    Standard format: child_count at offset 0, followed by child_count u32 offsets.
    The first child starts at offset 48 (after the header), and each child runs to
    the next larger offset (or EOF).
    
    Variant format (PL01-PL04/PL06): child_count=0 at offset 0, embedded children
    at offset 32 as (offset, size) u32 pairs. The offset is relative to the child
    start within the container, and size is the child length.
    
    Child0 (mesh) structure: 16-byte entries with offset/size pairs pointing
    to child6 (section bulk). Child6 starts with d7 00 00 00 magic (count
    215), followed by a 215-entry section offset table; each section starts
    with the pinned header decoded by child6_section_header().
    """
    f.seek(lba * SECTOR)
    head = f.read(160)  # Enough for 32 child entries (standard or variant)
    n = struct.unpack_from("<I", head, 0)[0]
    
    if n == 0:
        # Variant format: check for embedded children at offset 32
        # embedded_count at offset 32, then (offset, size) pairs
        embedded_n = struct.unpack_from("<I", head, 32)[0]
        if embedded_n > 0 and embedded_n <= 32:
            children = []
            for i in range(embedded_n):
                off = struct.unpack_from("<I", head, 36 + i * 8)[0]
                sz = struct.unpack_from("<I", head, 40 + i * 8)[0]
                if off > 0 and sz > 0:
                    children.append((off, sz))
            return 0, children
    
    # Standard format: n children at offsets 4, 8, ...
    offs = list(struct.unpack_from(f"<{n}I", head, 4)) if n else []
    out = []
    for o in offs:
        nxts = [x for x in offs if x > o]
        out.append((o, (min(nxts) if nxts else size) - o))
    return n, out


def parse_child_table(blob: bytes) -> list[int]:
    """Decode the child6 section-offset table: u32 count + count u32 offsets."""
    n = struct.unpack_from("<I", blob, 0)[0]
    if n == 0 or 4 + 4 * n > len(blob):
        raise ValueError("bad child table count %d" % n)
    offs = list(struct.unpack_from("<%dI" % n, blob, 4))
    if max(offs) > len(blob):
        raise ValueError("child table offset beyond blob")
    return offs


# Pinned prim census over all 215 sections of PL00/PL05 child6 (owned USA
# ISO, hex census 2026-11-09): even (data) sections carry prim in
# {0, 2, 6, 8, 10, 12, 14} (GS primitive opcodes; 0x2888 decodes to
# POINT/nloop 62), odd (palette) sections all carry prim == 4 (107/107).
_DATA_PRIMS = (0, 2, 6, 8, 10, 12, 14)


def child6_section_header(blob: bytes, off: int) -> dict:
    """Decode one pinned child6 section header at ``off``.

    Pinned layout (verified on PL00/PL05 child6 of the owned USA ISO,
    2026-11-09 hex census; the earlier 'GS GIF tag + CSM1 palette'
    classification is withdrawn -- no bit-field placement decodes both
    parity classes as GS uploads):

      8-byte lo (LE u64):  nloop = lo & 0xFFFF (section element count;
          entry 0 points at the table itself and carries nloop = 215 =
          the table count).  prim = (lo >> 47) & 0xF: data sections
          (even table index) carry prim in {0, 2, 6, 8, 10, 12, 14};
          palette sections (odd table index) all carry prim == 4.
          EOP/PRE/FLG/NREG bit positions observed zero in all 215 sections.
      4 post-header u32 words (LE), reg = word & 0xFFFF, value = word >> 16:
        data    -> bare register ids (0x2888: 0x40 XYZ2, 0x80 RGBAQ,
                   0xc0 FOG, 0x100) or packed (value << 16 | reg) pairs
                   (0xa1c4: 0x400040/0x400080/0x4000c0/0x400100, all
                   value 0x40)
        palette -> ascending byte run 0x04..0x13 followed by (index, size)
                   byte pairs and a trailing u32; the four words decode
                   as reg = (value << 16) | run-byte, i.e. carry no
                   meaningful register ids.

    Returns {"off", "nloop", "prim", "kind", "regs"} where kind is
    "palette" (prim == 4), "data" (prim in _DATA_PRIMS) or "unknown",
    and regs is the [(reg, value)] list of the four post-header words.
    """
    if off < 0 or off + 24 > len(blob):
        raise ValueError("child6 section header truncated at %x" % off)
    (lo,) = struct.unpack_from("<Q", blob, off)
    words = struct.unpack_from("<4I", blob, off + 8)
    nloop = lo & 0xFFFF
    prim = (lo >> 47) & 0xF
    if prim == 4:
        kind = "palette"
    elif prim in _DATA_PRIMS:
        kind = "data"
    else:
        kind = "unknown"
    return {
        "off": off,
        "nloop": nloop,
        "prim": prim,
        "kind": kind,
        "regs": [(w & 0xFFFF, w >> 16) for w in words],
    }


def parse_child6_table(blob) -> list[dict]:
    """Decode child6 (section-offset table) into interleaved section records.

    child6 layout (verified on PL00/PL05, 1,042,640 B):
        u32 count (0xd7 = 215), then 215 u32 offsets into the blob.
    The offsets interleave two streams (entry 0 points at the table itself):
        even index -> data section (prim in {0, 2, 6, 8, 10, 12, 14},
                       offsets strictly increasing, spatially packed)
        odd  index  -> palette section (prim == 4;
                       offsets repeat == shared palettes)

    Each record is the child6_section_header fields plus the pinned
    kind; returns records in table order; raises ValueError on
    malformed input.
    """
    n = struct.unpack_from("<I", blob, 0)[0]
    if n == 0 or 4 + 4 * n > len(blob):
        raise ValueError("bad child6 table count %d" % n)
    offs = list(struct.unpack_from("<%dI" % n, blob, 4))
    if len(offs) != n:
        raise ValueError("short child6 table")
    if any(o + 24 > len(blob) for o in offs):
        raise ValueError("child6 offset beyond blob")
    evens = offs[0::2]
    # Data stream is spatially packed: strictly increasing offsets.
    if evens != sorted(evens):
        raise ValueError("child6 data offsets not strictly increasing")
    return [child6_section_header(blob, o) for o in offs]


def decode_child6_sections(blob) -> dict:
    """Summarise child6 GS command streams by kind.

    Returns {"count", "data", "palette", "unique_palettes", "sections"} where
    "sections" is the raw list from parse_child6_table and the counts are the
    breakdown of data (geometry) vs palette (texture/CLUT upload) streams.
    "unique_palettes" is the number of distinct palette offsets (palettes are
    heavily shared across data streams).
    """
    recs = parse_child6_table(blob)
    data = [r for r in recs if r["kind"] == "data"]
    pal = [r for r in recs if r["kind"] == "palette"]
    return {
        "count": len(recs),
        "data": len(data),
        "palette": len(pal),
        "unique_palettes": len({r["off"] for r in pal}),
        "sections": recs,
    }


def parse_child6_mesh_section(sec: bytes) -> dict:
    """Decode one prim==4 child6 section (the per-mesh vertex payload).

    Pinned on the owned USA ISO (PL00 child6, 2026-11-10 census; replaces
    the withdrawn 'palette' reading for the payload semantics):
      u16 n (vertex count, == nloop), u16 flags, a 0x20-byte preamble,
      then u32 block offsets from 0x24 until the lowest offset is reached
      (31 or 29 blocks + one trailing sentinel == len(sec)).
      Each block = u32 k, (k-1) strictly increasing u16 partition
      boundaries whose last value is n-1, then float vertex attributes.
    Returns {"n", "flags", "blocks": [{"off", "k", "bounds"}], "end"}.
    """
    n, flags = struct.unpack_from("<2H", sec, 0)
    offs, q, lo = [], 0x24, len(sec)
    while q + 4 <= lo:
        v = struct.unpack_from("<I", sec, q)[0]
        offs.append(v)
        lo = min(lo, v)
        q += 4
    blocks = []
    end = None
    for v in offs:
        if v >= len(sec) - 3:
            end = v
            continue
        k = struct.unpack_from("<I", sec, v)[0]
        if not 2 <= k <= 1024 or v + 4 + 2 * (k - 1) > len(sec):
            blocks.append({"off": v, "k": k, "bounds": None})
            continue
        b = list(struct.unpack_from("<%dH" % (k - 1), sec, v + 4))
        blocks.append({"off": v, "k": k, "bounds": b})
    return {"n": n, "flags": flags, "blocks": blocks, "end": end}


def parse_child6_preamble(sec: bytes) -> list[tuple[int, bool]]:
    """32-byte preamble at +4 of a prim==4 section: (index, hi-bit flag).

    Observed on the owned ISO: 5-6 entries per section carry bit 7; the
    first entry is always 0x80 (index 0, flagged). Semantics unresolved.
    """
    return [(b & 0x7F, bool(b & 0x80)) for b in sec[4:0x24]]


def split_block_records(sec: bytes, off: int, end: int) -> list[dict]:
    """Split one block into records: u32 k, ceil((k-1)/2) words of u16
    bounds, then floats up to the next record header.  Only the k==2 form
    (header 2 words + 6 floats == 0x20 bytes) is fixed-size and verified;
    larger records are returned with `end=None` for the trailing float
    span (not split further).  Block 0x6c0+0xa4 holds k=13 @0xa4, k=2 @0x15c, k=11 @0x17c."""
    out, p = [], off
    while p + 8 <= end:
        k = struct.unpack_from("<I", sec, p)[0]
        if k == 2 and p + 0x20 <= end:
            bound = struct.unpack_from("<H", sec, p + 4)[0]
            fl = struct.unpack_from("<6f", sec, p + 8)
            out.append({"off": p, "k": 2, "bounds": [bound], "floats": fl})
            p += 0x20
        else:
            out.append({"off": p, "k": k, "bounds": None, "floats": None})
            break
    return out


def mesh_section_conforms(m: dict) -> bool:
    """True when every block partitions the n vertices (last bound == n-1)."""
    return bool(m["blocks"]) and all(
        b["bounds"] and b["bounds"] == sorted(set(b["bounds"]))
        and b["bounds"][-1] == m["n"] - 1 for b in m["blocks"])


def stream_sha256(f, lba: int, size: int) -> str:
    f.seek(lba * SECTOR)
    h = hashlib.sha256()
    rem = size
    while rem > 0:
        b = f.read(min(1 << 20, rem))
        if not b:
            break
        h.update(b)
        rem -= len(b)
    return h.hexdigest()


def inventory(iso: Path) -> dict:
    with open(iso, "rb") as f:
        groups = {}
        for g, (lba, sz) in GROUP_LBAS.items():
            groups[g] = [
                {"name": n, "size": s, "lba": e}
                for n, s, dr, e in walk_dir(f, lba, sz) if not dr
            ]
        pld = {n: (s, e) for n, s, dr, e in walk_dir(f, GROUP_LBAS["PLD"][0], GROUP_LBAS["PLD"][1]) if not dr}
        targets = {}
        for name, (size, lba) in pld.items():
            if name.startswith("PL0"):
                n, ch = parse_pld_children(f, lba, size)
                targets[name] = {"lba": lba, "size": size, "child_count": n, "children": ch}
        hashes = {}
        for nm in ("PL00.PLD", "PL05.PLD"):
            if nm in pld:
                s, e = pld[nm]
                hashes[nm] = stream_sha256(f, e, s)
        emd = {n: (s, e) for n, s, dr, e in walk_dir(f, GROUP_LBAS["EMD"][0], GROUP_LBAS["EMD"][1]) if not dr}
        if "EM00.EMD" in emd:
            s, e = emd["EM00.EMD"]
            hashes["EM00.EMD"] = stream_sha256(f, e, s)
    return {"groups": groups, "pld_targets": targets, "asset_sha256": hashes}


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("iso")
    ap.add_argument("--out", default="dmc1_manifest.json")
    a = ap.parse_args(argv)
    m = inventory(Path(a.iso))
    Path(a.out).write_text(json.dumps(m, indent=1))
    print(f"wrote {a.out}: {sum(len(v) for v in m['groups'].values())} files")


if __name__ == "__main__":
    main()
