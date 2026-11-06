"""Random character-skin swaps for MercMode rounds.

A round can play with another character's model group in the slot being played: the chosen character's archive is
rebuilt so its model entry carries a random other character's model group (gbox.mt_arc), and that rebuilt archive
is written into a LayeredFS build (gbox.switch_mods) the launch then plays. The slot keeps its own entry names, so
the game still finds the file it asks for.

Only titles whose character archives are mapped are swapped (RE5 Switch today: uPl00Chris*, uPl01Sheba*,
uPl02Jill*); everything else returns None and the round plays normally.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from . import mt_arc

# title id -> the character archives MercMode may swap, by the name the operator sees
CHARACTER_ARCS = {
    "010018100CD46000": {
        "chris": "nativeNXx64/ImgNX/Archive/uPl00ChrisNormal.arc",
        "sheva": "nativeNXx64/ImgNX/Archive/uPl01ShebaNormal.arc",
        "jill": "nativeNXx64/ImgNX/Archive/uPl02JillCos1.arc",
    },
}


def romfs_root(title_id: str) -> Path | None:
    """The extracted RomFS tree a swap is built from, when it exists."""
    candidate = Path.home() / "gBox_alt" / "switch" / "romfs" / title_id.upper()
    return candidate if candidate.is_dir() else None


def candidates(title_id: str) -> dict:
    """What a title's arcs look like, so mapping a NEW title is mechanical instead of a hunt.

    Every title lays its characters out differently: RE5 keeps a whole character per `uPlXX<Name><Variant>.arc`
    (41 character-ish archives), while RE6 keeps 3,209 archives under arc/NX with only per-part arcs for heads and
    hands (`uPl00AcHeadLeonUsa`, `uPl00HandLeftLeonUsa`) and nothing named after the body at all. This scans the
    extracted tree and groups the names - the step that has to happen before CHARACTER_ARCS can gain a title.
    """
    root = romfs_root(title_id)
    if root is None:
        return {"title_id": str(title_id).upper(), "extracted": False, "groups": {}, "arc_dirs": [],
                "character_arcs": [], "character_arc_count": 0}
    dirs = sorted({p.parent for p in root.rglob("*.arc")})
    groups: dict = {}
    for directory in dirs:
        for path in directory.glob("*.arc"):
            prefix = re.match(r"[A-Za-z]+", path.stem)
            key = (prefix.group(0)[:6] if prefix else "?") + " @ " + directory.name
            groups[key] = groups.get(key, 0) + 1
    characters = sorted({p.stem for d in dirs for p in d.glob("uPl*.arc")})
    # what a swap could actually target inside one character archive, so the caller can name a group when the default
    # heuristic would pick the wrong one (an RE6 head arc's largest group is its hair)
    sample = {}
    for stem in characters[:6]:
        path = next((d / (stem + ".arc") for d in dirs if (d / (stem + ".arc")).is_file()), None)
        if path is None:
            continue
        try:
            maps_by_group = material_groups(mt_arc.parse(path.read_bytes()))
        except mt_arc.ArcError:
            continue
        sample[stem] = {"default_group": body_group(maps_by_group),
                        "groups": {name: sorted(maps) for name, maps in list(maps_by_group.items())[:12]}}
    return {"title_id": str(title_id).upper(), "extracted": True,
            "arc_dirs": [str(d.relative_to(root)) for d in dirs],
            "groups": dict(sorted(groups.items(), key=lambda kv: -kv[1])[:20]),
            "character_arcs": characters[:40], "character_arc_count": len(characters),
            "material_groups": sample}


def model_entry(arc):
    return next((e for e in arc.entries if "\\model\\" in e.name), None)


def material_groups(arc) -> dict:
    """{group: {kind: entry}} for a character's model material sets (base/mask/normal maps)."""
    groups: dict = {}
    for entry in arc.entries:
        name = entry.name
        if "\\model\\" not in name or "\\" not in name:
            continue
        base = name.rsplit("\\", 1)[-1]
        for suffix in ("_BM", "_MM", "_NM"):
            if base.endswith(suffix):
                groups.setdefault(base[:-len(suffix)], {})[suffix[1:]] = entry
                break
    return groups


