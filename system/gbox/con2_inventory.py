"""Naruto: Clash of Ninja 2 (GameCube, GNUEDA, Eighting/Tomy) -- owned-disc inventory for character work.

Catalog 68913550d6c4eae8 is a Dolphin GCZ; `filemods.gcz_to_iso` unpacks it once to the shared mod base
(cache/modbase/<game_id>/<stem>.iso) and the GCZ is never modified.  The FST has 341 files: opening.bnr,
audio/ (127 MusyX .trk), movie/ (4 .h4m) and fpack/ (209 Eighting .fpk packs).  Every model, texture and
motion sits inside the packs:

  fpack/chr/<code>NNNN.fpk  per character <code> (24 fighters + cmn/scmn shared packs):
      0000/0100/0200/0300  costume packs: chr/<code>/NNNN.dat (HSD archive, root "scene_data") + .jcv
      1000                 motion bank 0000.mot + 1xxx effect .dat/.jcv + 1300/1400/2000 .txg textures
      3000                 MusyX sound (.h, .h_v, .poo, .pro, .sam, .sdi)
      4000                 4000.txg portrait/UI textures (main.dol table "chr/<code>/4000.txg")
  fpack/stg/NNN0000.fpk    stages, fpack/story/*.fpk story scenes, fpack/game*/gall*/seq0000 menus.

GC FPK layout (big-endian; differs from the Wii CNR2 pack):  0x00 u32 0 (no checksum on this build),
0x04 u32 entry count, 0x08 u32 table offset (0x10), 0x0C u32 file size; entries are 0x20 bytes =
name[0x10] (the pack path, cut to its LAST 15 characters + NUL: "chr/ali/0000.dat" -> "hr/ali/0000.dat"),
u32 0, u32 data offset, u32 stored size, u32 original size.  Payloads are Eighting PRS streams; stored ==
original means raw (55 of 1410 entries).

.dat files are HAL SysDolphin (HSD) archives: u32 file size, u32 data size, u32 relocation count, u32 root
count, u32 reference count, 12 reserved bytes, data at 0x20, relocation offsets, (offset, name) root and
reference records, string table.  All 332 decoded .dat entries pass that structure check (file size ==
PRS output size, every relocation inside the data block), which is the oracle for the PRS decoder.
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

GAME_IDS = {"68913550d6c4eae8": "Naruto - Clash of Ninja 2 (USA)"}
DISC_ID = "GNUEDA"
SHARED_CODES = {"cmn", "scmn"}


def fpk_index(data: bytes) -> list[dict]:
    """Directory of a GameCube Eighting .fpk pack (no decompression)."""
    if len(data) < 16:
        raise ValueError("fpk too short")
    _zero, count, table, size = struct.unpack_from(">4I", data, 0)
    if size != len(data) or table != 0x10 or table + count * 0x20 > len(data):
        raise ValueError(f"not a GC fpk (count {count}, table {table:#x}, size {size} vs {len(data)})")
    out = []
    for i in range(count):
        e = table + i * 0x20
        name = data[e:e + 0x10].split(b"\0", 1)[0].decode("ascii")
        flag, off, stored, orig = struct.unpack_from(">4I", data, e + 0x10)
        if off + stored > len(data):
            raise ValueError(f"fpk entry {name} runs past the end")
        out.append({"name": name, "offset": off, "stored": stored, "size": orig, "flag": flag,
                    "compressed": stored != orig})
    return out


def prs_decompress(data: bytes, size: int) -> bytes:
    """Decode an Eighting PRS stream to exactly `size` bytes (MSB-first flag bits: 1 = literal;
    00 = short copy, 2 length bits + 8-bit back-offset; 01 = long copy, 13-bit back-offset with the
    length in the low 3 bits or a following byte).  Same codec as the Wii CNR2 packs (GNTool spec)."""
    from .formats.lz import prs_msb_decompress       # shared Eighting PRS codec (also cnr2)
    return prs_msb_decompress(data, size, strict=True)


def fpk_files(data: bytes) -> list[tuple[dict, bytes]]:
    """(entry, decoded bytes) for every entry of a pack."""
    out = []
    for e in fpk_index(data):
        blob = data[e["offset"]:e["offset"] + e["stored"]]
        out.append((e, prs_decompress(blob, e["size"]) if e["compressed"] else blob))
    return out


def hsd_header(data: bytes) -> dict:
    """Validate an HSD archive and return its sizes and root/reference names."""
    if len(data) < 0x20:
        raise ValueError("HSD archive too short")
    size, dsz, nrel, nroot, nref = struct.unpack_from(">5I", data, 0)
    if size != len(data):
        raise ValueError(f"HSD size {size} != {len(data)}")
    rel = 0x20 + dsz
    root = rel + nrel * 4
    strs = root + (nroot + nref) * 8
    if strs > size:
        raise ValueError("HSD tables run past the end")
    for k in range(nrel):
        p = struct.unpack_from(">I", data, rel + k * 4)[0]
        if p + 4 > dsz:
            raise ValueError(f"HSD relocation {k} at {p:#x} outside the data block")
    names = []
    for k in range(nroot + nref):
        off, s = struct.unpack_from(">II", data, root + k * 8)
        end = data.find(b"\0", strs + s)
        if off >= dsz or end < 0:
            raise ValueError("bad HSD root record")
        names.append(data[strs + s:end].decode("latin-1"))
    return {"size": size, "data_size": dsz, "relocations": nrel, "roots": names[:nroot], "refs": names[nroot:]}


class Dol:
    def __init__(self, dol: bytes):
        self.b = dol
        offs = struct.unpack_from(">18I", dol, 0)
        addrs = struct.unpack_from(">18I", dol, 0x48)
        sizes = struct.unpack_from(">18I", dol, 0x90)
        self.secs = [(o, a, s) for o, a, s in zip(offs, addrs, sizes) if s]
        self.entry = struct.unpack_from(">I", dol, 0xE0)[0]

    def addr(self, fo: int) -> int | None:
        for o, a, s in self.secs:
            if o <= fo < o + s:
                return a + fo - o
        return None

    def cstr(self, va: int) -> str | None:
        for o, a, s in self.secs:
            if a <= va < a + s:
                fo = o + va - a
                end = self.b.find(b"\0", fo, fo + 64)
                return self.b[fo:end].decode("latin-1") if end > fo else None
        return None


def code_table(dol: bytes, codes: set[str]) -> tuple[int, list[str]]:
    """Locate main.dol's character-code pointer table by content: the longest run of consecutive u32
    pointers to the NUL-terminated 3-letter codes that name fpack/chr packs.  Returns (file offset, codes)."""
    d = Dol(dol)
    best = (0, [])
    run_at, run = 0, []
    for fo in range(0, len(dol) - 3, 4):
        s = d.cstr(struct.unpack_from(">I", dol, fo)[0])
        if s in codes:
            if not run:
                run_at = fo
            run.append(s)
            continue
        if len(run) > len(best[1]):
            best = (run_at, run)
        run = []
    return best


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def inventory(iso: Path, source: Path | None = None, source_sha256: str | None = None) -> dict:
    from .gcdisc import GCDisc

    disc = GCDisc(iso)
    if disc.game_id != DISC_ID:
        raise ValueError(f"{iso}: disc id {disc.game_id}, expected {DISC_ID}")
    head = disc._r(0, 0x440)
    region = struct.unpack(">I", disc._r(0x458, 4))[0]
    dol = disc.dol()
    exe = Dol(dol)
    packs, chars = [], defaultdict(lambda: {"packs": [], "costumes": [], "entries": 0})
    stats = Counter()
    for name in sorted(disc.files):
        if not name.endswith(".fpk"):
            continue
        raw = disc.read(name)
        rows = []
        for e, out in fpk_files(raw):
            ext = e["name"].rsplit(".", 1)[-1]
            row = {"name": e["name"], "stored": e["stored"], "size": e["size"], "compressed": e["compressed"],
                   "sha256": _sha(out)}
            if ext == "dat":
                h = hsd_header(out)
                row["hsd"] = {"data_size": h["data_size"], "relocations": h["relocations"], "roots": h["roots"]}
                stats["hsd"] += 1
            elif ext == "txg":
                row["textures"] = struct.unpack_from(">I", out, 0)[0]
            stats["entries"] += 1
            stats["compressed"] += e["compressed"]
            stats[ext] += 1
            rows.append(row)
        packs.append({"path": name, "size": len(raw), "sha256": _sha(raw), "entries": rows})
        if name.startswith("fpack/chr/"):
            stem = name.rsplit("/", 1)[-1][:-4]
            code, num = stem[:-4], stem[-4:]
            c = chars[code]
            c["packs"].append(num)
            c["entries"] += len(rows)
            if num[0] == "0":
                model = next((r for r in rows if r["name"].endswith(f"{num}.dat")), None)
                c["costumes"].append({"pack": num, "model_bytes": model and model["size"],
                                      "model_sha256": model and model["sha256"],
                                      "relocations": model and model["hsd"]["relocations"]})
            elif num == "1000":
                mot = next((r for r in rows if r["name"].endswith(".mot")), None)
                c["motion_bytes"] = mot and mot["size"]
    tbl_at, order = code_table(dol, {k for k in chars if k not in SHARED_CODES})
    return {
        "game_id": next(iter(GAME_IDS)), "title": GAME_IDS[next(iter(GAME_IDS))], "platform": "gamecube",
        "source": str(source) if source else None, "source_sha256": source_sha256,
        "image": {"path": str(iso), "size": iso.stat().st_size, "disc_id": disc.game_id, "title": disc.title,
                  "disc_number": head[6], "version": head[7], "region_bi2": region,
                  "apploader_date": disc._r(0x2440, 10).decode("ascii", "replace")},
        "main_dol": {"size": len(dol), "sha256": _sha(dol), "entry": f"{exe.entry:#x}",
                     "code_table_offset": f"{tbl_at:#x}", "code_table_addr": f"{exe.addr(tbl_at) or 0:#x}"},
        "fst_files": len(disc.files),
        "fst_dirs": dict(Counter(n.split("/")[0] if "/" in n else "(root)" for n in disc.files)),
        "stats": dict(stats),
        "roster_codes": order,
        "characters": {k: dict(v) for k, v in sorted(chars.items())},
        "packs": packs,
    }


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("iso", type=Path)
    ap.add_argument("--source", type=Path)
    ap.add_argument("--source-sha256")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    m = inventory(a.iso, a.source, a.source_sha256)
    text = json.dumps(m, indent=1)
    if a.out:
        a.out.write_text(text)
    summary = {k: m[k] for k in ("image", "main_dol", "fst_files", "stats", "roster_codes")}
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
