"""Legacy of Kain: Blood Omen 2 (GameCube, US GO2E4F) owned-disc inventory.

Resolves the owned build (the HyperSpin Dolphin GCZ image), verifies the platform label
against the disc header, hashes the executables, and enumerates the character / model /
texture / animation inventory.  Read-only on the source image; ``source_sha256`` is the
canonical owned-source identity reused across every later stage.

Engine: Crystal Dynamics' GOE ("Gex Object Engine") — the ``.bgg`` files open with the
``0xFF "goefile\\0"`` magic and a ``symlist`` section, and ``kain.react`` carries the
``Copyright (C) Crystal Dynamics Inc.`` banner.  Same engine family as Soul Reaver 2.

Disc layout (FST, 213 files):
  - boot: ``main.dol`` is NOT in the FST — it lives at the disc header's ``dol_offset``
    (0x1EC00), a 4 MB engine binary (entry 0x80003140).  ``bink.rel`` is the Bink REL.
  - code:  ``gogames/bo2/code.bgg`` (392 KB) and ``precode.bgg`` (53 KB) are the game /
    bootstrap code, packed as GOE ``goefile`` containers.
  - vault: ``gogames/bo2/gamecube.rkv`` (463 MB) — serialized named-entry vault holding the
    ``assets/etypes/*`` entity types (referenced by ``assets/etypes/list.txt`` virtual paths)
    plus audio streams (``streams/wav/STR_*``).
  - levels: 179 ``.bgg`` level/region geometry files under ``resources/levels/``.
  - characters: ``resources/levels/kain/{kain,kainc,kaind,kaine,kainf}.bgg`` are the player
    (Kain) model/animation packs; the NPC/enemy roster is the ``.etp`` entity types listed in
    ``assets/etypes/list.txt`` (``characters/`` subtree) and stored inside ``gamecube.rkv``.
  - animation: 18 ``.san`` cutscene/level animation files.
  - video: 10 Bink ``.bik``; banner ``opening.bnr``; config ``game.erg`` / reactions ``.react``.

``python -m gbox.bo2_inventory GCZ --source-sha256 SHA --out manifest.json`` writes the manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from collections import Counter
from pathlib import Path

DISC_ID = "GO2E4F"
GAME_ID = "af354bb8263e7b32"
TITLE = "Legacy of Kain, The - Blood Omen 2 (USA)"
SOURCE_REL = "collections/Nintendo GameCube/roms/Legacy of Kain, The - Blood Omen 2 (USA).gcz"
# Canonical owned-source identity (Dolphin GCZ); recorded once, reused across stages.
SOURCE_SHA256 = "e58b3490f052aae91ce9b4ecc29d23ecc39ae6db53c7d6c81822671f77f05672"
GOEFILE_MAGIC = b"\xffgoefile\x00"

KAIN_PACKS = ("kain.bgg", "kainc.bgg", "kaind.bgg", "kaine.bgg", "kainf.bgg")
KAIN_DIR = "gogames/bo2/resources/levels/kain/"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def goefile_names(data: bytes, limit: int = 1 << 16) -> list[str]:
    """NUL-terminated ASCII names that follow a 0xFF tag byte inside the first `limit` bytes of a
    GOE ``goefile`` container — the section vocabulary (``goefile``, ``symlist``, ``default``, ...).
    Bounded and best-effort: the full chunk grammar is analysis-stage work."""
    out, seen = [], set()
    for i in range(min(limit, len(data)) - 1):
        if data[i] != 0xFF:
            continue
        j = i + 1
        if j >= len(data) or not (0x21 <= data[j] < 0x7F):
            continue
        end = data.find(b"\x00", j, min(len(data), limit, j + 64))
        if end == -1 or end - j > 63:
            continue
        if not all(0x21 <= byte < 0x7f for byte in data[j:end]):
            continue
        name = data[j:end].decode("ascii")
        if len(name) >= 3 and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def character_etypes(list_txt: bytes) -> dict:
    """Parse ``assets/etypes/list.txt`` into the character roster.  Only the ``characters/`` subtree
    is counted; ``+name.etp`` entries are animation-only libraries, not actors.  ``*common*`` /
    ``*proto*`` leaves are shared prototypes and ``*actor`` leaves are actor wrappers, both excluded
    from the primary-actor count.  Returns {categories: {cat: [leaves]}, actor_count: int}."""
    paths = [l.strip() for l in list_txt.decode("latin-1", "replace").splitlines() if l.strip()]
    chars: dict[str, list[str]] = {}
    primary = 0
    for p in paths:
        if "/characters/" not in p:
            continue
        rest = p.split("/characters/", 1)[1]
        leaf = Path(rest).name
        if not leaf.endswith(".etp") or leaf.startswith("+"):
            continue
        cat = rest.split("/", 1)[0] if "/" in rest else "root"
        name = leaf[:-4]
        if name in chars.setdefault(cat, []):
            continue
        chars[cat].append(name)
        low = name.lower()
        if not ("common" in low or "proto" in low or low.endswith("actor")):
            primary += 1
    for v in chars.values():
        v.sort()
    return {"categories": dict(sorted(chars.items())), "actor_count": primary}


def _kind(name: str) -> str:
    n = name.lower()
    if n.endswith(".bgg"):
        return "goefile"
    if n.endswith(".san"):
        return "animation"
    if n.endswith(".bik"):
        return "video"
    if n.endswith(".rkv"):
        return "vault"
    if n.endswith((".rel", ".dol")):
        return "executable"
    if n.endswith((".react", ".erg", ".txt")):
        return "text"
    if n.endswith(".bnr"):
        return "banner"
    return "other"


def inventory(gcz: Path, source_sha256: str | None = None, source_path: str | None = None) -> dict:
    from .gcdisc import GCDisc

    disc = GCDisc(gcz)
    if disc.game_id != DISC_ID:
        raise ValueError(f"{gcz}: disc id {disc.game_id}, expected {DISC_ID}")

    dol = disc.dol()
    code_bgg = disc.read("gogames/bo2/code.bgg")
    precode_bgg = disc.read("gogames/bo2/precode.bgg")

    executables = [
        {"name": "main.dol (boot, not in FST)", "size": len(dol), "sha256": _sha(dol),
         "entry": hex(struct.unpack_from(">I", dol, 0xE0)[0])},
        {"name": "gogames/bo2/code.bgg", "size": len(code_bgg), "sha256": _sha(code_bgg),
         "goefile": code_bgg.startswith(GOEFILE_MAGIC)},
        {"name": "gogames/bo2/precode.bgg", "size": len(precode_bgg), "sha256": _sha(precode_bgg),
         "goefile": precode_bgg.startswith(GOEFILE_MAGIC)},
    ]

    totals: Counter = Counter()
    sizes: Counter = Counter()
    goefile_count = 0
    for name, (_off, size) in sorted(disc.files.items()):
        totals[_kind(name)] += 1
        sizes[_kind(name)] += size

    # Kain player packs + their goefile section vocabulary.
    kain = []
    for stem in KAIN_PACKS:
        name = KAIN_DIR + stem
        if name not in disc.files:
            continue
        raw = disc.read(name)
        kain.append({"name": name, "size": len(raw), "sha256": _sha(raw),
                     "goefile": raw.startswith(GOEFILE_MAGIC),
                     "sections": goefile_names(raw)})
    goefile_count = totals["goefile"]

    list_txt = disc.read("gogames/bo2/assets/etypes/list.txt")

    return {
        "game_id": GAME_ID,
        "title": TITLE,
        "platform": "gamecube",
        "region": "USA",
        "disc_id": disc.game_id,
        "disc_title": disc.title,
        "source": {"catalog_rel_path": SOURCE_REL, "path": source_path, "sha256": source_sha256,
                   "format": "Dolphin GCZ (zlib blocks)"},
        "engine": {"name": "Crystal Dynamics GOE (Gex Object Engine)", "evidence":
                   ["0xff 'goefile\\0' magic on .bgg containers",
                    "kain.react: 'Copyright (C) Crystal Dynamics Inc.'",
                    "vocabulary: goefile/symlist + .bgg/.san/.rkv/.erg/.react/.etp"]},
        "fst_file_count": len(disc.files),
        "totals_by_kind": dict(sorted(totals.items())),
        "bytes_by_kind": dict(sorted(sizes.items())),
        "executables": executables,
        "vault": {"name": "gogames/bo2/gamecube.rkv",
                  "size": disc.files["gogames/bo2/gamecube.rkv"][1],
                  "sha256": _sha(disc.read("gogames/bo2/gamecube.rkv")),
                  "note": "serialized named-entry vault: entity types (assets/etypes/*) + audio streams"},
        "characters": {
            "player": {"kain": {"packs": kain, "reaction": "gogames/bo2/assets/etypes/kain/kain.react"}},
            "roster": character_etypes(list_txt),
        },
        "animation": {"count": totals["animation"], "bytes": sizes["animation"],
                      "note": "GOE .san skeletal-animation files (cutscene/level) under resources/animations/"},

        "launch": {"core": "dolphin", "notes": "GC disc boots under Dolphin/RetroArch-dolphin; agent tests use 2% audio"},
        "next_stage": "analysis: reverse the GOE 'goefile' chunk grammar and the .rkv vault directory "
                      "in code.bgg/main.dol (Ghidra), locate the Kain model loader",
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Blood Omen 2 (GC, GO2E4F) owned-disc inventory manifest")
    ap.add_argument("gcz", type=Path, help="the owned .gcz (or plain .iso) disc image")
    ap.add_argument("--source-sha256", default=None, help="precomputed hash of this source image")
    ap.add_argument("--source-path", default=None)
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args(argv)
    m = inventory(a.gcz, a.source_sha256, a.source_path)
    text = json.dumps(m, indent=1)
    if a.out:
        a.out.write_text(text)
        print(f"wrote {a.out}")
    else:
        sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
