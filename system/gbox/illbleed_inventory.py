"""Illbleed (USA, Dreamcast) inventory: disc layout, executable identity, and the character / enemy /
texture / motion / scene container inventory.

The game is Crazy Games' survival horror (AIA USA, T46001N V1.002, 2001-03-21). Nearly everything
lives in AMAZON/ and uses a small set of containers:

* .NJ - Ninja model dumps: an NJTL texture-list header (u32 magic 'NJTL', u32 section_end, u16 ???,
  u16 texture_count, then count x 8-byte entries) whose first entry is the texture name table, then
  a stream of 16-byte chunks {char name[8], char type[4], u32 size}: POF0 (a small pointer table),
  NJCM (the Ninja chunk model), GBIX/PVRT (embedded PVR textures, named after the file's textures),
  ... Chunk walk must consume the file exactly.
* .NT - texture packs: u32 count, u32 stride, then count x stride-byte records followed by GBIX/PVRT
  PVR payloads (twiddled PVRs, no global palette; each GBIX blob is its own texture).
* .AFS - CRI ADX archives, one payload each ({u32 ??? = 0x80000-aligned size, u32 ???}), grouped per
  stage cell as <stage><cell><nnn>.AFS.
* .PMC - motion banks: u32 magic 'CGAM', u32 header_size, u32 count, then a record table and the
  same named-chunk stream (POF0 / CGTM transform-motion chunks).
* .CGM - 2D CG images: u32 magic 'CGLC', u32 size, u32 count, then {w, h, ...} records + palette and
  pixel payloads (menu portraits, event art).
* .MEB - message banks (u32 count + u32 offsets + Shift-JIS text): ME_* English, MJ_* Japanese,
  MC_* common.

Playable characters are C00-C04.NJ with per-costume variants (C01A-D, C01N/C02N normal maps); enemies
are E*.NJ, objects O*.NJ, title screen TBACK/TPIC.NJ. Stage scenery sits in <HB|HC|HK|HM|HS|HT|...>
prefixed AFS/EVE/PMC/CGM groups, IR*/IU*/ITEM.NT hold item textures, ADX is CRI audio, SFD is Sofdec.

    python -m gbox.illbleed_inventory DISC.gdi --sha256 <owned CHD sha256> --out manifest.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from collections import Counter
from pathlib import Path

KEY = 0x8C010000                      # 1ST_READ.BIN load address (SH-4)
CHUNK = struct.Struct("<4sI")           # {type[4], size} named-chunk header


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ------------------------------------------------------------------ containers

def njtl(data: bytes) -> dict:
    """NJTL texture-list header of a .NJ file: u32 magic 'NJTL', u32 hdr4, u32 name_base (=8), u32
    texture_count, then count x 12-byte entries {u32 name_off, u32 0, u32 0}. Texture names are
    NUL-terminated ASCII at name_base + name_off. The named-chunk stream starts at align4(name end).
    Raises ValueError when the header doesn't hold."""
    if len(data) < 0x10 or data[:4] != b"NJTL":
        raise ValueError("no NJTL header")
    hdr4, base, count = struct.unpack_from("<III", data, 4)
    if 0x10 + count * 12 > len(data):
        raise ValueError(f"{count} NJTL entries overrun the file")
    names, name_end = [], 0
    for i in range(count):
        off = struct.unpack_from("<I", data, 0x10 + i * 12)[0]
        at = base + off
        if not 0x10 <= at < len(data):
            raise ValueError(f"texture {i} name at 0x{at:x} outside the file")
        e = data.find(b"\0", at, min(len(data), at + 64))
        if e < 0 or not all(32 <= c < 127 for c in data[at:e]):
            raise ValueError(f"texture {i} name at 0x{at:x} is not ASCII")
        names.append(data[at:e].decode("ascii"))
        name_end = max(name_end, e + 1)
    start = (name_end + 3) & ~3
    return {"magic": "NJTL", "hdr4": hdr4, "name_base": base, "tex_count": count, "names": names,
            "chunk_start": start}


