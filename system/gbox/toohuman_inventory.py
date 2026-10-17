"""Too Human (Xbox 360) inventory manifest.

Silicon Knights' 2008 action-RPG. The owned disc is an XDVDFS image whose assets
are almost entirely gzip-wrapped ``.zzz`` archives (magic ``f00dcafe``), one per
character/weapon/stage, plus Wwise ``.bnk`` sound banks, Anark Gameface ``.bgf`` UI
scenes, XMA2 ``.xma`` audio and CSV ``DataTables`` for armor/weapon tables.

This module reuses ``gbox.re6.XDVD`` (platform-generic XDVDFS/Xbox-360 reader) and
stops at the inventory boundary: it enumerates every file, identifies the exact
build (default.xex), and classifies the character/mesh/texture/animation asset
families by name. It does NOT parse the ``f00dcafe`` container payload yet — that
is the analysis stage (the zzz header fields at +0x08/+0x0c/+0x10/+0x14 are
unresolved hash/offset tables, to be pinned from Ghidra xrefs on the executable).

CLI:  python -m gbox.toohuman_inventory ISO [--out m.json] [--source-sha256 HEX]

Pure stdlib plus gbox.re6 (XDVD reader); no numpy/PIL.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import struct
from collections import Counter, defaultdict
from pathlib import Path

from . import re6

XEX_MAGIC = b"XEX2"
ZZZ_MAGIC = b"\xf0\x0d\xca\xfe"          # Silicon Knights zzz container, gzip-wrapped
EXECUTION_INFO_KEY = 0x00040006  # XEX2 optional execution-info record

# Root-level character asset naming (the character models are single .zzz.gz files
# at the disc root, not inside an archive table).
PLAYER = re.compile(r"^/pla001\.zzz\.gz$", re.I)           # Baldur (player) base model
PLAYER_VARIANT = re.compile(r"^/pla001_", re.I)            # class bodies (e.g. pla001_assault)
AUG = re.compile(r"^/pla001_aug_", re.I)                   # cybernetic armor pieces
GOD = re.compile(r"^/god\d+", re.I)                         # Aesir gods
ENEMY = re.compile(r"^/enm\d+", re.I)                       # enemy classes
NPC = re.compile(r"^/npc\d+", re.I)                         # non-player characters
MONSTER = re.compile(r"^/mon\d+", re.I)                     # bosses/monsters
WEAPON = re.compile(r"^/wep\d+", re.I)                      # weapon models
AUG = re.compile(r"^/pla001_aug_", re.I)                    # cybernetic armor pieces
TEX_GROUP = re.compile(r"\.g\d{2}\.gz$", re.I)              # zzzgroup texture groups (g00-g49)
TEX_ZZZ = re.compile(r"_tex\.zzz\.gz$", re.I)               # per-asset texture zzz
BANK = re.compile(r"\.bnk$", re.I)                          # Wwise sound banks (audio, not models)
BGF = re.compile(r"\.bgf$", re.I)                           # Anark Gameface UI scenes
XMA = re.compile(r"\.xma$", re.I)                           # XMA2 audio


def xex_info(data: bytes) -> dict:
    """Read big-endian XEX2 identity and its pointed-to execution-info record.

    Layout: xenia-project/xenia src/xenia/kernel/util/xex2_info.h.
    """
    if len(data) < 24 or data[:4] != XEX_MAGIC:
        raise ValueError("not a complete XEX2 header")
    mod_flags, header_size = struct.unpack_from(">II", data, 4)
    count = struct.unpack_from(">I", data, 20)[0]
    table_end = 24 + 8 * count
    if not table_end <= header_size <= len(data):
        raise ValueError("XEX2 optional header table outside header")
    title_id, tid_off = None, -1
    for at in range(24, table_end, 8):
        key, offset = struct.unpack_from(">II", data, at)
        if key != EXECUTION_INFO_KEY:
            continue
        if offset < table_end or offset + 24 > header_size:
            raise ValueError("XEX2 execution info outside header")
        tid_off = offset + 12
        title_id = struct.unpack_from(">I", data, tid_off)[0]
        break
    build = None
    for m in re.finditer(rb"[\x20-\x7e]{8,}", data[:0x8000]):
        s = m.group().decode("ascii", "replace")
        if re.search(r"(TH1|TooHuman|Too Human|SK[_-])", s):
            build = s
            break
    return {
        "magic": "XEX2",
        "module_flags": f"{mod_flags:#x}",
        "header_size": f"{header_size:#x}",
        "title_id": f"{title_id:#010x}" if title_id else None,
        "title_id_offset": tid_off,
        "build_string": build,
        "size": len(data),
    }


def classify(files: dict) -> dict:
    """Group root-level .zzz.gz assets into character families and count the rest."""
    fam: dict[str, list[str]] = defaultdict(list)
    for p in files:
        n = p.rsplit("/", 1)[-1]
        if not p.endswith(".zzz.gz"):
            continue
        if p.count("/") != 1:                       # character assets live at the disc root
            continue
        if AUG.match(p):
            fam["player_armor"].append(n)
        elif PLAYER.match(p):
            fam["player_pla001"].append(n)
        elif PLAYER_VARIANT.match(p):
            fam["player_variants"].append(n)
        elif GOD.match(p):
            fam["gods"].append(n)
        elif MONSTER.match(p):
            fam["monsters"].append(n)
        elif ENEMY.match(p):
            fam["enemies"].append(n)
        elif NPC.match(p):
            fam["npcs"].append(n)
        elif WEAPON.match(p):
            fam["weapons"].append(n)
        else:
            fam["other_root_zzz"].append(n)
    return {k: sorted(v) for k, v in fam.items()}


def sample_zzz_headers(xdvd: re6.XDVD, paths: list[str]) -> list:
    """Decompress a few small zzz archives via cheap reads to confirm the f00dcafe
    container magic and report the header fields (magic, version word, and the three
    u32s that follow — candidates for the entry/hash table, unresolved at inventory)."""
    out = []
    for p in paths:
        off, size = xdvd.files[p]
        xdvd.f.seek(off)
        raw = xdvd.f.read(size)
        try:
            dec = gzip.decompress(raw)
        except (OSError, EOFError) as e:
            out.append({"path": p.rsplit("/", 1)[-1], "error": f"gzip: {e}"})
            continue
        magic = dec[:4]
        if len(dec) < 0x18:
            out.append({"path": p.rsplit("/", 1)[-1], "magic": magic.hex(), "error": "short header"})
            continue
        ver, a, b, c, d = struct.unpack_from("<IIIII", dec, 4)
        out.append({
            "path": p.rsplit("/", 1)[-1],
            "magic": magic.hex(),
            "version_word": f"{ver:#010x}",
            "u32_08": f"{a:#x}", "u32_0c": f"{b:#x}", "u32_10": f"{c:#x}", "u32_14": f"{d:#x}",
            "raw_size": size, "dec_size": len(dec),
        })
    return out


def inventory(iso, source_sha256: str | None = None) -> dict:
    iso = str(iso)
    disc = re6.XDVD(iso)
    try:
        files = disc.files
        xex_path = next(p for p in files if p.lower() == "/default.xex")
        xex = disc.read(xex_path)
        top = Counter(p.split("/", 2)[1] if p.count("/") >= 1 else "(root)" for p in files)
        exts = Counter(p.rsplit(".", 1)[-1].lower() if "." in p else "(none)" for p in files)
        fam = classify(files)
        samples = sample_zzz_headers(disc, [
            "/contents.zzz.gz", "/Characters.zzz.gz", "/engine.zzz.gz",
            "/pla001.zzz.gz", "/god014.zzz.gz",
        ])
        man = {
            "game": "Too Human",
            "platform": "xbox360",
            "game_id": "803022fa46bf058a",
            "engine": "Silicon Knights (TH1) + Anark Gameface UI + Wwise audio",
            "source": {"path": iso, "size": Path(iso).stat().st_size, "sha256": source_sha256},
            "executable": {"path": "/default.xex", "sha256": hashlib.sha256(xex).hexdigest(), **xex_info(xex)},
            "disc": {"partition": disc.part, "files": len(files), "bytes": sum(n for _, n in files.values()),
                     "top_dirs": dict(top), "extensions": dict(exts)},
            "assets": {
                "container": "XDVDFS -> .zzz (magic f00dcafe) gzip-wrapped, one file per character/weapon/stage",
                "character_families": {k: len(v) for k, v in fam.items()},
                "character_roster": {k: v for k, v in fam.items() if k not in ("other_root_zzz",)},
                "texture_groups": sum(1 for p in files if TEX_GROUP.search(p)),
                "per_asset_tex": sum(1 for p in files if TEX_ZZZ.search(p)),
                "wwise_banks": sum(1 for p in files if BANK.search(p)),
                "anark_bgf": sum(1 for p in files if BGF.search(p)),
                "xma_audio": sum(1 for p in files if XMA.search(p)),
                "sample_zzz_headers": samples,
            },
            "launch": {
                "emulator": "Xenia (canary)",
                "boot": "extracted folder with default.xex at root",
                "base_extraction": "gbox.re6.ensure_base (XDVD extract, resumable)",
                "note": "core currently unset in catalog (xbox360); launch acceptance needs a Xenia worker",
            },
        }
        return man
    finally:
        disc.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Too Human (Xbox 360) inventory manifest")
    ap.add_argument("iso", help="owned disc image (.iso)")
    ap.add_argument("--out", default="toohuman_inventory.json", help="manifest output path")
    ap.add_argument("--source-sha256", default=None, help="sha256 of the source image, if precomputed")
    args = ap.parse_args(argv)
    man = inventory(args.iso, args.source_sha256)
    Path(args.out).write_text(json.dumps(man, indent=1))
    print(json.dumps({k: man[k] for k in ("game", "engine", "executable", "disc")}, indent=1))
    print(json.dumps(man["assets"]["character_families"], indent=1))
    print(f"manifest -> {args.out}")


if __name__ == "__main__":
    main()
