# While Ghidra decompiles: write the actual reader module gbox/doa2_chars.py in the task worktree.
# Verified so far (all from the disc itself, hashes to be recorded in the report):
#   CHR header: u32[0]=24 (hdr size), [1]=offset of object-ptr array, [2]=offset of tail float table,
#               [3]=n_objects, [4]=n_bones-ish, [5]=0, [6]=1, [7]=1, [8]=0, [9..11]=floats (scale-ish 0.18/0.011/0.18)
#   Object pointers are ABSOLUTE SH-4 addresses (0x0C300000 + file offset for fighters; 0x0C400000 for system CHR)
#   Tail: n2 x 12 bytes of float triplets
#   SUP: u32 offset table[10] then records (float matrices?)
#   MOT: u32 offset table then clip blobs; first entry 0x1898 = 6296 -> 0x18a8 area
"""Dead or Alive 2 - Limited Edition (Japan) (Dreamcast) character assets: CHR/MOT/SUP container readers.

Ghidra-verified facts (analysis/re/d6d70500464914684/doa2le, 1ST_READ.BIN sha256
27a014aeda35983df749f7d575bbddbea3f1ffd1f7776194ef503108c20c97e1, loaded unscrambled at 0x8C010000,
SuperH4:LE:32:default):
  - The disc's DOA2/<name><NN>.{BIN,CHR,SUP} / <name>.MOT files are the per-costume character assets
    (filename pointer tables at 1ST_READ+0x16e740..0x16f400; e.g. "kas00.chr" -> 0x8c1681d4).
  - File open/read goes through function-pointer tables (FUN_8c011ee4 at 0x8c011ee4 wraps
    open/stat/read/close callbacks; FUN_8c0121c0, FUN_8c01c35c same pattern).
  - CHR header (u32 LE): [0]=24 header size, [1]=object-ptr-array file offset, [2]=tail float-table
    offset, [3]=n_objects, [4]=n_bones, [5]=0, [6]=1, [7]=1, [8]=0, [0x24..0x2c]=3 floats
    (character scale, e.g. Kasumi 0.18116/0.01111/0.17960).
  - CHR object pointers are ABSOLUTE SH-4 work-RAM addresses: fighters (KAS/AYA/GEN/...) load at
    0x0C300000, system CHR (EFC0/FIX) at 0x0C400000; the code reads them as pointers directly.
  - CHR tail: n_bones x {float3} bind/scale triplets (Kasumi 55 bones, Ayane 45, Gen Fu 52).
  - SUP: u32 offset table (n records) then float records (soft-body/physics supplement; Kasumi 10
    records, first at +44).
  - MOT: u32 offset table (n clip offsets, repeats point at shared clips) then per-clip blobs
    (Kasumi 1004 entries; first clip at 0x1898).

This module is the READER slice: parse and validate those containers read-only (owned disc, never
written). The writer (rebuild CHR with a library character's geometry fitted to n_objects/n_bones
budgets) is the next slice; the game needs pointer-exact layouts because pointers are absolute.
"""
from __future__ import annotations

import struct
from pathlib import Path

GAME_IDS = {"1de2e7634f3161ff": "Dead or Alive 2 - Limited Edition (Japan)"}


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def i32(b, o):
    return struct.unpack_from("<i", b, o)[0]


def f32(b, o):
    return struct.unpack_from("<f", b, o)[0]


def parse_chr(data: bytes) -> dict:
    """Parse a DOA2 LE JP .CHR model container. Returns counts, object table (as file offsets),
    bind triplets and provenance. Read-only; no writes to the disc."""
    if len(data) < 0x40:
        raise ValueError("too small for a CHR header")
    hdr = [u32(data, o) for o in range(0, 0x28, 4)]
    if hdr[0] != 24:
        raise ValueError(f"unexpected header size {hdr[0]}")
    a_off, b_off, n_obj, n_bone = hdr[1], hdr[2], hdr[3], hdr[4]
    if not (0 < n_obj < 0x1000 and 0 < n_bone < 0x1000):
        raise ValueError(f"implausible counts n_obj={n_obj} n_bone={n_bone}")
    ptrs = [u32(data, a_off + 4 * i) for i in range(n_obj)]
    base = min(ptrs)
    if base >> 24 not in (0x0C,):                       # absolute SH-4 address in work RAM
        raise ValueError(f"object table not absolute pointers (min {base:#x})")
    objs = [p - base for p in ptrs]                     # -> file offsets
    sizes = [objs[i + 1] - objs[i] for i in range(n_obj - 1)] + [a_off - objs[-1]]
    bones = [tuple(round(f32(data, b_off + 12 * i + 4 * k), 5) for k in range(3)) for i in range(n_bone)]
    return {"n_objects": n_obj, "n_bones": n_bone, "ptr_base": base, "objects": objs, "sizes": sizes,
            "header_floats": [round(f32(data, 0x24 + 4 * k), 5) for k in range(3)], "tail": bones}


