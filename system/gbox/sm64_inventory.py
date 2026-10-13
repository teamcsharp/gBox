"""Super Mario 64 (N64): owned-source inventory for the favorite-queue character replacement.

The favorite is "Super Mario 64 (Europe) (En,Fr,De)" (game 66062703301f4969): a zip holding one byte-order-correct
.z64 whose header says NSMP (PAL), version 0; its sha1 4ac57216... is the n64decomp/sm64 `baserom.eu.z64`.

Catalog-label finding: the hyperspin "Super Mario 64 (USA).zip" (game b7aecee966090bfa) holds the SAME NSMP ROM
(normalized bytes identical, different zip). Only quickswap2's "Super Mario 64 (USA).zip" is the real NSME build.
So the fixed offsets in gbox.sm64_mario / gbox.sm64_writer (segment 0x04 MIO0 at 0x0F5330, LOAD_MIO0 at 0x28CEE0,
geo 0x17002DD4, Mario animation table 0x4CE710) are EU offsets, verified by content here, and do not hold on NSME.

Level-script commands used (sm64 decomp include/level_commands.h, read as documentation only):
  0x00 EXECUTE / 0x01 EXIT_AND_EXECUTE                     {cmd, 0x10, u16 seg, u32 rom_start, u32 rom_end, u32 entry}
  0x17 LOAD_RAW / 0x18 LOAD_MIO0 / 0x1A LOAD_MIO0_TEXTURE  {cmd, 0x0C, u16 seg, u32 rom_start, u32 rom_end}
  0x22 LOAD_MODEL_FROM_GEO                                  {cmd, 0x08, u16 layer<<12 | model, u32 geo}
The scan accepts a command only when the next command in the stream also has a sane {cmd, len} header.

Second favorite (#1680, game b7aecee966090bfa, catalog title "Super Mario 64 (USA)", region US): its owned zip
(sha256 f10bc05d...ceac, member "Super Mario 64 (USA).z64") normalizes to the same NSMP sha1 4ac57216 as the EU zip.
`catalog_check` records the catalog region next to the ROM header region so a label mismatch is explicit in the
manifest and the EU-offset reader/writer is reused only because the bytes match, not because the titles do.

CLI: python -m gbox.sm64_inventory SRC [--game-id ID] [--out manifest.json]
"""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

from . import n64_rom
from . import sm64_mario as sm

GAME_ID = "66062703301f4969"
# sha1 of the normalized .z64 -> build; both rows were hashed from owned files on the Spark (#1363).
KNOWN = {
    "4ac5721683d0e0b6bbb561b58a71740845dceea9": {"code": "NSMP", "region": "EU", "version": 0,
                                                 "name": "Super Mario 64 (Europe) (En,Fr,De)", "decomp": "eu"},
    "9bef1128717f958171a4afac3ed78ee2bb4e86ce": {"code": "NSME", "region": "US", "version": 0,
                                                 "name": "Super Mario 64 (USA)", "decomp": "us"},
}
# Owned catalog rows (gbox catalog table) whose sources were hashed on the Spark: game_id -> catalog label.
CATALOG = {
    "66062703301f4969": {"title": "Super Mario 64 (Europe) (En,Fr,De)", "region": "EU",
                         "rel_path": "collections/Nintendo 64/roms/Europe/Super Mario 64 (Europe) (En,Fr,De).zip",
                         "source_sha256": "16870d2879e69b0c10d1368d5dcc684ebb2349cbb057d33ea51b42ad3bb0375f"},
    "b7aecee966090bfa": {"title": "Super Mario 64 (USA)", "region": "US",
                         "rel_path": "collections/Nintendo 64/roms/USA/Super Mario 64 (USA).zip",
                         "source_sha256": "f10bc05dbaa0453cc4e0829b9d8c04e651826ba8c5fa57e502de82e878feceac"},
}
REGION_BY_CODE = {"E": "US", "P": "EU", "J": "JP", "U": "AU"}
MARIO_MODEL = 1                                      # MODEL_MARIO
# Model ids that are NOT reused per level group (decomp include/model_ids.h): Mario, his loose caps (drawn when the
# cap leaves his head, so a full Mario replacement must cover them too) and the common character NPCs.
NAMED = {0x01: "mario", 0x85: "marios_winged_metal_cap", 0x86: "marios_metal_cap", 0x87: "marios_wing_cap",
         0x88: "marios_cap", 0xBF: "koopa_without_shell", 0xC3: "bobomb_buddy", 0xDD: "toad", 0xDE: "peach"}
