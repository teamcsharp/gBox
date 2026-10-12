"""Exact-build inventory for Sonic Shuffle (USA), Dreamcast (game 79ade87c3c2fad3e).

Reads the unpacked GD-ROM (``disc.gdi`` made by ``chdman extractcd`` from the owned HyperSpin
CHD) read-only and writes a JSON manifest: source/track hashes, IP.BIN identity, the
1ST_READ.BIN hash and its character file/name tables, the ``.MDL`` container layout of every
MDL on the disc, and the character inventory (Ninja chunk models, PVM texture packs, NMDM
motions) together with each file's LBA room and each entry's in-container room, which bound a
same-size native writer.

    python -m gbox.sshuffle_inventory disc.gdi --chd OWNED.chd --out manifest.json

Build: MK-51060 V1.000 (2000-10-19), area U. An ``.MDL`` is a flat container::

    u16 version (=2), u16 count, u32 max_entry   # max_entry = largest entry rounded up to 0x800
    count * (u32 type, u32 size, u32 offset)     # payloads start 0x800-aligned, no overlap
    type 1 = PVM (PVMH), 2 = Ninja chunk model (NJCM, rarely an NJTL), 4 = motion (NMDM),
    8 = shape/sound motion (NJSL/NSSM), 16 = raw data

The eight board characters are ``CHRDATA/C00.MDL``..``C07.MDL`` in the order of 1ST_READ's
name list (SONIC TAILS KNUCKLES AMY BIG GAMMA CHAO SUPER SONIC); each file's PVM texture names
confirm the order. ``H*.MDL`` are the higher-detail story-event models, the other ``C*.MDL``
are NPCs, bosses and enemies.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import struct
import sys
from pathlib import Path

GAME_ID = "79ade87c3c2fad3e"
TITLE = "Sonic Shuffle (USA)"
PRODUCT = "MK51060"
VERSION = "V1.000"
CATALOG = {"library": "hyperspin", "rel_path": "collections/Sega Dreamcast/roms/Sonic Shuffle (USA).chd"}
# owned HyperSpin CHD v4 (zlib, 3 tracks); every stage reuses this source identity
SOURCE_SHA256 = "46413e9486c89a0eb01aa13a09d9fa5ab30a0cbfd3ffc5431639859e9855b36b"
# 1ST_READ.BIN of the owned MK-51060 V1.000 disc; addresses found in it are build-specific.
FIRST_READ_SHA256 = "e765a5f5e998a9f549d8f062c65fdc478bc4e5e3641b1d2b02f13b156370dd04"
FIRST_READ_BASE = 0x8C010000
CHR_FILES = 0xDF8FC        # "C00.MDL".."C07.MDL", NUL-terminated, 4-byte aligned
PLAYER_NAMES = 0xE1060     # "SONIC" "TAILS" "KNUCKLES" "AMY" "BIG" "GAMMA" "CHAO" "SUPER SONIC"
SECTOR = 2048
ALIGN = 0x800
TYPES = {1: "pvm", 2: "model", 4: "motion", 8: "shape_motion", 16: "data"}
MAGIC = {1: (b"PVMH",), 2: (b"NJCM", b"NJTL"), 4: (b"NMDM",), 8: (b"NJSL", b"NSSM")}
# texture-name stem that each board character's PVMs carry (cross-check of the name-list order)
TEX_STEM = {"SONIC": "sonic", "TAILS": "mai", "KNUCKLES": "knuck", "AMY": "amy", "BIG": "big",
            "GAMMA": "e102", "CHAO": "chao", "SUPER SONIC": "ssonic"}
DISPLAY = {"SONIC": "Sonic", "TAILS": "Tails", "KNUCKLES": "Knuckles", "AMY": "Amy", "BIG": "Big",
           "GAMMA": "E-102 Gamma", "CHAO": "Chao", "SUPER SONIC": "Super Sonic"}


def sha256_file(path: str | Path, chunk: int = 1 << 22) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(chunk):
            h.update(b)
    return h.hexdigest()


def parse_ip(sector: bytes) -> dict:
    """Dreamcast IP.BIN meta block (first 0x100 bytes of the high-density data track)."""
    if sector[:16] != b"SEGA SEGAKATANA ":
        raise ValueError("No Dreamcast IP.BIN at the start of the high-density area")
    f = lambda a, b: sector[a:b].decode("latin-1").strip()  # noqa: E731
    return {"hardware": f(0x00, 0x10), "maker": f(0x10, 0x20), "device": f(0x20, 0x30),
            "area": f(0x30, 0x38), "peripherals": f(0x38, 0x40), "product": f(0x40, 0x4A),
            "version": f(0x4A, 0x50), "date": f(0x50, 0x60), "boot": f(0x60, 0x70),
            "company": f(0x70, 0x80), "title": f(0x80, 0x100)}


def name_list(exe: bytes, at: int, n: int, pat: bytes = rb"[0-9A-Z_. ]+") -> list[str]:
    """``n`` NUL-terminated names starting at ``at``, each 4-byte aligned (1ST_READ string pools)."""
    out, o = [], at
    while len(out) < n and o < len(exe):
        e = exe.find(b"\0", o)
        s = exe[o:e] if e >= 0 else b""
        if not s or not re.fullmatch(pat, s):
            raise ValueError(f"no name at {o:#x}")
        out.append(s.decode())
        o = (e + 4) & ~3
    return out


def file_room(files: dict[str, tuple[int, int]]) -> dict[str, int]:
    """Bytes each file may occupy without moving another file: up to the next file's LBA."""
    order = sorted(files.items(), key=lambda kv: (kv[1][0], kv[0]))
    room = {}
    for i, (name, (lba, size)) in enumerate(order):
        own = (size + SECTOR - 1) // SECTOR * SECTOR
        nxt = next((l for _, (l, _s) in order[i + 1:] if l > lba), None)
        room[name] = max(own, (nxt - lba) * SECTOR) if nxt is not None else own
    return room