def body_group(groups: dict) -> str | None:
    """The character's own skin set: the evfXXXX_01 base group, else a Body/Skin group, else the largest base map."""
    bases = {g: m for g, m in groups.items() if g.lower().startswith("evf") and "_01" in g and m.get("BM")}
    named = {g: m for g, m in groups.items() if any(w in g.lower() for w in ("body", "skin")) and m.get("BM")}
    pool = bases or named or {g: m for g, m in groups.items() if m.get("BM")}
    if not pool:
        return None
    return max(pool, key=lambda g: pool[g]["BM"].size)


def swap_arc(data: bytes, donor_data: bytes, *, follow_tag: bool = False,
             group: str | None = None, donor_group_name: str | None = None) -> tuple[bytes, str, str]:
    """The slot archive wearing the donor character's skin: its body group's base/mask/normal maps are replaced.

    Returns (bytes, slot group, donor group). Material entries keep their own names; a map the donor lacks is left
    alone. By default a map moves only when its tag matches (same dimensions and format), because a texture of
    another size under this tag is not a valid swap. With follow_tag the slot's tag moves with the donor's data, so
    the pair stays self-consistent and a differently sized skin can be tried.

    `group` names the slot's group explicitly. The heuristic below suits RE5 (a whole character per archive, skin in
    evfXXXX_01) but not every title: an RE6 head arc's largest group is the hair, and its hand arcs carry no material
    groups at all, so the caller can say which group it means instead of accepting a guess.
    """
    slot_arc, donor_arc = mt_arc.parse(data), mt_arc.parse(donor_data)
    slot_groups, donor_groups = material_groups(slot_arc), material_groups(donor_arc)
    slot_name = group if group in slot_groups else body_group(slot_groups)
    donor_name = donor_group_name if donor_group_name in donor_groups else body_group(donor_groups)
    if slot_name is None or donor_name is None:
        raise mt_arc.ArcError("a character has no body skin group to swap")
    # entry indices in the slot archive, so a repeated name cannot send a replacement to the wrong entry
    index = {e.name: i for i, e in enumerate(slot_arc.entries)}
    patched = data
    moved, skipped = 0, []
    for kind in ("BM", "MM", "NM"):
        dst, src = slot_groups[slot_name].get(kind), donor_groups[donor_name].get(kind)
        if dst is None or src is None:
            continue
        if dst.tag != src.tag and not follow_tag:
            skipped.append(dst.name)
            continue
        patched = mt_arc.replace_at(patched, index[dst.name], src.data,
                                    tag=(src.tag if follow_tag and dst.tag != src.tag else None))
        moved += 1
    if not moved:
        raise mt_arc.ArcError("the donor's skin maps do not match the slot's format (nothing safe to swap)")
    return patched, slot_name, donor_name


def random_swap_build(config, game_id: str, title_id: str, rng, *, name: str | None = None,
                      title: str = "", log=None) -> dict | None:
    """Build a LayeredFS overlay that plays `title_id`'s character with another character's model group.

    Returns {'build', 'slot', 'donor'} or None when the title has no mapped characters (the round plays normally).
    """
    arcs = CHARACTER_ARCS.get(str(title_id).upper())
    root = romfs_root(title_id)
    if not arcs or root is None:
        return None
    names = sorted(arcs)
    target, donor = rng.sample(names, 2)
    target_arc, donor_arc = root / arcs[target], root / arcs[donor]
    if not target_arc.is_file() or not donor_arc.is_file():
        return None
    try:
        patched, slot, donor_entry = swap_arc(target_arc.read_bytes(), donor_arc.read_bytes())
    except mt_arc.ArcError as exc:
        if log:
            log("skin_swap_failed", error=str(exc)[:200])
        return None
    build = name or f"skin-{target}-as-{donor}"
    try:
        from . import switch_mods
        folder = Path(switch_mods.create_build(config, game_id, build, title_id.upper(),
                                               game_title=title or game_id, kind="file"))
    except Exception as exc:                                 # noqa: BLE001 - a launch must never fail on a swap
        if log:
            log("skin_swap_build_failed", error=str(exc)[:200])
        return None
    target_path = folder / "romfs" / arcs[target]
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(patched)
    if log:
        log("skin_swap_built", build=build, slot=slot, donor=donor_entry, bytes=len(patched))
    return {"build": build, "slot": slot, "donor": donor_entry, "target": target, "source": donor,
            "at": time.time()}
