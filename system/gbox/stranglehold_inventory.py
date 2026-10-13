"""Stranglehold (PS3, BLUS30081) cooked-package inventory: which .xxx packages hold the player / enemy SkeletalMeshes (#1410).

Two package layouts ship in StrangleholdGame/CookedPS3 (UE3 v375, licensee 25 = Midway):

* chunked (content: char_*, levels, UI): the file starts with an uncompressed 0x71-byte summary (Midway fields, the
  "None" folder name at 0x18, then flags, name/export/import counts and offsets, depends offset, GUID, generations,
  engine 2605 / cooker 32, compression flags 1 = zlib) followed by the compressed-chunk table
  (uncompressed offset, uncompressed size, compressed offset, compressed size). Each chunk is a standard UE3 compressed
  chunk: tag 0x9E2A83C1, block size 0x10000, totals, block table, zlib blocks. The logical package = the 0x71-byte
  summary + the decompressed chunks at their uncompressed offsets; names start at 0x71.
* fully compressed (script packages: Core, Engine, StrangleholdGame, AIIU...): tag + block size 0x10000 in place of the
  version word, the whole package compressed (gbox.ue3.unpack).

Only the chunks that hold the name / import / export tables (everything before the depends offset) are read and
decompressed, so a full inventory of the ~1 GB folder reads a few MB per package. Bulk export data (mesh vertices,
textures) is not touched.

CLI:  python -m gbox.stranglehold_inventory [CookedPS3 folder] [--json out.json]
"""
from __future__ import annotations

import json
import re
import struct
import sys
import zlib
from collections import Counter
from pathlib import Path

from . import ue3

TAG = 0x9E2A83C1
GAME_ID = "9c436f5a9754f777"
SERIAL = "BLUS30081"
_DISC = "John Woo Presents Stranglehold (USA) (En,Fr,De,Es,It) (Collector's Edition)/PS3_GAME/USRDIR/StrangleholdGame/CookedPS3"
DEFAULT_ROOTS = [Path("//10.89.1.125/QuickSwap2/Emulation/PS3") / _DISC,          # the QuickSwap NAS from Windows
                 Path("/mnt/gbox/quickswap2/Emulation/PS3") / _DISC]             # the same folder mounted on the Spark

# SkeletalMesh roles from the cooked names: Tequila (player, four outfits + MP / cinematic variants), the faction enemy
# classes (assaultClass01.., dc_ / Imperial9_ prefixes per gang), named characters and bosses, civilians, props.
ENEMY_RX = re.compile(r"^(dc_|imperial9_)?(assault|smg|melee|pistol|sniper|lieutenant|elite|butcher|devil|depang)class|"
                      r"^sec_gkthug|^dragonclawscout", re.I)
BOSSES = ("damonzakarov", "vladzakarov", "jerryying", "wong_", "depangclass")
CHARACTERS = ("billie", "captainlee", "chopperpilotlou", "teahouseboss", "junkcaptain", "lok_", "yung_", "johnwoo", "nico_",
              "hkpd", "agedmerchant", "megamaitred", "sec_band", "sec_museumdoorman")
CIVILIANS = ("asianmale", "americanmale", "americanfemale")
VEHICLES = ("veh_", "thunderstrike", "baron_", "longhorn_", "regalia_")


class FormatError(ValueError):
    pass


def _u32s(b: bytes, o: int, n: int) -> tuple:
    return struct.unpack_from(f">{n}I", b, o)


def read_summary(head: bytes) -> dict:
    """Parse the package summary from the first bytes of a .xxx file (4 KiB is enough for every shipped package)."""
    if len(head) < 16 or struct.unpack(">I", head[:4])[0] != TAG:
        raise FormatError("not a UE3 package")
    word = struct.unpack(">I", head[4:8])[0]
    if not word & 0xFFFF:                                     # block size where the version should be
        csize, usize = struct.unpack(">II", head[8:16])
        return {"layout": "fully_compressed", "compression": "zlib", "block_size": word,
                "compressed_size": csize, "uncompressed_size": usize}
    i = head.find(b"\x00\x00\x00\x05None\x00")
    if i < 0:
        raise FormatError("no 'None' folder name in the summary")
    o = i + 9
    flags, nc, no, ec, eo, ic, io, dep = _u32s(head, o, 8)
    o += 32 + 16                                              # + package GUID
    gens = struct.unpack_from(">I", head, o)[0]
    if gens > 64:
        raise FormatError(f"implausible generation count {gens}")
    o += 4 + 12 * gens
    engine, cooker, cflags, nchunks = _u32s(head, o, 4)
    o += 16
    if nchunks > 4096 or o + 16 * nchunks > len(head):
        raise FormatError(f"chunk table ({nchunks}) outside the header read")
    chunks = [dict(zip(("uoff", "usize", "coff", "csize"), _u32s(head, o + 16 * k, 4))) for k in range(nchunks)]
    return {"layout": "chunked" if nchunks else "raw", "version": word & 0xFFFF, "licensee": word >> 16,
            "flags": flags, "names": nc, "name_offset": no, "exports": ec, "export_offset": eo,
            "imports": ic, "import_offset": io, "depends_offset": dep, "engine": engine, "cooker": cooker,
            "compression": {0: "none", 1: "zlib", 2: "lzo", 4: "lzx"}.get(cflags, f"flags {cflags}"),
            "summary_size": chunks[0]["uoff"] if chunks else None, "chunks": chunks}


