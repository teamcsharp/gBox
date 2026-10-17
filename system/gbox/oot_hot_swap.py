"""Bounded, in-session OoT NPC replacements. Never launch or reset a game."""
from pathlib import Path
import struct


def bounded_model(original, skeleton, parts, materials, regions, head_dls=(), head_limb=None):
    """Encode entirely inside reclaimed model bytes, including the empty display list."""
    from . import oot_writer as W
    regions = [tuple(r) for r in regions]
    reserve = next((i for i, (a, b) in enumerate(regions) if b - ((a + 7) & ~7) >= 8), None)
    if reserve is None:
        raise ValueError("no space for an empty display list")
    a, b = regions[reserve]
    empty_at = (a + 7) & ~7
    regions[reserve] = (empty_at + 8, b)
    tail, dls, pieces = W.encode(parts, materials, 0x06000000 + len(original),
                                regions=[(0x06000000 + a, 0x06000000 + b)
                                         for a, b in regions if b > a])
    if tail:
        raise ValueError("the fitted model requires object growth")
    out = bytearray(original)
    out[empty_at:empty_at + 8] = W.ENDDL
    empty = 0x06000000 + empty_at
    for address, data in pieces.items():
        at = address & 0xFFFFFF
        if not any(a <= at and at + len(data) <= b for a, b in regions):
            raise ValueError("model encoder exceeded a reclaimed region")
        out[at:at + len(data)] = data
    for i, limb in enumerate(skeleton["limbs"]):
        if any(limb["dls"]):
            for k in range(len(limb["dls"])):
                struct.pack_into(">I", out, limb["at"] + 8 + 4 * k, dls.get(i, empty))
    for _oid, at in head_dls:
        out[at:at + 8] = W._w(0xDE010000, dls.get(head_limb, empty))
    if len(out) != len(original):
        raise ValueError("model patch changed the object size")
    return bytes(out)


def unsupported(message):
    return {"status": "unsupported_live_swap", "in_engine": False,
            "session_preserved": True, "message": message}


def use(ctx, meta, game, inp):
    from . import characters as C, oot_swap as O
    if not inp.session_id:
        raise ValueError("live_use needs a running session_id")
    session = C._session(ctx, inp.session_id)
    if not session or session.get("state") != "running" or session.get("game_id") != game["game_id"]:
        raise ValueError("the selected game session is no longer running")
    if not O.is_oot(game):
        return unsupported(f"{game['title']} has no live character writer. No restart or overlay was performed.")
    if not C.library_root(ctx.config).is_dir():
        cp = next((w["id"] for w in C._api(ctx, "GET", "/api/workers")
                   if w.get("os") == "linux" and w.get("online")), None)
        if not cp:
            raise RuntimeError("the collection's control-plane worker is offline")
        j = C._job(ctx, "characters", inp.model_dump(), cp, 1800)
        if j.get("state") != "succeeded":
            raise RuntimeError(j.get("error") or f"live swap {j.get('state')}")
        return j["output"]["result"]
    rom, _ = O.rom_of(ctx.config, game)
    if rom.version != "ntsc-1.2":
        return unsupported("Live OoT swaps currently require NTSC 1.2; this session was left unchanged.")
    tg = O.resolve(ctx, rom, inp.session_id, "" if inp.slot == "player" else inp.slot, inp.x, inp.y)
    if tg["kind"] == "link":
        return unsupported("Link's live model and equipment writer is not implemented. The game was left running at the same point.")
    group = O.npc_group(rom, tg.get("actor"), tg["object"], tg.get("skel"))
    if len(group["objects"]) != 1:
        return unsupported("This NPC uses compound objects; its live writer is not implemented. The game was left unchanged.")
    oid, off = group["skel"]
    original = rom.object(oid)
    regions = O.npc_reclaim(rom, group, tg.get("actor_id"))
    budget = int(sum(b - a for a, b in regions) * .85)
    if budget < 1024:
        return unsupported("This NPC has insufficient reclaimable model space for a bounded live replacement.")
    root = C.library_root(ctx.config)
    model = root / meta["slug"] / meta["model"]
    target = O.npc_target(rom, oid, off, tg.get("frame"), group)
    fitted = O.fit(model, O.roles_of(meta, model, root), target,
                   Path(ctx.config.cache) / "characters_build" / meta["slug"] / "oot-live",
                   meta["name"], C._blender(ctx.config), budget,
                   scale=(meta.get("rig") or {}).get("scale"),
                   props=[p["node"] for p in meta.get("props") or []], progress=ctx.progress)
    try:
        data = bounded_model(original, O.OW.skeleton(original, off), fitted["parts"], fitted["mats"], regions,
                             group.get("head_dls", []), group.get("head_limb"))
    except ValueError as exc:
        return unsupported(f"The bounded live model could not be built: {exc}. The game was left unchanged.")
    result = O._api_job(ctx, inp.session_id, "replace_object", items=[{
        "object": oid, "expected": original.hex(), "data": data.hex(),
        "actor_id": tg.get("actor_id"),
    }])
    return {"status": "live_swapped", "in_engine": True, "session_id": inp.session_id,
            "character": meta["name"], "replaces": tg["name"], "scope": "loaded_object_type",
            "live": result, "message": f"{meta['name']} replaces {tg['name']} in the running game without a restart. "
            "All currently loaded actors sharing this model change. It lasts until that object reloads; "
            "swap again after a room load. The original pause state is preserved."}


