"""RE6 (Switch) cast roster: a different extracted Smash donor on every native body slot, as a LayeredFS overlay.

RE6 Switch keeps one body archive per native character **and costume** (`uPl00LeonUsa.arc`, `uPl00LeonAsia.arc`,
`uPl00LeonOmake00.arc`, ... 51 body slots measured including Carla and the helper), and the Mercenaries character select
picks a native character and costume each round (`gbox.mercs.round_controls.Controls.choose_character` already
randomises that choice). A roster mod that replaces every body slot therefore shows a different Smash donor each round
through the game's own selection, without a per-round relaunch.

The donors are library entries (`characters.list_all`: the `*_ssbu` and `*_ssbb` collections) whose rig carries the 18
anatomical roles; :func:`plan` assigns a distinct donor to every slot when the pool is large enough.
:func:`build` authors each body with :mod:`gbox.re6_switch_models` and blanking of the native head/hands, then writes
one `switch_mods` overlay (only the changed `romfs/nativeNXx64/arc/NX/*.arc` files).
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from . import characters as C
from . import re6_switch_models as M
from . import switch_mods

DEFAULT_NAME = "re6sw_smash_cast"


class CastError(ValueError):
    """The roster cannot be planned or built from the given donors."""


def donor_pool(library: Path) -> list[dict]:
    """Library entries that can be a body donor (skinned, all 18 roles, SSBU/SSBB collections)."""
    out = []
    for meta in C.list_all(Path(library)):
        rig = meta.get("rig") or {}
        roles = rig.get("roles") or {}
        if not rig.get("skinned") or not isinstance(roles, dict):
            continue
        if len(roles) < 18:
            continue
        if len(set(roles.values())) != len(roles):
            continue                                  # two roles sharing one joint cannot be a full-body donor (R.O.B.)
        out.append(meta)
    out.sort(key=lambda meta: meta["slug"])
    if not out:
        raise CastError("no library character with a complete 18-role rig is available as a donor")
    return out


def plan(romfs: Path, pool: list[dict], *, seed: int = 7, slots: list[tuple[str, str]] | None = None
         ) -> dict[tuple[str, str], dict]:
    """{(character, costume): donor meta} with a distinct donor per slot when the pool allows it."""
    available = slots or sorted(M.buildable_slots(romfs))
    if not available:
        raise CastError("no body slots")
    rng = random.Random(seed)
    donors = list(pool)
    rng.shuffle(donors)
    if len(donors) < len(available):
        raise CastError(f"{len(donors)} donors cannot fill {len(available)} slots distinctly; pass fewer slots or a "
                        f"larger pool")
    return {slot: donors[i] for i, slot in enumerate(available)}


def build(config, romfs: Path, library: Path, assignment: dict[tuple[str, str], dict], *, name: str = DEFAULT_NAME,
          height: float = 180.0, progress=None) -> dict:
    """Author every assigned body slot and write the overlay build; returns a receipt (never touches the RomFS)."""
    romfs = Path(romfs)
    library = Path(library)
    root = M.archive_root(romfs)
    bodies = M.body_arcs(romfs)
    cache = Path(config.cache) / "re6sw_cast_cache" / name
    cache.mkdir(parents=True, exist_ok=True)
    changes: dict[str, dict] = {}
    receipts, skipped = [], []
    for index, ((character, costume), meta) in enumerate(sorted(assignment.items()), 1):
        body = bodies.get((character, costume))
        if body is None:
            raise CastError(f"no body archive for {character}/{costume}")
        source = library / meta["slug"] / meta["model"]
        if not source.is_file():
            raise CastError(f"donor {meta['slug']} has no model file at {source}")
        if progress:
            progress(f"[{index}/{len(assignment)}] {character}/{costume} <- {meta['name']}")
        cached_arc, cached_receipt = cache / f"{body.stem}.arc", cache / f"{body.stem}.json"
        try:
            if cached_arc.is_file() and cached_receipt.is_file():
                payload = cached_arc.read_bytes()
                receipt = json.loads(cached_receipt.read_text())
            else:
                payload, receipt = M.build_body(body.read_bytes(), source, source_roles=meta["rig"]["roles"],
                                                height=height)
                cached_arc.write_bytes(payload)
                cached_receipt.write_text(json.dumps(receipt))
        except (M.SwitchModelError, ValueError) as exc:
            # one donor that cannot be fitted (odd skeleton/normals) must not throw away the whole roster
            skipped.append({"character": character, "costume": costume, "donor": meta["slug"],
                            "error": f"{type(exc).__name__}: {exc}"})
            if progress:
                progress(f"  skipped {meta['slug']}: {exc}")
            continue
        changes[f"romfs/{M.ARCHIVE_DIR.as_posix()}/{body.name}"] = {"bytes": payload}
        receipt = {"character": character, "costume": costume, "donor": meta["slug"], "donor_name": meta["name"],
                   "archive": body.name, **receipt}
        for stem in M.part_stems(body):
            part = root / f"{stem}.arc"
            if part.is_file():
                blank_cache = cache / "parts" / part.name
                blank_cache.parent.mkdir(parents=True, exist_ok=True)
                if blank_cache.is_file():
                    changes[f"romfs/{M.ARCHIVE_DIR.as_posix()}/{part.name}"] = {"bytes": blank_cache.read_bytes()}
                else:
                    data = M.blank_arc(part.read_bytes())
                    blank_cache.write_bytes(data)
                    changes[f"romfs/{M.ARCHIVE_DIR.as_posix()}/{part.name}"] = {"bytes": data}
                receipt.setdefault("blanked_parts", []).append(part.name)
        receipts.append(receipt)
    note = "RE6 Switch cast roster: " + ", ".join(f"{r['character']}/{r['costume']}<-{r['donor']}" for r in receipts)
    written = switch_mods.write_files(config, M.GAME_ID, name, changes,
                                      create={"title_id": M.TITLE_ID, "kind": "file", "game_title": "re6"},
                                      note=note[:9000])
    out = {"mod": name, "game_id": M.GAME_ID, "title_id": M.TITLE_ID,
           "files": len(changes), "slots": len(receipts), "skipped": skipped,
           "donors": sorted({r["donor"] for r in receipts}),
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
