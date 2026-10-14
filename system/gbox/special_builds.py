"""Special builds: one game's built mods, grouped for the game's right-click menu ("Special builds ▸").

The builds an operator's requests were tested or confirmed with (ticket numbers on the marker or the mod card), the
whole-cast swaps, single character swaps and everything else a writer built for this game, each with the ways to
launch it and the exact tool call that builds it again.

GET  /api/games/{game_id}/special_builds           groups: Favorites (the operator's ★ builds, only when there are
                                                   any), Confirmation builds (newest first, with the ticket titles),
                                                   Cast swaps (source group + per-slot summary), Character swaps, Other;
                                                   each build: launch_options + rebuild_recipe
POST /api/games/{game_id}/special_builds/rebuild   {recipes: [recipe, ...] | "all", group?, keys?} -> Spark jobs

A rebuild recipe is the `characters` call that made the build (op=use | match | cast_swap), recorded into the build's
.gbox-mod.json by the shared build path (characters tool: record_call) for every writer; builds made before that was
recorded get one inferred from the marker (the cast plan rows, the character + slot) and say so (recorded: false).
Rebuilds never launch anything (launch=false) and always build again (rebuild=true); they run on the Linux control
plane, where the character collection lives.

Reads only the built-mods index (memory) and the store: never the mod folders, never the busy cache disk.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi import Body, Depends, HTTPException

MARKER = ".gbox-mod.json"
RECIPE_KEY = "recipe"
RECIPE_OPS = ("use", "match", "cast_swap")
GROUPS = (("confirmation", "Confirmation builds"), ("cast", "Cast swaps"), ("character", "Character swaps"),
          ("other", "Other"))
FAVORITES = ("favorites", "Favorites")     # the operator's ★ builds, at the top when there are any (gbox.builds)
# Sonic showcase builds (gbox/sonic_showcase.py: showcase_sonic_<title> folders whose marker carries the `showcase`
# record) get their own group, listed after the confirmation builds when the game has any
SHOWCASE = ("showcase", "Sonic showcase")
# the CharIn fields each op's recipe keeps (everything else is the CharIn default or session-bound); a showcase cast
# keeps its fixed mod name and flag, so a rebuild lands in the same showcase_sonic_<title> folder
KEEP = {"use": ("character", "game_id", "slot", "active_id", "pairs", "title", "strict_cutscenes"),
        "match": ("game_id", "pairs", "title"),
        "cast_swap": ("target_game", "source", "mapping", "assign", "prefer", "seed", "slots", "assignments",
                      "strict_cutscenes", "mod_name", "showcase")}
FAILED = ("failed", "error", "missing", "not_in_collection", "unsupported", "needs_source", "planned", "empty",
          "native", "overlay")
REUSED = ("ready", "launched", "exists", "reused", "cached")


# ------------------------------------------------------------------------------------------------- recipes

def _clean(op: str, inp: dict) -> dict:
    keep = {"op": op}
    for k in KEEP[op]:
        v = inp.get(k)
        if k == "strict_cutscenes":
            if v is False:  # true is now the default; retain an explicit diagnostic opt-out
                keep[k] = False
            continue
        if v in (None, "", [], {}, False) and k not in ("game_id", "target_game"):
            continue
        keep[k] = v
    return keep | {"launch": False, "rebuild": True}


def recipe_from_call(inp: dict, result: dict) -> dict | None:
    """The `characters` call that rebuilds the mod this call built (or None: not a build, or nothing was built).
    inp: the CharIn as a dict; result: the tool's result."""
    op = inp.get("op")
    if op not in RECIPE_OPS or not isinstance(result, dict) or not result.get("mod") or inp.get("plan_only"):
        return None
    status = str(result.get("status") or "")
    if any(w in status for w in FAILED):
        return None
    gid = result.get("game_id") or inp.get("game_id") or ""
    if op == "use":
        call = dict(inp, character=result.get("slug") or inp.get("character"), game_id=gid)
    elif op == "match":
        pairs = inp.get("pairs") or [{"character": inp.get("character"), "slot": "" if inp.get("slot") == "player"
                                      else inp.get("slot")}]
        call = dict(inp, game_id=gid, pairs=pairs)
    else:                                                        # every planned row: the same plan -> the same mod name
        rows = result.get("assignments") or []
        call = dict(inp, target_game=gid or inp.get("target_game"),
                    assignments=[{"slot": r["slot"], "character": r["character"]} for r in rows
                                 if r.get("slot") and r.get("character")])
    if not (call.get("game_id") or call.get("target_game")):
        return None
    return {"tool": "characters", "input": _clean(op, call)}


