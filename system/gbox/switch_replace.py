"""One call that replaces a pack's mesh with a donor's proportions - the reusable step every replacement needs.

The four things the MercMode panel offers are one operation with different arguments:

    remove clothes        hide the materials of a garment slot          -> hide_materials
    swap clothes          morph the garment slot onto another character -> donor = another pack's slot
    swap character        morph the player pack onto an enemy's slot    -> template pl*, donor em*
    replace zombies       morph an enemy pack onto a collection model   -> template em*, donor = a .glb

The pieces already exist and are measured: `glb_donor` turns any extracted model into a BIN with its skeleton, `band_affine` transfers
proportions with a strength that follows the target's bands, `re4hd_edit` patches a slot in place, and `switch_mods` writes a
LayeredFS build. This module is the join: resolve the title's RomFS, pick the donor, apply, write, report.

It reports what it did rather than asserting it: the blend used, the slots touched, the vertices moved and whether any slot was skipped
and why.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import re4gc_inventory as INV
from . import re4hd_affine as AFFINE
from . import re4hd_edit as EDIT
from . import re4hd_models as MODELS

MIN_SLOT_VERTICES = 800          # below this a slot is an accessory or a prop, not a body: too small for a banded transfer


class ReplaceError(RuntimeError):
    """The replacement cannot be made; the message names the pack, the slot and the reason."""


@dataclass
class ReplaceReport:
    """What a replacement did, in the terms a page shows."""
    pack: str
    donor: str
    build: str = ""
    blend: float | None = None
    slots: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    vertices_changed: int = 0
    written: str = ""

    @property
    def touched(self) -> int:
        return len(self.slots)

    def as_dict(self) -> dict[str, Any]:
        return {"pack": self.pack, "donor": self.donor, "build": self.build, "blend": self.blend,
                "slots": self.slots, "skipped": self.skipped, "touched": self.touched,
                "vertices_changed": self.vertices_changed, "written": self.written}


def romfs_root(config, title_id: str) -> Path:
    """The extracted RomFS for a title, wherever this installation keeps it."""
    candidates = []
    root = getattr(config, "romfs", None)
    if root:
        candidates.append(Path(root) / title_id)
    candidates.append(Path.home() / "gBox_alt" / "switch" / "romfs" / title_id)
    for candidate in candidates:
        if (candidate / "bio4").is_dir():
            return candidate
    raise ReplaceError(f"no extracted RomFS with bio4/ for {title_id} (tried {', '.join(str(c) for c in candidates)})")


def _pack_slots(data: bytes) -> list[dict]:
    try:
        return INV.bin_slots(data, endian="<")
    except ValueError as exc:
        raise ReplaceError(f"not a DAT pack: {exc}") from exc


def donor_mesh(donor_glb: str | None, donor_pack: Path | None, donor_slot: int = 0):
    """The donor as a BIN: from a collection .glb (keeping its skeleton) or from another pack's slot."""
    if donor_glb:
        from . import glb_donor
        try:
            return MODELS.bin_read(glb_donor.donor_bin(donor_glb))
        except (MODELS.BINError, ValueError, OSError) as exc:
            raise ReplaceError(f"the donor {donor_glb} could not be converted: {exc}") from exc
    if donor_pack is None:
        raise ReplaceError("a donor is required: pass donor_glb (a collection model) or donor_pack (another pack)")
    data = Path(donor_pack).read_bytes()
    slots = _pack_slots(data)
    if not 0 <= donor_slot < len(slots):
        raise ReplaceError(f"{Path(donor_pack).name} holds {len(slots)} BIN slot(s), so slot {donor_slot} does not exist")
    entry = slots[donor_slot]
    try:
        return MODELS.bin_read(data[entry["offset"]:entry["offset"] + entry["size"]])
    except (MODELS.BINError, ValueError) as exc:
        raise ReplaceError(f"slot {donor_slot} of {Path(donor_pack).name} is not a mesh: {exc}") from exc


