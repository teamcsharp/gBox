"""Metroid Prime (USA, GameCube, GM8E01) -- owned-disc inventory for native character replacement.

The catalog build (bbc9d43db663e1aa) is a Dolphin GCZ; the owned source is read in place with
`gbox.gcdisc.GCDisc` (only the touched GCZ blocks are inflated) and never modified.

The assimilation fingerprint attached to the ticket is WRONG on the engine: it scored
"Unreal Engine 4/5 (0.72)" with no containers/codecs/models/textures detected and nearest-title
similarities of 0.028/0.019 (noise).  Metroid Prime is Retro Studios' proprietary engine, which
the matching decompilation (github.com/PrimeDecomp/prime) names "Kyoto".  Do NOT route this game
through gbox.ue_pak / gbox.ue_asset / gbox.ue_mesh.

Disc (GM8E01) layout: 178 FST files.  `default.dol` is the main executable (boot DOL in the disc
header at 0x420).  Game data lives in 18 `.pak` archives plus loose files (Audio/*.dsp = 115,
Video/*.thp = 35, 3 .rel NES-emu modules, client_pad.bin, opening.bnr).

PAK container (authoritative, from PrimeDecomp src/Kyoto/CPakFile.cpp)::

    header            s32 version == 0x00030005, s32 0, s32 nameCount
    name list         nameCount x { s32 fourCC, s32 id, string name }   (name = u32 len + bytes)
    resource table    s32 resTableCount, then resTableCount x 20-byte entries:
                          u32 flags, u32 fourCC, u32 id, u32 size, u32 offset
    data blobs        at `offset` (absolute, 32-byte aligned), `size` bytes (32-byte aligned)

`size`/`offset` are 32-byte aligned because the loader packs them into a 6-byte SResInfo with a
5-bit shift (CPakFile::SResInfo).  The name list is only the exported entry points (a world pak
exports one MLVL); the resource table holds EVERY asset (meshes, textures, anims, sub-resources),
so the per-type inventory is computed from the resource table, not the name list.
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from collections import Counter
from pathlib import Path
from .side_dirs import side_dir

GAME_IDS = {"bbc9d43db663e1aa": "Metroid Prime (USA)"}
DISC_ID = "GM8E01"
PAK_VERSION = 0x00030005

# FourCCs (Retro "Kyoto" engine resource types) grouped for the character pipeline.
CHARACTER_TYPES = {"ANCS", "CMDL", "CSKR", "CINF"}
MESH_TYPES = {"CMDL"}
SKELETON_TYPES = {"CSKR"}
ANIMATION_TYPES = {"ANIM"}
TEXTURE_TYPES = {"TXTR"}


def _read_string(data: bytes, off: int) -> tuple[str, int]:
    """u32 length + bytes (CStringExtras::ReadString)."""
    if off + 4 > len(data):
        raise ValueError("truncated pak string length")
    (n,) = struct.unpack_from(">I", data, off)
    off += 4
    if off + n > len(data):
        raise ValueError("truncated pak string")
    return data[off : off + n].decode("latin-1"), off + n


def pak_directory(data: bytes) -> dict:
    """Parse the full pak container (header + name list + resource table). No decompression."""
    if len(data) < 12:
        raise ValueError("pak too short")
    version, _zero, name_count = struct.unpack_from(">3I", data, 0)
    if version != PAK_VERSION:
        raise ValueError(f"pak version {version:#x} != {PAK_VERSION:#x}")
    off = 12
    names = []
    for _ in range(name_count):
        if off + 12 > len(data):
            raise ValueError("truncated pak name record")
        fourcc, rid = struct.unpack_from(">2I", data, off)
        off += 8
        name, off = _read_string(data, off)
        names.append({"type": fourcc, "id": rid, "name": name})
    if off + 4 > len(data):
        raise ValueError("truncated pak resource count")
    (res_count,) = struct.unpack_from(">I", data, off)
    off += 4
    if off + res_count * 20 > len(data):
        raise ValueError("truncated pak resource table")
    resources = []
    for _ in range(res_count):
        flags, fourcc, rid, size, offset = struct.unpack_from(">5I", data, off)
        off += 20
        if offset + size > len(data) or offset & 31 or size & 31:
            raise ValueError(
                f"bad resource {fourcc:08x} id={rid:08x} size={size} offset={offset} "
                f"(file {len(data)})"
            )
        resources.append(
            {"flags": flags, "type": fourcc, "id": rid, "size": size, "offset": offset}
        )
    return {
        "version": version,
        "name_count": name_count,
        "names": names,
        "res_count": res_count,
        "resources": resources,
    }


def fourcc(tag: int) -> str:
    return tag.to_bytes(4, "big").decode("latin-1")


def disc_identity(src: Path) -> dict:
    from .gcdisc import GCDisc

    disc = GCDisc(str(src))
    if disc.game_id != DISC_ID:
        raise ValueError(f"expected {DISC_ID}, found {disc.game_id}")
    dol = disc.dol()
    entry = struct.unpack(">I", dol[0xE0:0xE4])[0]
    return {
        "game_id": disc.game_id,
        "title": disc.title,
        "fst_file_count": len(disc.files),
        "dol_size": len(dol),
        "dol_sha256": hashlib.sha256(dol).hexdigest(),
        "dol_entry": f"0x{entry:08x}",
        "paks": sorted(p for p in disc.files if p.lower().endswith(".pak")),
    }


def build_manifest(src: Path, out: Path) -> dict:
    from .gcdisc import GCDisc

    disc = GCDisc(str(src))
    ident = disc_identity(src)
    digest = hashlib.sha256()
    with src.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    manifest = {
        "source_sha256": digest.hexdigest(),
        "identity": ident,
        "engine": "Retro Studios 'Kyoto' (proprietary); assimilation fingerprint 'Unreal 4/5' is a false positive",
        "paks": {},
        "type_histogram": {},
        "named_characters": [],
    }
    type_hist = Counter()
    for pak_name in ident["paks"]:
        data = disc.read(pak_name)
        d = pak_directory(data)
        hist = Counter(fourcc(r["type"]) for r in d["resources"])
        type_hist.update(hist)
        manifest["paks"][pak_name] = {
            "size": len(data),
            "name_count": d["name_count"],
            "res_count": d["res_count"],
            "types": dict(sorted(hist.items())),
            "names": [
                {"type": fourcc(n["type"]), "id": n["id"], "name": n["name"]} for n in d["names"]
            ],
        }
        manifest["named_characters"].extend(
            {
                "pak": pak_name,
                "type": fourcc(n["type"]),
                "id": n["id"],
                "name": n["name"],
            }
            for n in d["names"]
            if fourcc(n["type"]) in CHARACTER_TYPES
        )
    manifest["type_histogram"] = dict(sorted(type_hist.items()))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("src", type=Path, help="owned Metroid Prime .gcz/.iso")
    ap.add_argument(
        "--out",
        type=Path,
        default=side_dir("gbox-cache") / "gc/bbc9d43db663e1aa/manifest.json",
    )
    a = ap.parse_args(argv)
    m = build_manifest(a.src, a.out)
    print(f"game {m['identity']['game_id']}  FST {m['identity']['fst_file_count']} files  "
          f"dol {m['identity']['dol_sha256'][:16]}…")
    print("resource types:", m["type_histogram"])
    print(f"named character resources: {len(m['named_characters'])}")
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
