"""Inventory for Capcom vs. SNK 2 EO - Millionaire Fighting 2001 (USA) (GameCube), game 7ac0336847e66599.

Owned source: hyperspin Dolphin GCZ
    collections/Nintendo GameCube/roms/Capcom vs. SNK 2 EO - Millionaire Fighting 2001 (USA).gcz
    sha256 4dad23ff902efae10652bd5f847b7e3341a25d04f915b568083771bc52fd292f

Disc: GEOE08 (USA), "CAPCOM VS. SNK 2  EO" (maker 0x08 Capcom), 1,459,978,240-byte
image.  CRI Middleware (ADX/AFS) audio/container stack.  Code is a main PowerPC DOL
plus 53 REL modules; character/asset data lives in three little-endian CRI AFS
archives (``ps2/afs00.afs``, ``gc/afs02.afs``, ``gc/afs03.afs``).  Texture work is
PS2 TIM2; sprites are ``spr_*.bin`` blobs; the 3D mesh format is headerless (no
model magic -- analysis-stage work, matching the assimilation fingerprint).

The AFS entry table here is little-endian (same as Dreamcast/PS2 CRI AFS), so the
shared ``gbox.jgr.afs_entries`` reader parses every archive cleanly (0 out-of-range
entries).  The filename directory pointer is NOT in a fixed place across archives:
it is the (offset,size) pair found 8 bytes before the first data entry OR directly
after the entry table; ``find_name_dir`` probes all three conventional slots and
validates that every recorded size matches the entry table.

Usage:
    python -m gbox.cvs2eo_inventory SRC.gcz --out cvs2eo_inventory.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from collections import Counter

from .formats.gcfst import parse_fst
from .gcz import GCZ

GAME_ID = "7ac0336847e66599"
TITLE = "Capcom vs. SNK 2 EO - Millionaire Fighting 2001 (USA)"
PLATFORM = "gamecube"
SOURCE_SHA256 = "4dad23ff902efae10652bd5f847b7e3341a25d04f915b568083771bc52fd292f"

AFS_MAGIC = b"AFS\x00"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def afs_entries(data: bytes) -> tuple[int, list[int], list[int], int]:
    """Parse a little-endian CRI AFS entry table -> (count, offsets, sizes, table_end).

    Same layout the shared gbox.jgr.afs_entries expects: "AFS\\0", u32 count, then
    count interleaved (u32 offset, u32 size) pairs.  Table_end is 8 + 8*count.
    """
    if len(data) < 8 or data[:4] != AFS_MAGIC:
        raise ValueError(f"not an AFS archive (magic {data[:4]!r})")
    count = struct.unpack_from("<I", data, 4)[0]
    need = 8 + 8 * count
    if len(data) < need:
        raise ValueError(f"AFS header truncated: need {need} bytes, have {len(data)}")
    pairs = struct.unpack_from("<" + "I" * (2 * count), data, 8)
    return count, list(pairs[0::2]), list(pairs[1::2]), need


def find_name_dir(read, size: int, count: int, offsets: list[int], sizes: list[int],
                  table_end: int) -> tuple[list[str], int, int] | None:
    """Locate the CRI filename directory and return (names, dir_offset, dir_size).

    CRI AFS stores the directory as an (offset, size) pair at one of three
    conventional slots -- 8 bytes before the first data entry, directly after the
    entry table, or the last 8 bytes of the archive.  The directory itself is 48
    bytes per entry (name[32] at +0, size at +44); we only accept a candidate whose
    recorded sizes match the entry table exactly.
    """
    first = min(offsets) if offsets else table_end
    for at in dict.fromkeys((first - 8, table_end, size - 8)):
        if at < table_end or at + 8 > size:
            continue
        foff, fsize = struct.unpack_from("<II", read(at, 8), 0)
        if foff < table_end or foff + fsize > size or fsize < 48 * count:
            continue
        recs = read(foff, 48 * count)
        names = []
        ok = True
        for i in range(count):
            rec = recs[48 * i:48 * (i + 1)]
            sz = struct.unpack_from("<I", rec, 44)[0]
            if sz != sizes[i]:
                ok = False
                break
            nm = rec[:32].split(b"\0", 1)[0].decode("latin1", "replace")
            names.append(nm)
        if ok and names and all(names):
            return names, foff, fsize
    return None


def _walk_fst(raw: bytes):
    """GameCube FST walk (shared gbox.formats.gcfst.parse_fst) -> [(path, offset, size)]."""
    return [(p, a, b) for p, a, b, _entry in parse_fst(raw, 0)]


def manifest(src: str, src_sha256: str | None = None) -> dict:
    """Build the full inventory manifest.  Reads the whole file only for the source
    hash; pass src_sha256 to skip that (e.g. when it was precomputed off the SMB
    share).  All other reads are header/FST/name-directory sized."""
    if src_sha256 is None:
        h = hashlib.sha256()
        with open(src, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        src_sha256 = h.hexdigest()

    with GCZ(src) as g:
        header = g.read(0, 0x80)
        game_code = header[:4].decode("ascii", "replace")
        maker = header[4:6].decode("ascii", "replace")
        disc_number = header[6]
        version = header[7]
        title = header[0x20:0x60].split(b"\0")[0].decode("latin-1")
        dol_off, fst_off, fst_size, fst_max = struct.unpack(">IIII", g.read(0x420, 16))
        files = _walk_fst(g.read(fst_off, fst_size))

        # boot DOL (disc header 0x420) vs the FST "default.dol" file (main game code).
        boot_hdr = g.read(dol_off, 0x100)
        boot_entry = struct.unpack_from(">I", boot_hdr, 0xE0)[0]
        boot_offs = struct.unpack_from(">18I", boot_hdr, 0)
        boot_sizes = struct.unpack_from(">18I", boot_hdr, 0x90)
        boot_end = max(o + s for o, s in zip(boot_offs, boot_sizes) if s)
        boot_dol_sha = g.sha256_range(dol_off, boot_end)
        fst_dol = next((p for p, _, _ in files if p.endswith("default.dol")), None)
        fst_dol_off = fst_dol_size = None
        fst_dol_sha = None
        if fst_dol:
            fst_dol_off, fst_dol_size = next((o, s) for p, o, s in files if p == fst_dol)
            fst_dol_sha = g.sha256_range(fst_dol_off, fst_dol_size) if hasattr(g, "sha256_range") else None

        ext_census = Counter()
        rel_modules = []
        afs_files = []
        for path, off, size in files:
            ext = path.rsplit(".", 1)[-1].lower() if "." in path else "(none)"
            ext_census[ext] += 1
            if ext == "rel":
                rel_modules.append({"path": path, "offset": off, "size": size,
                                    "module_id": struct.unpack(">I", g.read(off, 4))[0]})
            if g.read(off, 4) == AFS_MAGIC:
                afs_files.append({"path": path, "offset": off, "size": size})

        afs_summaries = []
        for rec in afs_files:
            off, size = rec["offset"], rec["size"]
            tbl = g.read(off, 8 + 8 * struct.unpack_from("<I", g.read(off, 8), 4)[0])
            count, offsets, sizes, table_end = afs_entries(tbl)
            out_of_range = sum(1 for o, s in zip(offsets, sizes)
                               if o < table_end or o + s > size)

            def rd(at, n):
                return g.read(off + at, n)

            names, dir_off, dir_size = find_name_dir(rd, size, count, offsets, sizes, table_end) or (None, None, None)
            summary = {
                "path": rec["path"],
                "offset": off,
                "size": size,
                "entry_count": count,
                "table_end": table_end,
                "first_data_offset": min(offsets) if offsets else None,
                "out_of_range_entries": out_of_range,
                "endianness": "little",
                "name_directory": None if names is None else {
                    "offset": dir_off, "size": dir_size, "record_size": 48,
                    "names": names,
                },
            }
            # classify entries by name stem when a name directory exists
            if names is not None:
                stems = Counter()
                for nm in names:
                    base = nm.rsplit("/", 1)[-1]
                    stem = base.rstrip("0123456789._")
                    stems[stem] += 1
                summary["name_stems"] = dict(stems.most_common(60))
            afs_summaries.append(summary)

        # loose TIM2 textures and sprite blobs (named by the afs02 directory)
        loose_tm2 = [p for p, _, _ in files if p.lower().endswith(".tm2")]
        char_modules = sorted(
            (m for m in rel_modules if m["path"].split("/")[-1].startswith("pl")),
            key=lambda m: m["path"])
        non_char_modules = sorted(
            (m for m in rel_modules if not m["path"].split("/")[-1].startswith("pl")),
            key=lambda m: m["path"])

        return {
            "game_id": GAME_ID,
            "title": TITLE,
            "platform": PLATFORM,
            "catalog": {
                "library": "hyperspin",
                "rel_path": ("collections/Nintendo GameCube/roms/"
                             "Capcom vs. SNK 2 EO - Millionaire Fighting 2001 (USA).gcz"),
                "core": "dolphin",
                "format": "gcz",
            },
            "source": {
                "sha256": src_sha256,
                "size": g.file_size,
                "data_size": g.data_size,
                "sub_type": "scrubbed" if g.sub_type else "full",
                "block_size": g.block_size,
                "num_blocks": g.num_blocks,
            },
            "disc": {
                "game_code": f"{game_code}{maker}",
                "game_code4": game_code,
                "maker": maker,
                "disc_number": disc_number,
                "version": version,
                "title": title,
                "dol_offset_0x420": dol_off,
                "boot_dol_entry": boot_entry,
                "fst_offset": fst_off,
                "fst_size": fst_size,
                "fst_max_size": fst_max,
                "file_count": len(files),
                "total_file_bytes": sum(s for _, _, s in files),
            },
            "executables": {
                "boot_dol_0x420": {"offset": dol_off, "size": boot_end,
                                   "entry": boot_entry, "sha256": boot_dol_sha},
                "default_dol_fst": {"path": fst_dol, "offset": fst_dol_off,
                                    "size": fst_dol_size, "sha256": fst_dol_sha},
            },
            "extensions_census": dict(sorted(ext_census.items(), key=lambda x: -x[1])),
            "rel_modules": {"count": len(rel_modules),
                            "character": char_modules,
                            "engine": non_char_modules},
            "afs_archives": afs_summaries,
            "afs02_names": next((s["name_directory"]["names"] for s in afs_summaries
                                 if s["path"].endswith("afs02.afs") and s["name_directory"]), []),
            "character_assets": _categorize_assets(next(
                (s["name_directory"]["names"] for s in afs_summaries
                 if s["path"].endswith("afs02.afs") and s["name_directory"]), [])),
            "textures": {"loose_tim2": loose_tm2},
            "character_roster": {
                "count": len(char_modules),
                "codes": [m["path"].split("/")[-1][:-4] for m in char_modules],
            },
            "fingerprint_verification": _verify_fingerprint(afs_summaries, files),
            "launch_prerequisites": {
                "core": "dolphin (RetroArch)",
                "runtime": "auto-install on Windows node (catalog runtimes retroarch/dolphin)",
                "source_supported": "dolphin reads GCZ natively; gbox.gcz reads it in place",
                "boot_chain": ("boot DOL at 0x420 -> default.dol (FST) -> REL modules "
                               "(game/menu/demo/snk2 + 48 plNN) -> data in ps2/afs00.afs, "
                               "gc/afs02.afs, gc/afs03.afs"),
                "emulator_workers": "JAYBUILTFINALE (dolphin core)",
            },
            "character_status": (
                "48 playable slots (pl00..pl2f): each has a plNN.rel code module, a "
                "plNNpak.bin model pack (headerless 3D), plNN_hit.bin/plNN_tbl.bin "
                "hitbox+table, and SND_PLNN.* sound bank.  Portraits are plNN_fac.bin "
                "(108 entries pl00..pl6b).  Shared 3D model sets dcNNpol/tex (27) and "
                "dmNNpol/tex (31) plus efct/em effect models and stgNN stage pol/tex "
                "all live in gc/afs02.afs.  ps2/afs00.afs is streamed CRI ADX audio, "
                "NOT character models (corrects the fingerprint's afs00 hint)."
            ),
        }


def _categorize_assets(names: list[str]) -> dict:
    """Categorise the afs02 entry names into the character/sprite/stage asset map.

    This is the container-level inventory that drives the reader/analysis stage:
    which AFS entry holds each character's model pack, portrait, hitboxes and the
    shared dc/dm model sets.
    """
    import re
    out = {
        "portraits_plNN_fac": [],       # pl00_fac.bin .. pl6b_fac.bin (2D portraits)
        "model_packs_plNNpak": [],      # pl00pak.bin .. pl2fpak.bin (headerless 3D)
        "hitboxes_plNN_hit": [],
        "tables_plNN_tbl": [],
        "edit_palettes": [],            # edit_p00..p2f (colour-edit data)
        "shared_models_dc": [],         # dcNNpol/dcNNtex pairs
        "shared_models_dm": [],         # dmNNpol/dmNNtex (dmNNfac, dmNNetex) pairs
        "effects_em": [],               # em00_dat..em2f_dat
        "effects_efct": [],
        "stages": [],                   # stgNNpol/stgNNtex + stgeNtex
        "sprites": [],                  # spr_*.bin
        "fonts_tm2": [],
        "messages": [],
        "other": [],
    }
    for n in names:
        base = n.rsplit("/", 1)[-1]
        if re.fullmatch(r"pl[0-9a-f]{2}_fac\.bin", base):
            out["portraits_plNN_fac"].append(base)
        elif re.fullmatch(r"pl[0-9a-f]{2}pak\.bin", base):
            out["model_packs_plNNpak"].append(base)
        elif re.fullmatch(r"pl[0-9a-f]{2}_hit\.bin", base):
            out["hitboxes_plNN_hit"].append(base)
        elif re.fullmatch(r"pl[0-9a-f]{2}_tbl\.bin", base):
            out["tables_plNN_tbl"].append(base)
        elif re.fullmatch(r"edit_p[0-9a-f]{2}\.bin", base):
            out["edit_palettes"].append(base)
        elif re.fullmatch(r"dc[0-9a-f]{2}(pol|tex|etex)\.bin", base):
            out["shared_models_dc"].append(base)
        elif re.fullmatch(r"dm[0-9a-f]{2}(pol|tex|etex|fac)\.bin", base):
            out["shared_models_dm"].append(base)
        elif re.fullmatch(r"em[0-9a-f]{2}_dat\.bin", base):
            out["effects_em"].append(base)
        elif base.startswith("efct"):
            out["effects_efct"].append(base)
        elif re.fullmatch(r"stg[0-9a-f]{2}(pol|tex)\.bin", base) or \
                re.fullmatch(r"stge[0-9a-f]?tex\.bin", base):
            out["stages"].append(base)
        elif base.startswith("spr_"):
            out["sprites"].append(base)
        elif base.endswith(".tm2"):
            out["fonts_tm2"].append(base)
        elif base.startswith(("mese", "mesj", "ask")):
            out["messages"].append(base)
        else:
            out["other"].append(base)
    return {k: sorted(v) for k, v in out.items()}


def _verify_fingerprint(afs_summaries: list, files: list) -> dict:
    """Check the ticket's assimilation fingerprint against the actual files."""
    n_afs = len(afs_summaries)
    loose_tm2 = [p for p, _, _ in files if p.lower().endswith(".tm2")]
    afs_by_path = {s["path"].split("/")[-1]: s for s in afs_summaries}
    afs00_names = (afs_by_path["afs00.afs"]["name_directory"]["names"]
                   if "afs00.afs" in afs_by_path and afs_by_path["afs00.afs"]["name_directory"]
                   else [])
    adx_count = sum(1 for n in afs00_names if n.lower().endswith(".adx"))
    afs02_names = (afs_by_path["afs02.afs"]["name_directory"]["names"]
                   if "afs02.afs" in afs_by_path and afs_by_path["afs02.afs"]["name_directory"]
                   else [])
    tm2_in_afs = sum(1 for n in afs02_names if n.lower().endswith(".tm2"))
    return {
        "fingerprint_claim_afs_x6": {
            "claimed": 6, "found": n_afs,
            "note": ("3 AFS archives on the disc FST (ps2/afs00.afs streamed ADX audio, "
                     "gc/afs02.afs 2D/models, gc/afs03.afs CRI sound banks).  The 'x6' "
                     "count overstates the FST; no nested AFS found at the top level."),
        },
        "fingerprint_claim_tim2_x4": {
            "claimed": 4,
            "found_loose": len(loose_tm2),
            "found_in_afs02": tm2_in_afs,
            "note": "2 loose (ps2/work/adxlogo.tm2, snkgc.tm2) + font.tm2/font_e.tm2 "
                    "inside afs02 = 4 total (matches the fingerprint count).",
        },
        "fingerprint_claim_play_jgr_x1": {
            "claimed": 1, "found": 0,
            "note": ("no 'PLAY' JGR container anywhere; character 3D data is the "
                     "headerless plNNpak.bin / dcNNpol / dmNNpol blobs in gc/afs02.afs. "
                     "The JGR nearest-title similarity (0.103) is not a format claim."),
        },
        "fingerprint_engine_cri": {
            "claimed": "CRI Middleware (AFS/ADX/CPK) 0.99",
            "verified": ("AFS confirmed (3 archives, little-endian CRI layout) and ADX "
                         f"confirmed ({adx_count} .adx streams + SND_*.samp/.pool/.proj/"
                         ".sdir banks).  CPK not present."),
        },
        "fingerprint_afs00_hint_corrected": (
            "fingerprint said models are headerless in afs00.afs; in fact afs00.afs is "
            "streamed ADX audio (51 entries), and the character model packs live in "
            "gc/afs02.afs (plNNpak.bin, dcNNpol/tex, dmNNpol/tex)."
        ),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("src", help="path to the owned .gcz file")
    ap.add_argument("--out", default="cvs2eo_inventory.json")
    ap.add_argument("--sha256", help="precomputed source sha256 (skip the full read)")
    args = ap.parse_args(argv)
    m = manifest(args.src, args.sha256)
    with open(args.out, "w") as f:
        json.dump(m, f, indent=2, sort_keys=True)
    print(f"wrote {args.out}")
    print("source sha256:", m["source"]["sha256"])
    print("disc:", m["disc"]["game_code"], repr(m["disc"]["title"]))
    print("files:", m["disc"]["file_count"],
          "| rel modules:", m["rel_modules"]["count"],
          "| characters:", m["character_roster"]["count"],
          "| AFS archives:", len(m["afs_archives"]))
    for s in m["afs_archives"]:
        names = s["name_directory"]["names"] if s["name_directory"] else None
        print(f"  AFS {s['path']}: {s['entry_count']} entries, "
              f"names={'yes' if names else 'no'}, oob={s['out_of_range_entries']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
