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


def add_change(store, game_id, *, note, text, request_id, message_id, by="operator", session_id=None):
    """One change per evidence note. Never discard unfinished work or hide a persistence failure."""
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
                   "context": {"coaching_change": True, "coaching_change_id": change_id, "game_id": game_id,
                               "coaching_request_id": item["request_id"], "coaching_message_id": item["message_id"],
                               "session_id": item.get("session_id")},
                   "body": f"Operator critique: {item['text']}\n\n"
                           f"Improve the active bot for this title using the evidence on coaching ticket "
                           f"{item['request_id']}, message {item['message_id']}. Read the capture status at "
                           f"/api/sessions/{item.get('session_id')}/coach/{item['message_id']}; "
                           "captures may still be pending. Inspect the actual bot and reproduce the issue, implement a "
                           "bounded correction, run relevant tests, and attach a reviewable PR and verification evidence. "
                           "Do not claim the critique is fixed from button presses or a successful command alone. "
                           f"Update /api/autoplay/bots/{game_id}/changes/{change_id} through acknowledged, applied "
                           "(with pr), and verified (with verification). Respect current game ownership, admission, "
                           "review, and deployment rules; this request does not authorize taking another controller."}
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
