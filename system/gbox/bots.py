"""Durable per-title coaching changes, adapted from Hermes #2969 commit 3aaca405.

This integrates the useful queue, not the unfinished favorite/owner registry. Bot
matching uses the runtime's tuple of module names. A registry label alone cannot
prove that an engineering agent is active, so dispatch ownership is not invented.
"""
from __future__ import annotations

import importlib
import time
from typing import Literal

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from .models import new_id

CHANGES_KIND = "bot_changes"
MAX_ITEMS = 500
CHANGE_STATES = ("open", "acknowledged", "applied", "verified")
_TRANSITIONS = {"open": {"acknowledged", "applied"}, "acknowledged": {"applied"},
                "applied": {"verified"}, "verified": set()}

# Where each live Mercenaries bot lives (operator 2026-11-10: "these become reports that get sent through to Hermes that
# becomes changes"). The implementation request names these files so the agent starts in the bot that played: the
# Switch editions MercMode rotates (RE always means Switch), never the GameCube re4_merc_bot.py the old ticket text
# pointed at, nor gbox/mercs_bot.py (the playbook shell; a 2026-11-10 run spent its 200 calls there and changed nothing).
CORE_FILES = ("gbox/mercs/core/doctrine.py (the standing goals, the commands' fallback)",
              "gbox/mercs/core/combat.py (the shared fight: targets, throws, fire pattern)",
              "gbox/mercs/core/respond.py (the answer to a threat)",
              "gbox/mercs/directives.py (the PiP's instant commands)")
BOT_FILES = {
    "270a15eb98dab4d7": ("Resident Evil 4 (Switch, Mercenaries)", (
        "gbox/mercs/titles/re4_switch.py (class Bot: the fight, the walk to a Ganado, the commands)",
        "gbox/mercs/titles/re4_walk.py (the mesh walker)",
        "gbox/re4switch_bot.py (the playbook: menus, rounds, the Bot's keys)"),
        ("tests/test_re4_switch_fight.py", "tests/test_re4_switch_brain.py", "tests/test_re4switch_bot.py")),
    "52d15709be0fda1a": ("Resident Evil 5 (Switch, No Mercy)", (
        "gbox/mercs/titles/re5_switch.py (class Bot: the fight, mines, grenades, the commands)",
        "gbox/mercs/titles/re5_switch_aim.py / re5_switch_wall.py / re5_switch_mines.py (its helpers)"),
        ("tests/test_re5_switch.py", "tests/test_re5_switch_directives.py")),
    "115f9cdbba115432": ("Resident Evil 6 (Switch, No Mercy)", (
        "gbox/mercs/titles/re6_switch.py (class Bot: the fight, grenades _nade*, bombs, flash, the commands)",
        "gbox/mercs/titles/re6_switch_wall.py (walls and the nav mesh)",
        "gbox/mercs/titles/re6_switch_native.py (native flash / grenade ring)"),
        ("tests/test_re6_switch.py", "tests/test_re6_bomb_drop.py", "tests/test_re6_switch_parity.py")),
}


def bot_files(game_id, title=None) -> tuple:
    """(name, source files, tests) of the live bot for a game; a title naming RE4 / RE5 / RE6 maps to its Switch bot."""
    row = BOT_FILES.get(game_id)
    if row is None:
        t = str(title or "").lower()
        key = next((g for g, n in (("270a15eb98dab4d7", "resident evil 4"), ("52d15709be0fda1a", "resident evil 5"),
                                   ("115f9cdbba115432", "resident evil 6")) if n in t), None)
        row = BOT_FILES.get(key)
    if row is None:
        return (title or game_id, ("gbox/mercs_bot.py and the title module it names (gbox/mercs/titles/)",), ())
    return row


def files_text(game_id, title=None) -> str:
    """The bot's files as request text: the title's own first, then the shared core, then its tests."""
    name, files, tests = bot_files(game_id, title)
    rows = [f"The live bot for {name}. Start in:"] + [f"  - {f}" for f in files]
    rows += ["Shared by every Mercenaries bot:"] + [f"  - {f}" for f in CORE_FILES]
    if tests:
        rows.append("Tests to extend: " + ", ".join(tests))
    return "\n".join(rows)


def playbook_for(game: dict) -> str:
    """Read-only matching; never calls setup/play or imports a caller-supplied name."""
    from . import tools
    for name in tools.PLAYBOOKS:
        try:
            module = importlib.import_module(f".{name}", __package__)
            if module.matches(None, game):
                return name
        except (ImportError, AttributeError, TypeError, ValueError, OSError):
            continue
    return "imitate"


def _body(store, game_id):
    body = store.get(CHANGES_KIND, game_id)
    if body is None:
        return {"game_id": game_id, "items": []}
    if not isinstance(body, dict) or not isinstance(body.get("items"), list) \
            or any(not isinstance(row, dict) for row in body["items"]):
        raise ValueError("Invalid persisted coaching change queue; repair it before adding work")
    return body