def record(config, game_id: str, mod: str, recipe: dict, extra: dict | None = None) -> bool:
    """Write the recipe into the build's marker (kept otherwise as the writer wrote it), plus the build record fields
    (gbox.build_record: job_id, built_on, build_call, kind) when given. False when the build is not on this node or
    the marker can't be read / written."""
    from . import build_record, filemods
    try:
        path = filemods.mod_dir(config, game_id, mod) / MARKER
        meta = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(meta, dict):
        return False
    before = dict(meta)
    if extra:
        if isinstance(meta.get("replacement_scope"), dict) and isinstance(extra.get("replacement_scope"), dict):
            extra = extra | {"replacement_scope": meta["replacement_scope"] | extra["replacement_scope"]}
        try:
            meta = build_record.stamp(meta, **{k: v for k, v in extra.items() if k not in meta or k != "kind"})
        except ValueError:
            pass
    old = meta.get(RECIPE_KEY) if isinstance(meta.get(RECIPE_KEY), dict) else {}
    if {k: v for k, v in old.items() if k != "recorded"} == recipe and meta == before:
        return True
    if {k: v for k, v in old.items() if k != "recorded"} != recipe:
        meta[RECIPE_KEY] = dict(recipe, recorded=time.time())
    try:
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(meta, default=str), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        return False
    return True


def record_call(ctx, inp, out) -> dict | None:
    """The shared build path's hook (characters tool): record how the mod it built is built again. Never raises."""
    try:
        d = inp.model_dump() if hasattr(inp, "model_dump") else dict(vars(inp))
        res = (out or {}).get("result") if isinstance(out, dict) else None
        recipe = recipe_from_call(d, res or {})
        if not recipe:
            return None
        gid = recipe["input"].get("game_id") or recipe["input"].get("target_game")
        from . import build_record
        # the build record (job, node, exact call) only for a build that was just made: an existing build reused
        # as it is (ready / launched) keeps its marker byte for byte (it is part of the build's pinned manifest)
        reused = str(res.get("status") or "") in REUSED
        extra = None if reused else build_record.from_ctx(ctx) | {
            "build_call": build_record.call_of("characters", d),
            "kind": "cast" if d.get("op") == "cast_swap" else "character"}
        if not reused and isinstance(res.get("replacement_scope"), dict):
            extra["replacement_scope"] = res["replacement_scope"]
        return recipe if record(ctx.config, gid, res["mod"], recipe, extra) else None
    except Exception:                                            # noqa: BLE001 - bookkeeping never fails a build
        return None


def source_spec(label: str) -> str:
    """A cast marker's source label -> a `source=` the planner resolves (group labels back to their key)."""
    from .cast_swap import GROUPS as CAST_GROUPS
    by_label = {g["label"]: k for k, g in CAST_GROUPS.items()}
    text = str(label or "")
    for lab, key in by_label.items():                             # a group label may itself hold " + " (SA1 + SA2)
        text = text.replace(lab, key)
    parts = [p.strip() for p in text.split(" + ") if p.strip()]
    return ", ".join(by_label.get(p, p.split(" / ")[0]) for p in parts)