def decompress_chunk(blob: bytes) -> bytes:
    """One UE3 compressed chunk (tag, block size, totals, block table, zlib blocks) -> its uncompressed bytes."""
    tag, block, csum, usum = struct.unpack_from(">IIII", blob, 0)
    if tag != TAG:
        raise FormatError(f"bad chunk tag {tag:#x}")
    n = (usum + block - 1) // block
    table = [struct.unpack_from(">II", blob, 16 + 8 * k) for k in range(n)]
    o, out = 16 + 8 * n, bytearray()
    for c, _u in table:
        out += zlib.decompress(blob[o:o + c])
        o += c
    if len(out) != usum:
        raise FormatError(f"chunk inflated to {len(out)} bytes, header says {usum}")
    return bytes(out)


def logical_tables(path: Path) -> tuple[dict, bytes]:
    """(summary, logical package prefix covering the name / import / export tables), reading only what is needed."""
    with open(path, "rb") as f:
        head = f.read(4096)
        s = read_summary(head)
        if s["layout"] == "fully_compressed":
            f.seek(0)
            return s, ue3.unpack(f.read())                    # script packages: small except StrangleholdGame (25 MB)
        if s["layout"] == "raw":
            f.seek(0)
            return s, f.read()
        need = s["depends_offset"] or max(s["export_offset"], s["import_offset"]) + 1
        logical = bytearray(head[:s["summary_size"]])
        for c in s["chunks"]:
            if c["uoff"] >= need:
                break
            f.seek(c["coff"])
            data = decompress_chunk(f.read(c["csize"]))
            if len(logical) < c["uoff"]:
                logical += bytes(c["uoff"] - len(logical))
            logical[c["uoff"]:c["uoff"] + len(data)] = data
    return s, bytes(logical)


def mesh_role(name: str) -> str:
    """player | enemy | boss | character | civilian | weapon | vehicle | prop for one SkeletalMesh name."""
    low = name.lower()
    if low.startswith("tequila"):
        return "player"
    if any(low.startswith(b) for b in BOSSES):
        return "boss"
    if ENEMY_RX.search(low):
        return "enemy"
    if any(low.startswith(c) for c in CHARACTERS):
        return "character"
    if low.startswith(CIVILIANS):
        return "civilian"
    if low.startswith(("wpn_", "fmv_beretta", "rifle_")) or "guitarcase_weapons" in low:
        return "weapon"
    if low.startswith(VEHICLES):
        return "vehicle"
    return "prop"


def mesh_variant(name: str) -> str:
    low = name.lower()
    return "multiplayer" if low.endswith("_mp") or "_mp_" in low else "cinematic" if "_cine" in low else "game"


def scan_package(path: Path, root: Path | None = None) -> dict:
    """One package: layout, compression, table counts, and its SkeletalMesh / AnimSet / texture exports."""
    s, d = logical_tables(path)
    pkg = ue3.Package(d)
    classes = Counter((pkg.ref(e["class"])[1] if e["class"] else "Class") for e in pkg.exports)
    sk = [e for e in pkg.exports if e["class"] and pkg.ref(e["class"])[1] == "SkeletalMesh"
          and not e["name"].startswith("Default__")]
    meshes = [e["name"] for e in sk]
    rel = path.relative_to(root).as_posix() if root else path.name
    return {"package": path.stem, "path": rel, "bytes": path.stat().st_size, "layout": s["layout"],
            "compression": s["compression"] if isinstance(s["compression"], str) else "zlib",
            "chunks": len(s.get("chunks") or []) or None, "version": pkg.version, "licensee": pkg.licensee,
            "names": len(pkg.names), "imports": len(pkg.imports), "exports": len(pkg.exports),
            "skeletal_meshes": meshes, "skeletal_mesh_count": len(meshes),
            "skeletal_mesh_bytes": sum(e["size"] for e in sk),
            "mesh_roles": dict(Counter(mesh_role(m) for m in meshes)),
            "anim_sets": classes.get("AnimSet", 0), "anim_sequences": classes.get("AnimSequence", 0),
            "textures": classes.get("Texture2D", 0), "static_meshes": classes.get("StaticMesh", 0),
            "materials": classes.get("Material", 0) + classes.get("MaterialInstanceConstant", 0),
            "kind": ("character" if path.stem.lower().startswith("char_") else "cinematic" if "_cine" in path.stem.lower()
                     else "mission" if "mission" in path.stem.lower() or "_mso" in path.stem.lower() else "package")}


