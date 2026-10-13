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
import time

# Writers `characters op=use` routes to: (module, slots, what gets replaced). Games: the module's GAME_IDS; "routed" is
# read from characters_tool's own source, so a writer counts only once op=use actually reaches it.
WRITERS = [
    ("doa2_swap", ["fighter:<name>:<costume>"], "DOA2 LE Japan: native body replacement; fighter motions preserved, per-donor gameplay verification"),
    ("sm64_swap", ["player"], "Mario (20 joints, all his animations)"),
    ("gta_stories_models", ["player"], "Toni, every outfit"),
    ("gta3_swap", ["player"], "Claude, the GTA III player (player.dff/.txd in every GTA3.IMG copy on the disc)"),
    ("gta_vc_swap", ["player", "ped:<dff name>", "peds:all", "all"],
     "Tommy (player.dff/.txd), one ped or every ped on his skeleton in a rebuilt models/gta3.img (classic RenderWare PC "
     "port only; the owned install is the UE4 Definitive Edition, which use() detects and reports as a gap)"),
    ("re6_tool", ["player", "enemies", "enemy:<family>"], "Leon in every costume; zombies / J'avo"),
    ("metal_arms", ["player", "npc", "enemy"], "Glitch; any bot (picked on screen)"),
    ("aki_wrestling", ["<wrestler>", "player"], "any wrestler (several per ROM: op=match); No Mercy + World Tour "
                                                "(gbox.aki_wcw); Revenge has no writer yet"),
    ("yukes_sd", ["<wrestler>"], "any wrestler, every costume (several per disc: op=match); SmackDown! 2 (PS1)"),
    ("defjam_writer", ["<wrestler>", "player"],
     "Def Jam Vendetta PS2: any of the 58 wrestler containers (player = the four story heroes, every costume); "
     "BODY/BODY2 + texture page rebuilt, read back by the reader; not yet verified in an emulator"),
    ("pe_swap", ["player"], "Aya, all 5 outfits (field + battle share the model)"),
    ("pe2_swap", ["player"], "PE2 Aya, every outfit file (STAGE0.CDF 10200..10600: model + page + CLUT); unverified in game"),
    ("ff7_swap", ["player"], "Cloud: field model (FIELD/CLOUD.BCX) + battle model (ENEMY6/CLOUD.LZS)"),
    ("sa2_chars", ["player"], "Sonic (SA2 player model)"),
    ("pso_player", ["player", "enemy:<name>", "enemies"],
     "a PSO class (Ninja node tree, not drawn by the game yet); enemy:booma / gobooma / gigobooma / boomas or any BM_ENE "
     "pack on the enemy's own motions (gbox.pso_enemy, unverified in game)"),
    ("jgr_swap", ["player", "character:<name>", "id:<N>", "<00-15>"],
     "JGR USA: any of the 16 PLAYER.AFS cast (player = Beat unless active_id): every textured body group and its "
     "texlist's body atlas rebuilt in a new GD-ROM mod; gameplay replacement unverified until launched"),
    ("mgs_vr_swap", ["player"], "VR Missions Snake: currently only the HUcast donor KMD is routed; arbitrary donor replacement is unsupported"),
    ("mgs1_swap", ["player"], "MGS disc Snake: HUcast donor KMD only; visible replacement remains experimental/unverified"),
    ("clayfighter_swap", ["fighter:<name>", "player"],
     "Clay Fighter: Sculptor's Cut (N64): every sprite frame of one fighter re-drawn from a collection sprites entry "
     "(frame sizes, hotspots, moves, hit boxes and sounds kept; patched ROM with the header CRC fixed)"),
    ("crazy_taxi_swap", ["player", "driver:<axel|bd_joe|gena|gus>", "drivers", "pedestrian:<group>", "pedestrians",
                         "passenger:<group>", "passengers"],
     "Crazy Taxi GC: any driver (every .shp part, hand pose and sl_ LOD in ct/polDC0.all; accessory sub-parts "
     "hidden; skeleton and animations stay), or the pedestrians / fares; unverified in game"),
    ("doapp_swap", ["<fighter>[:<costume>]", "player"],
     "Dead Or Alive ++ (arcade, MAME doapp): any of the 11 fighters' costume models (player = all 44) rebuilt on the "
     "fighter's own 15 bones (motions, moves and accessory chains stay) in a new doapp set folder; read back through "
     "the game's fight init + skeleton build; unverified in MAME"),
]
SPECIAL = [                                               # writers routed by code in characters.py, not a module's use()
    ("re4gc", "build_re4(", ["player"], "Leon (story + Mercenaries, every costume pack)"),
    ("oot", "oot_swap.tool(", ["player (Link, both ages)", "npc:<name> / x,y", "swap a<->b", "place (statue)"],
     "Link or any NPC"),
]
# games docs/model_swaps.md discusses that have no writer yet (catalog search terms -> platform)
DISCUSSED = [("Resident Evil 3 Nemesis", "psx"), ("Resident Evil 2", "psx"), ("Resident Evil Director's Cut", "psx"),
             ("Mario Kart 64", "n64"), ("Resident Evil The Mercenaries 3D", "3ds"), ("Super Smash Bros. Melee", "gamecube"),
             ("Phantasy Star Online Ver. 2", "dreamcast"), ("Grand Theft Auto Vice City", "ps2"),
             ("Grand Theft Auto Vice City Stories", "ps2"), ("Resident Evil 4", "ps2"), ("Shenmue", "dreamcast"),
             ("Final Fantasy VIII", "psx"), ("Sonic Adventure 2", "dreamcast"),
             ("WWF SmackDown!", "psx"), ("WWE SmackDown! vs. RAW 2006", "psp"), ("Resident Evil 5", "xbox360")]


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