def inferred_recipe(meta: dict, game_id: str) -> dict | None:
    """A recipe for a build made before recipes were recorded: from the cast plan rows or the character + slot."""
    gid = meta.get("game_id") if isinstance(meta.get("game_id"), str) and meta.get("game_id") else game_id
    if isinstance(meta.get("cast"), list):
        # every row of the plan (failed ones too) and exactly its slots: the planner rebuilds the same plan, same mod
        rows = [{"slot": str(r.get("slot")), "character": str(r.get("character") or r.get("donor"))}
                for r in meta["cast"] if isinstance(r, dict) and r.get("slot") and (r.get("character") or r.get("donor"))]
        if not rows or not meta.get("cast_source"):
            return None
        showcase = showcase_of(meta)
        return {"tool": "characters", "input": _clean("cast_swap", {
            "target_game": gid, "source": source_spec(meta["cast_source"]), "mapping": meta.get("cast_mapping") or "auto",
            "seed": meta.get("cast_seed") or "", "slots": ",".join(r["slot"] for r in rows), "assignments": rows,
            **({"mod_name": meta.get("name") or "", "showcase": True} if showcase else {})})}
    if isinstance(meta.get("roster"), list):                     # DOA2 roster: one disc, every fighter
        pairs = [{"character": r.get("character"), "slot": str(r.get("fighter") or r.get("slot") or "")}
                 for r in meta["roster"] if isinstance(r, dict) and r.get("character")]
        if pairs:
            return {"tool": "characters", "input": _clean("use", {"character": pairs[0]["character"], "game_id": gid,
                                                                  "slot": "roster", "pairs": pairs})}
    ch = meta.get("character")
    if not isinstance(ch, str) or not ch:
        chars = meta.get("characters")
        ch = chars[0] if isinstance(chars, list) and len(chars) == 1 and isinstance(chars[0], str) else ""
    if not ch:
        return None
    slot = meta.get("slot")
    if not isinstance(slot, str) or not slot:
        rep = meta.get("replaces")
        slot = (f"fighter:{str(rep[0]).lower()}" if isinstance(rep, list) and len(rep) == 1
                and "clayfighter" in str(meta.get("files") or meta.get("writer") or "") else "player")
    return {"tool": "characters", "input": _clean("use", {"character": ch, "game_id": gid, "slot": slot})}


def showcase_of(meta: dict) -> dict | None:
    """The Sonic showcase record of a build's marker (gbox.sonic_showcase), else None."""
    sc = meta.get("showcase") if isinstance(meta, dict) else None
    return sc if isinstance(sc, dict) else None


def recipe_for(meta: dict, game_id: str, name: str = "") -> tuple[dict | None, bool]:
    """(recipe, recorded): the marker's recorded recipe, else one inferred from the marker. name: the build's folder
    (a showcase build's inferred recipe rebuilds into that same folder)."""
    r = meta.get(RECIPE_KEY)
    if isinstance(r, dict) and r.get("tool") == "characters" and isinstance(r.get("input"), dict):
        return {"tool": "characters", "input": dict(r["input"])}, True
    return inferred_recipe(meta | ({"name": name} if name else {}), game_id), False


# ------------------------------------------------------------------------------------------------- launching

def launch_options(item: dict, pcs: list[dict]) -> list[dict]:
    """Ways to start the build: this PC (the default), each online PC, the saved moment when a card links one, and
    the Spark's full debugger. `call` is the launch request the menus send (POST /api/games/{id}/launch)."""
    from urllib.parse import quote
    gid, mod, slot = item["game_id"], item["name"], item.get("state_slot")

    def opt(oid, label, node, moment=False, debug=False, default=False, target=""):
        # target "here": the menu puts its own PC's worker name in place of node=auto (the server's auto picks the
        # PC the operator last played on)
        q = f"node={quote(node, safe='')}&mod={quote(mod, safe='')}" + ("&debug=true" if debug else "")
        return {"id": oid, "label": label, "node": node, "target": target or node, "moment": moment, "debug": debug,
                "default": default, **({"state_slot": slot} if moment else {}),
                "call": {"method": "POST", "path": f"/api/games/{quote(gid, safe='')}/launch?{q}",
                         **({"then": {"tool": "session_op", "op": "load_state", "slot": slot}} if moment else {})}}
    out = [opt("here", "This PC", "auto", default=True, target="here")]
    for w in pcs:
        if w.get("name"):
            out.append(opt(f"pc:{w['name']}", f"Play on {w['name']}" + (f" ({w['os']})" if w.get("os") else ""),
                           w["name"]))
    if slot is not None:
        out.append(opt("moment", f"Play from saved moment (slot {slot})", "auto", moment=True, target="here"))
    out.append(opt("debug", "Play with the debugger (Spark)", "linux", debug=True))
    if slot is not None:
        out.append(opt("moment+debug", f"Saved moment with the debugger (slot {slot}, Spark)", "linux", moment=True,
                       debug=True))
    return out