def mdl_table(data: bytes) -> dict:
    """Parse and validate an ``.MDL`` container; raises ValueError on any inconsistency."""
    if len(data) < 8:
        raise ValueError("MDL too short")
    ver, count = struct.unpack_from("<HH", data, 0)
    max_entry = struct.unpack_from("<I", data, 4)[0]
    if ver != 2 or not count:
        raise ValueError(f"MDL header {ver}/{count}")
    end_tab = 8 + 12 * count
    if end_tab > len(data):
        raise ValueError("MDL table past EOF")
    ents = []
    for i in range(count):
        t, s, o = struct.unpack_from("<3I", data, 8 + 12 * i)
        if o % ALIGN or o < end_tab or o + s > len(data):
            raise ValueError(f"entry {i}: offset {o:#x} size {s:#x} out of bounds/unaligned")
        ok = data[o:o + 4] in MAGIC.get(t, (data[o:o + 4],))
        ents.append({"index": i, "type": t, "kind": TYPES.get(t, f"type{t}"), "offset": o, "size": s,
                     "magic": data[o:o + 4].decode("latin-1") if t != 16 else None, "magic_ok": ok})
    spans = sorted(ents, key=lambda e: e["offset"])
    for a, b in zip(spans, spans[1:]):
        if a["offset"] + a["size"] > b["offset"]:
            raise ValueError(f"entries {a['index']} and {b['index']} overlap")
    for a, b in zip(spans, spans[1:] + [None]):
        a["room"] = (b["offset"] if b else len(data)) - a["offset"]
    biggest = max((e["size"] + ALIGN - 1) & ~(ALIGN - 1) for e in ents)
    return {"version": ver, "count": count, "max_entry": max_entry, "max_entry_ok": max_entry == biggest,
            "table_end": end_tab, "data_end": max(e["offset"] + e["size"] for e in ents), "entries": ents}


def pvm_names(blob: bytes) -> list[str]:
    """Texture names of a PVM (PVMH flags: 8 names[28], 4 format u16, 2 dims u16, 1 GBIX u32)."""
    if blob[:4] != b"PVMH":
        raise ValueError("not a PVM")
    flags, n = struct.unpack_from("<HH", blob, 8)
    p, out = 12, []
    for _ in range(n):
        p += 2
        name = ""
        if flags & 8:
            name = blob[p:p + 28].split(b"\0")[0].decode("latin-1")
            p += 28
        p += 2 * bool(flags & 4) + 2 * bool(flags & 2) + 4 * bool(flags & 1)
        out.append(name)
    return out


