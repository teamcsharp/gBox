"""MGS (USA) disc 2 (PS1): read-only extractor + no-op roundtrip for the player KMD slot (analysis stage).

Source identity (same as ``gbox.mgs_disc2_inventory``): owned CHD sha256 ``8837b20d...9e489398b1d9ef``; ``MGS/STAGE.DIR``
is ISO LBA 100801, 71,888,896 B, sha256 ``c1657e57...0b44fd4a`` (not in ``mgs_vr_swap.STAGE_DIR_SIZES``, so
writers must open it with ``StageDir(strict=False)``).

Player model = member hash 39213 of stage ``init``'s DAR (STAGE.DIR offset 5,760,508, 13,608 B; the DAR is at
5,677,056).  ``init_tux`` holds a second, different copy (offset 69,061,296, 13,112 B).  Its 28 texture hashes
are ``p`` members of the stage's texture DAR (init: 5,832,704, 141,924 B).  Byte order little-endian, offset base =
start of STAGE.DIR (absolute disc byte = LBA*2048 + offset for cooked data; raw MODE2/2352 sector =
LBA + offset//2048, user data at +24).  Nothing here writes to the disc.
"""
from __future__ import annotations

import hashlib

from . import mgs_kmd
from . import mgs_vr_swap as vr

STAGE_LBA = 100801
STAGE_SHA256 = "c1657e57fc2c51b034342fccb61f36ec8b8546e5f8e486da5cdd69ae0b44fd4a"
PLAYER_HASH = 39213
STAGES = ("init", "init_tux")


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def raw_locator(offset, lba=STAGE_LBA):
    """Where a STAGE.DIR byte lives in a raw MODE2/2352 image."""
    sector = lba + offset // 2048
    return {"sector": sector, "raw_byte": sector * 2352 + 24 + offset % 2048, "in_sector": offset % 2048}


def player_sites(stage):
    return [s for s in vr.model_sites(stage, [PLAYER_HASH]) if s["stage"] in STAGES]


def resolve(stage, site):
    """The KMD slot plus its texture members for one site."""
    blob = stage[site["offset"]:site["offset"] + site["size"]]
    model = mgs_kmd.loads(blob)
    hashes = sorted({t for o in model.objects for t in o.textures})
    pools = vr.stage_textures(stage, site["stage_offset"])
    tex = {}
    for h in hashes:
        for p in pools:
            if h in p["entries"]:
                o, n = p["entries"][h]
                tex[h] = {"offset": o, "size": n, "sha256": _sha(stage[o:o + n]), "pool": p["offset"]}
                break
    return {"stage": site["stage"], "offset": site["offset"], "size": site["size"], "sha256": _sha(blob),
            "dar": site["dar"], "objects": len(model.objects), "faces": sum(len(o.faces) for o in model.objects),
            "verts": sum(len(o.vertices) for o in model.objects), "raw": raw_locator(site["offset"]),
            "texture_hashes": hashes, "textures": tex, "missing_textures": [h for h in hashes if h not in tex]}


def extract(stage, site):
    """Read-only: (kmd bytes, {texture hash: bytes})."""
    r = resolve(stage, site)
    kmd = bytes(stage[r["offset"]:r["offset"] + r["size"]])
    return kmd, {h: bytes(stage[t["offset"]:t["offset"] + t["size"]]) for h, t in r["textures"].items()}


def noop_roundtrip(stage, site):
    """Write the KMD back in place and repack its DAR with no changes; the image must not change."""
    sd = vr.StageDir(stage, strict=False)
    kmd, _ = extract(stage, site)
    sd.put(site["offset"], site["size"], kmd, "player kmd (no-op)")
    sd.repack_dar(site["dar"], _dar_size(stage, site), {}, "player dar (no-op)")
    return {"identical": bytes(sd.data) == bytes(stage), "changed_sectors": len(sd.changed_runs()),
            "sha256": _sha(bytes(sd.data))}


def _dar_size(stage, site):
    for f in vr.stage_files(stage, site["stage_offset"]):
        if f["offset"] == site["dar"]:
            return f["size"]
    raise ValueError("player DAR not found")


def report(stage):
    out = []
    for s in player_sites(stage):
        r = resolve(stage, s)
        r["noop_roundtrip"] = noop_roundtrip(stage, s)
        out.append(r)
    return {"stage_dir_sha256": _sha(stage), "sites": out}
