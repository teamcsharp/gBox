"""Dedicated character extractor for 007 - Nightfire (USA) GameCube (#1377).

Decompresses a level EDL database, reads its 0x01 object meshes and the HT_Skin skeleton
(gbox.nightfire_model), and emits an editable skinned .glb: strips per material group, UVs, and
2-bone weights from the node's influence runs bound to the HT_Skin inverse bind pose (Blender import:
73 bones, 0 unweighted vertices, posing a bone moves exactly its weighted vertices).  Textures (GX
`60000017` chunks) are not decoded yet.
"""
from __future__ import annotations

from pathlib import Path

from .gcdisc import GCDisc
from .nightfire_edl import decompress
from .nightfire_model import export_glb

DEFAULT_LEVEL = "07000001"

# Known human-ish type-2 objects discovered in level 07000001; more levels will add the rest.
ROSTER = [
    {"key": "bond", "slug": "nightfire_bond", "name": "James Bond (Nightfire)",
     "aliases": ["Bond", "007", "Nightfire Bond"], "kind": "character",
     "level": DEFAULT_LEVEL, "object": "01000075", "skin": "05000007"},
    {"key": "mayhew", "slug": "nightfire_mayhew", "name": "Mayhew (Nightfire)",
     "aliases": ["Mayhew"], "kind": "character",
     "level": DEFAULT_LEVEL, "object": "01000145", "skin": "05000007"},
    {"key": "grunt", "slug": "nightfire_grunt", "name": "Generic Grunt (Nightfire)",
     "aliases": ["grunt", "Nightfire grunt"], "kind": "character",
     "level": DEFAULT_LEVEL, "object": "0100006f", "skin": "05000007"},
]


def roster() -> list[dict]:
    return [dict(r) for r in ROSTER]


def extract_run(ctx, game: dict, entry: dict, work: Path) -> dict:
    """Decompress the level named in entry['level'] and export its object+skin as a .glb."""
    from . import characters as C  # local import avoids a top-level cycle with characters.DEDICATED

    iso = C._gc_iso(ctx, game)
    disc = GCDisc(iso)
    level_path = f"gc/{entry['level']}.bin"
    edl = disc.read(level_path)
    level_data = decompress(edl)

    out = Path(work) / f"nightfire_{entry['key']}.glb"
    export_glb(level_data, str(out), entry["object"], entry["skin"])
    return {
        "files": [out],
        "tool": "gbox.nightfire_chars",
        "source_files": [level_path, f"HT_Skin {entry['skin']}", f"0x01 object {entry['object']}"],
        "notes": ("Nightfire GC mesh + HT_Skin skeleton exported as a skinned, UV-mapped .glb "
                  "(2-bone weights from the native influence runs). Textures are not decoded yet."),
    }