# ------------------------------------------------------------------------------------------------- grouping

def cast_summary(item: dict, meta: dict) -> dict:
    rows = [r for r in (item.get("report") or meta.get("cast") or []) if isinstance(r, dict)]
    count = {}
    for r in rows:
        s = r.get("status") or "?"
        count[s] = count.get(s, 0) + 1
    n, ok = len(rows), count.get("built", 0)
    text = f"{ok}/{n} slots built" + "".join(f", {v} {k}" for k, v in sorted(count.items()) if k != "built")
    return {"source": item.get("cast_source") or meta.get("cast_source") or "", "slots": n, "counts": count,
            "summary": text,
            "rows": [{"slot": str(r.get("slot") or ""), "donor": str(r.get("character") or r.get("donor") or ""),
                      "status": r.get("status") or "", **({"reason": str(r["reason"])[:200]} if r.get("reason") else {})}
                     for r in rows]}


def kind_of(item: dict, meta: dict | None = None) -> str:
    if item.get("showcase") or (showcase_of(meta or {}) and str(item.get("name") or "").startswith("showcase_")):
        return "showcase"
    if item.get("cast"):
        return "cast"
    return "character" if item.get("changes") else "other"


def build_row(item: dict, meta: dict, pcs: list[dict]) -> dict:
    kind = kind_of(item, meta)
    recipe, recorded = recipe_for(meta, item["game_id"], item["name"] if kind == "showcase" else "")
    row = {k: item.get(k) for k in ("key", "name", "game_id", "mod_title", "display_name", "original_title", "writer",
                                    "built", "verified", "card_id", "state_slot", "last_launch", "tickets", "changes")}
    row["favorite"] = bool(item.get("favorite"))
    row["what"], row["reported"] = item.get("what"), item.get("reported")   # "What this changes", "Reported #N"
    row["size"], row["own_size"] = item.get("size"), item.get("own_size")
    pic = (item.get("images") or [{}])[0].get("url") or ((item.get("shots") or [{}])[0].get("url"))
    row |= {"kind": kind, "image": pic or "", "launch_options": launch_options(item, pcs),
            "rebuild_recipe": recipe, "recipe_recorded": recorded,
            **({"recipe_missing": "the marker records no character or cast plan to build it from"} if not recipe else {})}
    if kind == "showcase":
        sc = showcase_of(meta) or {}
        row["cast"] = cast_summary(item, meta)
        row["showcase"] = {"plan": sc.get("plan") or meta.get("cast_plan") or "", "writer": sc.get("writer") or "",
                           "previews": [p for p in item.get("fit_previews") or []][:6],
                           **({"linked_from": sc["linked_from"]} if isinstance(sc.get("linked_from"), dict) else {})}
        if not row["image"] and row["showcase"]["previews"]:
            row["image"] = row["showcase"]["previews"][0].get("url") or ""
        row["summary"] = f"Sonic Adventure cast · {row['cast']['summary']}"
    elif kind == "cast":
        row["cast"] = cast_summary(item, meta)
        row["summary"] = f"{row['cast']['source'] or 'cast'} · {row['cast']['summary']}"
    elif kind == "character":
        row["summary"] = "; ".join(f"{c.get('donor') or '?'} → {c.get('slot') or '?'}" for c in item["changes"])[:200]
    else:
        row["summary"] = f"built by {item.get('writer') or '?'}"
    return row


