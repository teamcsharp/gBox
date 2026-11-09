"""RE6 (Switch) cast roster: a different library character on every native body slot, as a LayeredFS overlay.

RE6 Switch keeps one body archive per native character **and costume** (`uPl00LeonUsa.arc`, `uPl00LeonAsia.arc`,
`uPl00LeonOmake00.arc`, ... 51 body slots measured), and the Mercenaries character select picks a native character and
costume each round (`gbox.mercs.round_controls.Controls.choose_character` already randomises that choice). A roster mod
that replaces body slots therefore shows a different donor each round through the game's own selection, without a
per-round relaunch; several overlays built from different seeds rotate the whole cast between launches.

The donors are **any** library entries (`characters.list_all`) whose rig carries the anatomical roles the writer
binds by - not one collection: Smash fighters, Metal Gear, Soul Calibur, Def Jam, 007, Stranglehold, PSO ... The
``full`` tier wants all 18 roles on distinct joints; the ``core`` tier accepts a rig without a neck and/or clavicles
(Dead or Alive, the wrestlers, Sonic Adventure), which the keep-bind writer can still author because those vertices
bind to the next named ancestor. :func:`plan` draws a seeded random assignment with no character twice in one overlay
and, with ``mix``, no source game twice while unused games remain. :func:`build` authors each body with
:mod:`gbox.re6_switch_models`, blanks the native head/hands and writes one `switch_mods` overlay (only the changed
`romfs/nativeNXx64/arc/NX/*.arc` files).
"""
from __future__ import annotations

import json
import random
import re
from pathlib import Path

from . import characters as C
from . import re6_switch_models as M
from . import switch_mods

DEFAULT_NAME = "re6sw_smash_cast"
FULL_ROLES = tuple(M.ROLE_IDS)                                   # the 18 anatomy roles
CORE_ROLES = tuple(role for role in M.REQUIRED if role != "neck")   # what the keep-bind writer cannot do without
TIERS = {"full": FULL_ROLES, "core": CORE_ROLES}
MODEL_SUFFIXES = (".glb", ".gltf")


class CastError(ValueError):
    """The roster cannot be planned or built from the given donors."""


def franchise(meta: dict) -> str:
    """The donor's source game with region and disc tags removed, so two dumps of one game are one franchise."""
    source = meta.get("source") if isinstance(meta.get("source"), dict) else {}
    title = str(source.get("game_title") or "").strip()
    title = re.sub(r"\s*\((?:USA|Europe|Japan|Korea|World|En|Fr|De|Es|It|Disc)[^)]*\)", "", title)
    return re.sub(r"[\s:\-]+", " ", title).strip().lower() or "(unknown source)"


def _game_key(meta: dict) -> str:
    """The grouping key of a source game: letters and digits only, so `Soul Calibur II` and `Soulcalibur II` agree."""
    return re.sub(r"[^a-z0-9]+", "", franchise(meta))


def identity(meta: dict) -> tuple[str, str]:
    """(source game, character name): one character collected twice under two game ids is still one cast member."""
    return _game_key(meta), str(meta.get("name") or meta.get("slug") or "").strip().lower()


def donor_check(meta: dict, *, tier: str = "full", library: Path | None = None) -> str | None:
    """None when the entry can be a body donor in this tier, else the reason it cannot (short, countable)."""
    if tier not in TIERS:
        raise CastError(f"tier must be one of {sorted(TIERS)}")
    model = str(meta.get("model") or "")
    if not model:
        return "no model file"
    if not model.lower().endswith(MODEL_SUFFIXES):
        return "not a 3D model (sprite sheet / image)"
    if library is not None and not (Path(library) / str(meta.get("slug")) / model).is_file():
        return "no model file"
    rig = meta.get("rig") if isinstance(meta.get("rig"), dict) else {}
    roles = rig.get("roles") if isinstance(rig.get("roles"), dict) else {}
    if not rig.get("skinned"):
        return "model is not skinned"
    wanted = TIERS[tier]
    absent = [role for role in wanted if role not in roles]
    if absent:
        return f"rig resolves {sum(1 for role in FULL_ROLES if role in roles)}/18 roles"
    present = [roles[role] for role in FULL_ROLES if role in roles]
    if len(set(present)) != len(present):
        return "two roles share one joint"            # map_weights needs distinct anchors (R.O.B.'s single leg)
    return None


def donor_pool(library: Path, *, tier: str = "full") -> list[dict]:
    """Library entries that can be a body donor: skinned, the tier's roles on distinct joints, whatever the game."""
    out = [meta for meta in C.list_all(Path(library)) if donor_check(meta, tier=tier) is None]
    out.sort(key=lambda meta: meta["slug"])
    if not out:
        raise CastError("no library character with a complete role rig is available as a donor")
    return out


