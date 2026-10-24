"""Session-local operator requests consumed by the existing bot's single input owner."""
import copy
import random
import threading
import time
import uuid
import weakref

from . import re5_weapons as weapons

LOCK = threading.RLock()
FRESH_S, REQUEST_S = 5.0, 30.0
FAMILIES = {"handgun", "automatic", "shotgun", "magnum", "bow"}


def eligible(item):
    spec = weapons.WEAPONS.get(item.get("item"))
    return item.get("type") == 1 and spec is not None and spec.family in FAMILIES \
        and (item.get("rounds") or 0) > 0 and bool(weapons.quick_key(item))


def bind_adapter(state,adapter):
    """An object-ID reused by another session must not inherit its gun choice."""
    with LOCK:
        ref=state.get('_weapon_adapter_ref')
        if ref is not None and ref() is not adapter:
            for key in ('preferred_weapon','random_weapon_request','weapon_pin'):
                state.pop(key,None)
        try:state['_weapon_adapter_ref']=weakref.ref(adapter)
        except TypeError:state.pop('_weapon_adapter_ref',None)


def preferred(state,snap):
    """Resolve the chosen gun afresh; storage slots can change between rounds."""
    with LOCK:
        choice=state.get('preferred_weapon') or {}
        options=[w for w in snap.get('inventory') or () if eligible(w)
                 or w.get('type')==1 and weapons.quick_key(w) and (w.get('cap') or 0)>0
                 and weapons.WEAPONS.get(w.get('item')) is not None
                 and weapons.WEAPONS[w['item']].family in FAMILIES]
        matching=[w for w in options if w.get('item')==choice.get('item')]
        return next((w for w in matching if weapons.inventory_key(w)==choice.get('target')),None) \
            or next(iter(matching),None)


def available(state,now=None):
    now=time.monotonic() if now is None else now
    with LOCK:
        ctl=state.get('controller') or {}
        if not ctl.get('active') or not 0<=now-ctl.get('seen',-1e9)<=FRESH_S:return []
        return [{'item':w['item'],'weapon':weapons.WEAPONS[w['item']].name,'slot':w.get('slot'),
                 'grid':w.get('grid'),'rounds':w.get('rounds'),'equipped':bool(w.get('hand'))}
                for w in ctl.get('inventory') or () if eligible(w)]


def preference_status(state,now=None):
    with LOCK:
        choice=state.get('preferred_weapon')
        if not choice:return None
        inventory=available(state,now)
        matching=[w for w in inventory if w['item']==choice['item']]
        return {'item':choice['item'],'weapon':choice['weapon'],'persistent':True,
                'available':bool(matching),'equipped':any(w['equipped'] for w in matching)}


def clear_preference(state):
    with LOCK:
        state.pop('preferred_weapon',None);state.pop('weapon_pin',None)
        req=state.get('random_weapon_request')
        if req and req['state'] in ('pending','deferred'):
            req.update(state='rejected',reason='Automatic gun selection resumed.')
    return {'verified':True,'preference_saved':True,'automatic':True}


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
        return {"available": False, "reason": "No supported loaded gun or longbow in a quick slot."}
    return {"available": True, "reason": "Equips a loaded quick-slot gun or longbow; excludes rockets and sniper rifles."}


def request_status(state, now=None):
    now = time.monotonic() if now is None else now
    with LOCK:
        req = state.get("random_weapon_request")
        if req and req["state"] == "pending":
            ctl = state.get("controller") or {}
            if now >= req["expires"] or not ctl.get("active") or not 0 <= now - ctl.get("seen", -1e9) <= FRESH_S:
                req.update(state="rejected", reason="The request expired or its input controller stopped.")
        return copy.deepcopy(req)


def request(state, now=None, choose=None, *, weapon=None,deferred=False):
    now = time.monotonic() if now is None else now
    with LOCK:
        pending = state.get("random_weapon_request")
        if weapon is None and pending and pending["state"] == "pending" and now < pending["expires"]:
            return {"queued": True, "verified": False, "request": copy.deepcopy(pending)}
        cap = capability(state, now)
        if not cap["available"]:
            return {"queued": False, "verified": False, "reason": cap["reason"]}
        ctl = state["controller"]
        pool = [w for w in ctl["inventory"] if not w.get("hand")] or ctl["inventory"]
        if weapon is not None:
            item=next((w for w in ctl['inventory'] if type(weapon) is int and w['item']==weapon),None)
            if item is None:return {'queued':False,'verified':False,'reason':'The selected gun is not currently available.'}
        else:item = (choose or random.SystemRandom().choice)(pool)
        pending = {"id": uuid.uuid4().hex, "state": "deferred" if deferred else "pending", "owner": ctl["owner"],
                   "player": ctl["player"], "target": weapons.inventory_key(item),
                   "weapon": weapons.WEAPONS[item["item"]].name, "expires": now + REQUEST_S}
        state["random_weapon_request"] = pending
        state['preferred_weapon']={'item':item['item'],'target':weapons.inventory_key(item),
                                   'weapon':pending['weapon']}
        return {"queued": True, "verified": False, "request": copy.deepcopy(pending),
                'preference_saved':True,'deferred':bool(deferred)}


def consume(state, owner, snap, switch, now, monotonic=None, *, input_allowed=True):
    """Return an ordinary D-pad action, never write inventory/weapon object IDs."""
    monotonic = time.monotonic() if monotonic is None else monotonic
    with LOCK:
        req = state.get("random_weapon_request")
        ctl=state.get('controller') or {}
        if not ctl.get('active') or ctl.get('owner')!=owner or ctl.get('player')!=(snap.get('player') or {}).get('ptr') \
                or not 0<=monotonic-ctl.get('seen',-1e9)<=FRESH_S:
            if req and req['state']=='pending':req.update(state='rejected',reason='The input controller changed.')
            return None
        if req and req['state']=='deferred':
            req.update(state='pending',owner=owner,player=ctl['player'],expires=monotonic+REQUEST_S)
        if not req or req["state"] != "pending":
            item=preferred(state,snap)
            if item is not None and not item.get('hand') and input_allowed:
                return switch(item,now,'persistent operator gun preference')
            return None
        if req["owner"] != owner or req["player"] != (snap.get("player") or {}).get("ptr") \
                or monotonic >= req["expires"]:
            req.update(state="rejected", reason="The round changed or the request expired.")
            return None
        item = preferred(state,snap)
        if item is None:
            req.update(state="rejected", reason="The requested quick-slot gun is no longer available.")
            return None
        if item.get("hand"):
            req.update(state="confirmed", reason="Confirmed equipped in the current inventory.")
            state['preferred_weapon']['target']=weapons.inventory_key(item)
            return None
        if not input_allowed:
            return None
        return switch(item, now, "operator random weapon request")


LONG_GUNS = {"rifle", "rocket"}


def leave_long_gun(snap, switch, now):
    """If a sniper rifle or rocket launcher is in hand, tap D-pad to a loaded quick-slot gun (magnum first)."""
    inventory = snap.get("inventory") or ()
    held = next((w for w in inventory if w.get("hand")), None)
    spec = weapons.WEAPONS.get((held or {}).get("item"))
    if held is None or held.get("type") != 1 or spec is None or spec.family not in LONG_GUNS:
        return None
    options = [w for w in inventory if not w.get("hand") and eligible(w)]
    options.sort(key=lambda w: weapons.WEAPONS[w["item"]].family != "magnum")
    return switch(options[0], now, "sniper/rocket equipped: swap to another gun") if options else None


def pinned(state, snap, now):
    item=preferred(state,snap)
    return bool(item and item.get('hand'))