def group(items: list[dict], metas: dict, pcs: list[dict]) -> list[dict]:
    """The four groups, newest build first in each; a build linked to a ticket is a confirmation build. Sonic showcase
    builds form a fifth group (after the confirmation builds), present only when the game has one. The operator's
    favorites (★) move to a "Favorites" group at the top (only when there are some); `home` keeps the group a build
    belongs to, so "rebuild every confirmation build" still includes a favorited one."""
    rows = {k: [] for k, _ in (*GROUPS, SHOWCASE)}
    favs = []
    for it in sorted(items, key=lambda m: -(m.get("built") or 0)):
        row = build_row(it, metas.get(it["key"]) or {}, pcs)
        row["home"] = "confirmation" if row["tickets"] else row["kind"]
        (favs if row["favorite"] else rows[row["home"]]).append(row)
    order = [*([FAVORITES] if favs else []), GROUPS[0], *([SHOWCASE] if rows["showcase"] else []), *GROUPS[1:]]
    rows["favorites"] = favs
    return [{"key": k, "label": label, "count": len(rows[k]), "builds": rows[k]} for k, label in order]


def for_game(items: list[dict], records: list[dict], game_id: str, pcs: list[dict]) -> dict:
    metas = {f"{r['game_id']}/{r['name']}": r.get("meta") or {} for r in records}
    mine = [m for m in items if m["game_id"] == game_id or (metas.get(m["key"]) or {}).get("game_id") == game_id]
    groups = group(mine, metas, pcs)
    return {"game_id": game_id, "total": len(mine), "groups": groups,
            "pcs": [{"name": w.get("name"), "os": w.get("os")} for w in pcs]}


# ------------------------------------------------------------------------------------------------- rebuilding

def sanitize(recipe) -> dict:
    """A recipe from the client -> the characters call to queue, or ValueError. Only builds (never a launch)."""
    if not isinstance(recipe, dict) or recipe.get("tool") != "characters" or not isinstance(recipe.get("input"), dict):
        raise ValueError("a recipe is {tool: 'characters', input: {op: use | match | cast_swap, ...}}")
    inp = dict(recipe["input"])
    if inp.get("op") not in RECIPE_OPS:
        raise ValueError(f"op={inp.get('op')!r}: a rebuild is characters op=use | match | cast_swap")
    inp = {k: v for k, v in inp.items() if k in ("op", "launch", "rebuild", *KEEP[inp["op"]])}
    if not (inp.get("game_id") or inp.get("target_game")):
        raise ValueError("the recipe names no game")
    return {"tool": "characters", "input": inp | {"launch": False, "rebuild": True}}


def pick(groups: list[dict], recipes, group_key: str = "confirmation", keys=None) -> tuple[list[dict], list[dict]]:
    """-> ([{key, label, recipe}], [{key, reason}]): the recipes asked for ("all" = every build of the group)."""
    builds = [b for g in groups for b in g["builds"]]
    todo, skipped = [], []
    if recipes == "all" or keys:
        want = set(keys or [])
        for g in groups:
            for b in g["builds"]:
                if (keys and b["key"] in want) or (not keys and (group_key in ("all", g["key"], b.get("home")))):
                    if b.get("rebuild_recipe"):
                        todo.append({"key": b["key"], "label": b.get("mod_title") or b["name"], "recipe": b["rebuild_recipe"]})
                    else:
                        skipped.append({"key": b["key"], "reason": b.get("recipe_missing") or "no recipe"})
    elif isinstance(recipes, list):
        by_recipe = {json.dumps(b.get("rebuild_recipe"), sort_keys=True): b for b in builds if b.get("rebuild_recipe")}
        for i, r in enumerate(recipes):
            b = by_recipe.get(json.dumps(r, sort_keys=True)) or {}
            todo.append({"key": b.get("key") or f"recipe:{i}", "label": b.get("mod_title") or b.get("name") or "", "recipe": r})
    else:
        raise ValueError('recipes: a list of recipes or "all"')
    return todo, skipped