def changes_for(store, game_id):
    with store.lock:
        return _body(store, game_id)


def for_game(store, game_id):
    game = store.catalog_get(game_id) or {"game_id": game_id}
    return {"game_id": game_id, "playbook": playbook_for(game), "owner": None,
            "ownership_available": False, "dispatch": "hermes_guarded_inbox",
            "open_changes": sum(row.get("state") != "verified" for row in changes_for(store, game_id)["items"])}


def add_change(store, game_id, *, note, text, request_id, message_id, by="operator", session_id=None, moment=None):
    """One change per evidence note. Never discard unfinished work or hide a persistence failure. `moment`: one line of
    what the bot was doing when the note came (coaching.moment_line), written into the implementation request."""
    if not game_id or not request_id or not message_id or not text.strip():
        raise ValueError("A coaching change needs its game, note, ticket and text")
    with store.lock:
        body = _body(store, game_id)
        items = list(body["items"])
        existing = next((row for row in items if row.get("request_id") == request_id
                         and row.get("message_id") == message_id), None)
        if existing:
            if existing.get("text") != text:
                raise ValueError("The evidence note already has a different queued change")
            return existing
        while len(items) >= MAX_ITEMS:
            completed = next((i for i, row in enumerate(items) if row.get("state") == "verified"), None)
            if completed is None:
                raise ValueError("The coaching change queue is full of unfinished work")
            items.pop(completed)
        now = time.time()
        item = {"id": "chg-" + new_id(), "note": note, "text": text, "request_id": request_id,
                "message_id": message_id, "session_id": session_id, "state": "open", "by": by,
                "pr": None, "verification": None, "ts": now, "updated": now}
        if moment:
            item["moment"] = str(moment)[:600]
        items.append(item)
        store.put(CHANGES_KIND, game_id, {"game_id": game_id, "items": items, "updated": now})
        return item


def _child_for(store, game_id, item):
    return next((row for row in store.game_requests(game_id,
                 statuses=("open", "in_progress", "blocked", "done", "rejected"), limit=MAX_ITEMS * 2 + 1)
                 if (row.get("context") or {}).get("coaching_change_id") == item["id"]
                 and (row.get("context") or {}).get("coaching_request_id") == item["request_id"]), None)


def dispatch_status(store, game_id, change_id):
    """Read status; reconcile a lost creation response from authoritative stored context only."""
    with store.lock:
        body = _body(store, game_id)
        item = next((row for row in body["items"] if row["id"] == change_id), {})
        if item.get("dispatch_state") in ("creating", "uncertain"):
            child = _child_for(store, game_id, item)
            if child:
                item.update(implementation_request_id=child["id"], implementation_number=child.get("number"),
                            dispatch_state="queued")
                item.pop("dispatch_error", None)
                store.put(CHANGES_KIND, game_id, body)
        return item


def request_body(game_id, title, change_id, item) -> str:
    """The implementation request's text: the critique, where the bot is, the moment, how to read the evidence, and
    the one deliverable. A run with no file pointers or evidence route read for 200 calls and left nothing
    (2026-11-10, #7097); "⚠ Flawed (PiP button)" was taken for a game mechanic."""
    sid, mid, rid = item.get("session_id"), item["message_id"], item["request_id"]
    moment = item.get("moment")
    return "\n\n".join(x for x in (
        f"Operator critique of the {title} bot (typed or clicked in the gBox picture-in-picture while it played): "
        f"{item['text']}",
        "\"PiP\", \"⚠ Flawed\" and the quick commands are the operator's buttons in the gBox app, not game mechanics: "
        "the operator saw the bot handle this moment badly and wants its code to change.",
        files_text(game_id, title),
        f"The bot at that moment: {moment}" if moment else "",
        f"Evidence: coaching ticket {rid}, message {mid} (note {item['note']}). GET /api/sessions/{sid}/coach/{mid} "
        "lists each capture with its state and sha256 (they may still be pending); GET /api/artifacts/<sha256> "
        "downloads one: coach-N-frame.png / coach-N-report-frame.jpg (the picture), coach-N-report-moment.json (the "
        "bot's telemetry: doing, why, directive, target, and the tactical frame with every enemy), coach-N-*-ram.gz "
        "(the main RAM).",
        "Deliverable: ONE bounded change in the bot code above that makes the bot do what the critique asks, with a "
        "focused unit test built from the moment's fields; run the title's tests; publish it as a draft PR "
        "(publish_task_changes); post the PR link and the effect you expect as a reply on this request; then "
        f"POST /api/autoplay/bots/{game_id}/changes/{change_id} with state applied and the pr. If you cannot finish, "
        "post what you found (files, functions, the failing check) on this request before you stop - never end "
        "silently. Do not claim the critique is fixed from button presses or a successful command alone: the live "
        "bot measures the change after a deploy (state verified, with the verification). Do not launch, stop, "
        "restart or swap games, MercMode or gBox; this request does not authorize taking another controller.",
    ) if x)