def pool_report(entries: list[dict], *, tier: str = "full") -> dict:
    """How much of a library can be cast, per source game, and why the rest cannot.

    ``entries`` are library metas (`characters.list_all`). Returns the usable count, the distinct characters among
    them (:func:`identity`), a per-franchise table and the rejection reasons with their counts.
    """
    games: dict[str, dict] = {}
    reasons: dict[str, int] = {}
    usable, people = 0, set()
    labels: dict[str, str] = {}
    for meta in entries:
        label = labels.setdefault(_game_key(meta), franchise(meta))
        row = games.setdefault(label, {"entries": 0, "usable": 0, "rejected": {}})
        row["entries"] += 1
        why = donor_check(meta, tier=tier)
        if why is None:
            row["usable"] += 1
            usable += 1
            people.add(identity(meta))
        else:
            row["rejected"][why] = row["rejected"].get(why, 0) + 1
            reasons[why] = reasons.get(why, 0) + 1
    return {"tier": tier, "entries": len(entries), "usable": usable, "distinct_characters": len(people),
            "franchises_with_donors": sum(1 for row in games.values() if row["usable"]),
            "by_franchise": dict(sorted(games.items(), key=lambda item: (-item[1]["usable"], item[0]))),
            "rejected": dict(sorted(reasons.items(), key=lambda item: -item[1]))}


def _draw(pool: list[dict], count: int, rng: random.Random, mix: bool) -> list[dict]:
    """`count` donors in a seeded random order: no character twice, and with `mix` franchises taken in turn."""
    donors = list(pool)
    rng.shuffle(donors)
    seen, unique = set(), []
    for meta in donors:                               # the same character under two slugs is one cast member
        key = identity(meta) if meta.get("source") else ("", str(meta.get("slug")))
        if key not in seen:
            seen.add(key)
            unique.append(meta)
    if not mix:
        return unique
    groups: dict[str, list[dict]] = {}
    for meta in unique:
        groups.setdefault(_game_key(meta), []).append(meta)
    order = list(groups)
    rng.shuffle(order)
    out: list[dict] = []
    while len(out) < count and any(groups.values()):
        for name in order:                            # one from each game before any game gives a second
            if groups[name]:
                out.append(groups[name].pop())
            if len(out) >= count:
                break
    return out


def plan(romfs: Path, pool: list[dict], *, seed: int = 7, slots: list[tuple[str, str]] | None = None,
         per_character: bool = False, mix: bool = False) -> dict[tuple[str, str], dict]:
    """{(character, costume): donor meta}: a seeded random draw with no donor character twice in the overlay.

    ``per_character`` gives each native character one donor for all of its costumes (what a build that should look
    the same whichever costume the round draws needs). ``mix`` spreads the draw over the source games: no game
    supplies a second donor while another game has not supplied one, so a seven-slot overlay shows seven franchises
    when the pool has that many.
    """
    available = slots or sorted(M.buildable_slots(romfs))
    if not available:
        raise CastError("no body slots")
    rng = random.Random(seed)
    if per_character:
        characters = sorted({character for character, _costume in available})
        donors = _draw(pool, len(characters), rng, mix)
        if len(donors) < len(characters):
            raise CastError(f"{len(donors)} donors cannot fill {len(characters)} characters")
        chosen = {character: donors[index] for index, character in enumerate(characters)}
        return {slot: chosen[slot[0]] for slot in available}
    donors = _draw(pool, len(available), rng, mix)
    if len(donors) < len(available):
        raise CastError(f"{len(donors)} donors cannot fill {len(available)} slots distinctly; pass fewer slots or a "
                        f"larger pool")
    return {slot: donors[i] for i, slot in enumerate(available)}


def author_slot(romfs: Path, library: Path, slot: tuple[str, str], meta: dict, *, height: float = 180.0,
                textures: bool = False, source_geometry=None, blank: bool = True) -> tuple[dict, dict]:
    """One body slot authored from one donor: ({archive name: bytes}, receipt). Nothing is written.

    The donor mesh is drawn with a body material vetted from the costume's own texture set
    (:func:`gbox.re6_switch_models.donor_material`): opaque and, when there is one, without the cloth displacement.
    Material 0 is not assumed - on Helena (USA) and Chris (Asia) it is `pl_nuki`, an alpha-tested patch material that
    would cut the donor out by a patch texture's alpha.
    """
    romfs, library = Path(romfs), Path(library)
    character, costume = slot
    body = M.body_arcs(romfs).get((character, costume))
    if body is None:
        raise CastError(f"no body archive for {character}/{costume}")
    source = library / meta["slug"] / meta["model"]
    if not source.is_file():
        raise CastError(f"donor {meta['slug']} has no model file at {source}")
    material = M.donor_material(romfs, body)
    payload, receipt = M.build_body(body.read_bytes(), source, source_roles=meta["rig"]["roles"], height=height,
                                    textures=textures, source_geometry=source_geometry,
                                    material_index=material["index"])
    files = {body.name: payload}
    receipt = {"character": character, "costume": costume, "donor": meta["slug"], "donor_name": meta["name"],
               "donor_source": (meta.get("source") or {}).get("game_title"), "archive": body.name,
               "material_choice": material, **receipt}
    if blank:
        for stem in M.part_stems(body):
            part = M.archive_root(romfs) / f"{stem}.arc"
            if part.is_file():
                files[part.name] = M.blank_arc(part.read_bytes())
                receipt.setdefault("blanked_parts", []).append(part.name)
    return files, receipt