def replace_pack(config, title_id: str, pack: str, *, donor_glb: str | None = None, donor_pack: str | None = None,
                 donor_slot: int = 0, blend: float | None = None, bands: int = 6, build: str = "",
                 min_vertices: int = MIN_SLOT_VERTICES, hide: list[int] | None = None,
                 write: bool = True, game_id: str = "", hide_mode: str = "vanish") -> ReplaceReport:
    """Morph `pack`'s body slots toward the donor's proportions and write the result into a LayeredFS build.

    `hide` takes material indices to collapse instead of (or before) the transfer, which is the "remove clothes" case. With `write=False`
    the result is computed and reported but nothing is written - what a page calls to preview a change.
    """
    root = romfs_root(config, title_id)
    pack_path = root / "bio4" / "em" / pack
    if not pack_path.is_file():
        raise ReplaceError(f"{pack} is not in {root / 'bio4' / 'em'}")
    data = pack_path.read_bytes()
    slots = _pack_slots(data)
    name = build or f"gbox-replace-{Path(pack).stem}"
    source = donor_glb or (str(donor_pack) if donor_pack else "")
    if not source and not hide:
        raise ReplaceError("a donor is required: pass donor_glb or donor_pack (or hide= for a hide-only edit)")
    # "remove clothes" is a hide with no donor at all: the transfer loop is skipped and only the materials are collapsed.
    donor = donor_mesh(donor_glb, Path(donor_pack) if donor_pack else None, donor_slot) if source else None

    report = ReplaceReport(pack=pack, donor=os.path.basename(source) if source else "hide-only", build=name)
    patched = data
    for index, entry in enumerate(slots if donor is not None else []):
        body = patched[entry["offset"]:entry["offset"] + entry["size"]]
        try:
            mesh = MODELS.bin_read(body)
        except (MODELS.BINError, ValueError) as exc:
            report.skipped.append({"slot": index, "reason": f"not a mesh ({str(exc)[:60]})"})
            continue
        if mesh.pos is None or len(mesh.pos) < min_vertices:
            report.skipped.append({"slot": index, "reason": f"{0 if mesh.pos is None else len(mesh.pos)} vertices "
                                                            f"(under {min_vertices})"})
            continue
        try:
            replacement, bands_report = AFFINE.band_affine_bin(mesh, donor, bands=bands, blend=blend)
            used_blend = blend if blend is not None else AFFINE.auto_blend(mesh, donor, bands=bands)
        except (MODELS.BINError, ValueError) as exc:
            report.skipped.append({"slot": index, "reason": f"transfer refused: {str(exc)[:80]}"})
            continue
        replacement = MODELS.pad_to(replacement, entry["size"])
        patched = patched[:entry["offset"]] + replacement + patched[entry["offset"] + entry["size"]:]
        report.blend = round(float(used_blend), 3) if report.blend is None else max(report.blend,
                                                                                   round(float(used_blend), 3))
        report.slots.append({"slot": index, "vertices": len(mesh.pos), "blend": round(float(used_blend), 3),
                             "bands": bands_report})
        report.vertices_changed += len(mesh.pos)

    if donor is not None and not report.slots:
        raise ReplaceError(f"no slot of {pack} was big enough to transfer (min {min_vertices} vertices); "
                           f"skipped: {report.skipped[:3]}")

    if hide:
        try:
            patched, edit_report = EDIT.edit_pack(patched, 0, hide=hide, pack_name=pack, hide_mode=hide_mode)
            report.skipped.append({"slot": 0, "reason": f"materials hidden: {edit_report.detail.get('hidden')}"})
        except EDIT.EditError as exc:
            raise ReplaceError(f"the hide step was refused: {exc}") from exc

    if write:
        from . import switch_mods
        # the catalog key the launcher resolves a build through; the route passes it because only it holds the catalog
        game_id = game_id or _game_id(config, title_id)
        result = switch_mods.write_files(config, game_id, name, {f"romfs/bio4/em/{pack}": {"bytes": patched}},
                                         create={"title_id": title_id, "kind": "file", "game_title": title_id},
                                         note=f"replace {pack} with {report.donor}")
        report.build = str(result.get("mod") or name) if isinstance(result, dict) else name
        report.written = str(result.get("dir", "")) if isinstance(result, dict) else ""
    return report


def _game_id(config, title_id: str) -> str:
    """The catalog game id a mod build must be filed under, because the launcher resolves a launch's mod by that key.

    Filing a build under the bare title id makes it invisible to `launch?mod=`, which is how a build silently does nothing. The
    catalog is the authority: match the Switch entries' serial against the title id.
    """
    store = getattr(config, "_catalog_store", None) or getattr(config, "store", None)
    database = getattr(store, "db", None)
    if database is not None:
        try:
            rows = database.execute(
                "SELECT game_id, body FROM catalog WHERE json_extract(body,'$.platform')='switch'").fetchall()
            for game_id, body in rows:
                try:
                    entry = json.loads(body)
                except (TypeError, ValueError):
                    continue
                if str(entry.get("serial") or "").upper() == title_id.upper():
                    return str(game_id)
        except Exception:                                     # noqa: BLE001 - the catalog may be absent or mid-migration
            pass
    return title_id.upper()
