"""Coverage of the operator's standing requirement "every character we study: rip it, and reimport it into any game we
discuss": per studied game, can gBox RIP its characters (an extractor -> the collection) and REIMPORT any collection
character into it (a swap writer that `characters op=use` routes to), and which character slots.

`characters op=coverage` returns the matrix (docs/model_swaps.md "Coverage matrix" is its snapshot). Games without a
writer answer `characters op=use` with the overlay fallback (gbox.overlay_swap: drawn over the player in the desktop
app, any game, now) and a gap report in the inbox (source "gap") so the writer gets built.
"""
from __future__ import annotations

import inspect
import json
import re

# Writers `characters op=use` routes to: (module, slots, what gets replaced). Games: the module's GAME_IDS; "routed" is
# read from characters_tool's own source, so a writer counts only once op=use actually reaches it.
WRITERS = [
    ("sm64_swap", ["player"], "Mario (20 joints, all his animations)"),
    ("gta_stories_models", ["player"], "Toni, every outfit"),
    ("re6_tool", ["player", "enemies", "enemy:<family>"], "Leon in every costume; zombies / J'avo"),
    ("metal_arms", ["player", "npc", "enemy"], "Glitch; any bot (picked on screen)"),
    ("aki_wrestling", ["<wrestler>", "player"], "any wrestler (several per ROM: op=match); No Mercy + World Tour "
                                                "(gbox.aki_wcw); Revenge has no writer yet"),
    ("yukes_sd", ["<wrestler>"], "any wrestler, every costume (several per disc: op=match); SmackDown! 2 (PS1)"),
    ("pe_swap", ["player"], "Aya, all 5 outfits (field + battle share the model)"),
    ("ff7_swap", ["player"], "Cloud: field model (FIELD/CLOUD.BCX) + battle model (ENEMY6/CLOUD.LZS)"),
    ("sa2_chars", ["player"], "Sonic (SA2 player model)"),
    ("pso_player", ["player"], "a PSO class (Ninja node tree)"),
    ("jgr", ["<name> (beat = new-game player)", "id:<0-15>", "<00-15>"],
     "a Jet Grind Radio character's high-detail body (PLAYER.AFS PLAY + PTEX texture 0), named from the disc"),
]
SPECIAL = [                                               # writers routed by code in characters.py, not a module's use()
    ("re4gc", "build_re4(", ["player"], "Leon (story + Mercenaries, every costume pack)"),
    ("oot", "oot_swap.tool(", ["player (Link, both ages)", "npc:<name> / x,y", "swap a<->b", "place (statue)"],
     "Link or any NPC"),
]
# games docs/model_swaps.md discusses that have no writer yet (catalog search terms -> platform)
DISCUSSED = [("Resident Evil 3 Nemesis", "psx"), ("Resident Evil 2", "psx"), ("Resident Evil Director's Cut", "psx"),
             ("Mario Kart 64", "n64"), ("Resident Evil The Mercenaries 3D", "3ds"), ("Super Smash Bros. Melee", "gamecube"),
             ("Phantasy Star Online Ver. 2", "dreamcast"), ("Grand Theft Auto III", "ps2"), ("Grand Theft Auto Vice City", "ps2"),
             ("Grand Theft Auto Vice City Stories", "ps2"), ("Resident Evil 4", "ps2"), ("Shenmue", "dreamcast"),
             ("Parasite Eve II", "psx"), ("Final Fantasy VIII", "psx"), ("Sonic Adventure 2", "dreamcast"),
             ("WWF SmackDown!", "psx"), ("WWE SmackDown! vs. RAW 2006", "psp")]


def _mod(name):
    import importlib
    try:
        return importlib.import_module(f"gbox.{name}")
    except Exception:                                      # noqa: BLE001 - a writer module that doesn't import isn't routed
        return None


def writer_for(game: dict) -> dict | None:
    """The swap writer op=use reaches for this catalog game, or None."""
    from . import characters as C
    src = inspect.getsource(C.characters_tool)
    gid, t, plat = game.get("game_id", ""), (game.get("title") or "").lower(), game.get("platform") or ""
    for name, slots, what in WRITERS:
        m = _mod(name)
        if m is not None and gid in (getattr(m, "GAME_IDS", None) or {}):
            alias = re.search(rf"from \. import {name}(?: as (\w+))?", src)
            routed = bool(alias) and f"{alias.group(1) or name}.use(" in src
            return {"writer": f"gbox.{name}", "routed": routed, "slots": slots, "replaces": what}
    if gid in C.RE4GC or gid in C.RE4WII:
        return {"writer": "gbox.characters.build_re4 (+ re4wii)", "routed": "build_re4(" in src, "slots": SPECIAL[0][2],
                "replaces": SPECIAL[0][3]}
    o = _mod("oot_swap")
    if o is not None and getattr(o, "is_oot", None) and o.is_oot(game):
        return {"writer": "gbox.oot_swap", "routed": "oot_swap.tool(" in src, "slots": SPECIAL[1][2], "replaces": SPECIAL[1][3]}
    return None


