"""007 - Nightfire (USA) (GameCube, GO7E69, EA Games / Eurocom) -- owned-disc inventory for character work.

Catalog 744ba3bc797403bf is a Dolphin GCZ in the HyperSpin "Nintendo GameCube" collection.  The disc header
proves the platform label (GameCube magic 0xC2339F3D at 0x1C, no Wii magic at 0x18): id GO7E69, version 0,
bi2 region 1 (NTSC-U).  `filemods.gcz_to_iso` unpacks it once to cache/modbase/<game_id>/<stem>.iso; the GCZ is
never modified.  The FST has 315 files:

  main.dol (entry 0x80500000, the same as BaseGC/ColdGC_Release.elf) boots a loader; the game ELFs Nightfire.elf
  and driving.elf load at 0x80007100.  Four stripped PowerPC ELFs at the root: BaseGC_Release.elf (an ELF segment loader: "Now loading
      segment %d at %08x"), ColdGC_Release.elf (the dev "odrun" target in run.bat), Nightfire.elf (on-foot game;
      Eurocom-style HT_ hashcodes, "Gamecube View Skinning.cpp") and driving.elf (EA EAGL driving engine).
  gc/<hash>.bin  on-foot data named by HT_File hashcodes 0x07xxxxxx (Nightfire.elf "%s%8.8x.bin"), two layouts:
      EDL         "EDL" + flag byte (0x81 everywhere), u32 BE file size, u32 BE unpacked size, u32 LE build
                  timestamp, then a compressed payload whose codec is not yet identified (analysis stage).
                  One per level: 0x07000001..0x0700004b and 0x07000500.
      hash pack   u32 BE table size T, u32 BE entry count, 24 header bytes; entries from 0x20 are u32 LE size,
                  u8 type, NUL-terminated name (normally an 8-digit hashcode); payloads follow back to back from
                  0x20 + T and end exactly at end of file.  Type 4 names are 0x04xxxxxx hashcodes and each payload
                  starts with its own hash, little-endian (5937/5938 on this disc; the exception is a 32-byte
                  "00000000" placeholder in 0x07E00007); type 7 = 0x06xxxxxx, type 0 = 0x01xxxxxx,
                  types 13/14 = "GC EXTRA STATIC"/"GC EXTRA DISCARD".  Families 0x078/0x079/0x07A/0x07D are per
                  level (low 20 bits = level), 0x07E00000..7 are shared packs chosen per level by gc/common.bin,
                  0x07F packs are empty.  Which type is HT_Skin versus animation/script data is the analysis
                  question ("HT_Script / HT_Skin 0x%x not loaded in HT_Level %x", "Bondcombat skin must be loaded
                  on all levels!"); the string virtual addresses recorded here are the Ghidra xref entry points.
  driving/*.viv|*.mus|*.spe  EA BIGF archives for the driving missions; actor specs in driving.elf look like
      "2.c_bond.h_bond.t_bond.100" (body, head, texture).
  common/*Txt.dat text banks, gc/movies/*.h4m (HVQM4) and gc/audio/SFX sound banks.
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

GAME_IDS = {"744ba3bc797403bf": "007 - Nightfire (USA)"}
DISC_ID = "GO7E69"
GC_MAGIC, WII_MAGIC = 0xC2339F3D, 0x5D1C9EA3
REGIONS = {0: "NTSC-J", 1: "NTSC-U", 2: "PAL", 4: "NTSC-K"}
EXECUTABLES = ("BaseGC_Release.elf", "ColdGC_Release.elf", "Nightfire.elf", "driving.elf")
NEEDLES = re.compile(
    r"%s%8\.8[xX]\.bin|%scommon\.bin|HT_Script|HT_Skin|Skin 0x%x|skin must be loaded|Anim Seq|Anim script|"
    r"Anim sequence|Bad Datum in Skin|View Skinning|malloc_GC_Skins|malloc_anim_skin|Now loading segment|"
    r"actors\\|\b(?:bond|dominique|zoe|mayhew|kiko|rook|drake|alura|makiko)\b", re.I)
DRIVING_ACTOR = re.compile(r"^(\d+)\.c_(\w+)\.h_(\w+)\.t_(\w+)\.(\d+)$")
NAMES = re.compile(r"\b(?:bond|dominique|zoe|mayhew|kiko|rook|drake|alura|makiko)\b", re.I)


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def disc_identity(head: bytes, bi2: bytes) -> dict:
    """Disc header (0x440 bytes) + bi2.bin: id, version, title, platform from the magic words, bi2 region."""
    gc, wii = struct.unpack_from(">I", head, 0x1C)[0], struct.unpack_from(">I", head, 0x18)[0]
    region = struct.unpack_from(">I", bi2, 0x18)[0]
    return {"disc_id": head[:6].decode("ascii", "replace"), "maker": head[4:6].decode("ascii", "replace"),
            "disc_number": head[6], "version": head[7],
            "title": head[0x20:0x60].split(b"\0")[0].decode("latin-1"),
            "platform": "wii" if wii == WII_MAGIC else ("gamecube" if gc == GC_MAGIC else "unknown"),
            "region_bi2": region, "region": REGIONS.get(region, "unknown")}


def elf_sections(data: bytes) -> list[dict]:
    if data[:4] != b"\x7fELF" or data[4] != 1 or data[5] != 2:
        raise ValueError("not a 32-bit big-endian ELF")
    shoff = struct.unpack_from(">I", data, 0x20)[0]
    shentsize, shnum, shstrndx = struct.unpack_from(">HHH", data, 0x2E)
    raw = [struct.unpack_from(">10I", data, shoff + i * shentsize) for i in range(shnum)]
    tab = data[raw[shstrndx][4]:raw[shstrndx][4] + raw[shstrndx][5]]
    return [{"name": tab[s[0]:tab.index(b"\0", s[0])].decode("latin-1"), "type": s[1], "addr": s[3],
             "offset": s[4], "size": s[5]} for s in raw]


def elf_info(data: bytes) -> dict:
    secs = elf_sections(data)
    return {"size": len(data), "sha256": _sha(data), "machine": struct.unpack_from(">H", data, 0x12)[0],
            "entry": f"{struct.unpack_from('>I', data, 0x18)[0]:#x}", "symtab": any(s["type"] == 2 for s in secs),
            "sections": [{"name": s["name"], "addr": f"{s['addr']:#x}", "size": s["size"]} for s in secs if s["name"]]}


def elf_strings(data: bytes, pattern: re.Pattern = NEEDLES, min_len: int = 4) -> list[dict]:
    """Printable strings matching pattern, with file offset and loaded virtual address (PROGBITS sections)."""
    secs = [s for s in elf_sections(data) if s["type"] == 1 and s["addr"]]
    out = []
    for m in re.finditer(rb"[\x20-\x7e]{%d,}" % min_len, data):
        text = m.group().decode("latin-1")
        if not pattern.search(text):
            continue
        off = m.start()
        va = next((s["addr"] + off - s["offset"] for s in secs if s["offset"] <= off < s["offset"] + s["size"]), None)
        out.append({"text": text, "offset": off, "vaddr": None if va is None else f"{va:#x}"})
    return out


def edl_header(data: bytes) -> dict:
    if len(data) < 16 or data[:3] != b"EDL":
        raise ValueError("not an EDL file")
    size, unpacked = struct.unpack_from(">II", data, 4)
    if size != len(data):
        raise ValueError(f"EDL size field {size} != file size {len(data)}")
    return {"flags": data[3], "size": size, "unpacked": unpacked, "stamp": struct.unpack_from("<I", data, 12)[0]}


def pack_index(data: bytes) -> dict:
    """Hash pack table: every entry is located, the payloads must tile the file exactly."""
    if len(data) < 0x20:
        raise ValueError("hash pack shorter than its 0x20-byte header")
    table, count = struct.unpack_from(">II", data, 0)
    rows, p = [], 0x20
    for _ in range(count):
        size, typ = struct.unpack_from("<IB", data, p)
        end = data.index(b"\0", p + 5)
        rows.append({"type": typ, "name": data[p + 5:end].decode("latin-1"), "size": size})
        p = end + 1
    if p > 0x20 + table:
        raise ValueError("entry table overruns its declared size")
    off = 0x20 + table
    for r in rows:
        r["offset"] = off
        off += r["size"]
    if off != len(data):
        raise ValueError(f"payloads end at {off:#x}, file is {len(data):#x}")
    for r in rows:
        if re.fullmatch(r"[0-9A-Fa-f]{8}", r["name"]):
            h = int(r["name"], 16)
            r["hash"] = f"{h:#010x}"
            if r["size"] >= 4:
                r["self_hash"] = struct.unpack_from("<I", data, r["offset"])[0] == h
    return {"table": table, "count": count, "entries": rows}


def bigf_index(data: bytes) -> dict:
    """EA BIGF archive: u32 LE total size, u32 BE count, u32 BE header size, (BE offset, BE size, name) rows."""
    if data[:4] != b"BIGF":
        raise ValueError("not an EA BIGF archive")
    total = struct.unpack_from("<I", data, 4)[0]
    count, header = struct.unpack_from(">II", data, 8)
    rows, p = [], 16
    for _ in range(count):
        off, size = struct.unpack_from(">II", data, p)
        end = data.index(b"\0", p + 8)
        if off + size > len(data):
            raise ValueError(f"BIGF entry at {p:#x} runs past the archive")
        rows.append({"name": data[p + 8:end].decode("latin-1"), "offset": off, "size": size})
        p = end + 1
    return {"size_field": total, "size_matches": total == len(data), "count": count, "header": header,
            "entries": rows}


def common_map(data: bytes) -> dict:
    """gc/common.bin: u32 BE words; (0x070xxxxx level file, 0x07Exxxxx shared pack) pairs."""
    words = struct.unpack(f">{len(data) // 4}I", data[:len(data) // 4 * 4])
    pairs, rest, i = [], [], 0
    while i < len(words):
        if i + 1 < len(words) and words[i] >> 20 == 0x070 and words[i + 1] >> 20 == 0x07E:
            pairs.append([f"{words[i]:#010x}", f"{words[i + 1]:#010x}"])
            i += 2
        else:
            rest.append(f"{words[i]:#010x}")
            i += 1
    return {"words": len(words), "pairs": pairs, "unpaired": rest}


def driving_actor_assets(bigf: dict) -> dict:
    """EA actor assets named inside the driving BIGF archives: model stems (c_ body, h_ head, p_/a_ props and
    peds), textures and animation banks, each with the archives that carry it."""
    out = {"models": defaultdict(set), "textures": defaultdict(set), "anims": defaultdict(set)}
    for arc, idx in bigf.items():
        for e in idx["entries"]:
            m = re.match(r"data\\actors\\(models|textures|anims)\\([^\\]+?)(?:\.[^.\\]*)?$", e["name"], re.I)
            if m:
                out[m.group(1).lower()][m.group(2).lower()].add(arc)
    return {k: {n: sorted(a) for n, a in sorted(v.items())} for k, v in out.items()}


def family(path: str) -> int | None:
    m = re.fullmatch(r"gc/([0-9A-Fa-f]{8})\.bin", path)
    return int(m.group(1), 16) if m else None


def inventory(iso: Path, source: Path | None = None, source_sha256: str | None = None,
              hash_files: bool = True) -> dict:
    from .gcdisc import GCDisc

    disc = GCDisc(iso)
    ident = disc_identity(disc._r(0, 0x440), disc._r(0x440, 0x2000))
    if ident["disc_id"] != DISC_ID:
        raise ValueError(f"{iso}: disc id {ident['disc_id']}, expected {DISC_ID}")
    dol = disc.dol()
    exes = {"main.dol": {"size": len(dol), "sha256": _sha(dol), "entry": f"{struct.unpack_from('>I', dol, 0xE0)[0]:#x}"}}
    strings = {}
    for name in EXECUTABLES:
        data = disc.read(name)
        exes[name] = elf_info(data)
        strings[name] = elf_strings(data)
        if name == "driving.elf":
            strings[name] += elf_strings(data, DRIVING_ACTOR)
    rows, edl, packs, bigf = [], {}, {}, {}
    stats, types, classes, selfhash = Counter(), Counter(), Counter(), Counter()
    common = None
    for path in sorted(disc.files):
        off, size = disc.files[path]
        leaf = path.rsplit("/", 1)[-1]
        ext = leaf.rsplit(".", 1)[-1].lower() if "." in leaf else ""
        h = family(path)
        row = {"path": path, "offset": off, "size": size}
        data = disc.read(path) if (hash_files or h is not None or ext in ("viv", "mus", "spe")
                                   or path == "gc/common.bin") else None
        if hash_files:
            row["sha256"] = _sha(data)
        if path == "gc/common.bin":
            common = common_map(data)
        elif h is not None and data[:3] == b"EDL":
            row["kind"] = "edl"
            edl[path] = edl_header(data)
            stats["edl"] += 1
        elif h is not None:
            row["kind"] = "pack"
            pk = pack_index(data)
            for e in pk["entries"]:
                types[e["type"]] += 1
                if "hash" in e:
                    classes[e["hash"][:4]] += 1
                if "self_hash" in e:
                    selfhash[f"type{e['type']}:{e['self_hash']}"] += 1
                if hash_files:
                    e["sha256"] = _sha(data[e["offset"]:e["offset"] + e["size"]])
            packs[path] = pk
            stats["packs"] += 1
            stats["empty_packs"] += pk["count"] == 0
        elif data is not None and data[:4] == b"BIGF":
            row["kind"] = "bigf"
            bigf[path] = bigf_index(data)
            stats["bigf"] += 1
        stats[f"ext:{ext}"] += 1
        rows.append(row)
    levels = defaultdict(dict)
    for path in list(edl) + list(packs):
        h = family(path)
        fam = f"{h >> 20:#05x}"
        if h >> 20 == 0x07E:
            continue
        lv = levels[f"{h & 0xFFFFF:05x}"]
        if path in edl:
            lv["edl"] = {"path": path, "size": edl[path]["size"], "unpacked": edl[path]["unpacked"]}
        else:
            lv.setdefault("packs", {})[fam] = {"path": path, "entries": packs[path]["count"]}
    actor_specs = sorted({m.group(0) for s in strings["driving.elf"] if (m := DRIVING_ACTOR.match(s["text"]))})
    actors = driving_actor_assets(bigf)
    return {
        "game_id": next(iter(GAME_IDS)), "title": GAME_IDS[next(iter(GAME_IDS))], "platform": ident["platform"],
        "source": str(source) if source else None, "source_sha256": source_sha256,
        "image": {"path": str(iso), "size": Path(iso).stat().st_size, **ident,
                  "apploader_date": disc._r(0x2440, 10).decode("ascii", "replace")},
        "launch": {"runtime": "Dolphin-compatible GameCube emulator (no IPL dump needed; HLE boot)",
                   "region": ident["region"], "boot": "main.dol",
                   "runtime_elfs": list(EXECUTABLES), "multi_disc": False},
        "executables": exes,
        "fst_files": len(disc.files),
        "fst_dirs": dict(Counter(n.split("/")[0] if "/" in n else "(root)" for n in disc.files)),
        "stats": dict(stats),
        "pack_entry_types": {str(k): v for k, v in sorted(types.items())},
        "pack_hash_classes": dict(sorted(classes.items())),
        "pack_self_hash": dict(sorted(selfhash.items())),
        "common_map": common,
        "levels": dict(sorted(levels.items())),
        "characters": {
            "on_foot": {"executable": "Nightfire.elf",
                        "loader_strings": [s for s in strings["Nightfire.elf"] if not NAMES.search(s["text"])],
                        "named_strings": [s for s in strings["Nightfire.elf"]
                                          if NAMES.search(s["text"]) and "James Bond 007" not in s["text"]],
                        "containers": "gc EDL level databases + hash packs (HT_Skin type mapping pending analysis)"},
            "driving": {"executable": "driving.elf", "actor_specs": actor_specs, **actors}},
        "strings": {k: v for k, v in strings.items() if k != "Nightfire.elf"},
        "edl": edl,
        "packs": packs,
        "bigf": bigf,
        "files": rows,
    }


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("iso", type=Path)
    ap.add_argument("--source", type=Path)
    ap.add_argument("--source-sha256")
    ap.add_argument("--no-hash", action="store_true")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    m = inventory(a.iso, a.source, a.source_sha256, hash_files=not a.no_hash)
    if a.out:
        a.out.write_text(json.dumps(m, indent=1))
    keys = ("image", "launch", "fst_files", "fst_dirs", "stats", "pack_entry_types", "pack_hash_classes",
            "pack_self_hash", "common_map")
    summary = {k: m[k] for k in keys}
    summary["executables"] = {k: {"sha256": v["sha256"], "entry": v["entry"]} for k, v in m["executables"].items()}
    summary["levels"] = len(m["levels"])
    summary["driving_actor_specs"] = m["characters"]["driving"]["actor_specs"]
    summary["driving_models"] = sorted(m["characters"]["driving"]["models"])
    summary["driving_textures"] = len(m["characters"]["driving"]["textures"])
    summary["driving_anims"] = sorted(m["characters"]["driving"]["anims"])
    summary["on_foot_loader_strings"] = {x["text"]: x["vaddr"] for x in m["characters"]["on_foot"]["loader_strings"]}
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