def find_root() -> Path | None:
    return next((p for p in DEFAULT_ROOTS if p.is_dir()), None)


def inventory(root: Path | None = None, pattern: str = "*.xxx", progress=None) -> dict:
    """Scan every cooked package under root; packages with SkeletalMeshes first, grouped by role."""
    root = Path(root) if root else find_root()
    if not root or not root.is_dir():
        raise FileNotFoundError("Stranglehold CookedPS3 folder not found (QuickSwap2 share)")
    rows, errors = [], []
    files = sorted(root.rglob(pattern))
    for k, p in enumerate(files):
        if progress:
            progress(k, len(files), p.name)
        try:
            rows.append(scan_package(p, root))
        except Exception as e:                                # one odd package must not hide the rest
            errors.append({"path": p.relative_to(root).as_posix(), "error": f"{type(e).__name__}: {e}"})
    with_mesh = [r for r in rows if r["skeletal_mesh_count"]]
    roles: dict[str, dict] = {}
    for r in with_mesh:
        for m in r["skeletal_meshes"]:
            ro = roles.setdefault(mesh_role(m), {"meshes": set(), "packages": set()})
            ro["meshes"].add(m)
            ro["packages"].add(r["path"])
    by_role = {k: {"unique_meshes": len(v["meshes"]), "packages": len(v["packages"]),
                   "game_meshes": sorted(m for m in v["meshes"] if mesh_variant(m) == "game"),
                   "sample_packages": sorted(v["packages"], key=lambda p: (not p.startswith("char_"), p))[:12]}
               for k, v in sorted(roles.items())}
    return {"game_id": GAME_ID, "serial": SERIAL, "root": str(root), "packages": len(rows),
            "layouts": dict(Counter(r["layout"] for r in rows)),
            "compression": dict(Counter(r["compression"] for r in rows)),
            "packages_with_skeletal_meshes": len(with_mesh),
            "skeletal_meshes": sum(r["skeletal_mesh_count"] for r in rows),
            "unique_skeletal_meshes": len({m for r in rows for m in r["skeletal_meshes"]}),
            "by_role": by_role,
            "rows": sorted(with_mesh, key=lambda r: r["path"]) +
                    sorted((r for r in rows if not r["skeletal_mesh_count"]), key=lambda r: r["path"]),
            "errors": errors}


# What a native model reader still needs (tracked on #1410; the inventory above is the first stage).
READER_NOTES = """\
A UE3 v375/licensee-25 SkeletalMesh reader needs, per export blob (offset/size from the export table, logical
package offsets, the chunks above decompressed in full):
1. the UObject property block (tagged properties, terminated by the 'None' name) - Materials, Origin, RotOrigin,
   SkelMirrorTable, ...;
2. FBoxSphereBounds, the Materials TArray (object refs), Origin / RotOrigin;
3. RefSkeleton: TArray<FMeshBone> (name, flags, FQuat orientation, FVector position, num children, parent index,
   and for this engine age no BoneColor) and SkeletalDepth;
4. LODModels: TArray<FStaticLODModel>: sections (material index, chunk index, base index, triangle count), the
   index buffer (FRawStaticIndexBuffer: TArray<WORD> with an element-size prefix), ActiveBoneIndices, chunks
   (FSkelMeshChunk: rigid + soft vertices with packed normals and up to 4 influences), RequiredBones and the raw
   point indices; licensee 25 may insert Midway fields that must be found by diffing two meshes;
5. bulk data for vertices may live in the package's own bulk area (PS3 cooks inline), so the export's chunks must be
   decompressed rather than just the table chunks;
6. textures: Texture2D mips (DXT1/DXT5 on PS3, big-endian 16-bit swaps not needed for DXT) referenced by the
   MaterialInstanceConstants the mesh's Materials point at.
The output target is the gBox character collection format (glTF + rig roles), like the other native readers.
"""


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    out = argv[argv.index("--json") + 1] if "--json" in argv else None
    if out in args:
        args.remove(out)
    inv = inventory(Path(args[0]) if args else None,
                    progress=lambda k, n, name: print(f"[{k + 1}/{n}] {name}", file=sys.stderr))
    if out:
        Path(out).write_text(json.dumps(inv, indent=1), encoding="utf-8")
    print(f"{inv['packages']} packages {inv['layouts']} {inv['compression']}; "
          f"{inv['packages_with_skeletal_meshes']} hold {inv['skeletal_meshes']} SkeletalMeshes "
          f"({inv['unique_skeletal_meshes']} unique names); {len(inv['errors'])} errors")
    for role, v in inv["by_role"].items():
        print(f"  {role:9} {v['unique_meshes']:3} meshes in {v['packages']:3} packages, e.g. {', '.join(v['sample_packages'][:5])}")
        print(f"            game meshes: {', '.join(v['game_meshes'][:12])}{' ...' if len(v['game_meshes']) > 12 else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
