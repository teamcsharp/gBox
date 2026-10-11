"""DOA2 LE Japan native character archives: CHR geometry, BIN textures, SUP/MOT facts.

The owned 1ST_READ.BIN SHA-256 is
27a014aeda35983df749f7d575bbddbea3f1ffd1f7776194ef503108c20c97e1.
CHR contains NaomiLib models and texture descriptors, NOT a skeleton.
Independent format implementation credits VincentNL, EgregiousGuy and The_Zocker160:
https://github.com/NaomiMod/games-ExtractTools/blob/main/DOA2/CHR_Format.md
https://github.com/NaomiMod/NL-ModelFormat/wiki
"""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

GAME_IDS = {"1de2e7634f3161ff": "Dead or Alive 2 - Limited Edition (Japan)"}


def parse_chr(data: bytes) -> dict:
    """Validated archive facts; models use absolute work-RAM pointers.

    File offsets include the 24-byte archive header. Texture count/table are
    reported as textures; they must never be advertised as bones or bind poses.
    """
    from .doa2_geometry import decode_chr
    a = decode_chr(data)
    models = a["models"]
    return {"n_objects": len(models), "n_models": len(models),
            "n_textures": len(a["textures"]), "ptr_base": a["pointer_base"],
            "objects": [m["offset"] for m in models],
            "sizes": [m["end_offset"] - m["offset"] for m in models],
            "model_table_offset": a["model_table_offset"],
            "texture_table_offset": a["texture_table_offset"],
            "textures": [{"width": wh & 65535, "height": wh >> 16,
                          "pixel": flags & 255, "format": flags >> 8 & 255,
                          "address": ptr} for wh, flags, ptr in a["textures"]]}


def parse_sup(data: bytes) -> dict:
    """Supplement record boundaries, retained without inventing a skeleton."""
    if len(data) < 4:
        raise ValueError("Truncated SUP table")
    first = struct.unpack_from("<I", data)[0]
    if first % 4 or first < 4 or first > len(data):
        raise ValueError("Invalid SUP table boundary")
    offsets = list(struct.unpack_from(f"<{first // 4}I", data))
    if offsets[-1] == 0:
        offsets.pop()
    if not offsets or offsets[0] != first or offsets != sorted(set(offsets)) or any(o >= len(data) for o in offsets):
        raise ValueError("Invalid SUP record offsets")
    return {"n_records": len(offsets), "offsets": offsets,
            "records": [{"offset": start, "size": end-start}
                        for start, end in zip(offsets, offsets[1:] + [len(data)])]}


def parse_mot_table(data: bytes) -> dict:
    """Find the bounded outer pointer table; clip pointers can share tracks.

    The first clip can follow its track payloads, so its offset does not give
    the outer table length. The first invalid pointer terminates this table.
    Track channels require the game's animation decoder.
    """
    offsets = []
    for o in range(0, min(len(data)-3, 0x4000), 4):
        v = struct.unpack_from("<I", data, o)[0]
        if not v or v >= len(data):
            break
        offsets.append(v)
    return {"n_clips": len(offsets), "offsets": offsets}


# costume prefix -> (display name, aliases). Confirmed against the disc's arts_*.bin / *.mot tables
# (1ST_READ+0x16e7fc arts_*, +0x16e890 *_mot names: zack tina janlee ryu kasumi genfu bayman bass
# leifan ayane hika karate ind raido tengu sambo). KTE is Ein in the selectable roster.
FIGHTERS = [
    ("KAS", "Kasumi", ["Kasumi-chan", "DOA2 Kasumi"]),
    ("AYA", "Ayane", ["DOA2 Ayane"]),
    ("LEI", "Leifang", ["Lei Fang", "DOA2 Leifang"]),
    ("TIN", "Tina", ["Tina Armstrong", "DOA2 Tina"]),
    ("BAS", "Bass", ["Bass Armstrong", "DOA2 Bass"]),
    ("JAN", "Jann Lee", ["Jan Lee", "DOA2 Jann Lee"]),
    ("GEN", "Gen Fu", ["Genfu", "DOA2 Gen Fu"]),
    ("BAY", "Bayman", ["DOA2 Bayman"]),
    ("RYU", "Ryu Hayabusa", ["Ryu", "DOA2 Ryu"]),
    ("ZAC", "Zack", ["DOA2 Zack"]),
    ("HIK", "Helena", ["Helena Douglas", "DOA2 Helena"]),
    ("SAM", "Leon", ["DOA2 Leon"]),                       # arts_sam + sambo motion set
    ("TNG", "Tengu", ["Bankotsu-bo", "DOA2 Tengu"]),
    ("KTE", "Ein", ["DOA2 Ein"]),      # Ein costume family
]
# single-costume families that are not part of the selectable roster (boss/story variants)
VARIANTS = ["LOR", "MAM", "PDG", "WBA", "YTI"]
# motion files are named by the character's full nickname (1ST_READ+0x16e890: zack.mot tina.mot
# janlee.mot ryu.mot kasumi.mot genfu.mot bayman.mot bass.mot leifan.mot ayane.mot hika.mot
# karate.mot ind.mot raido.mot tengu.mot sambo.mot comon.mot). Only name-identical mappings here.
MOT_FILES = {"KAS": "KASUMI", "AYA": "AYANE", "LEI": "LEIFAN", "TIN": "TINA", "BAS": "BASS",
             "JAN": "JANLEE", "GEN": "GENFU", "BAY": "BAYMAN", "RYU": "RYU", "ZAC": "ZACK",
             "HIK": "HIKA", "TNG": "TENGU"}           # SAM/KTE motion names unconfirmed (sambo/karate/ind/raido)


