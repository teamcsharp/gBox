"""GoldenEye 007 (Europe, N64) character writer: a collection character as a player or enemy.

`characters op=use game="GoldenEye 007 (Europe)" character=<slug> slot=<slot>` routes here.
Slot naming follows the 80 PAL body files: `body:<name>` where name is one of the 80 body
filenames (e.g. body:CdjbondZ for James Bond, body:CborisZ for Boris, etc.).

The build is gbox.goldeneye_writer: the donor is retargeted to the target body's native
node tree using the shared Ninja retarget (gbox.ninja_swap.fit), decimated until it fits
the body's triangle budget, and written back into the ROM with byte-exact coverage
(gbox.goldeneye_writer.serialize). The ROM is modified in place; the mod directory
contains the modified ROM copy.

The original ROM (owned by the operator) is never written. The mod is a copy
(cache/mods/<game>/<name>/).
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

from gbox import goldeneye_files as F, goldeneye_reader as R, goldeneye_writer as W
from gbox import ninja_swap as NS

GAME_IDS = {
    "eecd1708cb2b8d14": "GoldenEye 007 (Europe)",
}


def _pretty(name: str) -> str:
    """'CdjbondZ' -> 'James Bond'."""
    stem = name
    if stem.startswith("C"):
        stem = stem[1:]
    if stem.endswith("Z"):
        stem = stem[:-1]
    # Convert camelCase/PascalCase to spaced words
    words, cur = [], ""
    for ch in stem:
        if ch.isupper() and cur and not cur[-1].isupper():
            words.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        words.append(cur)
    # Special mappings for known names
    special = {
        "Dj Bond": "James Bond",
        "Boris": "Boris",
        "Orumov": "Orumov",
        "Trevelyan": "Trevelyan",
        "Boiler Trev": "Boris",
        "Valentin": "Valentin",
        "Xenia": "Xenia",
        "Baron Samedi": "Baron Samedi",
        "Jaws": "Jaws",
        "May Day": "May Day",
        "Oddjob": "Oddjob",
        "Natalya": "Natalya",
        "Armour Guard": "Armour Guard",
        "Comm Guard": "Comm Guard",
        "Great Guard": "Great Guard",
        "Navy Guard": "Navy Guard",
        "Snow Guard": "Snow Guard",
        "Boiler Bond": "Boris",
        "Suit Bond": "James Bond",
        "Timber Bond": "James Bond",
        "Snow Bond": "James Bond",
        "Blue Woman": "Female Guard",
        "Fat Tech Woman": "Tech Woman",
        "Tech Woman": "Tech Woman",
        "Jean Woman": "Female Guard",
        "Grey Man": "Grey Man",
        "Blue Man": "Blue Man",
        "Red Man": "Red Man",
        "Cardi Man": "Cardi Man",
        "Check Man": "Check Man",
        "Tech Man": "Tech Man",
        "Pilot": "Pilot",
        "Great Guard 2": "Great Guard",
        "Blue Cam Guard": "Camouflage Guard",
        "Moon Guard": "Moon Guard",
        "Moon Female": "Moon Female",
        "Suit Lf Hand": "Suit Lf Hand",
        "Head Karl": "Head Karl",
        "Head Alan": "Head Alan",
        "Head Pete": "Head Pete",
        "Head Martin": "Head Martin",
        "Head Mark": "Head Mark",
        "Head Duncan": "Head Duncan",
        "Head Shaun": "Head Shaun",
        "Head Dwayne": "Head Dwayne",
        "Head B": "Head B",
        "Head Dave": "Head Dave",
        "Head Grant": "Head Grant",
        "Head Des": "Head Des",
        "Head Chris": "Head Chris",
        "Head Lee": "Head Lee",
        "Head Neil": "Head Neil",
        "Head Jim": "Head Jim",
        "Head Robin": "Head Robin",
        "Head Steveh": "Head Steveh",
        "Head Balaclava": "Head Balaclava",
        "Head Bike": "Head Bike",
        "Head Graham": "Head Graham",
        "Head Stevee": "Head Stevee",
        "Head Joel": "Head Joel",
        "Head Scott": "Head Scott",
        "Head Joe": "Head Joe",
        "Head Ken": "Head Ken",
        "Head Joe 2": "Head Joe 2",
        "Head Mishkin": "Head Mishkin",
        "Head Sally": "Head Sally",
        "Head Marion": "Head Marion",
        "Head Mandy": "Head Mandy",
        "Head Vivien": "Head Vivien",
        "Head Brosnan Boiler": "Head Brosnan",
        "Head Brosnan Suit": "Head Brosnan",
        "Head Brosnan Timber": "Head Brosnan",
        "Head Brosnan Snow": "Head Brosnan",
        "Head Brosnan": "Head Brosnan",
        "Spice Bond": "Spice Bond",
    }
    result = " ".join(w[:1].upper() + w[1:].lower() for w in words if w).strip()
    return special.get(result, result) or name


def cast() -> list[dict]:
    """The 80 PAL body files as characters."""
    out = []
    for name in R.ROSTER_NAMES:
        slug = f"ge_{name.lower().replace('_', '').replace('z', '')}"
        out.append({
            "slot": f"body:{name}",
            "name": _pretty(name),
            "native_name": name,
            "collection_slug": slug,
            "aliases": [name, _pretty(name)]
        })
    return out


def cast_slots() -> list[dict]:
    """The cast menu for characters op=collect / char_coverage.cast_slots."""
    rows = []
    for c in cast():
        rows.append({
            "slot": c["slot"],
            "name": c["name"],
            "kind": "character",
            "writer": "gbox.goldeneye_swap",
            "status": "unverified"
        })
    return rows


def parse_slot(slot: str | None) -> str:
    """-> native body name (e.g. 'CdjbondZ')."""
    s = (slot or "body:CdjbondZ").strip()
    if s.startswith("body:"):
        name = s[5:].strip()
        # Normalize
        if not name.startswith("C"):
            name = "C" + name
        if not name.endswith("Z"):
            name = name + "Z"
        if name not in R.ROSTER_NAMES:
            raise ValueError(f"unknown GoldenEye body {name!r} ({', '.join(R.ROSTER_NAMES[:5])}...)")
        return name
    # Try direct name
    name = s
    if not name.startswith("C"):
        name = "C" + name
    if not name.endswith("Z"):
        name = name + "Z"
    if name not in R.ROSTER_NAMES:
        raise ValueError(f"unknown GoldenEye body {s!r}")
    return name


def is_slot(slot: str | None) -> bool:
    try:
        parse_slot(slot)
        return True
    except ValueError:
        return False


def mod_name(slug: str, slot: str) -> str:
    """-> 'ge_<slug>_as_<body>'."""
    name = parse_slot(slot)
    body = name.replace("C", "").replace("Z", "").lower().replace("_", "")
    return f"ge_{slug}_as_{body}"


def _write_body(ge, rom_path, body_name: str, body_data: bytes) -> int:
    """Serialize a retargeted body back into the ROM through the writer.

    The ROM slot holds a rarezip-compressed Z-file, so the inflated body must
    be re-compressed and size-checked by the writer; a raw byte write at the
    file offset would leave the loader an unloadable ROM.
    """
    from gbox import goldeneye_writer as GW
    try:
        new_rom = GW.splice_file(ge, body_name, body_data)
    except Exception as exc:
        err = getattr(GW, "GoldenEyeFormatError", None)
        if err is None or not isinstance(exc, err):
            raise
        new_rom = GW.rom_relayout(ge, body_name, body_data)
    rom_path.write_bytes(new_rom)
    return len(body_data)

def use(ctx, meta: dict, game: dict, inp) -> dict:
    """characters op=use for GoldenEye: slot=body:<name> (default CdjbondZ). Built on the
    control plane as ge_<slug>_as_<body> (a ROM copy), launched on request. Unverified in game."""
    from gbox import characters as C, filemods, fit_events as FE
    slot = inp.slot or "body:CdjbondZ"
    body_name = parse_slot(slot)
    gid, name = game["game_id"], mod_name(meta["slug"], slot)
    
    # Check if mod already exists
    have = (filemods.mod_dir(ctx.config, gid, name) / ".gbox-mod.json").exists()
    built = None
    
    if getattr(inp, "rebuild", False) or not have:
        if not C.library_root(ctx.config).is_dir():
            raise ValueError("GoldenEye swaps are built on the control-plane node (the Spark): run this there")
        
        # Get the source ROM
        rom_path = C._rom_path(ctx.config, game)
        if not rom_path.exists():
            raise ValueError(f"ROM not found: {rom_path}")
        
        # Copy ROM to mod directory
        mod_dir = filemods.mod_dir(ctx.config, gid, name)
        mod_dir.mkdir(parents=True, exist_ok=True)
        mod_rom = mod_dir / "007_GoldenEye_Europe_norm.z64"
        mod_rom.write_bytes(rom_path.read_bytes())
        
        FE.plan([(slot, meta["slug"], f"{meta.get('name') or meta['slug']} -> {slot}")])
        FE.model(slot)
        
        # Get donor model
        model_path = Path(meta["model"]) if meta.get("model") else None
        if not model_path or not model_path.exists():
            raise ValueError(f"Model not found: {meta.get('model')}")
        
        roles = meta.get("rig", {}).get("roles", {})
        
        # Get target body file
        ge = F.GoldenEyeROM.from_bytes(mod_rom.read_bytes())
        try:
            body_data = ge.read_file(body_name)
        except Exception as e:
            raise ValueError(f"Failed to read body {body_name}: {e}")
        
        # Parse target nodes
        root_off = ge.root_offsets.get(body_name)
        if root_off is None:
            raise ValueError(f"No root offset for {body_name}")
        
        target_nodes = R.parse_nodes(body_data, root_off)
        
        # Build target spec for retarget
        # For now, use the first render node as the target
        render_nodes = [n for n in target_nodes if n.op in (0x04, 0x18)]
        if not render_nodes:
            raise ValueError(f"No render nodes in {body_name}")
        
        # Use the first render node's triangles as the budget
        budget_triangles = len(render_nodes[0].triangles) if render_nodes[0].triangles else 100
        
        # Retarget donor to target
        FE.stage("retarget", data={"budget_triangles": budget_triangles})
        
        # Use ninja_swap.fit for the actual retargeting
        # We need to create a target spec that matches GoldenEye's expectations
        target_spec = NS.target_from_ge(body_data, target_nodes, body_name)
        
        work_dir = mod_dir / "work"
        work_dir.mkdir(exist_ok=True)
        
        r = NS.fit(model_path, roles, target_spec, work_dir, meta["name"], 
                   (budget_triangles * 2, budget_triangles, budget_triangles // 2, 
                    max(1, budget_triangles // 3), max(1, budget_triangles // 4)),
                   None, lambda x: x, 256, None, FE.progress)
        
        # Get the modified body
        modified_body = r["data"]
        
        # Write back to ROM using goldeneye_writer
        FE.stage("write", data={"body_bytes": len(modified_body)})
        
        # Z-file, so the retargeted body must be re-compressed and size-checked
        # (a raw byte write leaves the loader an unloadable ROM).
                _write_body(ge, mod_rom, body_name, modified_body)
        
        # Create mod metadata
        (mod_dir / ".gbox-mod.json").write_text(
            '{"name": "' + name + '", "game_id": "' + gid + '", "slot": "' + slot + '", "donor": "' + meta["slug"] + '"}'
        )
        
        built = {"files": [str(mod_rom)], "body_bytes": len(modified_body)}
        
        C._api(ctx, "POST", f"/api/characters/{meta['slug']}/targets",
               json={"game_id": gid, "slot": slot, "mod": name, "nodes": [C.HOST_OS],
                     "notes": f"replaces {slot} (gbox.goldeneye_swap); unverified in game; preview targets/ge_*_preview.png"})
    
    out = {"mod": name, "build": built, "slot": slot, "verification": "unverified in game (docs/goldeneye.md)"}
    if not getattr(inp, "launch", False):
        return out | {"status": "built" if built else "ready"}
    return out | {"status": "built+launched" if built else "launched", "launch": C._launch(ctx, gid, name, C.HOST_OS)}


def main(argv=None) -> int:
    """Offline build: python -m gbox.goldeneye_swap <rom> <donor dir (meta.json)> <out dir> --slot body:CdjbondZ"""
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("rom")
    ap.add_argument("donor", help="a collection entry directory (meta.json + model)")
    ap.add_argument("out")
    ap.add_argument("--slot", default="body:CdjbondZ")
    a = ap.parse_args(argv)
    
    from gbox import goldeneye_files as F, goldeneye_reader as R
    
    meta_path = Path(a.donor) / "meta.json"
    if not meta_path.exists():
        raise ValueError(f"meta.json not found: {meta_path}")
    meta = json.loads(meta_path.read_text())
    
    body_name = parse_slot(a.slot)
    mod_dir = Path(a.out)
    mod_dir.mkdir(parents=True, exist_ok=True)
    mod_rom = mod_dir / "007_GoldenEye_Europe_norm.z64"
    mod_rom.write_bytes(Path(a.rom).read_bytes())
    
    ge = F.GoldenEyeROM.from_bytes(mod_rom.read_bytes())
    body_data = ge.read_file(body_name)
    root_off = ge.root_offsets.get(body_name)
    if root_off is None:
        raise ValueError(f"No root offset for {body_name}")
    target_nodes = R.parse_nodes(body_data, root_off)
    
    # Get donor
    model_path = Path(a.donor) / meta["model"]
    roles = meta.get("rig", {}).get("roles", {})
    
    # Build target spec
    render_nodes = [n for n in target_nodes if n.op in (0x04, 0x18)]
    budget_triangles = len(render_nodes[0].triangles) if render_nodes and render_nodes[0].triangles else 100
    
    # Retarget
    work_dir = mod_dir / "work"
    work_dir.mkdir(exist_ok=True)
    
    import gbox.ninja_swap as NS
    target_spec = NS.target_from_ge(body_data, target_nodes, body_name)
    
    r = NS.fit(model_path, roles, target_spec, work_dir, meta["name"],
               (budget_triangles * 2, budget_triangles, budget_triangles // 2,
                max(1, budget_triangles // 3), max(1, budget_triangles // 4)),
               None, lambda x: x, 256, None, lambda p, m: print(f"{p}%: {m}"))
    
    # Write back
    modified_body = r["data"]
    body_offset = ge.file_offsets.get(body_name)
    if body_offset is None:
        raise ValueError(f"No offset for {body_name}")
    
    # Z-file, so the retargeted body must be re-compressed and size-checked
    # (a raw byte write leaves the loader an unloadable ROM).
                _write_body(ge, mod_rom, body_name, modified_body)
    
    print(f"Built {meta['name']} as {body_name} -> {mod_rom}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