def chunks(data: bytes, start: int, end: int | None = None) -> list[dict]:
    """Walk the 8-byte chunk stream {char type[4], u32 size} from `start` to the end of the file.
    The walk must consume the file exactly; raises ValueError on the first broken header.
    Returns [{type, off, size}]."""
    end = len(data) if end is None else end
    out, o = [], start
    while o < end:
        if o + CHUNK.size > end:
            raise ValueError(f"chunk header at 0x{o:x} overruns the file")
        typ, size = CHUNK.unpack_from(data, o)
        if size > end - o - CHUNK.size:
            raise ValueError(f"chunk {typ!r} at 0x{o:x}: size {size} overruns the file")
        if not all(32 <= c < 127 for c in typ):
            raise ValueError(f"chunk at 0x{o:x}: non-ASCII type {typ!r}")
        out.append({"type": typ.decode(), "off": o, "size": size})
        o += CHUNK.size + size
    if o != end:
        raise ValueError(f"chunk stream ends at 0x{o:x}, file ends at 0x{end:x}")
    return out


def afs(data: bytes) -> dict:
    """CRI AFS header of a stage .AFS. Header: u32 magic 'AFS\0', u32 count, then count x 8-byte
    {u32 a, u32 b} records. For this title a==the file's 0x80000-rounded size and b is the name-dir
    offset field; both readings are reported and validated structurally."""
    if len(data) < 8 or data[:4] != b"AFS\0":
        raise ValueError("no AFS magic")
    count = struct.unpack_from("<I", data, 4)[0]
    if 8 + count * 8 > len(data):
        raise ValueError(f"{count} AFS records overrun the file")
    recs = [struct.unpack_from("<II", data, 8 + i * 8) for i in range(count)]
    return {"count": count, "records": recs}


def cgsp(data: bytes) -> dict:
    """CGSP 2D sprite container (EF* effect sprites): u32 magic 'CGSP', u32 size, u32 ??, u32
    stride, then stride-byte records. Validated structurally."""
    if len(data) < 0x10 or data[:4] != b"CGSP":
        raise ValueError("no CGSP magic")
    size, a, stride = struct.unpack_from("<III", data, 4)
    if size > len(data) or stride < 4:
        raise ValueError(f"CGSP size {size} stride {stride} implausible")
    return {"size": size, "u32_a": a, "stride": stride}


def raw_chunks(data: bytes) -> list[dict]:
    """A file that is a bare {type4, u32 size} chunk stream from offset 0."""
    return chunks(data, 0)


def cgam(data: bytes) -> dict:
    if len(data) < 0x10 or data[:4] != b"CGAM":
        raise ValueError("no CGAM magic")
    size, count = struct.unpack_from("<II", data, 4)
    if size > len(data):
        raise ValueError(f"CGAM header size {size} overruns the file")
    return {"size": size, "count": count}


def cglc(data: bytes) -> dict:
    if len(data) < 0x14 or data[:4] != b"CGLC":
        raise ValueError("no CGLC magic")
    size, count = struct.unpack_from("<II", data, 4)
    if size > len(data):
        raise ValueError(f"CGLC header size {size} overruns the file")
    return {"size": size, "count": count}


def meb(data: bytes) -> dict:
    """Message bank: u32 count + count u32 offsets (first offset is the text start), Shift-JIS text."""
    if len(data) < 4:
        raise ValueError("empty MEB")
    count = struct.unpack_from("<I", data, 0)[0]
    if 4 + count * 4 > len(data):
        raise ValueError(f"{count} MEB offsets overrun the file")
    offs = list(struct.unpack_from(f"<{count}I", data, 4))
    if offs and not all(0 <= o <= len(data) for o in offs):
        raise ValueError("MEB offset outside the file")
    return {"count": count, "offsets": offs}


def pvr_globals(data: bytes) -> int:
    """Count of embedded PVR texture headers (GBIX) in a blob."""
    return data.count(b"GBIX")


# ------------------------------------------------------------------ inventory