def cast_slots(game: dict) -> list[dict]:
    """The slots a game's writer can put a collection character into, for the cast menu (characters op=collect
    "slots"): the writer module's own list (cast_slots(): PSO's enemies, gbox.pso_enemy.slots) plus the fixed slot
    names from WRITERS (placeholders like enemy:<family> are left to the module)."""
    w = writer_for(game)
    if not w or not w["routed"]:
        return []
    out: list[dict] = []
    m = _mod(w["writer"].split(".")[-1])
    if m is not None and callable(getattr(m, "cast_slots", None)):
        try:
            out += [dict(s, writer=s.get("writer", w["writer"])) for s in m.cast_slots()]
        except Exception:                                  # noqa: BLE001 - a writer that can't list keeps its fixed slots
            pass
    for s in w["slots"]:
        if "<" not in s and not any(o.get("slot") == s for o in out):
            out.append({"slot": s, "name": s, "kind": "player" if s == "player" else "slot", "writer": w["writer"]})
    return out


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
    from . import game_capabilities as GC
    from .favorite_capabilities import read_favorites
    chars = api(ctx, "GET", "/api/characters")
    ids: dict[str, dict] = {}
    favorites, catalog = read_favorites(ctx, api)
    ids.update((g['game_id'], g) for g in favorites)

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
        capabilities = GC.describe(g, chars, extractor=ex, roster=roster, writer=w)
        rows.append({"game_id": gid, "title": g.get("title"), "platform": g.get("platform"),
                     "favorite": bool(g.get('favorite')), "library": g.get('library'),
                     "capabilities": capabilities, "backlog": GC.backlog(capabilities),
                     "rip": {"extractor": ex or (tools[0] if tools else None), "roster": len(roster),
                             "in_collection": sorted(slugs), "usable": sorted(m["slug"] for m in have
                                                                             if (m.get("rig") or {}).get("roles")),
                             "not_ripped": missing},
                     "reimport": (w | {"fallback": None}) if w and w["routed"] else
                     {"writer": (w or {}).get("writer"), "routed": False, "slots": [],
                      "fallback": "overlay (characters op=overlay: drawn over the player in the desktop app)"}})
    rows.sort(key=lambda r: (not r["reimport"]["routed"], not r["rip"]["in_collection"], r["title"] or ""))
    return {"games": rows, "favorite_catalog": catalog,
            "summary": {"games": len(rows), "favorites": len(favorites),
                                       "complete_sources_verified": sum(r['capabilities']['complete_source_verified'] for r in rows),
                                       "verified_fighter_costume_sources": sum(bool(r['capabilities']['verified_fighter_costume_source']) for r in rows),
                                       "rip": sum(bool(r["rip"]["extractor"]) for r in rows),
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
    parent = getattr(ctx, "parent_request_id", None)
    if parent:
        request = api(ctx, "GET", f"/api/requests/{parent}")
        if (request.get("context") or {}).get("native_replacement"):
            _post_message(ctx, api, parent, f"Native writer missing: {json.dumps(need)}. Attempt: {asked}")
            return {"number": request.get("number"), "id": parent, "existing": True}
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
        "on a test worker and reply here. A donor preview or overlay does not satisfy this native replacement request."])
    r = api(ctx, "POST", "/api/requests", json={"title": title, "body": body, "source": "gap", "kind": "text",
                                                 "parent_request_id": getattr(ctx, "parent_request_id", None),
                                                 "context": {"character": meta["slug"], "game_id": game["game_id"],
                                                             "native_replacement": True, "needs_rebuild": True,
                                                             "job_id": ctx.job_id}})
    return {"number": r.get("number"), "id": r["id"], "existing": False}


