"""Mashup orchestrator: turn a natural-language cross-title request into a concrete gBox plan and dispatch it.

The operator can say things like "put the Mario 64 sprite in Ocarina of Time" or
"replace Link with Ganondorf". This tool parses the intent, resolves the source
character and target game against the live catalog and character library, checks
what gBox can do today (coverage), optionally dispatches the required jobs, and
returns a durable plan with job IDs.
"""
from __future__ import annotations

import json
import re
import time
from typing import Literal

import httpx
from pydantic import BaseModel, Field

from . import char_coverage as CC
from .models import Permission as P
from .registry import tool


STOP = {"the", "a", "an", "in", "into", "of", "as", "with", "from", "and", "or",
        "put", "place", "replace", "swap", "use", "play", "have", "make", "want",
        "character", "model", "sprite", "skin", "mod", "mashup", "game", "title"}


def _words(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", s.lower())) - STOP


def _api(ctx, method: str, path: str, **kw):
    """Call the gBox control plane."""
    server = getattr(ctx, "server", None)
    if not server:
        raise RuntimeError("mashup needs the control plane: ctx.server is not set on this worker")
    headers = getattr(ctx, "headers", None) or {}
    r = httpx.request(method, f"{server}{path}", headers=headers, timeout=kw.pop("timeout", 60), **kw)
    r.raise_for_status()
    return r.json() if "json" in r.headers.get("content-type", "") else r.content


def _resolve_character(name: str, ctx) -> dict | None:
    """Fuzzy-match a character name/slug against the live library."""
    if not name:
        return None
    entries = _api(ctx, "GET", "/api/characters")
    q = name.strip().lower()
    # exact slug / name / alias
    for e in entries:
        if q == str(e.get("slug", "")).lower() or q == str(e.get("name", "")).lower():
            return e
    for e in entries:
        if q in [str(a).lower() for a in e.get("aliases", [])]:
            return e
    # word overlap
    qw = _words(q)
    best, score = None, 0.0
    for e in entries:
        hay = _words(" ".join([str(e.get("slug", "")), str(e.get("name", "")),
                               *[str(a) for a in e.get("aliases", [])]]))
        s = len(qw & hay) / len(qw | hay) if qw and hay else 0.0
        if s > score:
            best, score = e, s
    return best if score >= 0.34 else None


def _resolve_game(name: str, ctx) -> dict | None:
    """Fuzzy-match a game title/id against the live catalog."""
    if not name:
        return None
    q = name.strip().lower()
    if re.fullmatch(r"[0-9a-f]{16}", q):
        try:
            return _api(ctx, "GET", f"/api/catalog/{q}")
        except httpx.HTTPError:
            return None
    hits = _api(ctx, "GET", "/api/catalog/best", params={"q": name, "limit": 8})
    hits = hits.get("items", hits) if isinstance(hits, dict) else hits
    if not hits:
        return None
    # prefer title match
    qw = _words(q)
    best, score = None, -1.0
    for g in hits:
        hw = _words(g.get("title", ""))
        s = len(qw & hw) / len(qw | hw) if qw and hw else 0.0
        if s > score:
            best, score = g, s
    return best


def _parse_request(request: str) -> tuple[str, str]:
    """Very rough source/target extraction from a free-form request.

    Examples:
      "Mario 64 sprite in Ocarina of Time" -> source "mario 64 sprite", target "ocarina of time"
      "replace Link with Ganondorf" -> source "ganondorf", target "link" (the replaced character, not a game:
                                       say "... in Ocarina of Time" or pass target= for the game)
      "replace Link with Ganondorf in Ocarina of Time" -> source "ganondorf", target "ocarina of time"
      "swap Link and Ganondorf" -> source "ganondorf", target "link"
      "metal gear solid 2 snake in metal gear solid 1" -> source "metal gear solid 2 snake", target "metal gear solid 1"
    """
    r = request.lower()
    places = (" in ", " into ", " inside ", " within ")
    # "replace X with Y" / "swap A and B" first: their "with" / "and" are not the source/target separators below
    m = re.search(r"replace\s+(.+?)\s+with\s+(.+)", r) or re.search(r"swap\s+(.+?)\s+and\s+(.+)", r)
    if m:
        src, replaced = m.group(2).strip(), m.group(1).strip()
        for splitter in places:                          # "... with Ganondorf in Ocarina of Time": the game wins
            if splitter in src:
                src, game = src.split(splitter, 1)
                return src.strip(), game.strip()
        return src, replaced
    # split on common prepositions that separate source and target
    for splitter in places:
        if splitter in r:
            parts = r.split(splitter, 1)
            return parts[0].strip(), parts[1].strip()
    for splitter in (" as ", " with ", " using "):
        if splitter in r:
            parts = r.split(splitter, 1)
            return parts[1].strip(), parts[0].strip()
    return r.strip(), ""


_EVERYONE = r"(?:everyone|everybody|every character|all (?:the )?characters|the (?:entire |whole )?cast|(?:the )?entire cast|(?:the )?whole cast|all of them)"
_CAST_RX = [
    # "replace everyone in PSO with wrestlers", "replace the entire cast of PSO with the entire cast of JGR"
    re.compile(rf"(?:replace|swap|change|turn|make)\s+{_EVERYONE}\s+(?:in|of)\s+(?P<target>.+?)\s+(?:with|into|to|as)\s+"
               rf"(?:the\s+)?(?:(?:entire|whole)\s+cast\s+of\s+|characters\s+(?:from|of)\s+|cast\s+of\s+)?(?P<source>.+)"),
    # "make PSO's cast the wrestlers", "PSO cast as wrestlers"
    re.compile(r"(?P<target>.+?)(?:'s)?\s+(?:entire\s+|whole\s+)?cast\s+(?:as|with|replaced by)\s+(?:the\s+)?(?P<source>.+)"),
    # "everyone in PSO as Jet Grind Radio characters"
    re.compile(rf"{_EVERYONE}\s+in\s+(?P<target>.+?)\s+(?:as|with)\s+(?:the\s+)?(?P<source>.+)"),
]


def parse_cast_request(request: str) -> tuple[str, str] | None:
    """A whole-cast request -> (target game, source game / group), else None. 'replace everyone in PSO with
    wrestlers' -> ('pso', 'wrestlers'): routed to characters op=cast_swap, not a one-character swap."""
    r = re.sub(r"[.!?]+$", "", (request or "").strip().lower())
    for rx in _CAST_RX:
        m = rx.search(r)
        if m:
            src = re.sub(r"\s+(?:characters|character models|models|cast|roster|guys|ones)$", "", m.group("source").strip())
            src = re.sub(r"^(?:characters|the characters)\s+(?:from|of)\s+", "", src)
            tgt = re.sub(r"^(?:the\s+)?(?:game\s+)?", "", m.group("target").strip())
            return tgt, src
    return None


def _slot_default(game: dict) -> str:
    """Pick a sensible default slot for a game that has a native writer."""
    title = (game.get("title") or "").lower()
    plat = game.get("platform", "")
    if "no mercy" in title or "wrestlemania" in title or "smackdown" in title or "wcw" in title:
        return "player"
    if "metal arms" in title:
        return "player"
    if "gta" in title and "liberty city" in title:
        return "player"
    if "resident evil 4" in title:
        return "player"
    if "sonic adventure 2" in title:
        return "player"
    if "super mario 64" in title:
        return "player"
    if "ocarina" in title or ("zelda" in title and plat == "n64"):
        return "player"                    # gbox.oot_swap: "player" is Link; any other slot names an NPC
    if "parasite eve" in title:
        return "player"
    if "final fantasy vii" in title:
        return "player"
    return "player"


def _feasibility(character: dict, game: dict, ctx) -> dict:
    """Return coverage info for this source/target pair."""
    ex, roster = CC.extractor_for(game)
    writer = CC.writer_for(game)
    source_ready = bool(character and (character.get("rig") or {}).get("roles"))
    source_game_id = (character.get("source") or {}).get("game_id") if character else None
    source_same_game = source_game_id == game.get("game_id")
    return {
        "source_ready": source_ready,
        "source_in_collection": bool(character),
        "target_extractor": ex,
        "target_roster_count": len(roster),
        "target_writer": writer,
        "target_native": bool(writer and writer.get("routed")),
        "target_rip_possible": bool(ex),
        "source_same_game": source_same_game,
    }


def _dispatch_job(ctx, tool_name: str, inp: dict, limit: float = 900) -> dict:
    """Submit a job to the control plane and wait for it to leave queued/running, up to limit seconds."""
    j = _api(ctx, "POST", "/api/jobs", json={"tool": tool_name, "input": inp,
             "parent_request_id": getattr(ctx, "parent_request_id", None)})
    t0 = time.time()
    while j.get("state") in ("queued", "running") and time.time() - t0 < limit:
        time.sleep(1)
        j = _api(ctx, "GET", f"/api/jobs/{j['id']}")
    return j


def _build_plan(character: dict, game: dict, feas: dict, auto_dispatch: bool, ctx) -> dict:
    """Produce the ordered plan and optionally dispatch the jobs."""
    steps = []
    jobs = []
    status = "pending"

    # Step 1: source character must exist and be retargetable
    if not character:
        steps.append({"step": 1, "action": "identify_source",
                      "status": "needed", "detail": "Could not resolve a source character from the request"})
        status = "unresolvable"
        return {"steps": steps, "jobs": jobs, "status": status}

    steps.append({"step": 1, "action": "identify_source", "status": "ok",
                  "detail": f"Source character: {character.get('name')} ({character.get('slug')})"})

    if not feas["source_ready"]:
        source_game_id = (character.get("source") or {}).get("game_id")
        if source_game_id:
            steps.append({"step": 2, "action": "collect_source", "status": "needed" if not auto_dispatch else "dispatched",
                          "detail": f"Source {character.get('slug')} needs a mapped rig; collect from {source_game_id}"})
            if auto_dispatch:
                j = _dispatch_job(ctx, "characters", {"op": "collect", "game_id": source_game_id})
                jobs.append({"tool": "characters", "op": "collect", "game_id": source_game_id, "job": j})
        else:
            steps.append({"step": 2, "action": "collect_source", "status": "blocked",
                          "detail": "Source character has no recorded origin game_id"})
            status = "blocked"

    # Step 2: target game
    if not game:
        steps.append({"step": 3, "action": "identify_target", "status": "needed",
                      "detail": "Could not resolve a target game from the request"})
        status = "unresolvable"
        return {"steps": steps, "jobs": jobs, "status": status}

    steps.append({"step": 3, "action": "identify_target", "status": "ok",
                  "detail": f"Target game: {game.get('title')} ({game.get('game_id')}, {game.get('platform')})"})

    # Step 3: feasibility
    if not feas["target_native"]:
        steps.append({"step": 4, "action": "check_feasibility", "status": "blocked",
                      "detail": "Target game has no routed native writer; overlay is the only immediate option",
                      "writer": feas["target_writer"],
                      "fallback": "characters op=overlay for a visual-only overlay, or build the native writer"})
        status = "needs_writer"
        # file a gap report if source is ready
        if feas["source_ready"]:
            steps.append({"step": 5, "action": "file_gap_report", "status": "needed",
                          "detail": "A native writer gap report should be filed for this target"})
        return {"steps": steps, "jobs": jobs, "status": status}

    steps.append({"step": 4, "action": "check_feasibility", "status": "ok",
                  "detail": f"Target has routed writer {feas['target_writer'].get('writer')}"})

    # Step 4: dispatch the swap
    slot = _slot_default(game)
    steps.append({"step": 5, "action": "build_and_launch_swap", "status": "needed" if not auto_dispatch else "dispatched",
                  "detail": f"characters op=use character={character.get('slug')} game_id={game.get('game_id')} slot={slot}"})
    if auto_dispatch:
        j = _dispatch_job(ctx, "characters", {"op": "use", "character": character.get("slug"),
                                              "game_id": game.get("game_id"), "slot": slot})
        jobs.append({"tool": "characters", "op": "use", "character": character.get("slug"),
                     "game_id": game.get("game_id"), "slot": slot, "job": j})
        if j.get("state") == "succeeded":
            status = "dispatched_succeeded"
        else:
            status = "dispatched_failed"
    else:
        status = "ready_to_dispatch"

    return {"steps": steps, "jobs": jobs, "status": status}


class MashupIn(BaseModel):
    request: str = Field(default="", description="Free-form mashup request, e.g. 'Mario 64 sprite in Ocarina of Time'.")
    source: str = Field(default="", description="Optional explicit source character name/slug.")
    target: str = Field(default="", description="Optional explicit target game title/id.")
    dry_run: bool = Field(default=False, description="If true, only return the plan; do not submit jobs.")
    auto_dispatch: bool = Field(default=False, description="If true, submit the required collection/use jobs.")


class MashupOut(BaseModel):
    result: dict


@tool("mashup", "1.0", MashupIn, MashupOut,
      capabilities=["planning", "characters", "catalog"], permissions=[P.READ, P.NETWORK, P.EXECUTE],
      timeout_s=1200,
      side_effects=["May submit characters collection/use jobs when auto_dispatch=true"],
      artifacts=["mashup-plan.json"])
def mashup(inp: MashupIn, ctx):
    """Turn a natural-language cross-title request into a concrete gBox plan and optionally dispatch it.

    The operator can say things like "put the Mario 64 sprite in Ocarina of Time"
    or "replace Link with Ganondorf". This tool resolves the source character and
    target game, checks what gBox can do today via the coverage matrix, and returns
    an ordered plan with job IDs when auto_dispatch is enabled.
    """
    if not inp.request.strip() and not (inp.source and inp.target):
        raise ValueError("Provide a request string, or both source and target")

    cast = parse_cast_request(inp.request) if inp.request.strip() else None
    if cast:                                              # "replace everyone in PSO with wrestlers": one whole-cast mod
        result = _cast_plan(cast, inp, ctx)
        ctx.artifact("mashup-plan.json", json.dumps(result, indent=2).encode(), "application/json",
                     request=inp.request, target=result["understood"].get("target_game_id"), source=cast[1])
        return {"result": result}

    parsed_source, parsed_target = _parse_request(inp.request) if inp.request.strip() else ("", "")
    source_name = (inp.source or parsed_source).strip()
    target_name = (inp.target or parsed_target).strip()

    character = _resolve_character(source_name, ctx) if source_name else None
    game = _resolve_game(target_name, ctx) if target_name else None

    feas = _feasibility(character, game, ctx) if (character and game) else {
        "source_ready": False, "source_in_collection": bool(character),
        "target_extractor": None, "target_roster_count": 0,
        "target_writer": None, "target_native": False,
        "target_rip_possible": bool(game), "source_same_game": False,
    }

    plan = _build_plan(character, game, feas, inp.auto_dispatch and not inp.dry_run, ctx)

    result = {
        "request": inp.request,
        "understood": {
            "source_name": source_name,
            "source_slug": character.get("slug") if character else None,
            "source_character": character.get("name") if character else None,
            "target_name": target_name,
            "target_game_id": game.get("game_id") if game else None,
            "target_title": game.get("title") if game else None,
        },
        "feasibility": feas,
        "plan": plan["steps"],
        "jobs": [{k: v for k, v in j.items() if k != "job"} for j in plan["jobs"]],
        "job_details": [j["job"] for j in plan["jobs"]],
        "status": plan["status"],
        "next_action": _next_action(plan["status"]),
        "dry_run": inp.dry_run or not inp.auto_dispatch,
    }

    ctx.artifact("mashup-plan.json", json.dumps(result, indent=2).encode(), "application/json",
                 request=inp.request, target=game.get("game_id") if game else None,
                 source=character.get("slug") if character else None)
    return {"result": result}


def _cast_plan(cast: tuple[str, str], inp: MashupIn, ctx) -> dict:
    """A whole-cast request: characters op=cast_swap target_game=<game> source=<game | group> (gbox.cast_swap)."""
    from .cast_swap import expand
    target_name, source_name = (inp.target or cast[0]), (inp.source or cast[1])
    game = _resolve_game(expand(target_name), ctx)
    call = {"op": "cast_swap", "target_game": (game or {}).get("game_id") or target_name, "source": source_name,
            "mapping": "auto", "launch": False}
    steps = [{"step": 1, "action": "identify_target", "status": "ok" if game else "needed",
              "detail": f"Target game: {game.get('title')} ({game.get('game_id')})" if game else
              f"Could not resolve the game {target_name!r}"},
             {"step": 2, "action": "cast_swap", "status": "needed",
              "detail": f"characters op=cast_swap target_game={call['target_game']} source={source_name!r}: every "
                        "replaceable slot gets a donor of the source cast, built as one mod (plan_only=true first to "
                        "review the assignments)"}]
    jobs, status = [], "unresolvable" if not game else "ready_to_dispatch"
    if game and inp.auto_dispatch and not inp.dry_run:
        j = _dispatch_job(ctx, "characters", call, limit=14400)
        jobs.append({"tool": "characters", "op": "cast_swap", "game_id": game["game_id"], "job": j})
        steps[1]["status"] = "dispatched"
        status = "dispatched_succeeded" if j.get("state") == "succeeded" else "dispatched_failed"
    return {"request": inp.request, "kind": "cast_swap",
            "understood": {"target_name": target_name, "target_game_id": (game or {}).get("game_id"),
                           "target_title": (game or {}).get("title"), "source_name": source_name},
            "call": {"tool": "characters", "input": call}, "plan": steps,
            "jobs": [{k: v for k, v in j.items() if k != "job"} for j in jobs], "job_details": [j["job"] for j in jobs],
            "status": status, "next_action": _next_action(status), "dry_run": inp.dry_run or not inp.auto_dispatch}


def _next_action(status: str) -> str:
    return {
        "unresolvable": "Rephrase the request with explicit source/target, or run again with source= and target=.",
        "blocked": "The source character needs a mapped rig; collect or extract it first.",
        "needs_writer": "This target has no native writer yet; use characters op=overlay for a visual-only preview, or build the writer.",
        "ready_to_dispatch": "Set auto_dispatch=true to submit the characters op=use job.",
        "dispatched_succeeded": "The swap job succeeded; verify it in-game.",
        "dispatched_failed": "The swap job failed; inspect the job details for the exact error.",
        "pending": "Review the plan and set auto_dispatch=true to execute.",
    }.get(status, "Review the plan.")
