"""Compose a measured native player into its destination's resource namespace.

A player ARC filename is not its internal lookup name. Copying Sheva's entire
ARC to Chris's filename left Chris invisible in the engine. This bounded recipe
keeps Chris's lookup names and motion/control resources, replaces the paired MOD
and MRL payloads, and imports the MRL's exact native TEX dependencies. It neither
renames embedded strings nor translates skeletons. Gameplay acceptance is owned
by the caller; successful composition alone never means the pair is supported.
"""
from __future__ import annotations

from dataclasses import replace
import hashlib
import zlib

from . import mt_arc, mt_model, mtf_mrl

NATIVE_SHA256 = {
    "chris": "8ab0dc181d1f6ec155e193c5820d1756d877acf711424863b16f7850b592f6c8",
    "sheva": "77e9ede6a6bf84d74fa487acaca77624e503377c2910d1af62dda0b7f914957e",
}
MODEL_PATHS = {"chris": r"pawn\pl\pl00\model\pl0000", "sheva": r"pawn\pl\pl01\model\pl0100"}
MOD_CLASS, MRL_CLASS, TEX_CLASS = 0x58A15856, 0x2749C8A8, 0x241F5DEB
EXTERNAL_TEXTURES = frozenset({r"system\texture\NullWhite", r"system\texture\DefaultCube_CM"})
REQUIRED_ANIMATION_IDS = frozenset(range(24))
MAX_RESOURCE_BYTES = 64 * 1024 * 1024


class PlayerArchiveError(ValueError):
    """The pair cannot be composed without guessing a resource dependency."""


def _raw(entry: mt_arc.Entry, magic: bytes) -> bytes:
    declared = entry.tag & 0x3FFFFFFF
    if entry.tag >> 30 != 1 or not 4 <= declared <= MAX_RESOURCE_BYTES:
        raise PlayerArchiveError(f"{entry.name}: unsupported compression tag or resource size")
    try:
        decoder = zlib.decompressobj()
        data = decoder.decompress(entry.data, declared + 1)
    except zlib.error as exc:
        raise PlayerArchiveError(f"{entry.name}: invalid wrapped resource") from exc
    if len(data) != declared or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise PlayerArchiveError(f"{entry.name}: compressed resource length does not match its tag")
    if not data.startswith(magic):
        raise PlayerArchiveError(f"{entry.name}: resource class and magic disagree")
    return data


def _index(archive: mt_arc.Arc) -> dict:
    if archive.version != 7:
        raise PlayerArchiveError("expected the measured Switch ARC version 7")
    result = {}
    for index, entry in enumerate(archive.entries):
        key = (entry.name, entry.hash)
        if key in result:
            raise PlayerArchiveError("duplicate resource name and class in player archive")
        result[key] = index
    return result


def _player(archive: mt_arc.Arc, index: dict, character: str):
    selected = []
    for resource_class, magic in ((MOD_CLASS, b"MOD\0"), (MRL_CLASS, b"MRL\0")):
        at = index.get((MODEL_PATHS[character], resource_class))
        if at is None:
            raise PlayerArchiveError(f"{character}: missing expected player model/material resource")
        selected.append((at, _raw(archive.entries[at], magic)))
    (model_index, model_data), (material_index, material_data) = selected
    model = mt_model.parse_mod(model_data)
    header = model.header()
    if (header["version"], header["revision"]) != (211, 0) or not model.split_valid():
        raise PlayerArchiveError("expected a complete native Switch MOD v211")
    animation_ids = set(model.bone_table()["anim_map"])
    if not REQUIRED_ANIMATION_IDS <= animation_ids:
        raise PlayerArchiveError("native player model lacks the measured common body animation IDs")
    mtf_mrl.inspect_bindings(material_data, model)
    return {"model_index": model_index, "material_index": material_index,
            "animation_ids": animation_ids, "bone_count": header["bone_count"],
            "textures": mtf_mrl.parse(material_data)["textures"]}