def queue(todo: list[dict], submit) -> tuple[list[dict], list[dict]]:
    """Queue each recipe once as a Spark job: submit(tool, input, require_os) -> job dict. -> (jobs, skipped)."""
    jobs, skipped, seen = [], [], {}
    for t in todo:
        try:
            call = sanitize(t["recipe"])
        except ValueError as e:
            skipped.append({"key": t["key"], "reason": str(e)})
            continue
        sig = json.dumps(call, sort_keys=True)
        if sig in seen:
            skipped.append({"key": t["key"], "reason": f"same recipe as {seen[sig]} (queued once)"})
            continue
        seen[sig] = t["key"]
        try:
            j = submit(call["tool"], call["input"], "linux")
        except Exception as e:                                   # noqa: BLE001 - one bad recipe never stops the rest
            skipped.append({"key": t["key"], "reason": str(getattr(e, "detail", "") or e)[:300]})
            continue
        j = j.model_dump(mode="json") if hasattr(j, "model_dump") else dict(j)
        row = {"key": t["key"], "label": t["label"], "job_id": j.get("id"), "state": j.get("state"), "tool": j.get("tool"),
               "input": j.get("input")}
        if j.get("state") == "rejected":
            skipped.append({"key": t["key"], "reason": j.get("error") or "rejected", "job_id": j.get("id")})
            continue
        jobs.append(row)
    return jobs, skipped


# ------------------------------------------------------------------------------------------------- routes

def routes(app, store, config, auth, *, submit, workers):
    """submit(tool, input, require_os, actor) -> job; workers() -> [worker + online] (the server's own)."""
    from . import built_mods

    def current_items(fresh: bool = False) -> tuple[list[dict], list[dict], dict]:
        index = getattr(app.state, "built_mods", None)
        if index is None:
            return [], [], {}
        index.start()
        if fresh:
            index.ask()
        cur = getattr(app.state, "built_mods_current", None)
        data = cur(fresh) if cur else built_mods.gallery(store, config, index.records(), register=False)
        return data["items"], index.records(), index.status()

    def online_pcs() -> list[dict]:
        try:
            return sorted(({"name": w.get("name"), "os": w.get("os"), "id": w.get("id")} for w in workers()
                           if w.get("online") and w.get("name")), key=lambda w: str(w["name"]).lower())
        except Exception:                                        # noqa: BLE001
            return []

    @app.get("/api/games/{game_id}/special_builds")
    def special_builds(game_id: str, fresh: bool = False, actor=Depends(auth)):
        """This game's built mods for the right-click menu: Confirmation builds (linked to requests), Cast swaps,
        Character swaps, Other; each with launch options and the recipe that rebuilds it."""
        items, records, status = current_items(fresh)
        return for_game(items, records, game_id, online_pcs()) | status

    @app.post("/api/games/{game_id}/special_builds/rebuild")
    def special_rebuild(game_id: str, body: dict = Body(default={}), actor=Depends(auth)):
        """Queue rebuilds as Spark jobs: {recipes: [recipe, ...] | "all", group: confirmation | cast | character |
        other | all (with "all"), keys: [build key, ...]} -> {jobs: [{key, job_id, state}], job_ids, skipped}."""
        recipes, keys = body.get("recipes", "all"), body.get("keys") or None
        items, records, _status = current_items(False)
        groups = for_game(items, records, game_id, [])["groups"]
        try:
            todo, skipped = pick(groups, recipes, str(body.get("group") or "confirmation"), keys)
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
        jobs, more = queue(todo, lambda tool, inp, os_: submit(tool, inp, os_, actor))
        store.audit(actor, "special_builds.rebuild", game_id, {"jobs": [j["job_id"] for j in jobs],
                                                               "skipped": len(skipped) + len(more)})
        return {"game_id": game_id, "jobs": jobs, "job_ids": [j["job_id"] for j in jobs], "skipped": skipped + more,
                "queued": len(jobs)}

    return special_builds, special_rebuild