def motion_frames(blob: bytes) -> int | None:
    """nbFrame of the NJS_MOTION at the start of an NMDM chunk, or None when it is not there."""
    if blob[:4] != b"NMDM" or len(blob) < 20:
        return None
    size = struct.unpack_from("<I", blob, 4)[0]
    mdata, nb, typ, _inp = struct.unpack_from("<IIHH", blob, 8)
    return nb if mdata < size and 0 < nb < 100000 and not typ & ~0x3FF else None


def _count(x) -> int | None:
    return len(x) if hasattr(x, "__len__") else (x if isinstance(x, int) else None)


def model_stats(blob: bytes) -> dict:
    """Decode one NJCM with ``gbox.ninja.NJ`` (bones/triangles/texture ids) or report the error."""
    if blob[:4] == b"NJTL":
        from .ninja import njtl
        return {"texlist": njtl(blob)}
    try:
        from .ninja import NJ
        nj = NJ(blob)
        tris = nj.tris if isinstance(nj.tris, dict) else {}       # texture id -> [triangle, ...]
        return {"bones": _count(nj.bones), "tris": sum(len(v) for v in tris.values()),
                "verts": _count(nj.vbuf), "tex_ids": sorted(tris)}
    except Exception as e:  # recorded for the analysis stage, never fatal for the inventory
        return {"decode_error": f"{type(e).__name__}: {e}"[:200]}


def mdl_inventory(data: bytes, decode: bool = True) -> dict:
    t = mdl_table(data)
    tex, models, frames = [], [], []
    for e in t["entries"]:
        blob = data[e["offset"]:e["offset"] + e["size"]]
        e["sha256"] = hashlib.sha256(blob).hexdigest()
        if e["type"] == 1 and e["magic_ok"]:
            e["textures"] = pvm_names(blob)
            tex.extend(e["textures"])
        elif e["type"] == 2 and decode:
            e.update(model_stats(blob))
            models.append(e)
        elif e["type"] == 4:
            e["frames"] = motion_frames(blob)
            frames.append(e["frames"])
    t["counts"] = dict(collections.Counter(e["kind"] for e in t["entries"]))
    t["texture_names"] = tex
    t["motions_with_frames"] = sum(f is not None for f in frames)
    return t