GEO_FIRST = {0x00, 0x01, 0x02, 0x04, 0x08, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F, 0x13, 0x14, 0x15, 0x16, 0x18, 0x19,
             0x1C, 0x1D, 0x20}                       # opcodes a geo layout can start with
MARIO_END = 0x1CD20                                  # = sm64_writer.MARIO_END: Mario's part of segment 0x04
LOADS = {0x17: "raw", 0x18: "mio0", 0x1A: "mio0_texture"}


def _sane_next(rom: bytes, o: int) -> bool:
    if o + 2 > len(rom):
        return False
    cmd, ln = rom[o], rom[o + 1]
    return cmd <= 0x3C and 4 <= ln <= 0x40 and ln % 4 == 0


def level_loads(rom: bytes) -> list[dict]:
    """Every level-script segment load: [{at, cmd, kind, seg, start, end}] in ROM order."""
    out = []
    for o in range(0, len(rom) - 16, 4):
        cmd = rom[o]
        if cmd in (0x00, 0x01) and rom[o + 1] == 0x10 and rom[o + 2] == 0:
            # EXECUTE / EXIT_AND_EXECUTE {cmd, 0x10, u16 seg, u32 start, u32 end, u32 entry}: loads a level-script
            # segment raw (0x0E per level, 0x14 menus); the level's geo layouts live in that same segment.
            seg = rom[o + 3]
            start, end, entry = struct.unpack_from(">III", rom, o + 4)
            if 0x01 <= seg <= 0x1F and 0 < start < end <= len(rom) and entry >> 24 == seg and \
                    (entry & 0xFFFFFF) < end - start and _sane_next(rom, o + 16):
                out.append({"at": o, "cmd": cmd, "kind": "raw", "seg": seg, "start": start, "end": end})
            continue
        if cmd not in LOADS or rom[o + 1] != 0x0C or rom[o + 2] != 0:
            continue
        seg = rom[o + 3]
        start, end = struct.unpack_from(">II", rom, o + 4)
        if not (0x01 <= seg <= 0x1F and 0 < start < end <= len(rom)) or not _sane_next(rom, o + 12):
            continue
        if cmd != 0x17 and rom[start:start + 4] != b"MIO0":
            continue
        out.append({"at": o, "cmd": cmd, "kind": LOADS[cmd], "seg": seg, "start": start, "end": end})
    return out


def model_loads(rom: bytes, segs=frozenset(range(0x0C, 0x18))) -> list[dict]:
    """LOAD_MODEL_FROM_GEO commands: [{at, model, layer, geo}] whose geo address is in a model segment."""
    out = []
    for o in range(0, len(rom) - 8, 4):
        if rom[o] != 0x22 or rom[o + 1] != 0x08:
            continue
        mv, geo = struct.unpack_from(">HI", rom, o + 2)
        if (geo >> 24) not in segs or (geo & 3) or not _sane_next(rom, o + 8):
            continue
        out.append({"at": o, "model": mv & 0x0FFF, "layer": mv >> 12, "geo": geo})
    return out


def containers(rom: bytes, loads: list[dict]) -> list[dict]:
    """Unique ROM ranges the level scripts load, with every (segment, kind) they are loaded as, MIO0 decoded."""
    by = {}
    for ld in loads:
        c = by.setdefault((ld["start"], ld["end"]), {"start": ld["start"], "end": ld["end"], "kind": ld["kind"],
                                                     "segments": set(), "refs": 0})
        c["segments"].add(ld["seg"])
        c["refs"] += 1
    res = []
    for (s, e), c in sorted(by.items()):
        item = {"start": hex(s), "end": hex(e), "stored": e - s, "kind": c["kind"],
                "segments": sorted(hex(x) for x in c["segments"]), "refs": c["refs"]}
        if c["kind"] != "raw":
            dec = sm.mio0(rom, s)
            if len(dec) != struct.unpack_from(">I", rom, s + 4)[0]:
                raise ValueError(f"MIO0 at {s:#x} decoded to {len(dec)} bytes")
            item["decoded"] = len(dec)
            item["decoded_sha256"] = hashlib.sha256(dec).hexdigest()
        res.append(item)
    return res


