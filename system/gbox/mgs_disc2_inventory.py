"""Metal Gear Solid (USA) disc 2 (PS1, SLUS_007.76): owned-disc manifest and character-figure census.

Verified against the owned image (``Metal Gear Solid (USA) (Disc 2).chd``, 474,878,219 B,
sha256 ``8837b20ddff61e5527fe95cbd186169e724f40409dd873cd549e489398b1d9ef``), not copied from a catalogue.
The CHD holds an ISO9660 image with 11 files: the ``MGS/`` tree plus ``DUMMY3M.DAT`` and ``SYSTEM.CNF``
(``docs/mgs_disc2_manifest.json`` is the per-member manifest: path, LBA, size, streamed sha256).

Container chain, confirmed on this disc:

* ``MGS/STAGE.DIR`` (71,888,896 B) is the stage container.  ``gbox.mgs_vr_swap.stage_dir`` reads its 96
  stage headers; ``stage_files`` reads one stage's file table.  A stage file is either a raw asset or a
  ``DAR`` container whose members are named by a one-character extension and a 16-bit hash
  (``gbox.mgs_vr_swap.dar_entries``): ``k`` = KMD model, ``o`` = KMD animation, ``t`` = TIM texture.
* 1,876 KMD model members were found (1,836 unique hashes).  47 of them are character figures: 16 objects
  whose parent list equals the canonical humanoid tree ``gbox.mgs_vr_swap.TREE``.
* The player model is member hash **39213** (13,608 B, 341 faces / 369 vertices) in stage ``init``
  (STAGE.DIR offset 5,760,508; also present in ``init_tux``).  Its bytes are identical to the player KMD
  that ``gbox.mgs_vr_swap`` already targets for VR Missions, so that writer's player-slot recipe applies
  to this disc once the stage offsets are re-pointed - that is the one identified native target asset.

Read-only by construction: this module never writes to the owned CHD or to the extracted image.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import mgs_kmd
from . import mgs_vr_swap as vr
from . import psxdisc

CHD_PATH = "/mnt/gbox/hyperspin/Arcade/collections/Sony Playstation/roms/Metal Gear Solid (USA) (Disc 2).chd"
SOURCE_SHA256 = "8837b20ddff61e5527fe95cbd186169e724f40409dd873cd549e489398b1d9ef"
SOURCE_BYTES = 474878219
STAGE_MEMBER = "MGS/STAGE.DIR"
STAGE_BYTES = 71888896
STAGE_COUNT = 96
KMD_SITES = 1876
FIGURE_COUNT = 47
FIGURE_OBJECTS = 16
PLAYER_MODEL_HASH = 39213
CHUNK = 1 << 22


def _close(disc):
    close = getattr(disc, "close", None)
    if close:
        close()


def open_disc(path=CHD_PATH):
    """Open the owned CHD (read-only)."""
    return psxdisc.PSXDisc(path)


def member_manifest(disc, path, chunk=CHUNK):
    """One ISO member as ``path`` / ``lba`` / ``size`` / streamed ``sha256``."""
    lba, size = disc.files[path]
    h = hashlib.sha256()
    off = 0
    while off < size:
        blob = disc.read(path, off, min(chunk, size - off))
        if not blob:
            break
        h.update(blob)
        off += len(blob)
    return {"path": path, "lba": lba, "size": size, "sha256": h.hexdigest()}


def manifest(path=CHD_PATH, members=None):
    """The authoritative per-member manifest of the owned disc."""
    disc = open_disc(path)
    try:
        names = sorted(disc.files) if members is None else list(members)
        rows = [member_manifest(disc, n) for n in names]
    finally:
        _close(disc)
    return {"source": path, "source_sha256": SOURCE_SHA256, "source_bytes": SOURCE_BYTES,
            "member_count": len(rows), "members": rows}


def read_member(disc, path, chunk=CHUNK):
    """Stream a whole member out of the CHD."""
    _, size = disc.files[path]
    out = bytearray()
    off = 0
    while off < size:
        blob = disc.read(path, off, min(chunk, size - off))
        if not blob:
            break
        out += blob
        off += len(blob)
    return bytes(out)


def stage_bytes(disc=None):
    """The ``MGS/STAGE.DIR`` container."""
    own = disc is None
    disc = disc or open_disc()
    try:
        return read_member(disc, STAGE_MEMBER)
    finally:
        if own:
            _close(disc)


def kmd_sites(stage):
    """Every KMD model member in the disc: ``(stage, offset, size, hash)``."""
    out = []
    for name, off in sorted(vr.stage_dir(stage).items(), key=lambda kv: kv[1]):
        for f in vr.stage_files(stage, off):
            ext = f.get("ext")
            if ext == "k":
                out.append((name, f.get("offset"), f.get("size"), f.get("hash")))
            elif ext == "d" and not f.get("cached"):
                try:
                    entries = vr.dar_entries(stage, f.get("offset"), f.get("size"))
                except ValueError:
                    continue
                for e in entries:
                    if e.get("ext") == "k":
                        out.append((name, e.get("offset"), e.get("size"), e.get("hash")))
    return out


def figures(stage, tree=None):
    """Census of the character figures (16-object models on the canonical tree)."""
    tree = list(tree if tree is not None else vr.TREE)
    found = {}
    sites = 0
    for sname, off, size, mhash in kmd_sites(stage):
        sites += 1
        blob = stage[off:off + size]
        try:
            model = mgs_kmd.loads(blob)
        except Exception:
            continue
        if len(model.objects) != FIGURE_OBJECTS:
            continue
        if [o.parent for o in model.objects] != tree:
            continue
        key = str(mhash)
        row = found.setdefault(key, {
            "hash": mhash, "bytes": size, "sha256": hashlib.sha256(blob).hexdigest(),
            "faces": sum(len(o.faces) for o in model.objects),
            "verts": sum(len(o.vertices) for o in model.objects),
            "textures": sorted({t for o in model.objects for t in o.textures}),
            "sites": []})
        if len(row["sites"]) < 8:
            row["sites"].append({"stage": sname, "offset": off, "size": size})
    return {"kmd_sites": sites, "figure_count": len(found), "figures": found}


def player_slot(stage, tree=None):
    """The one identified native target asset: the player model, member hash 39213."""
    return figures(stage, tree)["figures"].get(str(PLAYER_MODEL_HASH))


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="MGS (USA) disc 2 manifest + character-figure census")
    ap.add_argument("chd", nargs="?", default=CHD_PATH)
    ap.add_argument("--json", help="write the manifest to this path")
    args = ap.parse_args(argv)
    doc = manifest(args.chd)
    if args.json:
        Path(args.json).write_text(json.dumps(doc, indent=1))
    print(json.dumps(doc, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
