"""Session-local operator requests consumed by the existing bot's single input owner."""
import copy
import random
import threading
import time
import uuid

from . import re5_weapons as weapons

LOCK = threading.RLock()
FRESH_S, REQUEST_S, PIN_S = 5.0, 30.0, 15.0
FAMILIES = {"handgun", "automatic", "shotgun", "magnum"}


def eligible(item):
    spec = weapons.WEAPONS.get(item.get("item"))
    return item.get("type") == 1 and spec is not None and spec.family in FAMILIES \
        and (item.get("rounds") or 0) > 0 and bool(weapons.quick_key(item))


def publish(state, owner, snap, active, now=None):
    now = time.monotonic() if now is None else now
    player = (snap.get("player") or {}).get("ptr")
    with LOCK:
        state["controller"] = {"owner": owner, "player": player, "seen": now, "active": bool(active),
                               "inventory": [dict(w) for w in snap.get("inventory") or () if eligible(w)]}
        request = state.get("random_weapon_request")
        if request and request["state"] == "pending":
            if not active or request["owner"] != owner or request["player"] != player:
                request.update(state="rejected", reason="The round or input controller changed.")
            elif now >= request["expires"]:
                request.update(state="rejected", reason="No equipment confirmation before the request expired.")


def capability(state, now=None):
    now = time.monotonic() if now is None else now
    ctl = state.get("controller") or {}
    if not ctl.get("active") or not 0 <= now - ctl.get("seen", -1e9) <= FRESH_S:
        return {"available": False, "reason": "Waiting for a fresh active RE5 bot."}
    if not ctl.get("inventory"):
        return {"available": False, "reason": "No supported loaded gun in a quick slot."}
    return {"available": True, "reason": "Equips a loaded quick-slot gun; excludes rockets and sniper rifles."}


def request_status(state, now=None):
    now = time.monotonic() if now is None else now
    with LOCK:
        req = state.get("random_weapon_request")
        if req and req["state"] == "pending":
            ctl = state.get("controller") or {}
            if now >= req["expires"] or not ctl.get("active") or not 0 <= now - ctl.get("seen", -1e9) <= FRESH_S:
                req.update(state="rejected", reason="The request expired or its input controller stopped.")
        return copy.deepcopy(req)


def request(state, now=None, choose=None):
    now = time.monotonic() if now is None else now
    with LOCK:
        pending = state.get("random_weapon_request")
        if pending and pending["state"] == "pending" and now < pending["expires"]:
            return {"queued": True, "verified": False, "request": copy.deepcopy(pending)}
        cap = capability(state, now)
        if not cap["available"]:
            return {"queued": False, "verified": False, "reason": cap["reason"]}
        ctl = state["controller"]
        pool = [w for w in ctl["inventory"] if not w.get("hand")] or ctl["inventory"]
        item = (choose or random.SystemRandom().choice)(pool)
        pending = {"id": uuid.uuid4().hex, "state": "pending", "owner": ctl["owner"],
                   "player": ctl["player"], "target": weapons.inventory_key(item),
                   "weapon": weapons.WEAPONS[item["item"]].name, "expires": now + REQUEST_S}
        state["random_weapon_request"] = pending
        return {"queued": True, "verified": False, "request": copy.deepcopy(pending)}


def consume(state, owner, snap, switch, now, monotonic=None, *, input_allowed=True):
    """Return an ordinary D-pad action, never write inventory/weapon object IDs."""
    monotonic = time.monotonic() if monotonic is None else monotonic
    with LOCK:
        req = state.get("random_weapon_request")
        if not req or req["state"] != "pending":
            return None
        if req["owner"] != owner or req["player"] != (snap.get("player") or {}).get("ptr") \
                or monotonic >= req["expires"]:
            req.update(state="rejected", reason="The round changed or the request expired.")
            return None
        item = next((w for w in snap.get("inventory") or ()
                     if weapons.inventory_key(w) == req["target"] and eligible(w)), None)
        if item is None:
            req.update(state="rejected", reason="The requested quick-slot gun is no longer available.")
            return None
        if item.get("hand"):
            req.update(state="confirmed", reason="Confirmed equipped in the current inventory.")
            state["weapon_pin"] = {"target": req["target"], "until": now + PIN_S}
            return None
        if not input_allowed:
            return None
        return switch(item, now, "operator random weapon request")


def pinned(state, snap, now):
    pin = state.get("weapon_pin") or {}
    return now < pin.get("until", 0) and any(w.get("hand") and eligible(w)
        and weapons.inventory_key(w) == pin.get("target") for w in snap.get("inventory") or ())