def extractor_for(game: dict) -> tuple[str | None, list[dict]]:
    from . import characters as C
    t, plat = (game.get("title") or "").lower(), game.get("platform") or ""
    for name, test, roster, _run in C.DEDICATED:
        if test(t, plat):
            try:
                return name, [r for r in roster() if r.get("kind", "character") == "character"]
            except Exception:                              # noqa: BLE001
                return name, []
    return None, []


def coverage(ctx, api) -> dict:
    """The rip / reimport matrix over every game gBox has studied: games with a writer, games the collection came from,
    and the games docs/model_swaps.md discusses."""
    from . import characters as C
    chars = api(ctx, "GET", "/api/characters")
    ids: dict[str, dict] = {}

    def game(gid):
        if gid not in ids:
            try:
                ids[gid] = api(ctx, "GET", f"/api/catalog/{gid}")
            except Exception:                              # noqa: BLE001 - e.g. a Steam id outside the catalog
                ids[gid] = {"game_id": gid, "title": next((m["source"].get("game_title") for m in chars
                                                           if m["source"].get("game_id") == gid), gid), "platform": ""}
        return ids[gid]
    for name, *_r in WRITERS:
        m = _mod(name)
        for gid in (getattr(m, "GAME_IDS", None) or {}) if m else {}:
            game(gid)
    for gid in list(C.RE4GC) + list(C.RE4WII):
        game(gid)
    for m in chars:
        if m["source"].get("game_id"):
            game(m["source"]["game_id"])
    for q, plat in DISCUSSED:
        try:
            hits = api(ctx, "GET", "/api/catalog/best", params={"q": q, "limit": 3})
            hits = hits.get("items", hits) if isinstance(hits, dict) else hits
            hit = next((h for h in hits if h.get("platform") == plat and _close(q, h.get("title", ""))), None)
            if hit:
                ids.setdefault(hit["game_id"], hit)
        except Exception:                                  # noqa: BLE001
            pass
    rows = []
    for gid, g in ids.items():
        ex, roster = extractor_for(g)
        have = [m for m in chars if m["source"].get("game_id") == gid and m.get("kind", "character") == "character"
                and not m.get("variant_of")]
        slugs = {m["slug"] for m in have}
        missing = [r["name"] for r in roster if r["slug"] not in slugs]
        tools = sorted({m.get("extraction_tool") or "" for m in have} - {""})
        w = writer_for(g)
        rows.append({"game_id": gid, "title": g.get("title"), "platform": g.get("platform"),
                     "rip": {"extractor": ex or (tools[0] if tools else None), "roster": len(roster),
                             "in_collection": sorted(slugs), "usable": sorted(m["slug"] for m in have
                                                                             if (m.get("rig") or {}).get("roles")),
                             "not_ripped": missing},
                     "reimport": (w | {"fallback": None}) if w and w["routed"] else
                     {"writer": (w or {}).get("writer"), "routed": False, "slots": [],
                      "fallback": "overlay (characters op=overlay: drawn over the player in the desktop app)"}})
    rows.sort(key=lambda r: (not r["reimport"]["routed"], not r["rip"]["in_collection"], r["title"] or ""))
    return {"games": rows, "summary": {"games": len(rows), "rip": sum(bool(r["rip"]["extractor"]) for r in rows),
                                       "reimport": sum(r["reimport"]["routed"] for r in rows),
                                       "both": sum(bool(r["rip"]["extractor"]) and r["reimport"]["routed"] for r in rows),
                                       "collection": len([m for m in chars if m.get("kind", "character") == "character"])}}


def _close(q: str, title: str) -> bool:
    w = set(re.findall(r"[a-z0-9]+", q.lower())) - {"the", "of"}
    return len(w & set(re.findall(r"[a-z0-9]+", title.lower()))) >= max(1, len(w) - 1)