def _post_message(ctx, api, rid: str, text: str, step: dict | None = None):
    """Best-effort agent message on a request (task_step detail when given); never raises."""
    try:
        api(ctx, "POST", f"/api/requests/{rid}/messages",
            json={"author": "agent", "text": text} | ({"task_step": step} if step else {}))
    except Exception:                                              # noqa: BLE001 - evidence notes must not break the swap answer
        pass


def _run_job(ctx, api, tool: str, inp: dict, rid: str, limit: float = 180) -> dict:
    """Dispatch one job linked to the request and wait for its terminal state (the job dict)."""
    j = api(ctx, "POST", "/api/jobs", json={"tool": tool, "input": inp, "parent_request_id": rid})
    t0 = time.time()
    while j.get("state") in ("queued", "running") and time.time() - t0 < limit:
        time.sleep(1.0)
        j = api(ctx, "GET", f"/api/jobs/{j['id']}")
    return j


def _moment_slot(ctx, api, rid: str) -> int:
    """A dedicated slot per preserved moment on this request (issue reports use 60+; pickwhips start at 70)."""
    n = 0
    try:
        r = api(ctx, "GET", f"/api/requests/{rid}") or {}
        n = sum(1 for m in r.get("messages", [])
                if (m.get("task_step") or {}).get("action") == "preserve pickwhip moment")
    except Exception:                                              # noqa: BLE001
        pass
    return 70 + n