def ip_info(sector0: bytes) -> dict:
    f = lambda a, b: sector0[a:b].decode("latin-1").strip()
    return {"hardware": f(0, 16), "maker": f(16, 32), "device": f(32, 48), "area": f(48, 56),
            "peripherals": f(56, 64), "product": f(64, 74), "version": f(74, 80), "date": f(80, 96),
            "boot": f(96, 112), "company": f(112, 128), "title": f(128, 256)}


def inventory(gdi: str | Path, source_sha256: str | None = None) -> dict:
    from .gdrom import GDRom
    g = GDRom(gdi)
    hd = min(t[0] for t in g.tracks if t[0] >= 45000)
    ip = ip_info(g.sector(hd))
    exe = g.read(ip["boot"] or "1ST_READ.BIN")
    disc = set(g.files)
    problems: list[str] = []

    nj_files, nt_files, afs_files, pmc_files, cgm_files, meb_files, pvr_glob = [], [], [], [], [], [], 0
    for n in sorted(disc):
        ext = n.rsplit(".", 1)[-1].upper()
        if ext == "NJ":
            nj_files.append(n)
        elif ext == "NT":
            nt_files.append(n)
        elif ext == "AFS":
            afs_files.append(n)
        elif ext == "PMC":
            pmc_files.append(n)
        elif ext == "CGM":
            cgm_files.append(n)
        elif ext == "MEB":
            meb_files.append(n)
        elif ext == "PVR":
            pvr_glob += pvr_globals(g.read(n))

    def stage_kind(n: str) -> str:
        for k in ("HB", "HC", "HE", "HH", "HK", "HM", "HP", "HR", "HS", "HT", "HZ"):
            if n.startswith(f"AMAZON/{k}"):
                return k
        return n.split("/")[1][:2]

    stage_counts = Counter(stage_kind(n) for n in disc if n.startswith("AMAZON/"))

    nj_info, nj_tex = [], {}
    for n in nj_files:
        d = g.read(n)
        try:
            if d[:4] == b"NJTL":
                head = njtl(d)
                walk = chunks(d, head["chunk_start"])
                nj_info.append({"file": n, "kind": "model", "bytes": len(d), "sha256": sha(d), **head,
                                "chunks": {c["type"]: c["size"] for c in walk},
                                "pvr": pvr_globals(d)})
            elif d[:4] == b"CGSP":
                nj_info.append({"file": n, "kind": "cgsp", "bytes": len(d), "sha256": sha(d),
                                **cgsp(d), "pvr": pvr_globals(d)})
            else:
                walk = raw_chunks(d)
                nj_info.append({"file": n, "kind": "raw", "bytes": len(d), "sha256": sha(d),
                                "chunks": {c["type"]: c["size"] for c in walk},
                                "pvr": pvr_globals(d)})
        except ValueError as e:
            problems.append(f"{n}: {e}")

    afs_info, afs_ok = [], 0
    for n in afs_files:
        try:
            afs_info.append({"file": n, "bytes": g.files[n][1], **afs(g.read(n))})
            afs_ok += 1
        except ValueError as e:
            problems.append(f"{n}: {e}")

    pmc_info, cgm_info, meb_info = [], [], []
    for n in pmc_files:
        try:
            d = g.read(n)
            if d[:4] == b"CGAM":
                pmc_info.append({"file": n, "bytes": len(d), **cgam(d)})
            else:
                walk = raw_chunks(d)
                pmc_info.append({"file": n, "bytes": len(d), "raw_chunks":
                                 {c["type"]: c["size"] for c in walk}})
        except ValueError as e:
            problems.append(f"{n}: {e}")
    for n in cgm_files:
        try:
            cgm_info.append({"file": n, "bytes": g.files[n][1], **cglc(g.read(n))})
        except ValueError as e:
            problems.append(f"{n}: {e}")
    for n in meb_files:
        try:
            meb_info.append({"file": n, "bytes": g.files[n][1], **meb(g.read(n))})
        except ValueError as e:
            problems.append(f"{n}: {e}")

    characters = []
    for i, stem in enumerate("C00 C01 C02 C03 C04".split()):
        variants = []
        for v in sorted(disc):
            if v.startswith(f"AMAZON/{stem}") and v.endswith(".NJ"):
                variants.append(v)
        main = f"AMAZON/{stem}.NJ" if f"AMAZON/{stem}.NJ" in disc else (variants[0] if variants else None)
        entry = {"id": i, "stem": stem, "files": variants}
        if main:
            info = next((x for x in nj_info if x["file"] == main), None)
            if info:
                entry.update(main=main, main_sha256=info["sha256"], bytes=info["bytes"],
                             textures=info["names"], chunks=info["chunks"])
        characters.append(entry)

    enemies = [x for x in nj_info if x["file"].startswith("AMAZON/E") and x.get("kind") == "model"]
    effects = [x for x in nj_info if x.get("kind") == "cgsp"]
    objects = [x for x in nj_info if x["file"].startswith("AMAZON/O")]
    title = [x for x in nj_info if x["file"].startswith("AMAZON/T")]

    kinds = Counter(n.rsplit(".", 1)[-1].upper() if "." in n else "(none)" for n in disc)
    return {
        "game": "Illbleed (USA)", "platform": "dreamcast", "source_sha256": source_sha256, "ip": ip,
        "file_count": len(disc), "kinds": dict(sorted(kinds.items())),
        "executable": {"name": ip["boot"], "bytes": len(exe), "sha256": sha(exe),
                       "load_address": f"0x{KEY:08X}"},
        "containers": {
            "nj": {"count": len(nj_files), "all_walk_ok": len(nj_info) == len(nj_files)},
            "nt": {"count": len(nt_files)},
            "afs": {"count": len(afs_files), "parsed": afs_ok},
            "pmc": {"count": len(pmc_info)}, "cgm": {"count": len(cgm_info)},
            "meb": {"count": len(meb_info)}, "pvr_loose": pvr_glob},
        "stage_cells": dict(sorted(stage_counts.items())),
        "characters": characters,
        "enemies": [{"file": x["file"], "bytes": x["bytes"], "sha256": x["sha256"],
                     "textures": x["names"], "chunks": x["chunks"]} for x in enemies],
        "effect_sprites": [{"file": x["file"], "bytes": x["bytes"], "sha256": x["sha256"]}
                           for x in effects],
        "objects": [{"file": x["file"], "bytes": x["bytes"], "sha256": x["sha256"]} for x in objects],
        "title_screen": [{"file": x["file"], "bytes": x["bytes"], "sha256": x["sha256"],
                          "chunks": x["chunks"]} for x in title],
        "afs_files": afs_info, "pmc_files": pmc_info, "cgm_files": cgm_info, "meb_files": meb_info,
        "formats": {
            "NJ": "NJTL texture-list header + {type4,u32 size} chunk stream (POF0/NJCM/CGCL/NMDM/"
                 "CGTM/CMCK); CMCK holds the embedded animation",
            "NJ_CGSP": "CGSP 2D effect-sprite container (EF* files)",
            "NT": "u32 count, u32 stride, count records + GBIX/PVRT twiddled PVR textures",
            "AFS": "CRI 'AFS\\0' archive, one payload per stage cell",
            "PMC": "CGAM motion bank (record table + POF0/CGTM chunks)",
            "CGM": "CGLC 2D CG image (header + palette + pixel payloads)",
            "MEB": "Shift-JIS message bank (u32 count + offsets)",
            "ADX": "CRI ADX audio", "SFD": "Sofdec movie", "SPC": "sequenced audio",
            "EVE": "event scripts", "OSB": "object scripts"},
        "problems": problems,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("gdi")
    ap.add_argument("--sha256", help="sha256 of the owned source (CHD) to record")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    text = json.dumps(inventory(a.gdi, a.sha256), indent=1)
    if a.out:
        Path(a.out).write_text(text)
    else:
        print(text)


if __name__ == "__main__":
    sys.exit(main())
