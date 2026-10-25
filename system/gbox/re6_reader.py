"""RE6 reader stage: export Leon Usa (body+head+hands, LOD0) from the owned ISO to GLB.

Extracts the needed arcs from the ISO into a temp dir, runs export_character, and
hashes the result so the reader stage evidence is reproducible.

    python -m gbox.re6_reader "<Resident Evil 6.iso>" --out /tmp/re6_leon.glb
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

from gbox import re6
from gbox.re6_models import CHARACTERS, PARTS, arc_dir, export_character


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def extract_character_arcs(iso_path: str, char: str = "leon", costume: str | None = None) -> dict:
    """Pull the character's part arcs + texture arcs from the ISO into a temp dir."""
    c = CHARACTERS[char]
    costume = costume or c["costumes"][0]
    tmp = Path(tempfile.mkdtemp(prefix=f"re6_{char}_"))
    x = re6.XDVD(iso_path)
    extracted = []
    try:
        # part arcs (body, head, hands)
        stems = [c["arc"].format(part=part, costume=costume) for part in PARTS]
        # texture arcs for this model (e.g. pl0000 -> uPlTex0000_*)
        model = c["pl"]  # pl0000
        tex_stems = []
        for p in x.files:
            nm = Path(p).name.lower()
            if nm.startswith(f"upltex{model[2:5]}0_") and nm.endswith(".arc"):
                tex_stems.append(Path(p).stem)
        for stem in stems + tex_stems:
            src = f"/nativeXenon/arc/X360/{stem}.arc"
            try:
                data = x.read(src)
            except KeyError:
                continue
            dst = tmp / "nativeXenon" / "arc" / "X360" / f"{stem}.arc"
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(data)
            extracted.append({"stem": stem, "bytes": len(data), "sha256": sha(data)})
    finally:
        x.close()
    return {"tmp": str(tmp), "extracted": extracted, "costume": costume}


def reader_probe(iso_path: str, char: str = "leon", costume: str | None = None,
                 glb_out: str | None = None) -> dict:
    info = extract_character_arcs(iso_path, char, costume)
    base = Path(info["tmp"])
    glb_path = Path(glb_out) if glb_out else base / f"re6_{char}.glb"
    stats = export_character(base, char, glb_path, info["costume"])
    glb_bytes = glb_path.read_bytes()
    result = {
        "iso": iso_path,
        "character": char,
        "costume": info["costume"],
        "extracted_arcs": info["extracted"],
        "glb": {
            "path": str(glb_path),
            "bytes": len(glb_bytes),
            "sha256": sha(glb_bytes),
        },
        "stats": stats,
    }
    shutil.rmtree(info["tmp"], ignore_errors=True)
    return result


NAMES = {  # display names + aliases for the roster the collection shows
    "leon": ("Leon S. Kennedy", ["Leon", "Leon Kennedy", "RE6 Leon"]),
    "helena": ("Helena Harper", ["Helena", "RE6 Helena"]),
    "chris": ("Chris Redfield", ["Chris", "RE6 Chris"]),
    "piers": ("Piers Nivans", ["Piers", "RE6 Piers"]),
    "jake": ("Jake Muller", ["Jake", "Jake Muller", "RE6 Jake"]),
    "sherry": ("Sherry Birkin", ["Sherry", "RE6 Sherry"]),
    "ada": ("Ada Wong", ["Ada", "RE6 Ada"]),
}


def roster() -> list[dict]:
    """The 7 playable heroes, slugged re6_<key> for the collection."""
    return [{"key": k, "slug": f"re6_{k}", "name": NAMES[k][0], "aliases": NAMES[k][1], "kind": "character"}
            for k in CHARACTERS]


def extract_run(ctx, game: dict, e: dict, work: Path) -> dict:
    """characters.DEDICATED hook: export <key> (body+head+hands, LOD0, albedo textures) from the owned ISO."""
    from .models import CatalogEntry
    from .tools import rom_path

    iso = rom_path(CatalogEntry.model_validate(game), ctx.config)
    glb = Path(work) / f"{e['slug']}.glb"
    r = reader_probe(str(iso), e["key"], glb_out=str(glb))
    return {"files": [glb], "tool": "gbox.re6_reader (MT Framework Mod/Mrl, Xenon textures)",
            "source_files": [a["stem"] + ".arc" for a in r["extracted_arcs"]],
            "notes": f"{r['stats']['triangles']} triangles, costume {r['costume']}; GLB sha256 "
                     f"{r['glb']['sha256'][:16]}... from the owned XDVDFS ISO"}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("iso")
    ap.add_argument("--char", default="leon")
    ap.add_argument("--costume", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--json-out", default=None)
    a = ap.parse_args(argv)
    r = reader_probe(a.iso, a.char, a.costume, a.out)
    s = json.dumps(r, indent=1)
    if a.json_out:
        open(a.json_out, "w").write(s)
    print(s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