def resolve_models(rom: bytes, loads: list[dict], models: list[dict]) -> list[dict]:
    """Mark each model load whose geo address lands on a geo opcode in some container loaded as that segment."""
    data, by_seg = {}, {}
    for ld in loads:
        by_seg.setdefault(ld["seg"], set()).add((ld["start"], ld["end"], ld["kind"]))
    for m in models:
        seg, off = m["geo"] >> 24, m["geo"] & 0xFFFFFF
        hit = None
        cands = sorted(by_seg.get(seg, ()), key=lambda c: (not (c[0] <= m["at"] < c[1]), c[0]))
        if cands and cands[0][0] <= m["at"] < cands[0][1]:
            cands = cands[:1]            # a level script resolves its own segment (0x0E) to the range holding it
        for s, e, kind in cands:
            if (s, e) not in data:
                data[(s, e)] = rom[s:e] if kind == "raw" else sm.mio0(rom, s)
            d = data[(s, e)]
            if off + 4 <= len(d) and d[off] in GEO_FIRST:
                hit = s
                break
        m["container"] = hex(hit) if hit is not None else None
    return models


def named_models(models: list[dict]) -> dict:
    out = {}
    for m in models:
        if m["model"] in NAMED:
            out.setdefault(NAMED[m["model"]], set()).add(hex(m["geo"]))
    return {k: sorted(v) for k, v in sorted(out.items())}


def identify(rom: bytes) -> dict:
    from .sm64_writer import crc6102
    sha1 = hashlib.sha1(rom).hexdigest()
    crc = struct.unpack_from(">II", rom, 0x10)
    return {"size": len(rom), "title": rom[0x20:0x34].decode("ascii", "replace").strip(),
            "game_code": rom[0x3B:0x3F].decode("ascii", "replace"), "version": rom[0x3F],
            "entry": hex(struct.unpack_from(">I", rom, 8)[0]), "header_crc": [hex(crc[0]), hex(crc[1])],
            "cic": "6102" if tuple(crc6102(rom)) == crc else "unknown",
            "md5": hashlib.md5(rom).hexdigest(), "sha1": sha1, "sha256": hashlib.sha256(rom).hexdigest(),
            "known": KNOWN.get(sha1)}


def writer_layout(rom: bytes) -> dict:
    """Content checks behind every fixed offset the gbox SM64 reader/writer patches."""
    cmd, _ln, seg, start, end = struct.unpack_from(">BBHII", rom, sm.LOAD_SEG04)
    seg17 = [ld for ld in level_loads(rom) if ld["seg"] == 0x17 and ld["start"] == sm.SEG17[0]]
    n = struct.unpack_from(">I", rom, sm.ANIM_TABLE)[0]
    ents = [struct.unpack_from(">II", rom, sm.ANIM_TABLE + 8 + 8 * i) for i in range(n)] if 0 < n < 0x400 else []
    bank_end = max((o + s for o, s in ents), default=0)
    return {"load_seg04": {"at": hex(sm.LOAD_SEG04), "ok": (cmd, seg, start, end) == (0x18, 4, *sm.SEG04)},
            "seg04_mio0": rom[sm.SEG04[0]:sm.SEG04[0] + 4] == b"MIO0",
            "seg17_raw_load": bool(seg17) and seg17[0]["end"] == sm.SEG17[1],
            "anim_table": {"at": hex(sm.ANIM_TABLE), "count": n, "bank_end": hex(sm.ANIM_TABLE + bank_end),
                           "ok": bool(ents) and sm.ANIM_TABLE + bank_end <= len(rom)},
            "free_tail": len(rom) == 0x800000}