def roster(disc_files: dict | None = None) -> list[dict]:
    """Costume entries from the disc listing (dict[str, tuple] like GDRom.files). With none, the
    static roster above."""
    import re
    fam: dict[str, list[str]] = {}
    if disc_files:
        for n in disc_files:
            m = re.match(r"^DOA2/([A-Z]+)(\d+)\.(?:CHR|SUP|BIN)$", n)
            if m and m.group(1) not in ("STAGE", "EFC", "FIX", "DV"):
                fam.setdefault(m.group(1), []).append(m.group(2))   # keep zero padding as-is
    out = []
    for pre, name, aliases in FIGHTERS:
        costumes = sorted(set(fam.get(pre, [])), key=int) or ["0"]
        out.append({"key": pre, "slug": f"doa2_{pre.lower()}", "name": name, "aliases": aliases,
                    "kind": "character", "costumes": costumes})
    for pre in VARIANTS:
        if not fam or pre in fam:
            out.append({"key": pre, "slug": f"doa2_{pre.lower()}", "name": f"{pre} (variant)",
                        "aliases": [], "kind": "variant", "costumes": sorted(set(fam.get(pre, ["0"])), key=int)})
    return out


def export(gdi: str, out_dir: str, key: str, costume: str = "0", *, assemble: bool = True,
           native_cache: str | Path | None = None) -> dict:
    """Decompose a costume into native files, real mesh parts and PNG textures.

    Parts retain native local coordinates. Skeleton confidence stays missing
    until the runtime joint map is verified; no false assembled bind pose.
    The native CHR/BIN are preserved for exact binary reconstruction.
    """
    from .gdrom import GDRom
    from .doa2_geometry import decode_chr
    from .doa2_textures import descriptors, decode
    from . import uap
    if key not in {e["key"] for e in roster()}:
        raise ValueError(f"Unknown fighter family {key}")
    if not costume.isdigit() or len(costume) > 2:
        raise ValueError("Costume must be a one/two digit disc costume number")
    stem = f"{key}{costume.zfill(2)}"
    disc = GDRom(gdi)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    names = [f"DOA2/{stem}.{e}" for e in ("CHR", "BIN", "SUP", "APV") if f"DOA2/{stem}.{e}" in disc.files]
    bodies = {name: disc.read(name) for name in names}
    acs = None
    if "1ST_READ.BIN" in disc.files:
        from .doa2_bindings import resolve_archive_binding, accessory_filename
        from .doa2_native_export.source_binding import owned_path
        executable = disc.read("1ST_READ.BIN")
        binding=resolve_archive_binding(executable,f"DOA2/{stem}.CHR")
        accessory = accessory_filename(executable, binding['render_slot'], binding['costume'])
        acs = owned_path(disc, accessory['filename'])
        bodies[acs] = disc.read(acs)
        control='DOA2/'+binding['files']['control'].upper()
        if control in disc.files: bodies[control]=disc.read(control)
    files = []
    for name, body in bodies.items():
        dest = out / Path(name).name
        dest.write_bytes(body)
        files.append(dest.name)
    chr_data, bin_data = bodies[names[0]], bodies[names[1]]
    archive = decode_chr(chr_data)
    textures = descriptors(chr_data, bin_data)
    (out / "textures").mkdir(exist_ok=True)
    materials = []
    for tex in textures:
        rel = f"textures/tex{tex.index:03d}.png"
        decode(tex, bin_data).save(out / rel)
        files.append(rel)
        materials.append({"name": f"native_texture_{tex.index}", "texture": rel,
                          "source": {"width": tex.width, "height": tex.height,
                                     "pixel_format": tex.pixel, "data_format": tex.format,
                                     "bin_offset": tex.offset, "bytes": tex.size}})
    meshes, nodes = [], []
    for model in archive["models"]:
        for k, mesh in enumerate(model["meshes"]):
            if not mesh["triangles"]:
                continue
            verts = mesh["vertices"]
            tid = mesh["texture_id"]
            if tid >= len(textures) or tid < -1:
                raise ValueError(f"Invalid native material texture slot {tid}")
            name = f"part{model['id']:03d}_material{k:03d}"
            nodes.append({"name": name, "mesh": len(meshes), "skinned": False})
            meshes.append({"name": name, "positions": [list(v[:3]) for v in verts],
                           "normals": [list(v[3:6]) for v in verts], "uvs": [list(v[6:8]) for v in verts],
                           "indices": [i for tri in mesh["triangles"] for i in tri],
                           "material": tid if tid >= 0 else None})
    mot_name = f"DOA2/{MOT_FILES.get(key, key)}.MOT"
    if mot_name in disc.files:
        body = disc.read(mot_name)
        (out / Path(mot_name).name).write_bytes(body)
        files.append(Path(mot_name).name)
        bodies[mot_name] = body
    manifest = {"uap_version": "0.1", "name": f"doa2_{key.lower()}_{costume.zfill(2)}",
                "source": {"game_id": next(iter(GAME_IDS)), "title": next(iter(GAME_IDS.values())),
                           "resource_ids": list(bodies), "extraction_method": "gbox.doa2_chars native NaomiLib decoder",
                           "part_coordinates": "native local model coordinates; runtime joint transforms required"},
                "coordinate_system": {"up": "Y", "forward": "-Z", "handedness": "right"},
                "meshes": meshes, "materials": materials, "nodes": nodes, "roots": list(range(len(nodes))),
                "skeleton": [], "animations": [],
                "container_facts": {"n_models": len(archive["models"]), "n_textures": len(textures),
                                    "model_pointer_base": archive["pointer_base"], "chr_bytes": len(chr_data),
                                    "bin_bytes": len(bin_data)},
                "confidence": {"entity": "verified", "geometry": "verified", "materials": "verified",
                               "textures": "verified", "skeleton": "missing", "skin_weights": "missing",
                               "animations": "missing", "runtime_linkage": "partial", "source_identity": "verified"},
                "provenance": [{"file": name, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
                               for name, body in bodies.items()]}
    validated = uap.Manifest.model_validate(manifest)
    issues = uap.validate(validated, out)
    if issues:
        raise ValueError("DOA2 asset validation: " + "; ".join(issues))
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    (out / f"{stem}_parts.glb").write_bytes(uap.to_glb(validated, out))
    files.extend(["manifest.json", f"{stem}_parts.glb"])
    core = None
    if assemble and "1ST_READ.BIN" in disc.files:
        from . import doa2_rig as R, doa2_seams as S
        import numpy as np
        profile = R.for_archive(disc, f"DOA2/{stem}.CHR")
        if native_cache is not None:
            from .doa2_native_export import assemble_native, write_complete
            core = assemble_native(executable, stem, chr_data, bin_data,
                                   bodies[f"DOA2/{stem}.SUP"], bodies[acs], profile,
                                   cache_directory=native_cache, acs_filename=acs.rsplit('/', 1)[-1])
            path = write_complete(out / f"{stem}_rigged.gltf", core, stem)
            profile = core['profile']
        else:
            core = S.assemble_core(chr_data, bodies[f"DOA2/{stem}.SUP"], bin_data,
                                   np.asarray(profile['world']), profile['component_models'],
                                   S.native_coefficients(executable))
            path = S.write_core(out / f"{stem}_rigged.gltf", core, profile, stem)
        files.insert(0, path.name)
        (out / "rig.json").write_text(json.dumps(profile, indent=2), encoding="utf-8")
        (out / "core-report.json").write_text(json.dumps(core['report'], indent=2), encoding="utf-8")
        files += ["rig.json", "core-report.json"]
    else:
        files.insert(0, f"{stem}_parts.glb")
    assembled_confidence = manifest['confidence'] | ({'skeleton': 'partial', 'skin_weights': 'partial'} if core else {})
    return {"files": files, "manifest": manifest, "assembled_confidence": assembled_confidence,
            "roles": {role: role for role in profile['roles']} if core else {},
            "core_report": core['report'] if core else None,
            "assembly": "complete_native_source" if core and native_cache is not None else
                        "partial_core" if core else "unassembled_parts"}