def markdown(cov: dict) -> str:
    """The matrix as the docs table (a multi-disc game is one row: the collection is per game, discs share writers)."""
    out = ["| Game | Platform | Rip (extractor) | In the collection | Reimport (writer, slots) |", "|---|---|---|---|---|"]
    seen = set()
    for r in cov["games"]:
        base = re.sub(r"\s*\(Disc \d\)", "", r["title"] or "")
        if (base, r["platform"]) in seen:
            continue
        seen.add((base, r["platform"]))
        discs = sorted(re.findall(r"Disc (\d)", " ".join(x["title"] or "" for x in cov["games"]
                                                         if re.sub(r"\s*\(Disc \d\)", "", x["title"] or "") == base
                                                         and x["platform"] == r["platform"])))
        r = r | {"title": base + (f" (Discs {discs[0]}-{discs[-1]})" if len(discs) > 1 else
                                  f" (Disc {discs[0]})" if discs else "")}
        rip, re_ = r["rip"], r["reimport"]
        coll = ", ".join(rip["in_collection"][:8]) + (f" (+{len(rip['in_collection']) - 8})" if len(rip["in_collection"]) > 8 else "")
        if rip["not_ripped"]:
            coll += f"; not ripped yet: {', '.join(rip['not_ripped'][:8])}" + ("..." if len(rip["not_ripped"]) > 8 else "")
        wr = (f"**{re_['writer']}**: {', '.join(re_['slots'])}" if re_["routed"] else
              ("overlay only" + (f" ({re_['writer']} exists, not routed)" if re_.get("writer") else "")))
        out.append(f"| {r['title']} | {r['platform'] or '-'} | {rip['extractor'] or '-'} | {coll or '-'} | {wr} |")
    return "\n".join(out)


def gap(ctx, api, meta: dict, game: dict, need: dict, asked: str) -> dict:
    """File (once) an inbox gap report: no swap writer for this game (agent._gap_report's layout, source "gap")."""
    title = f"GAP: character writer for {game['title']}"
    for r in api(ctx, "GET", "/api/requests", params={"status": "open,in_progress"}):
        if r.get("title") == title:
            return {"number": r.get("number"), "id": r["id"], "existing": True}
    body = "\n".join([
        "## What the operator asked", asked, "",
        f"## Context\ngame: {game['title']} ({game['game_id']}, {game.get('platform')}) · character: {meta['name']} "
        f"('{meta['slug']}', from {meta['source'].get('game_title')})", "",
        "## What gBox tried", "- `characters op=use`: no swap writer is routed for this game (characters op=coverage)", "",
        "## What failed", f"- no writer; what it needs: {json.dumps(need)[:1500]}", "",
        "## For Claude",
        "Build the writer for this game like gbox/pe_swap.py / ff7_swap.py / sm64_swap.py (read the player model, rigid "
        "retarget with sm64_swap.retarget + a role map onto the game's skeleton, fit the game's budgets, rebuild the "
        "file/disc as a file mod), route it in characters_tool, add it to char_coverage.WRITERS, verify in an emulator "
        "on the Spark and reply here. Meanwhile the operator has the overlay (characters op=overlay)."])
    r = api(ctx, "POST", "/api/requests", json={"title": title, "body": body, "source": "gap", "kind": "text",
                                                 "parent_request_id": getattr(ctx, "parent_request_id", None),
                                                 "context": {"character": meta["slug"], "game_id": game["game_id"], "job_id": ctx.job_id}})
    return {"number": r.get("number"), "id": r["id"], "existing": False}


def no_writer(ctx, api, meta: dict, game: dict, need: dict, inp) -> dict:
    """characters op=use on a game without a writer: the overlay now (when a session runs it), plus a gap report."""
    asked = f"characters op=use character={meta['slug']} game={game['title']} slot={inp.slot}"
    req = gap(ctx, api, meta, game, need, asked)
    res = {"status": "missing", "missing": need, "request": req, "fallback": "overlay"}
    sid = inp.session_id
    if sid:
        try:
            from . import overlay_swap
            ov = overlay_swap.start(ctx, api, meta, sid, inp.x, inp.y)
            return res | {"status": "overlay", "overlay": ov,
                          "message": f"{game['title']} has no in-engine swap writer yet, so {meta['name']} is drawn over the "
                                     f"player as an overlay in the desktop app now (the game itself is unchanged). Gap report "
                                     f"#{req.get('number')} asks for the writer."}
        except Exception as e:                             # noqa: BLE001 - session not running / not on screen
            res["overlay_error"] = str(e)
    return res | {"message": f"{game['title']} has no in-engine swap writer yet (gap report #{req.get('number')} filed so it "
                             f"gets built). Right now: characters op=overlay character={meta['slug']} session_id=<the "
                             "running game> draws it over the player in the desktop app (an overlay, not in-engine)."}