def mario(rom: bytes) -> dict:
    """Mario's native data: geo parts (joints), triangles per part, textures, animation bank."""
    model = sm.extract(rom)
    joints = [{"parent": j["parent"], "dls": [hex(d) for d in j["dls"]], "tris": len(j["tris"])}
              for j in model["joints"]]
    fmts = {0: "RGBA", 1: "YUV", 2: "CI", 3: "IA", 4: "I"}
    tex = [{"addr": hex(k[0]), "fmt": fmts.get(k[1], k[1]), "bits": 4 << k[2], "w": k[3], "h": k[4]}
           for k in sorted(model["textures"])]
    _root, rots, n = sm.anim_frame(rom, 197)
    return {"model_id": MARIO_MODEL, "geo": hex(sm.MARIO_GEO), "seg04_range": [0, hex(MARIO_END)],
            "joints": len(joints), "animated_bones": len(rots), "triangles": sum(j["tris"] for j in joints),
            "parts": joints, "textures": tex, "animations": n, "fit_pose_anim": 197}


def catalog_check(game_id: str, source_sha256: str, ident: dict) -> dict:
    """Compare the catalog row's label with the ROM header; a region mismatch is reported, never silently trusted."""
    row = CATALOG.get(game_id)
    rom_region = REGION_BY_CODE.get(ident["game_code"][-1:], "unknown")
    out = {"game_id": game_id, "catalog_title": row and row["title"], "catalog_region": row and row["region"],
           "rom_game_code": ident["game_code"], "rom_region": rom_region,
           "build": (ident.get("known") or {}).get("name")}
    out["source_hash_matches_catalog"] = bool(row) and row["source_sha256"] == source_sha256
    out["region_label_matches_rom"] = bool(row) and row["region"] == rom_region
    return out


def inventory(src: Path, game_id: str = GAME_ID) -> dict:
    src = Path(src)
    rom = n64_rom.read(src)
    ident = identify(rom)
    src_sha = hashlib.sha256(src.read_bytes()).hexdigest()
    loads = level_loads(rom)
    models = resolve_models(rom, loads, model_loads(rom))
    lay = writer_layout(rom)
    mario_loads = [m for m in models if m["model"] == MARIO_MODEL and m["geo"] == sm.MARIO_GEO]
    compat = (lay["load_seg04"]["ok"] and lay["seg04_mio0"] and lay["seg17_raw_load"] and lay["anim_table"]["ok"]
              and bool(mario_loads))
    manifest = {
        "game_id": game_id,
        "source": {"path": str(src), "sha256": src_sha, "bytes": src.stat().st_size},
        "rom": ident,
        "catalog_check": catalog_check(game_id, src_sha, ident),
        "launch": {"core": "retroarch/parallel_n64", "cic": ident["cic"], "video": "PAL 50 Hz" if ident["game_code"]
                   .endswith("P") else "NTSC 60 Hz", "save": "EEPROM 4 Kbit", "byte_order": "z64 (big-endian)"},
        "layout": {"level_loads": len(loads), "containers": containers(rom, loads),
                   "model_loads": len(models), "distinct_models": len({(m["model"], m["geo"]) for m in models}),
                   "model_loads_resolved": sum(m["container"] is not None for m in models),
                   "named_models": named_models(models),
                   "mio0_magic": rom.count(b"MIO0")},
        "writer_layout": lay,
        "writer_compatible": compat,
        "mario_model_loads": [hex(m["at"]) for m in mario_loads],
        # sm64_mario reads Mario at the fixed EU offsets; on another layout it would decode garbage, so skip it.
        "characters": {"playable": ["Mario"], "mario": mario(rom) if compat else None},
    }
    return manifest


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("src")
    ap.add_argument("--game-id", default=GAME_ID, choices=sorted(CATALOG))
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    m = inventory(Path(a.src), a.game_id)
    text = json.dumps(m, indent=1)
    if a.out:
        Path(a.out).write_text(text)
    print(json.dumps({k: m[k] for k in ("rom", "catalog_check", "launch", "writer_compatible")} |
                     {"containers": len(m["layout"]["containers"]), "named_models": m["layout"]["named_models"],
                      "mario": {k: v for k, v in (m["characters"]["mario"] or {}).items()
                                if k not in ("parts", "textures")}},
                     indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