def replace_object(ad, item, previous=None):
    """Validate every changed byte before writing; rollback a partial/failed write."""
    from . import oot, oot_live as L
    expected, data = bytes.fromhex(item["expected"]), bytes.fromhex(item["data"])
    if not expected or len(expected) != len(data) or len(data) > 0x80000:
        raise ValueError("a live replacement must retain its original object size")
    oid = int(item["object"])
    if oid <= 1:
        raise ValueError("shared gameplay objects cannot be replaced")
    slots = [s for s in L.object_slots(ad) if s["id"] == oid]
    if len(slots) != 1:
        raise ValueError("the target object is not uniquely loaded")
    base = slots[0]["segment"]
    start = L.u32(ad, oot.play(ad) + L.OBJECT_CTX)
    end = L.u32(ad, oot.play(ad) + L.OBJECT_CTX + 4)
    later = [s["segment"] for s in L.object_slots(ad) if s["segment"] > base]
    bound = min([end, *later])
    if not 0x80000000 <= start <= base < base + len(data) <= bound <= 0x80400000:
        raise ValueError("the replacement exceeds the loaded object's allocation")
    if not any(a["object"] == oid and a["drawn"] and
               (item.get("actor_id") is None or a["id"] == item["actor_id"]) for a in L.actors(ad)):
        raise ValueError("the chosen actor is no longer drawn with this object")
    current = oot._rd(ad, base, len(data))
    accepted = expected
    if previous and previous["base"] == base and previous["original"] == expected:
        # If a room reload restored the original, accept that instead of stale swapped bytes.
        accepted = expected if current == expected else previous["data"]
    changes = [i for i, (a, b) in enumerate(zip(accepted, data)) if a != b]
    if any(current[i] != accepted[i] for i in changes):
        raise ValueError("the loaded model differs from the expected source; no bytes were written")
    ranges = []
    for i in changes:
        if ranges and ranges[-1][1] == i:
            ranges[-1] = (ranges[-1][0], i + 1)
        else:
            ranges.append((i, i + 1))
    written = []
    try:
        for a, b in ranges:
            written.append((a, b))  # include a write that fails after partially changing memory
            oot._wr(ad, base + a, data[a:b])
        if any(oot._rd(ad, base + a, b - a) != data[a:b] for a, b in ranges):
            raise RuntimeError("live swap readback did not match")
    except Exception:
        for a, b in reversed(written):
            oot._wr(ad, base + a, current[a:b])
        if any(oot._rd(ad, base + a, b - a) != current[a:b] for a, b in written):
            raise RuntimeError("live swap rollback failed; keep the game paused")
        raise
    return {"base": base, "original": expected, "data": data,
            "bytes_written": len(changes), "object": oid}