def build(config, romfs: Path, library: Path, assignment: dict[tuple[str, str], dict], *, name: str = DEFAULT_NAME,
          height: float = 180.0, textures: bool = False, progress=None) -> dict:
    """Author every assigned body slot and write the overlay build; returns a receipt (never touches the RomFS).

    ``textures`` authors the body with the donor's atlas UVs and writes that atlas into every `0x2B` albedo of each
    character's texture set (`gbox.re6_switch_models.texture_changes`); it therefore expects a per-character plan.
    """
    romfs = Path(romfs)
    library = Path(library)
    bodies = M.body_arcs(romfs)
    cache = Path(config.cache) / "re6sw_cast_cache" / (name + ("_tex" if textures else ""))
    cache.mkdir(parents=True, exist_ok=True)
    changes: dict[str, dict] = {}
    receipts, skipped, atlases = [], [], {}
    mesh_cache: dict[str, tuple] = {}
    if textures:
        # one atlas + one atlas-UV mesh per donor, reused by every slot the donor fills
        for meta in {meta["slug"]: meta for meta in assignment.values()}.values():
            source = library / meta["slug"] / meta["model"]
            if progress:
                progress(f"packing {meta['slug']} atlas")
            vertices, triangles, atlas, _appearance = M.mtf_materials.source_mesh(
                source, atlas_size=(1024, 1024), strict_samplers=False)
            mesh_cache[meta["slug"]] = (vertices, triangles, atlas)
    for index, ((character, costume), meta) in enumerate(sorted(assignment.items()), 1):
        body = bodies.get((character, costume))
        if body is None:
            raise CastError(f"no body archive for {character}/{costume}")
        if progress:
            progress(f"[{index}/{len(assignment)}] {character}/{costume} <- {meta['name']}")
        cached_arc, cached_receipt = cache / f"{body.stem}.arc", cache / f"{body.stem}.json"
        parts = cache / "parts"
        try:
            if cached_arc.is_file() and cached_receipt.is_file():
                receipt = json.loads(cached_receipt.read_text())
                files = {body.name: cached_arc.read_bytes()}
                files |= {part: (parts / part).read_bytes() for part in receipt.get("blanked_parts", [])}
            else:
                cached = mesh_cache.get(meta["slug"])
                files, receipt = author_slot(romfs, library, (character, costume), meta, height=height,
                                             textures=textures,
                                             source_geometry=(cached[0], cached[1]) if cached else None)
                parts.mkdir(parents=True, exist_ok=True)
                for part, data in files.items():
                    (cached_arc if part == body.name else parts / part).write_bytes(data)
                cached_receipt.write_text(json.dumps(receipt))
        except CastError:
            raise
        except (M.SwitchModelError, ValueError, OSError) as exc:
            # one donor that cannot be fitted (odd skeleton/normals) must not throw away the whole roster
            skipped.append({"character": character, "costume": costume, "donor": meta["slug"],
                            "error": f"{type(exc).__name__}: {exc}"})
            if progress:
                progress(f"  skipped {meta['slug']}: {exc}")
            continue
        for part, data in files.items():
            changes[f"romfs/{M.ARCHIVE_DIR.as_posix()}/{part}"] = {"bytes": data}
        receipts.append(receipt)
    if textures:
        for character in sorted({row["character"] for row in receipts}):
            meta = next(meta for (slot_character, _costume), meta in assignment.items()
                        if slot_character == character)
            atlas = atlases.get(character) or mesh_cache[meta["slug"]][2]
            atlases[character] = atlas
            changes.update(M.texture_changes(romfs, character, atlas))
    note = "RE6 Switch cast roster: " + ", ".join(f"{r['character']}/{r['costume']}<-{r['donor']}" for r in receipts)
    written = switch_mods.write_files(config, M.GAME_ID, name, changes,
                                      create={"title_id": M.TITLE_ID, "kind": "file", "game_title": "re6"},
                                      note=note[:9000])
    out = {"mod": name, "game_id": M.GAME_ID, "title_id": M.TITLE_ID, "textured": textures,
           "files": len(changes), "slots": len(receipts), "skipped": skipped,
           "donors": sorted({r["donor"] for r in receipts}),
           "franchises": sorted({franchise({"source": {"game_title": r.get("donor_source")}}) for r in receipts}),
           "receipts": receipts, "written": written.get("files") or sorted(changes)}
    folder = Path(config.cache) / "mods" / M.GAME_ID / name
    try:
        (folder / ".gbox-cast.json").write_text(json.dumps(out, indent=1))
    except OSError:
        pass
    return out


def status(config, name: str = DEFAULT_NAME) -> dict:
    """What a written roster contains, read back from its `.gbox-cast.json` (empty when absent)."""
    folder = Path(config.cache) / "mods" / M.GAME_ID / name
    receipt = folder / ".gbox-cast.json"
    if not receipt.is_file():
        return {"mod": name, "built": False, "folder": str(folder)}
    data = json.loads(receipt.read_text())
    return {"mod": name, "built": True, "folder": str(folder), "files": data.get("files"),
            "slots": data.get("slots"), "donors": data.get("donors")}