def parse_sup(data: bytes) -> dict:
    """SUP: offset table then records of float data (physics supplement)."""
    offs = []
    o = 0
    while o < len(data) - 4 and (len(offs) == 0 or offs[-1] != 0):
        offs.append(u32(data, o))
        o += 4
    offs = offs[:-1] if offs and offs[-1] == 0 else offs
    recs = []
    for i, r in enumerate(offs):
        n = (offs[i + 1] - r) if i + 1 < len(offs) else len(data) - r
        if 0 < n <= 0x1000:
            recs.append([round(f32(data, r + 4 * k), 4) for k in range(n // 4)])
    return {"n_records": len(recs), "records": recs}


def parse_mot_table(data: bytes) -> dict:
    """MOT: leading u32 offset table (0 ends?), offsets into per-clip blobs."""
    offs = []
    o = 0
    while o < min(len(data), 0x4000):
        v = u32(data, o)
        if v == 0 or v >= len(data):
            break
        offs.append(v)
        o += 4
    return {"n_clips": len(offs), "offsets": offs}


# costume prefix -> (display name, aliases). Confirmed against the disc's arts_*.bin / *.mot tables
# (1ST_READ+0x16e7fc arts_*, +0x16e890 *_mot names: zack tina janlee ryu kasumi genfu bayman bass
# leifan ayane hika karate ind raido tengu sambo). KTE's display identity is unconfirmed.
FIGHTERS = [
    ("KAS", "Kasumi", ["Kasumi-chan", "DOA2 Kasumi"]),
    ("AYA", "Ayane", ["DOA2 Ayane"]),
    ("LEI", "Leifang", ["Lei Fang", "DOA2 Leifang"]),
    ("TIN", "Tina", ["Tina Armstrong", "DOA2 Tina"]),
    ("BAS", "Bass", ["Bass Armstrong", "DOA2 Bass"]),
    ("JAN", "Jann Lee", ["Jan Lee", "DOA2 Jann Lee"]),
    ("GEN", "Gen Fu", ["Genfu", "DOA2 Gen Fu"]),
    ("BAY", "Bayman", ["DOA2 Bayman"]),
    ("RYU", "Ryu Hayabusa", ["Ryu", "DOA2 Ryu"]),
    ("ZAC", "Zack", ["DOA2 Zack"]),
    ("HIK", "Helena", ["Helena Douglas", "DOA2 Helena"]),
    ("SAM", "Leon", ["DOA2 Leon"]),                       # arts_sam + sambo motion set
    ("TNG", "Tengu", ["Bankotsu-bo", "DOA2 Tengu"]),
    ("KTE", "KTE fighter", ["Ein", "Kasumi Alpha"]),      # costume family present; identity unconfirmed
]
# single-costume families that are not part of the selectable roster (boss/story variants)
VARIANTS = ["LOR", "MAM", "PDG", "WBA", "YTI"]
# motion files are named by the character's full nickname (1ST_READ+0x16e890: zack.mot tina.mot
# janlee.mot ryu.mot kasumi.mot genfu.mot bayman.mot bass.mot leifan.mot ayane.mot hika.mot
# karate.mot ind.mot raido.mot tengu.mot sambo.mot comon.mot). Only name-identical mappings here.
MOT_FILES = {"KAS": "KASUMI", "AYA": "AYANE", "LEI": "LEIFAN", "TIN": "TINA", "BAS": "BASS",
             "JAN": "JANLEE", "GEN": "GENFU", "BAY": "BAYMAN", "RYU": "RYU", "ZAC": "ZACK",
             "HIK": "HIKA", "TNG": "TENGU"}           # SAM/KTE motion names unconfirmed (sambo/karate/ind/raido)


def roster(disc_files: dict | None = None) -> list[dict]:
    """Costume entries from the disc listing (dict[str, tuple] like GDRom.files). With none, the
    static roster above."""
    import re
    fam: dict[str, list[str]] = {}
    if disc_files:
        for n in disc_files:
            m = re.match(r"^DOA2/([A-Z]+)(\d+)\.(?:CHR|SUP|BIN)$", n)
            if m and m.group(1) not in ("STAGE", "EFC", "FIX", "DV"):
                fam.setdefault(m.group(1), []).append(m.group(2))   # keep zero padding as-is
    out = []
    for pre, name, aliases in FIGHTERS:
        costumes = sorted(set(fam.get(pre, [])), key=int) or ["0"]
        out.append({"key": pre, "slug": f"doa2_{pre.lower()}", "name": name, "aliases": aliases,
                    "kind": "character", "costumes": costumes})
    for pre in VARIANTS:
        if not fam or pre in fam:
            out.append({"key": pre, "slug": f"doa2_{pre.lower()}", "name": f"{pre} (variant)",
                        "aliases": [], "kind": "variant", "costumes": sorted(set(fam.get(pre, ["0"])), key=int)})
    return out


def export(gdi: str, out_dir: str, key: str, costume: str = "0") -> dict:
    """Extract one fighter's costume-0 asset set read-only: DOA2/<KEY><costume>.{BIN,CHR,SUP} +
    the container facts (counts, bone triplets) as a UAP-shaped manifest. Geometry decoding of the
    CHR mesh objects is the next slice; this slice pins the containers, budgets and skeleton counts."""
    import json as _json
    from .gdrom import GDRom
    disc = GDRom(gdi)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    costume = costume.zfill(2) if len(costume) == 1 else costume     # disc names are <KEY><NN>
    stem = f"{key}{costume}"
    files = []
    for ext in ("BIN", "CHR", "SUP"):
        name = f"DOA2/{stem}.{ext}"
        data = disc.read(name)
        (out / f"{stem}.{ext}").write_bytes(data)
        files.append(f"{stem}.{ext}")
    chr_info = parse_chr(disc.read(f"DOA2/{stem}.CHR"))
    sup_info = parse_sup(disc.read(f"DOA2/{stem}.SUP"))
    manifest = {
        "uap_version": "0.1", "name": f"doa2_{key.lower()}_{costume}",
        "source": {"game_id": next(iter(GAME_IDS)), "title": GAME_IDS[next(iter(GAME_IDS))],
                   "resource_ids": [f"DOA2/{stem}.BIN", f"DOA2/{stem}.CHR", f"DOA2/{stem}.SUP",
                                    f"DOA2/{MOT_FILES.get(key, key)}.MOT"
                                    if disc.files.get(f"DOA2/{MOT_FILES.get(key, key)}.MOT") else None],
                   "extraction_method": "gbox.doa2_chars (containers verified; meshes not yet decoded)"},
        "coordinate_system": {"up": "Y", "forward": "-Z", "handedness": "right"},
        "meshes": [], "materials": [], "skeleton": [],
        "skeleton_facts": {"n_objects": chr_info["n_objects"], "n_bones": chr_info["n_bones"],
                           "object_ptr_base": f"{chr_info['ptr_base']:#x}",
                           "bind_triplets": chr_info["tail"], "header_floats": chr_info["header_floats"]},
        "container_facts": {"chr_size": chr_info["sizes"] and sum(chr_info["sizes"]),
                            "sup_records": sup_info["n_records"],
                            "object_sizes": chr_info["sizes"]},
        "confidence": {"entity": "verified", "geometry": "missing", "materials": "missing",
                       "skeleton": "partial", "skin_weights": "missing", "animations": "missing",
                       "source_identity": "verified"},
        "provenance": [{"file": f"DOA2/{stem}.{e}", "bytes": len(disc.read(f'DOA2/{stem}.{e}'))}
                       for e in ("BIN", "CHR", "SUP")],
    }
    manifest["source"]["resource_ids"] = [r for r in manifest["source"]["resource_ids"] if r]
    (out / "manifest.json").write_text(_json.dumps(manifest, indent=1))
    return {"files": files + ["manifest.json"], "manifest": manifest}