def preserve_moment(ctx, api, rid: str, sid: str, game: dict, meta: dict, inp) -> dict:
    """#1146: keep the exact game moment a pickwhip landed on. Saves a checkpoint (session_op save_state, which
    reports the slot the emulator ACTUALLY wrote and its frame thumbnail), exports it as a portable artifact
    (state_transfer export keyed to that slot, so a stale newest-file can't be picked), attaches the live frame
    to the request (/api/requests/{rid}/capture) and posts the evidence. Every failure degrades to a note on the
    request; the gap report itself is never blocked."""
    out: dict = {"session_id": sid}
    slot = _moment_slot(ctx, api, rid)
    t0 = time.time()                                               # export_saved rejects a checkpoint older than this
    j = _run_job(ctx, api, "session_op", {"session_id": sid, "op": "save_state", "args": {"slot": slot}}, rid)
    if j.get("state") != "succeeded":
        why = j.get("error") or j.get("state") or "unknown"
        _post_message(ctx, api, rid, f"Save state unavailable for this moment (slot {slot}): {why}.",
                      {"action": "preserve pickwhip moment", "attempt": "1", "result": f"save_state: {why}",
                       "status": "failed"})
        return out | {"saved": False, "error": why}
    res = (j.get("output") or {}).get("result") or {}
    out |= {"saved": True, "slot": res.get("slot", slot), "frame": res.get("frame")}
    line = (f"Checkpoint of this moment saved in slot {res.get('slot', slot)}"
            + (f"; frame thumbnail artifact {res['frame']}" if res.get("frame") else "") + ".")
    # export_saved uploads THAT checkpoint file (exact slot, not older than t0); op=export would save again first,
    # overwriting the pickwhip moment with a later one and breaking the match with the captured frame
    x = _run_job(ctx, api, "state_transfer",
                 {"session_id": sid, "op": "export_saved", "slot": res.get("slot", slot), "not_before": t0}, rid)
    if x.get("state") == "succeeded":
        r = (x.get("output") or {}).get("result") or {}
        out |= {"artifact": r.get("artifact"), "bytes": r.get("bytes")}
        line += (f" Portable export {r.get('bytes')} bytes ({r.get('file')}), artifact {r.get('artifact')}:"
                 " restore it with state_transfer op=import once the writer exists.")
    else:
        line += f" Portable export unavailable: {x.get('error') or x.get('state')}."
    where = f" at ({inp.x:.0%} across, {inp.y:.0%} down)" if getattr(inp, "x", None) is not None else ""
    try:
        api(ctx, "POST", f"/api/requests/{rid}/capture", timeout=90,
            json={"session_id": sid,
                  "text": f"The frame the operator pickwhipped {meta['name']} onto{where} "
                          f"({game['title']}): the before-image the swap gets tested against.",
                  "task_step": {"action": "capture pickwhip frame", "attempt": "1",
                                "result": "frame attached to the request", "status": "succeeded"}})
        out["captured"] = True
        _post_message(ctx, api, rid, line,
                      {"action": "preserve pickwhip moment", "attempt": "1", "result": line, "status": "succeeded"})
    except Exception as e:                                         # noqa: BLE001 - e.g. the session ended mid-flow
        out["captured"] = False
        _post_message(ctx, api, rid, line + f" Frame capture unavailable: {e}.",
                      {"action": "preserve pickwhip moment", "attempt": "1", "result": line, "status": "partial"})
    return out


def no_writer(ctx, api, meta: dict, game: dict, need: dict, inp) -> dict:
    """characters op=use without a native writer leaves a durable repair request.
    A running session also gets its moment preserved on the gap report (#1146): checkpoint, portable export, frame."""
    asked = (f"characters op=use character={meta['slug']} game={game['title']} slot={inp.slot} "
             f"session_id={inp.session_id} x={inp.x} y={inp.y}")
    req = gap(ctx, api, meta, game, need, asked)
    _post_message(ctx, api, req['id'], f"Replacement still required: {asked}")
    res = {"status": "missing", "missing": need, "request": req, "native_replacement": False}
    sid = inp.session_id
    if sid:
        running = False
        try:                                                       # preserve only a live session; a dead one just reports
            running = next((s.get("state") == "running" for s in api(ctx, "GET", "/api/sessions")
                            if s.get("session_id") == sid), False)
        except Exception:                                          # noqa: BLE001
            pass
        if running:
            try:
                res["preserved"] = preserve_moment(ctx, api, req["id"], sid, game, meta, inp)
            except Exception as e:                                 # noqa: BLE001 - the gap report is the deliverable
                _post_message(ctx, api, req["id"], f"Moment preservation failed: {e}.",
                              {"action": "preserve pickwhip moment", "attempt": "1", "result": str(e)[:400],
                               "status": "failed"})
    return res | {"message": f"{meta['name']} has not replaced the character in {game['title']}. "
                             f"Native writer work is tracked in request #{req.get('number')}; "
                             "the saved target must be rebuilt and verified in gameplay."}
