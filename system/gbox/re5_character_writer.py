"""Bounded RE5 Switch character-library route using original native counterparts.

The two exact RE5 PS3 collection entries identify Chris/Sheva, whose original
Switch archives are already owned and extracted. This selects that Switch
counterpart; it does not import the collection GLB or PS3 archive. Edited models,
other donors, enemies and automatic cast assignment remain unsupported.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from .re_switch import RE5_TITLE_ID

# Whole-player ARC filename substitution booted an invisible, nonfunctional
# Chris slot in the 2026-11-09 live test. Only individually proven composed
# player pairs may be exposed through characters use/live_use.
VERIFIED_NATIVE_PAIRS: frozenset[tuple[str, str]] = frozenset({("sheva", "chris")})
UNVERIFIED_REASON = ("This native RE5 player pair has not passed slot composition and gameplay acceptance. "
                     "Only original Sheva normal into Chris normal is supported. Whole-player archive filename "
                     "substitution can leave the player invisible; no files were written.")
NATIVE_ACCEPTANCE = {
    "recipe": "native_player_resource_composition_v1", "donor": "sheva", "target": "chris",
    "written_sha256": "ee04244c4d3012904b4858cef1ce10352f20361963fcc52787543f4ecf9a9800",
    "observed_at_unix": 1794204816, "selected_character": "Chris (BSAA)", "stage": "Public Assembly",
    "score_from": 300, "score_to": 2400, "kills_from": 1, "kills_to": 8,
    "visible_native_donor": True, "gameplay_verified": True,
    "coverage": "Native Sheva body/materials and advancing combat in the Chris BSAA slot; other costumes, "
                "cutscenes, physics fidelity and feet contact are not verified",
}


def _native_donor(meta: dict | None) -> str:
    from . import re5ps3_collection as source
    from .re5ps3_roles import CHRIS_MODEL, SHEVA_MODEL

    if not isinstance(meta, dict):
        raise ValueError("Choose one original RE5 library character; automatic cast replacement is not supported")
    origin, evidence = meta.get("source") or {}, meta.get("native_evidence") or {}
    if not isinstance(origin, dict) or not isinstance(evidence, dict):
        raise ValueError("The library character has no exact native RE5 provenance")
    if any(meta.get(k) for k in ("variant_of", "variant", "props", "derived_from")) or origin.get("variant_of") \
            or (isinstance(meta.get("rig"), dict) and meta["rig"].get("scale")):
        raise ValueError("Edited or variant models need a custom mesh writer; native counterparts preserve original appearance")
    rows = {
        "re5ps3_chris_normal": ("chris", source.CHRIS, r"pawn\pl\pl00\model\pl0000", CHRIS_MODEL),
        "re5ps3_sheva_normal": ("sheva", source.SHEVA, r"pawn\pl\pl01\model\pl0100", SHEVA_MODEL),
    }
    row = rows.get(meta.get("slug"))
    if row is None:
        raise ValueError("Only the original RE5 Chris and Sheva library entries have native Switch counterparts; "
                         "custom donors such as Sonic still require gameplay-verified mesh import")
    character, archive, model, model_hash = row
    hashes = {p: source.FILES[p][1] for p in (source.SFO, source.EBOOT, archive)}
    files = [f"{p} SHA256 {digest}" for p, digest in hashes.items()] + [model]
    if not (origin.get("game_id") == source.GAME_ID and origin.get("platform") == "ps3"
            and origin.get("files") == files and meta.get("extraction_tool") == "gbox.re5ps3_collection"
            and meta.get("kind") == "character" and isinstance(meta.get("name"), str) and bool(meta["name"].strip())
            and meta.get("model") == meta["slug"] + ".glb"
            and meta.get("re5ps3_reader") == source.READER_VERSION
            and evidence.get("game_id") == source.GAME_ID and evidence.get("title_id") == source.TITLE_ID
            and evidence.get("disc_version") == "02.00" and evidence.get("app_version") == "01.00"
            and evidence.get("archive_member") == archive and evidence.get("archive_sha256") == hashes[archive]
            and evidence.get("model_member") == model and evidence.get("source_sha256") == model_hash
            and evidence.get("source_files_sha256") == hashes):
        raise ValueError("Native counterpart selection requires the exact original RE5 collection provenance and hashes")
    return character


def _target(inp, arcs: dict[str, str]) -> str:
    def named(value):
        value = str(value or "").strip().replace("\\", "/").casefold()
        for prefix in ("character:", "player:"):
            value = value.removeprefix(prefix)
        for name, path in arcs.items():
            if value in (name, path.casefold(), Path(path).name.casefold()):
                return name
        raise ValueError("Name the target player slot explicitly: " + ", ".join(arcs)
                         + "; generic player does not identify the currently selected character")

    slot, target = getattr(inp, "slot", "player"), getattr(inp, "target", "")
    if target:
        resolved = named(target)
        if slot not in (None, "", "player") and named(slot) != resolved:
            raise ValueError("The named slot and target identify different RE5 players")
        return resolved
    return named(slot)


def _romfs(config) -> Path:
    from . import skin_swap, switch_mods, re5_char_swap
    roots = [skin_swap.romfs_root(RE5_TITLE_ID), switch_mods.base_romfs(config, RE5_TITLE_ID)]
    for root in roots:
        if root is not None and (Path(root) / re5_char_swap.ARCHIVE_DIR).is_dir():
            return Path(root)
    raise ValueError("The owned RE5 Switch RomFS with nativeNXx64/ImgNX/Archive must already be extracted on this worker")


def plan_player_pair(root: Path, donor: str, target: str) -> tuple[dict, dict]:
    """Shared panel/library gate and immutable-source composition; no writes or launch."""
    from . import re5_char_swap, re5_player_archive, skin_swap
    if (donor, target) not in VERIFIED_NATIVE_PAIRS:
        raise ValueError(UNVERIFIED_REASON)
    arcs = skin_swap.CHARACTER_ARCS[RE5_TITLE_ID]
    archive_root = re5_char_swap.archive_root(root).resolve()
    for name in (donor, target):
        path = root / arcs[name]
        if not path.resolve().is_relative_to(archive_root) or not path.is_file():
            raise ValueError(f"The owned Switch archive for {name} is absent or outside its archive directory")
    payload, composition = re5_player_archive.compose((root / arcs[target]).read_bytes(),
                                                     (root / arcs[donor]).read_bytes(), target=target, donor=donor)
    if composition['written_sha256'] != NATIVE_ACCEPTANCE['written_sha256']:
        raise ValueError("Composed player archive differs from the exact gameplay-tested artifact; a new acceptance is required")
    acceptance = NATIVE_ACCEPTANCE
    scope = {"route": "native_archive_counterpart", "complete": False, "gameplay_verified": bool(acceptance['gameplay_verified']),
             "written_platform": "switch", "donor_archive": arcs[donor], "target_archive": arcs[target],
             "written_sha256": hashlib.sha256(payload).hexdigest(), "composition": composition,
             "gameplay_acceptance": dict(acceptance),
             "notes": ["The destination's model/material lookup names and motion/control resources are retained; "
                       "the donor's model, materials and exact referenced textures are composed into that slot",
                       "Only the reported native pair and gameplay coverage are verified; other costumes, "
                       "cutscenes, movies, physics fidelity and feet contact are unverified",
                       "The title restarts to load the archive; the current round is not preserved"]}
    return {"romfs/" + arcs[target]: {"bytes": payload}}, scope


def plan(ctx, game: dict, inp, meta: dict | None) -> dict:
    """Return one composed native player archive and its scope; never write or launch."""
    from . import re5_char_swap, skin_swap, switch_mods
    try:
        tid = switch_mods.title_id_for(None, game.get("serial") or (game.get("launch") or {}).get("title_id"))
        if game.get("platform") != "switch" or tid != RE5_TITLE_ID:
            raise ValueError("This native counterpart writer supports only the measured RE5 Switch title")
        if getattr(inp, "op", "use") == "cast_swap" or getattr(inp, "pairs", None) or getattr(inp, "assignments", None):
            raise ValueError("Choose one named player and one original RE5 library character; cast assignment is not supported")
        if getattr(inp, "head_scale", 0) or getattr(inp, "scale", None) or getattr(inp, "props", None):
            raise ValueError("Native counterpart selection cannot apply custom model edits or proportions")
        donor = _native_donor(meta)
        arcs = skin_swap.CHARACTER_ARCS[RE5_TITLE_ID]
        target = _target(inp, arcs)
        if donor == target:
            raise ValueError(f"{target.title()} already uses that native normal archive; no replacement was written")
        if (donor, target) not in VERIFIED_NATIVE_PAIRS:
            return {"reason": UNVERIFIED_REASON}
        root = _romfs(ctx.config)
        changes, scope = plan_player_pair(root, donor, target)
        scope.update(source_platform="ps3", collection_model_used=False,
                     requested_character={"slug": meta["slug"], "name": meta["name"]})
        scope['notes'].insert(0, "The original PS3 collection identity selects the same character's owned Switch archive; "
                                "the collection GLB and PS3 bytes are not imported")
        return {"changes": changes, "kind": "character", "replacement_scope": scope,
                "slots": [{"slot": target, "donor": meta["slug"], "archive": arcs[target],
                           "native_counterpart": arcs[donor]}],
                "note": f"native Switch counterpart: {target} <- {donor} (original PS3 collection identity)"}
    except (ValueError, OSError, re5_char_swap.SwapError) as exc:
        return {"reason": str(exc)}