def inventory(gdi: str | Path, chd: str | Path | None = None, chd_sha256: str | None = None,
              hash_tracks: bool = True) -> dict:
    from .gdrom import GDRom
    gdi = Path(gdi)
    g = GDRom(gdi)
    ip = parse_ip(g.sector(45000))
    if ip["product"].replace("-", "") != PRODUCT or ip["version"] != VERSION:
        raise ValueError(f"not {TITLE} {PRODUCT} {VERSION}: {ip['product']} {ip['version']}")
    exe = g.read("1ST_READ.BIN")
    exe_sha = hashlib.sha256(exe).hexdigest()
    pinned = exe_sha == FIRST_READ_SHA256
    chr_files = name_list(exe, CHR_FILES, 8) if pinned else []
    players = name_list(exe, PLAYER_NAMES, 8) if pinned else []
    room = file_room(g.files)
    man: dict = {"game_id": GAME_ID, "title": TITLE, "platform": "dreamcast", "catalog": CATALOG, "ip": ip,
                 "first_read": {"sha256": exe_sha, "size": len(exe), "base": hex(FIRST_READ_BASE),
                                "matches_pinned": pinned, "unscrambled_sh4": exe[:2] == b"\x09\x00",
                                "chr_files": {"offset": hex(CHR_FILES), "names": chr_files},
                                "player_names": {"offset": hex(PLAYER_NAMES), "names": players}},
                 "launch": {"core": "flycast", "media": "GD-ROM (3 tracks: data, audio, high-density data)",
                            "bios": "dc_boot.bin + dc_flash.bin (flycast; HLE BIOS fallback)",
                            "boot_file": ip["boot"], "scrambled_1st_read": False, "region": ip["area"],
                            "peripherals": ip["peripherals"]},
                 "files": len(g.files)}
    if chd:
        man["source"] = {"path": str(chd), "sha256": chd_sha256 or sha256_file(chd),
                         "size": Path(chd).stat().st_size, "format": "CHD v4 (zlib)"}
    if hash_tracks:
        man["tracks"] = [{"lba": lba, "sector": ss, "file": p.name, "sha256": sha256_file(p)}
                         for lba, ss, p in g.tracks] + _gdi_audio(gdi)
    kinds: dict[str, int] = collections.Counter(
        n.rsplit(".", 1)[-1] if "." in n.rsplit("/", 1)[-1] else "" for n in g.files)
    man["extensions"] = dict(sorted(kinds.items()))
    man["directories"] = dict(sorted(collections.Counter(n.rsplit("/", 1)[0] if "/" in n else "."
                                                         for n in g.files).items()))
    # container format check over every MDL on the disc
    fmt = {"mdl_files": 0, "valid": 0, "max_entry_ok": 0, "type_magic": {}, "errors": {}}
    magic = collections.defaultdict(collections.Counter)
    chrdata = {}
    for n in sorted(x for x in g.files if x.endswith(".MDL")):
        d = g.read(n)
        fmt["mdl_files"] += 1
        try:
            t = mdl_inventory(d, decode=n.startswith("CHRDATA/")) if n.startswith("CHRDATA/") else mdl_table(d)
        except ValueError as e:
            fmt["errors"][n] = str(e)
            continue
        fmt["valid"] += 1
        fmt["max_entry_ok"] += t["max_entry_ok"]
        for e in t["entries"]:
            magic[e["kind"]][e["magic"] or "raw"] += 1
        if n.startswith("CHRDATA/"):
            chrdata[n] = {"lba": g.files[n][0], "size": len(d), "room": room[n],
                          "sha256": hashlib.sha256(d).hexdigest(), **t}
    fmt["type_magic"] = {k: dict(v) for k, v in sorted(magic.items())}
    man["mdl_format"] = fmt
    roster = []
    for i, (fname, key) in enumerate(zip(chr_files, players)):
        n = f"CHRDATA/{fname}"
        c = chrdata.get(n)
        if not c:
            continue
        stem = TEX_STEM.get(key, "")
        models = [{k: e.get(k) for k in ("index", "offset", "size", "room", "bones", "tris", "verts", "tex_ids",
                                         "decode_error", "sha256")} for e in c["entries"] if e["type"] == 2]
        roster.append({"slot": i, "key": key, "name": DISPLAY.get(key, key.title()), "file": n,
                       "lba": c["lba"], "size": c["size"], "room": c["room"], "sha256": c["sha256"],
                       "counts": c["counts"], "max_entry": c["max_entry"],
                       "texture_names": c["texture_names"],
                       "texture_stem": stem, "name_check": any(stem in t.lower() for t in c["texture_names"]),
                       "models": models, "motions": c["counts"].get("motion", 0),
                       "motions_with_frames": c["motions_with_frames"],
                       "decoded_models": sum(m.get("bones") is not None for m in models)})
    man["roster"] = roster
    board = {r["file"] for r in roster}
    others = {}
    for n, c in sorted(chrdata.items()):
        if n in board:
            continue
        others[n] = {"group": "event_hi_detail" if n.startswith("CHRDATA/H") else "npc_boss_enemy",
                     "size": c["size"], "room": c["room"], "sha256": c["sha256"], "counts": c["counts"],
                     "texture_names": c["texture_names"][:12],
                     "models": [{k: e.get(k) for k in ("index", "size", "bones", "tris", "decode_error")}
                                for e in c["entries"] if e["type"] == 2]}
    man["other_characters"] = others
    man["loose_chr_pvm"] = {n: {"size": g.files[n][1], "room": room[n]} for n in sorted(g.files)
                            if n.startswith("CHRDATA/") and n.endswith(".PVM")}
    return man


def _gdi_audio(gdi: Path) -> list[dict]:
    out = []
    for ln in gdi.read_text().splitlines()[1:]:
        p = ln.split()
        if len(p) >= 5 and p[2] == "0":
            out.append({"lba": int(p[1]), "sector": int(p[3]), "file": p[4].strip('"'), "audio": True,
                        "sha256": sha256_file(gdi.parent / p[4].strip('"'))})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("gdi")
    ap.add_argument("--chd")
    ap.add_argument("--chd-sha256")
    ap.add_argument("--no-track-hashes", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    man = inventory(a.gdi, a.chd, a.chd_sha256, hash_tracks=not a.no_track_hashes)
    text = json.dumps(man, indent=1)
    if a.out:
        Path(a.out).write_text(text)
    else:
        sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
