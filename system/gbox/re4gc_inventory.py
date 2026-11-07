"""Resident Evil 4 (GameCube, G4BE08 USA, Disc 1) -- owned-disc inventory for character-replacement work.

Catalog 78ab9efa2e310db4 is the HyperSpin Dolphin GCZ "collections/Nintendo GameCube/roms/Resident Evil 4 (USA)
(Disc 1).gcz".  `filemods.gcz_to_iso` unpacks it once to cache/modbase/<game_id>/<stem>.iso (the GCZ is never
modified); this module only reads that plain image through `gcdisc.GCDisc`.

Disc layout (FST, 1018 files): em/ 128 UDAS packs (.drs: 22 pl* player/partner, em* enemies/NPCs, wep* weapons),
St1/St2/St4 stage archives (.das; no St3 on Disc 1), Evd/ cutscene event data, ss/ menu+item BIN/TPL, etc/ shared
models (pl01/pl05 hand meshes), Rel/ code modules, bgm/, Movie/ (.sfd), font/.  main.dol sits at the header's 0x420
offset and is not in the FST.

Containers (see gbox/re4gc_models.py, the existing reader/writer):
  UDAS (.drs/.das)  0x20 fill bytes, then 32-byte entries (type, size, 0, offset, 16 more) ended by 0xFFFFFFFF inside
                    the first 0x400 bytes.  Type 0 = DAT model pack, type 4 = sound (a nested UDAS).
  DAT               u32 count, u32 tail, 8 pad, count x u32 offsets, count x 4-char extensions:
                    BIN (big-endian mesh), TPL (GX textures), FCV / SEQ (motion data, decoded in the analysis stage),
                    EFF (effects); an empty extension is an unused slot.
  BIN header        0x00 header size (0x60 skinned / 0x40 rigid; = bone table offset), 0x18 u8 weights,
                    0x19 u8 bones, 0x1A u16 materials, 0x28 u8 position frac bits, 0x38 u16 positions,
                    0x3A u16 normals; bones are 16-byte records (id, parent, pad, xyz).

`python -m gbox.re4gc_inventory ISO --source GCZ --source-sha256 SHA --out manifest.json` writes the manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

GAME_IDS = {"78ab9efa2e310db4": "Resident Evil 4 (USA) (Disc 1)"}
DISC_ID = "G4BE08"
SOURCE_REL = "collections/Nintendo GameCube/roms/Resident Evil 4 (USA) (Disc 1).gcz"
GC_MAGIC = 0xC2339F3D
TPL_MAGIC = 0x0020AF30
REGIONS = {0: "NTSC-J", 1: "NTSC-U", 2: "PAL"}
GX_FORMATS = {0: "I4", 1: "I8", 2: "IA4", 3: "IA8", 4: "RGB565", 5: "RGB5A3", 6: "RGBA8", 8: "C4", 9: "C8",
              10: "C14X2", 14: "CMPR"}
# Only pl00 is proven (the verified re4gc reader's Leon, LEON_PARTS); the other player-pack ids are mapped in the
# analysis stage from main.dol's loader table, so they stay "unmapped" here instead of being guessed.
KNOWN_PACKS = {"em/pl00.drs": "Leon S. Kennedy (chapter-1 jacket; re4gc reader target)"}


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def disc_header(head: bytes, bi2: bytes) -> dict:
    """Boot header (first 0x440 bytes) + bi2 (0x440..) -> identity, DOL/FST location and region."""
    if len(head) < 0x430 or len(bi2) < 0x1C:
        raise ValueError("disc header too short")
    if struct.unpack_from(">I", head, 0x1C)[0] != GC_MAGIC:
        raise ValueError("not a GameCube disc (magic at 0x1C)")
    dol_off, fst_off, fst_size = struct.unpack_from(">III", head, 0x420)
    region = struct.unpack_from(">I", bi2, 0x18)[0]
    return {"disc_id": head[:6].decode("ascii", "replace"), "maker": head[4:6].decode("ascii", "replace"),
            "disc_number": head[6] + 1, "version": head[7],
            "title": head[0x20:0x60].split(b"\0")[0].decode("latin-1"),
            "dol_offset": dol_off, "fst_offset": fst_off, "fst_size": fst_size,
            "region": REGIONS.get(region, f"unknown({region})")}


def udas_entries(data: bytes, endian: str = ">") -> list[dict]:
    """Bounded UDAS directory: [{type, size, offset}] (refuses tables that leave the 0x400 header or the file).

    `endian` is the field order. RE4 on GameCube/Wii writes the entries big-endian; the HD port (RE4 Switch, and the
    PC/PS4/XB1 UHD releases) writes the SAME container little-endian - identical 0xCAB6BE20 fill, identical 32-byte
    entries, identical 0xFFFFFFFF terminator inside the first 0x400 bytes (measured 2026-11-07 on
    bio4/em/em10.udas: entry 0 type 0, size 8,863,840 at 0x420, then a type-4 sound entry). One reader serves both.
    """
    if endian not in (">", "<"):
        raise ValueError(f"endian must be '>' or '<', not {endian!r}")
    out, o = [], 0x20
    word = endian + "I"
    fields = endian + "IIII"
    while True:
        if o + 4 > min(0x400, len(data)):
            raise ValueError("UDAS table has no 0xFFFFFFFF terminator inside 0x400 bytes")
        if struct.unpack_from(word, data, o)[0] == 0xFFFFFFFF:
            return out
        if o + 16 > len(data):
            raise ValueError(f"UDAS entry {len(out)} truncated")
        t, size, _zero, off = struct.unpack_from(fields, data, o)
        if off < 0x400 or off + size > len(data):
            raise ValueError(f"UDAS entry {len(out)} ({off:#x}+{size:#x}) is outside the file")
        out.append({"type": t, "size": size, "offset": off})
        o += 32


def dat_entries(data: bytes, endian: str = ">") -> list[tuple[str, int, int]]:
    """[(ext, offset, size)] for a DAT model pack; empty slots keep ext '' and size 0.

    Same little-endian variant as `udas_entries`: the HD port's DAT has the identical count/tail/offset-table/
    4-char-extension layout, with the fields byte-swapped.
    """
    if endian not in (">", "<"):
        raise ValueError(f"endian must be '>' or '<', not {endian!r}")
    if len(data) < 16:
        raise ValueError("DAT too short")
    n, tail = struct.unpack_from(endian + "II", data, 0)
    end = tail or len(data)
    if n == 0 or 16 + 8 * n > len(data) or end > len(data):
        raise ValueError(f"not a DAT pack (count {n}, tail {tail:#x}, size {len(data)})")
    offs = list(struct.unpack_from(f"{endian}{n}I", data, 16))
    exts = [data[16 + 4 * n + 4 * i:20 + 4 * n + 4 * i].rstrip(b"\0").decode("latin-1") for i in range(n)]
    out = []
    for i in range(n):
        if not exts[i]:
            out.append(("", offs[i], 0))
            continue
        nxt = next((o for o in offs[i + 1:] if o >= offs[i]), end)
        if offs[i] > end or nxt > end:
            raise ValueError(f"DAT entry {i} runs past the data")
        out.append((exts[i], offs[i], nxt - offs[i]))
    return out


def bin_slots(data: bytes, endian: str = "<") -> list[dict]:
    """The BIN slots of a pack, in DAT order: [{bin, slot, offset, size}] with `offset` inside the pack file.

    `bin` is the position among the BIN slots (what the decrypt lab's `entry` names) and `slot` is the DAT index
    (what the slot tables use) - the two differ because a pack interleaves BIN with EFF/TPL/FCV.
    """
    ents = udas_entries(data, endian)
    dat = next((e for e in ents if e["type"] == 0), None)
    if dat is None:
        raise ValueError("this pack has no DAT entry")
    blob = data[dat["offset"]:dat["offset"] + dat["size"]]
    out = []
    for slot, (ext, off, size) in enumerate(dat_entries(blob, endian)):
        if ext == "BIN":
            out.append({"bin": len(out), "slot": slot, "offset": dat["offset"] + off, "size": size})
    return out


def pack_patch(data: bytes, bin_index: int, replacement: bytes, endian: str = "<") -> bytes:
    """One BIN slot replaced in place, everything else byte-for-byte as it was.

    This is the safe writer for these packs, and it is the same rule the GameCube work paid for: a replacement must be
    **exactly the slot's size** (a shorter file leaves the original tail readable and the game draws the ORIGINAL out of
    it, a longer one overwrites the next slot). Pad the replacement first - `re4hd_models.pad_to` does that - and the
    patch only touches the bytes the slot owns.

    Rewriting the DAT/UDAS tables is deliberately NOT done here: real packs leave 960 B before the first entry, up to
    18 KB between entries and trailing bytes after the last, so a table rebuild has to reproduce all of that to stay
    faithful. A same-size patch needs none of it.
    """
    if endian not in (">", "<"):
        raise ValueError(f"endian must be '>' or '<', not {endian!r}")
    slots = bin_slots(data, endian)
    if not slots:
        raise ValueError("this pack holds no BIN slot")
    if not 0 <= bin_index < len(slots):
        raise ValueError(f"this pack holds {len(slots)} BIN slot(s); #{bin_index} is out of range")
    slot = slots[bin_index]
    if len(replacement) != slot["size"]:
        raise ValueError(f"slot #{bin_index} is {slot['size']} bytes and the replacement is {len(replacement)}: "
                         f"a patch must be the slot's own size (pad it first)")
    out = bytearray(data)
    out[slot["offset"]:slot["offset"] + slot["size"]] = replacement
    return bytes(out)


def bin_header(b: bytes) -> dict:
    """Counts from a big-endian RE4 GC BIN header; refuses headers whose tables point outside the BIN."""
    if len(b) < 0x40:
        raise ValueError("BIN too short")
    hsize = struct.unpack_from(">I", b, 0)[0]
    if hsize not in (0x40, 0x60):
        raise ValueError(f"BIN header size {hsize:#x} (want 0x40 rigid or 0x60 skinned)")
    for at in (0x0C, 0x10, 0x14, 0x1C, 0x30, 0x34):
        off = struct.unpack_from(">I", b, at)[0]
        if off > len(b):
            raise ValueError(f"BIN table pointer at {at:#x} = {off:#x} beyond {len(b):#x}")
    nbones = b[0x19]
    if hsize + 16 * nbones > len(b):
        raise ValueError("BIN bone table runs past the end")
    return {"skinned": hsize == 0x60, "weights": b[0x18], "bones": nbones,
            "materials": struct.unpack_from(">H", b, 0x1A)[0], "pos_frac": b[0x28],
            "positions": struct.unpack_from(">H", b, 0x38)[0], "normals": struct.unpack_from(">H", b, 0x3A)[0]}


def tpl_images(b: bytes) -> list[dict]:
    """[{w, h, fmt}] for a GameCube TPL."""
    if len(b) < 12 or struct.unpack_from(">I", b, 0)[0] != TPL_MAGIC:
        raise ValueError("not a TPL (magic 0x0020AF30)")
    n, table = struct.unpack_from(">II", b, 4)
    if table + 8 * n > len(b):
        raise ValueError("TPL image table runs past the end")
    out = []
    for i in range(n):
        ih = struct.unpack_from(">I", b, table + 8 * i)[0]
        if ih + 12 > len(b):
            raise ValueError(f"TPL image header {i} outside the file")
        h, w, fmt, data = struct.unpack_from(">HHII", b, ih)
        if data > len(b):
            raise ValueError(f"TPL image {i} data outside the file")
        out.append({"w": w, "h": h, "fmt": GX_FORMATS.get(fmt, str(fmt))})
    return out


def pack_summary(drs: bytes, decode: bool = False, endian: str = ">") -> dict:
    """Inventory one UDAS character pack: DAT slot types, BIN meshes, TPL textures and motion entries.
    decode=True also runs re4gc_models.bin_read on every BIN (triangle counts; a decoder oracle).

    `endian` selects the edition: '>' is the GameCube/Wii pack this module was written for, '<' the HD port
    (RE4 Switch). The container layer is the same either way, so slots, sizes and motion bytes are inventoried for
    both; the PAYLOAD decoders are not. An HD BIN starts with a 0x98 header size (the GC writer knows 0x40/0x60) and
    an HD "TPL" starts with 0x12345678 (the GX TPL magic is 0x0020AF30), so those slots are reported by size with the
    reason they were not decoded instead of being parsed as if they were the GC layout.
    """
    from . import re4gc_models as R                      # noqa: F401  (numpy; only used when decode=True)
    ents = udas_entries(drs, endian)
    out = {"udas": [{"type": e["type"], "size": e["size"]} for e in ents], "meshes": [], "textures": [],
           "slots": Counter(), "motion_bytes": 0, "errors": [],
           "edition": "gamecube" if endian == ">" else "hd"}
    for e in ents:
        if e["type"] != 0:
            continue
        dat = drs[e["offset"]:e["offset"] + e["size"]]
        for i, (ext, off, size) in enumerate(dat_entries(dat, endian)):
            blob = dat[off:off + size]
            out["slots"][ext or "empty"] += 1
            try:
                if ext == "BIN":
                    if endian != ">":                    # HD BIN: header layout differs, so report it, never guess
                        out["meshes"].append({"slot": i, "size": size, "decoded": False,
                                              "header": hex(struct.unpack_from("<I", blob, 0)[0]) if len(blob) >= 4 else None})
                        continue
                    row = {"slot": i, "size": size, **bin_header(blob)}
                    if decode:
                        m = R.bin_read(blob)
                        row["triangles"] = sum(R._tri_count(x.prims) for x in m.mats)
                        npos = 0 if m.pos is None else len(m.pos)
                        if len(m.bones) != row["bones"] or npos != row["positions"]:
                            raise ValueError("bin_read disagrees with the header counts")
                    out["meshes"].append(row)
                elif ext == "TPL":
                    if endian != ">":
                        out["textures"].append({"slot": i, "size": size, "decoded": False,
                                                "magic": hex(struct.unpack_from("<I", blob, 0)[0]) if len(blob) >= 4 else None})
                        continue
                    out["textures"].append({"slot": i, "size": size, "images": tpl_images(blob)})
                elif ext in ("FCV", "SEQ"):
                    out["motion_bytes"] += size
            except (ValueError, struct.error, IndexError) as exc:
                out["errors"].append(f"slot {i} {ext}: {exc}")
    out["slots"] = dict(out["slots"])
    return out


PACK_KINDS = (("em/pl", "player/partner"), ("em/em", "enemy/NPC"), ("em/wep", "weapon"))


def pack_kind(name: str) -> str:
    return next((k for p, k in PACK_KINDS if name.startswith(p)), "other")


def motion_families(rows: list[dict]) -> list[list[str]]:
    """Group player packs that share one motion set (same FCV/SEQ slot counts and motion bytes) -- costume variants of
    one character use one animation bank, so a family is the unit a replacement must keep animating."""
    fam = defaultdict(list)
    for r in rows:
        fam[(r["slots"].get("FCV", 0), r["slots"].get("SEQ", 0), r["motion_bytes"])].append(r["file"])
    return sorted((sorted(v) for v in fam.values()), key=lambda v: v[0])


def inventory(iso: Path, source: Path | None = None, source_sha256: str | None = None, decode: bool = True) -> dict:
    from .gcdisc import GCDisc

    disc = GCDisc(iso)
    hdr = disc_header(disc._r(0, 0x440), disc._r(0x440, 0x20))
    if hdr["disc_id"] != DISC_ID:
        raise ValueError(f"{iso}: disc id {hdr['disc_id']}, expected {DISC_ID}")
    dol = disc.dol()
    dirs = defaultdict(Counter)
    sizes = Counter()
    for name, (_off, size) in disc.files.items():
        top = name.split("/", 1)[0] if "/" in name else "<root>"
        dirs[top][name.rsplit(".", 1)[-1].lower() if "." in name.rsplit("/", 1)[-1] else ""] += 1
        sizes[top] += size
    chars, others, totals, fmts = [], [], Counter(), Counter()
    for name in sorted(n for n in disc.files if n.startswith("em/") and n.endswith(".drs")):
        raw = disc.read(name)
        kind = pack_kind(name)
        player = kind == "player/partner"
        s = pack_summary(raw, decode=decode and player)
        row = {"file": name, "kind": kind, "size": len(raw), "sha256": _sha(raw), "role": KNOWN_PACKS.get(name, "unmapped"),
               "slots": s["slots"], "meshes": len(s["meshes"]), "textures": sum(len(t["images"]) for t in s["textures"]),
               "vertices": sum(m["positions"] for m in s["meshes"]),
               "max_bones": max((m["bones"] for m in s["meshes"]), default=0),
               "motion_bytes": s["motion_bytes"], "sound_entries": sum(1 for u in s["udas"] if u["type"] == 4),
               "errors": s["errors"]}
        if player:
            row["triangles"] = sum(m.get("triangles", 0) for m in s["meshes"])
            row["mesh_detail"] = s["meshes"]
            for t in s["textures"]:
                fmts.update(i["fmt"] for i in t["images"])
            chars.append(row)
        else:
            others.append(row)
        totals["packs"] += 1
        totals["errors"] += len(s["errors"])
    extra = {n: {"size": disc.files[n][1], "sha256": _sha(disc.read(n))}
             for n in sorted(disc.files) if n.startswith("etc/pl")}
    stages = sorted({n.split("/", 1)[0] for n in disc.files if n.startswith("St")})
    return {
        "game_id": next(iter(GAME_IDS)), "title": GAME_IDS[next(iter(GAME_IDS))],
        "source": {"catalog_rel_path": SOURCE_REL, "path": str(source) if source else None,
                   "sha256": source_sha256, "format": "Dolphin GCZ (zlib blocks)", "image": str(iso)},
        "disc": hdr, "files": len(disc.files),
        "dol": {"size": len(dol), "sha256": _sha(dol), "entry": hex(struct.unpack_from(">I", dol, 0xE0)[0])},
        "layout": {d: {"files": sum(c.values()), "bytes": sizes[d], "ext": dict(c)} for d, c in sorted(dirs.items())},
        "characters": chars, "motion_families": motion_families(chars), "other_packs": others,
        "other_pack_kinds": dict(Counter(r["kind"] for r in others)), "etc_player_parts": extra,
        "texture_formats": dict(fmts), "totals": dict(totals),
        "launch": {"core": "dolphin (catalog runtimes retroarch/dolphin, rocketlauncher windows-node)",
                   "disc_swap": f"Disc 1 holds {', '.join(stages)}; no St3 archives, so play past Disc 1 needs the "
                                "separately owned Disc 2 image",
                   "mod_base": "filemods.gcz_to_iso -> cache/modbase/<game_id>/<stem>.iso; mods are copies "
                               "(filemods.build_image), the GCZ stays untouched"},
    }


SWITCH_TITLE = "010099A00BC1E000"                 # RE4 Switch (Mercenaries edition, gbox.re_switch)


def switch_inventory(root: Path, *, limit: int = 0) -> dict:
    """Inventory an extracted RE4-Switch RomFS tree (bio4/em/*.udas) with the same readers the GC disc uses.

    The HD port keeps the GameCube era tree (`bio4/em`, `bio4/st1..st4`, `bio4/ss`) and the same UDAS/DAT containers,
    only little-endian, so the pack/entry layer is shared and the only thing that has to be per-edition is the payload
    decoder. This is the listing half of the pipeline for this title: what each pack holds, by slot, before any
    writer exists - the same first step the GC work started from.
    """
    root = Path(root)
    em = root / "bio4" / "em"
    if not em.is_dir():
        raise ValueError(f"not an RE4 Switch RomFS tree (no bio4/em under {root})")
    packs = sorted(p for p in em.glob("*.udas") if p.is_file())
    if limit:
        packs = packs[:limit]
    rows, totals, fmts = [], Counter(), Counter()
    for path in packs:
        raw = path.read_bytes()
        name = f"em/{path.name}"
        s = pack_summary(raw, decode=False, endian="<")
        row = {"file": name, "kind": pack_kind(name), "size": len(raw), "sha256": _sha(raw),
               "slots": s["slots"], "meshes": len(s["meshes"]), "textures": len(s["textures"]),
               "motion_bytes": s["motion_bytes"],
               "sound_entries": sum(1 for u in s["udas"] if u["type"] == 4),
               "payload_decoded": False, "errors": s["errors"]}
        rows.append(row)
        totals["packs"] += 1
        totals["bytes"] += len(raw)
        totals["errors"] += len(s["errors"])
        for m in s["meshes"]:
            fmts[m.get("header") or "unknown"] += 1
    return {"title_id": SWITCH_TITLE, "root": str(root), "edition": "hd",
            "container": "UDAS little-endian (same 32-byte entries as the GC disc, byte-swapped)",
            "packs": rows, "pack_count": len(rows), "totals": dict(totals),
            "bin_header_sizes": dict(fmts),
            "payload_note": "slots are listed and sized; the HD BIN header (0x98) and HD TPL magic (0x12345678) are "
                            "not the GC payload layouts, so no mesh or texture is decoded yet",
            "next": "decode the HD BIN (0x98 header) to reuse rig_roles/re4gc_zombies for this title"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="RE4 GC (G4BE08) owned-disc inventory manifest")
    ap.add_argument("iso", type=Path, nargs="?")
    ap.add_argument("--source", type=Path)
    ap.add_argument("--source-sha256")
    ap.add_argument("--switch-romfs", type=Path, help="an extracted RE4 Switch RomFS tree (bio4/em/*.udas)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    if a.switch_romfs:
        m = switch_inventory(a.switch_romfs, limit=a.limit)
    elif a.iso:
        m = inventory(a.iso, a.source, a.source_sha256)
    else:
        ap.error("give an iso, or --switch-romfs for the HD port")
    text = json.dumps(m, indent=1)
    if a.out:
        a.out.write_text(text)
    else:
        sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
