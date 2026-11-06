"""Swap whole models between MT Framework .arc archives - the reusable half of the lab's model-swap.

Two measured rules hold this together:

* **The model is the entry whose payload is `MRL\\0`**, not the largest entry under `model\\`. `uWp06.arc` carries two
  `wp0600` entries - the MRL model (1,047 B) and a MOD container (13,617 B) - and choosing by size wrote the MOD into
  the MRL slot, which the engine cannot parse, so the title hung at `loading`. Selecting by magic is what made the
  object shape swap work (verified 2026-11-06: mine <- grenade reached `screen=playing`, rounds 1).
* **An MRL model names its textures in its own path table**, and the slot archive may not hold them. Copying the missing
  entries in by the path the model names is what makes a swap self-contained (the grenade names `om4e00_*`; the mine's
  archive had never heard of them, and 3 entries had to be added).

Directions that are established, and one that is not:

* enemy <- character: **works** (uEm6c.arc took uPl00ChrisNormal.arc's model and 21 textures; the round played);
* character <- enemy: builds but the title never produced a session - not established, suspect the rig/animation
  mismatch. Callers should keep the player side to textures (`swap_arc`) unless that is solved.
"""
from __future__ import annotations

import zlib

from . import mt_arc, mt_model


class SwapError(ValueError):
    """The archive pair cannot be swapped without breaking the slot."""


MAGICS = (b"MRL\x00", b"MOD\x00")


def model_indices(arc: mt_arc.Arc, magic: bytes | None = None) -> list[int]:
    """The indexes of the entries that are model payloads (MRL models and MOD meshes), optionally of one magic.

    These are the two halves of a model and both must travel for a shape swap: `MRL\\0` is the model resource (its material
    block and the texture paths it names) and `MOD\\0` is the geometry (measured 2026-11-06: `MOD` carries a header of
    offsets into vertex data followed by floats, while `MRL` carries the path table). Replacing only the MRL changes the
    materials and leaves the shape, which is what the first "shape" swap actually did.
    """
    wanted = (magic,) if magic else MAGICS
    found = []
    for index, entry in enumerate(arc.entries):
        try:
            raw = zlib.decompress(entry.data)
        except zlib.error:
            continue
        if raw[:4] in wanted:
            found.append(index)
    return found


def model_paths(data: bytes) -> list[str]:
    """Every texture path that any MRL model in this archive names."""
    import zlib as _z
    paths: list[str] = []
    arc = mt_arc.parse(data)
    for entry in arc.entries:
        try:
            raw = _z.decompress(entry.data)
        except _z.error:
            continue
        if raw[:4] != mt_model.MAGIC:
            continue
        try:
            paths.extend(mt_model.parse(raw).paths)
        except mt_model.ModelError:
            continue
    return paths


def swap_models(slot: bytes, donor: bytes, *, textures: bool = True, geometry: bool = False) -> dict:
    """The slot archive wearing the donor's model(s), with the textures those models name.

    `geometry` brings the donor's `MOD` mesh as well. It is OFF by default because a MOD does not travel safely between
    slots that were not built for it: mine <- grenade with the MRL **and** the MOD both swapped boots to a white screen
    (measured 2026-11-06, frame brightness a constant 238.6, `screen=unknown`), while the MRL alone plays a full round.
    A MOD carries its own offsets into vertex data and its own bone/material counts, so only a slot with a matching
    skeleton can take one - that is the constraint a Sonic/Mario import has to satisfy.

    Returns {"data": the new .arc bytes, "meshes": [entry names replaced], "textures": [paths added]}.
    """
    slot_arc, donor_arc = mt_arc.parse(slot), mt_arc.parse(donor)
    data = slot
    meshes: list[str] = []
    swapped = 0
    # pair by magic, not by order: a slot and a donor can list their MRL and MOD entries in different orders, and an MRL
    # written over a MOD slot is exactly the kind of mismatch that hangs the load
    for magic in (MAGICS if geometry else MAGICS[:1]):
        slot_models, donor_models = model_indices(slot_arc, magic), model_indices(donor_arc, magic)
        if not slot_models or not donor_models:
            continue
        for slot_i, donor_i in zip(slot_models, donor_models):
            data = mt_arc.replace_at(data, slot_i, donor_arc.entries[donor_i].data)
            meshes.append(slot_arc.entries[slot_i].name)
            swapped += 1
    if not swapped:
        raise SwapError("this swap needs a model payload in both archives")
    added: list[str] = []
    if textures:
        slot_arc = mt_arc.parse(data)
        present = {e.name for e in slot_arc.entries}
        by_base = {e.name.rsplit("\\", 1)[-1]: e for e in donor_arc.entries}
        for path in model_paths(data):
            if path in present:
                continue
            donor_entry = by_base.get(path.rsplit("\\", 1)[-1])
            if donor_entry is None:
                continue
            slot_arc.entries.append(mt_arc.Entry(name=path, hash=donor_entry.hash, tag=donor_entry.tag,
                                                 size=donor_entry.size, offset=0, data=donor_entry.data))
            present.add(path)
            added.append(path)
        if added:
            data = mt_arc.build(slot_arc)
    return {"data": data, "meshes": meshes, "textures": added}