def compose(target_bytes: bytes, donor_bytes: bytes, *, target="chris", donor="sheva") -> tuple[bytes, dict]:
    """Return a self-contained candidate ARC and an honest composition receipt.

    Only the exact owned normal Sheva -> normal Chris pair is measured. Original
    archives are hash checked before parsing; caller supplies pristine bytes.
    All target entries except the two named model/material payloads stay intact.
    """
    if (donor, target) != ("sheva", "chris"):
        raise PlayerArchiveError("only the measured Sheva normal into Chris normal composition is available")
    for character, data in ((target, target_bytes), (donor, donor_bytes)):
        if hashlib.sha256(data).hexdigest() != NATIVE_SHA256[character]:
            raise PlayerArchiveError(f"{character}: original Switch archive SHA256 does not match the measured source")
    target_arc, donor_arc = mt_arc.parse(target_bytes), mt_arc.parse(donor_bytes)
    target_index, donor_index = _index(target_arc), _index(donor_arc)
    target_info = _player(target_arc, target_index, target)
    donor_info = _player(donor_arc, donor_index, donor)
    if len(set(donor_info["textures"])) != len(donor_info["textures"]):
        raise PlayerArchiveError("duplicate donor texture paths are not an unambiguous dependency table")
    entries = list(target_arc.entries)
    replaced = []
    for key in ("model_index", "material_index"):
        at, source = target_info[key], donor_arc.entries[donor_info[key]]
        entries[at] = replace(source, name=entries[at].name)
        replaced.append(at)
    appended, reused, external = [], [], []
    for path in donor_info["textures"]:
        source_index = donor_index.get((path, TEX_CLASS))
        if source_index is None:
            if path not in EXTERNAL_TEXTURES or path not in target_info["textures"]:
                raise PlayerArchiveError(f"donor material texture is missing: {path}")
            external.append(path)
            continue
        source = donor_arc.entries[source_index]
        _raw(source, b"TEX\0")
        existing = target_index.get((path, TEX_CLASS))
        if existing is not None:
            old = entries[existing]
            if old.data != source.data or old.tag != source.tag:
                raise PlayerArchiveError(f"texture dependency collides with a different target resource: {path}")
            reused.append(path)
        else:
            entries.append(replace(source))
            appended.append(path)
    result = mt_arc.build(mt_arc.Arc(target_arc.version, entries))
    reread = mt_arc.parse(result)
    if len(reread.entries) != len(entries):
        raise PlayerArchiveError("composed archive count changed on reread")
    # Offsets naturally change during rebuild; identities, tags and payloads may not.
    for actual, expected in zip(reread.entries, entries):
        if (actual.name, actual.hash, actual.tag, actual.data) != (expected.name, expected.hash, expected.tag, expected.data):
            raise PlayerArchiveError("composed archive resource failed byte-for-byte reread")
    _player(reread, _index(reread), target)
    report = {"recipe": "native_player_resource_composition_v1", "gameplay_verified": False,
              "target_sha256": NATIVE_SHA256[target], "donor_sha256": NATIVE_SHA256[donor],
              "written_sha256": hashlib.sha256(result).hexdigest(),
              "target_model_path": MODEL_PATHS[target], "donor_model_path": MODEL_PATHS[donor],
              "replaced_entry_indices": replaced, "preserved_target_entries": len(target_arc.entries) - len(replaced),
              "appended_textures": appended, "reused_textures": reused, "external_textures": external,
              "target_bones": target_info["bone_count"], "donor_bones": donor_info["bone_count"],
              "shared_animation_ids": sorted(target_info["animation_ids"] & donor_info["animation_ids"]),
              "donor_only_animation_ids": sorted(donor_info["animation_ids"] - target_info["animation_ids"]),
              "target_motion_and_control_resources_preserved": True,
              "limitations": ["Native donor skeleton and materials are preserved; engine animation/physics compatibility requires live acceptance",
                              "Other costumes, cutscenes and movies are unverified"]}
    return result, report