def ensure_request(store, create_request, game_id, change_id, actor):
    """File one ordinary operator child for Hermes; never pump or bypass admission.

    The durable change ID reconciles a creation whose response was lost. An
    uncertain creation with no matching stored request is held for inspection.
    """
    with store.lock:
        body = _body(store, game_id)
        item = next(row for row in body["items"] if row["id"] == change_id)
        child = _child_for(store, game_id, item)
        if child:
            item.update(implementation_request_id=child["id"], implementation_number=child.get("number"),
                        dispatch_state="queued")
            item.pop("dispatch_error", None)
            store.put(CHANGES_KIND, game_id, body)
            return item
        if item.get("dispatch_state") in ("creating", "uncertain", "queued"):
            return item  # never replay an uncertain creation or a removed request
        item["dispatch_state"] = "creating"
        store.put(CHANGES_KIND, game_id, body)
        parent = store.get("request", item["request_id"]) or {}
        title = (parent.get("context") or {}).get("title") or game_id
        request = {"title": f"Improve {title}: coaching note {item['note']}"[:140], "source": "coach_change",
                   "kind": "text", "author": "operator", "parent_request_id": item["request_id"],
                   # operator_requested: the Hermes queue works an operator's critique before the backlog
                   # (hermes_work_queue.sync / choose); it edits bot code only, so a game in play never holds it
                   "context": {"coaching_change": True, "coaching_change_id": change_id, "game_id": game_id,
                               "coaching_request_id": item["request_id"], "coaching_message_id": item["message_id"],
                               "session_id": item.get("session_id"), "operator_requested": True},
                   "body": request_body(game_id, title, change_id, item)}
        try:
            child = create_request(request, actor)
            item.update(implementation_request_id=child["id"], implementation_number=child.get("number"),
                        dispatch_state="queued")
        except Exception as error:
            item.update(dispatch_state="uncertain", dispatch_error=f"{type(error).__name__}: {error}"[:300])
            store.put(CHANGES_KIND, game_id, body)
            # The local request may already have committed before its response failed.
            return ensure_request(store, create_request, game_id, change_id, actor)
        store.put(CHANGES_KIND, game_id, body)
        return item


def set_change_state(store, game_id, change_id, state, *, by, pr=None, verification=None):
    if state not in CHANGE_STATES:
        raise ValueError("Unknown change state")
    if pr is not None:
        pr = pr.strip()
        if not pr:
            raise ValueError("A supplied PR reference must not be empty")
    if verification is not None:
        verification = verification.strip()
        if not verification:
            raise ValueError("A supplied verification summary must not be empty")
    with store.lock:
        body = _body(store, game_id)
        items = list(body["items"])
        for index, item in enumerate(items):
            if item.get("id") != change_id:
                continue
            current = item.get("state", "open")
            if state != current and state not in _TRANSITIONS.get(current, set()):
                raise ValueError(f"Illegal change transition: {current} -> {state}")
            if state == "applied" and not (pr or item.get("pr")):
                raise ValueError("Applied changes require a PR reference")
            if state == "verified" and not (verification or item.get("verification")):
                raise ValueError("Verified changes require a verification summary")
            updated = item | {"state": state, "by": by, "updated": time.time()}
            if pr is not None:
                updated["pr"] = pr
            if verification is not None:
                updated["verification"] = verification
            items[index] = updated
            store.put(CHANGES_KIND, game_id, body | {"items": items, "updated": updated["updated"]})
            return updated
        raise KeyError("No such coaching change for this game")


class ChangeIn(BaseModel):
    state: Literal["open", "acknowledged", "applied", "verified"]
    pr: str | None = Field(default=None, min_length=1, max_length=300)
    verification: str | None = Field(default=None, min_length=1, max_length=2000)


def routes(app, store, auth):
    @app.get("/api/autoplay/bots/{game_id}")
    def bot_status(game_id: str, actor=Depends(auth)):
        return for_game(store, game_id)

    @app.get("/api/autoplay/bots/{game_id}/changes")
    def bot_changes(game_id: str, actor=Depends(auth)):
        return changes_for(store, game_id)

    @app.post("/api/autoplay/bots/{game_id}/changes/{change_id}")
    def bot_change(game_id: str, change_id: str, body: ChangeIn, actor=Depends(auth)):
        try:
            return set_change_state(store, game_id, change_id, body.state, by=actor,
                                    pr=body.pr.strip() if body.pr else None,
                                    verification=body.verification.strip() if body.verification else None)
        except KeyError as error:
            raise HTTPException(404, str(error)) from error
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
