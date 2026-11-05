"""Devil May Cry (USA) SLUS_202.16 (PS2) ISO-9660 inventory (#1856).

Read-only.  Owned source is a CHD v5 (gBox native reader is v4-only), so the
authoritative raw image is produced with ``chdman extractcd`` from:

    /mnt/gbox/hyperspin/Arcade/collections/Sony Playstation 2/roms/USA/Devil May Cry (USA).chd
    sha256 = 1e6d865218bfb4abf1f6e35cbcc244fbd4fcc68aef558ae2403e3d4944693a60

Extracted raw image (4,698,767,360 B, 2,294,320 MODE1/2048 sectors):
    dmc1_usa.bin sha256 = 9e4d87fa0bae06e7282c085bb58693f83cf857bede9803f4bd235e3dfcfe0726

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
    then 215 u32 section offsets relative to child6 start (table ends at 864).
    Verified on the real image: all offsets < child6 size; the even-indexed
    entries are strictly increasing, the odd-indexed ones are not (two
    interleaved offset streams).  parse_child6_table() classifies each via its
    GS GIF-tag register descriptor: even entries are PACKED geometry streams
    (registers XYZ2 0x40 + RGBAQ 0x80, e.g. `c0 00 00 00 00 01 00 00 ...`),
    odd entries are texture/CLUT uploads (descriptor leads FRAME 0x3e /
    SCISSOR 0x1f / 0x80 -- the CSM1 palettes).  110 data / 105 palette streams,
    50 unique palettes (heavily shared).  Section boundary: table ends 0x360,
    first palette header at 0x6c0 (`3e 00 1f ff 80 01 02 03 ...`).

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
    
    Child0 (mesh) structure: 16-byte entries with offset/size pairs pointing to
    child6 (texture bulk). Child6 starts with d7 00 00 00 magic, followed by
    offset/size pairs pointing to texture sections. Each texture section starts
    with GS packet header (0x80).
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


def _gif_tag(blob: bytes, off: int) -> dict:
    """Decode a 128-bit PS2 GS GIF tag at ``off`` (little-endian).

    The tag is two little-endian u64s: ``lo`` holds NLOOP(0:15)/EOP(15)/
    PRE(46)/PRIM(47)/FLG(58:60)/NREG(60:64); ``hi`` holds the register
    descriptor bytes.  We expose nloop, eop, prim (raw PRIM bit), flg and a
    ``regs`` byte tuple so callers can dispatch palette (TEX/CLUT upload) vs
    geometry (XYZ2+RGBAQ) streams.  Verified against PL00 child6 bytes:
    section 0x2888 carries registers XYZ2(0x40)+RGBAQ(0x80) in a packed
    vertex stream; odd-indexed sections carry FRAME(0x3e)/SCISSOR(0x1f) +
    0x80 texture-upload descriptors (CSM1 palettes).
    """
    lo, hi = struct.unpack_from("<QQ", blob, off)
    nloop = lo & 0x7FFF
    eop = (lo >> 15) & 1
    pre = (lo >> 46) & 1
    prim = (lo >> 47) & 1
    flg = (lo >> 58) & 3
    nreg = (lo >> 60) & 0xF
    regs = tuple((hi >> (8 * i)) & 0xFF for i in range(8))
    return {
        "nloop": nloop,
        "eop": eop,
        "pre": pre,
        "prim": prim,
        "flg": flg,
        "nreg": nreg,
        "regs": regs,
    }


# GS register 0x40 == XYZ2 (untextured vertex), 0x80 == RGBAQ (colour/ST).
# A geometry stream packs XYZ2+RGBAQ; a palette upload carries FRAME(0x3e)/
# SCISSOR(0x1f) + texture/CLUT descriptors.
_GEOM_REGS = {0x40: "XYZ2", 0x80: "RGBAQ", 0x01: "PRIM", 0x14: "TEX0"}


# 0x3e == GS FRAME register, 0x1f == SCISSOR: the two high descriptor bytes of a
# palette/upload GIF tag in child6 (e.g. 3e 00 1f ff 80 01 02 03 ...).
# A geometry stream instead carries XYZ2(0x40)+RGBAQ(0x80) in its descriptor.
_PALETTE_FRAME = 0x3E


def parse_child6_table(blob) -> list[dict]:
    """Decode child6 (GS command stream) into interleaved section records.

    child6 layout (verified on PL00/PL05, 1,042,640 B):
        u32 count (0xd7 = 215), then 215 u32 offsets into the blob.
    The offsets interleave two streams (entry 0 points at the table itself):
        even index -> geometry/data GIF tag (offsets strictly increasing)
        odd  index -> palette GIF tag   (offset repeats == shared palettes)

    Each record is {"off", "kind", "regs", "nloop"}, where "kind" is "palette"
    when the GIF tag descriptor leads with FRAME(0x3e) (a texture/CLUT upload),
    else "data".  Returns records in table order; raises ValueError on
    malformed input.
    """
    n = struct.unpack_from("<I", blob, 0)[0]
    if n == 0 or 4 + 4 * n > len(blob):
        raise ValueError("bad child6 table count %d" % n)
    offs = list(struct.unpack_from("<%dI" % n, blob, 4))
    if len(offs) != n:
        raise ValueError("short child6 table")
    if any(o >= len(blob) for o in offs):
        raise ValueError("child6 offset beyond blob")
    evens = offs[0::2]
    # Geometry stream is spatially packed: strictly increasing offsets.
    if evens != sorted(evens):
        raise ValueError("child6 data offsets not strictly increasing")
    out = []
    for i, o in enumerate(offs):
        tag = _gif_tag(blob, o)
        kind = "palette" if tag["regs"][0] == _PALETTE_FRAME else "data"
        out.append({"off": o, "kind": kind, "regs": tag["regs"],
                    "nloop": tag["nloop"]})
    return out


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
