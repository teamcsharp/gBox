"""PSO GC 3OE2 survival layer: infinite Scape Dolls, a never-die revive backstop, and a
per-death learning log. Called each tick from pso_master_build for BOTH players.

Goal: perpetual autonomous play never stalls or ends on a death, yet every down is
RECORDED as a learning signal for the nav agent's pathfinding / boss-management / dodge.

Mechanisms (all RAM-level, fail-soft, built on verified pso_gc_live / pso_gc_extras
primitives — never raises into the bot loop):
  - infinite Scape Dolls: keep both players stocked with Scape Doll (item 030900). The
    game auto-uses one on death (instant native revive); we re-stock every tick so the
    count never depletes. Plus the P1 Virtual Scape Doll (Extras.survival, per-frame
    native revival, no inventory needed) as a belt-and-suspenders.
  - revive backstop: if a player is downed (HP at p+0x32c == 0) we revive immediately —
    native REVIVE (Extras.revive) first, then a raw HP write as a last resort — so a
    death is recovered within the tick even if the Scape Doll race is lost.
  - death log: a death is detected by HP->0 OR a drop in the Scape Doll count (catches
    deaths the auto-revive already undid). Each is captured as a structured record BEFORE
    reviving, counted, and appended to a JSONL file that survives across runs. The nav
    agent reads it back via read_deaths()/death_stats() to bias away from fatal spots.

Item codes resolved from the owned disc catalog (ItemPMT): Scape Doll 030900,
Moon Atomizer 030400.
"""
import json
import os
import struct
import threading
import time

SCAPE_DOLL = "030900"
MOON_ATOMIZER = "030400"
TARGET_DOLLS = 10          # top up to this when low
LOW_DOLLS = 3              # restock when at or below this
MAX_LOG = 500             # in-memory ring size
FLOOR = 0x805D5FC0
EPISODE_FLOOR = 0x805D6060
PLAYER = 0x8050EA10
FLOOR_NAMES = {0: "Pioneer2", 1: "Forest1", 2: "Forest2", 3: "Cave1", 4: "Cave2",
               5: "Cave3", 6: "Mine1", 7: "Mine2", 8: "Ruins1", 9: "Ruins2",
               10: "Ruins3", 11: "Dragon", 12: "DeRolLe", 13: "VolOpt", 14: "DarkFalz"}
BOSS_FLOORS = frozenset({11, 12, 13, 14})

_guard = threading.Lock()


def _ensure_pso_speed_fresh():
    """pso_speed is NOT a BOT_MODULE, so the worker's hot-reload never refreshes it and a
    stale cached copy (an older scaffold without probe_tick) sticks. nav importlib.reloads
    THIS module (pso_survival) on every bot-reload, so reload pso_speed here too -> its
    phase-(a) attack-state probe runs the current code live, no service restart needed."""
    try:
        import importlib
        from . import pso_speed
        importlib.reload(pso_speed)
    except Exception:
        pass


_ensure_pso_speed_fresh()


def _log_path():
    # Persist under the deployment's gbox-data (same home mercs/pso knowledge uses).
    try:
        base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gbox-data", "pso")
        os.makedirs(base, exist_ok=True)
        return os.path.join(base, "deaths.jsonl")
    except Exception:
        return None


def _state(ad):
    with _guard:
        st = getattr(ad, "_pso_survival", None)
        if st is None:
            st = {"players": {0: {}, 1: {}}, "revives": {0: 0, 1: 0}, "log": [], "last_death": None}
            ad._pso_survival = st
            # Alias the in-memory log so a consumer's ad._pso_deaths fallback resolves to
            # the same list (mutated in place, so the reference stays valid across appends).
            try:
                ad._pso_deaths = st["log"]
            except Exception:
                pass
        return st


def _record_death(ad, rec):
    st = _state(ad)
    with _guard:
        st["log"].append(rec)
        if len(st["log"]) > MAX_LOG:
            del st["log"][:-MAX_LOG]
        st["revives"][rec["player"]] = st["revives"].get(rec["player"], 0) + 1
        st["last_death"] = rec
    path = _log_path()
    if path:
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, separators=(",", ":")) + "\n")
        except Exception:
            pass  # in-memory log still holds it; persistence is best-effort


def read_deaths(ad, limit=200):
    """Recent death records (newest last). Nav calls this at runtime to bucket fatal
    positions per (episode, floor, boss) and bias pathfinding/boss-positioning/dodge."""
    st = _state(ad)
    with _guard:
        return [dict(r) for r in st["log"][-max(1, min(limit, MAX_LOG)):]]


def death_stats(ad):
    """Flat-friendly summary for telemetry / quick consumption."""
    st = _state(ad)
    with _guard:
        r = dict(st["revives"])
        return {"revives_p1": r.get(0, 0), "revives_p2": r.get(1, 0),
                "total": r.get(0, 0) + r.get(1, 0), "last_death": dict(st["last_death"]) if st["last_death"] else None}


def _scape_count(rows):
    n = 0
    for r in rows:
        if r.get("code") == SCAPE_DOLL:
            data = bytes.fromhex(r.get("data", "")) if r.get("data") else b""
            n += max(1, data[5]) if len(data) > 5 else 1
    return n


def _make_record(m, p, player_index, hp, maxhp, cause, run):
    try:
        x, y, z = struct.unpack(">3f", m.read(p + 0x38, 12))
    except Exception:
        x = y = z = 0.0
    try:
        floor = m.u32(FLOOR)
    except Exception:
        floor = -1
    try:
        episode = m.u32(EPISODE_FLOOR) + 1
    except Exception:
        episode = 1
    try:
        room = m.u16(p + 0x28)
    except Exception:
        room = -1
    return {"ts": round(time.time(), 3), "player": player_index, "episode": episode,
            "floor": floor, "area": FLOOR_NAMES.get(floor, str(floor)), "boss": floor in BOSS_FLOORS,
            "x": round(x, 1), "y": round(y, 1), "z": round(z, 1), "room": room,
            "hp_before": hp, "max_hp": maxhp, "cause": cause, "run": run}


HEAVY_INTERVAL_S = 2.0          # native inventory/stock/survival cadence; the revive runs EVERY tick
SURVIVAL_HP_FLOOR = 9999        # raise max HP (+0x2B8) to this each tick so a low-level char can tank
#                                 boss hits; the current-HP pin then heals into the big pool. u16-safe
#                                 (0x270F). Written every tick so an engine recompute can't hold it low.


def _do_revive(ad, player_index, p, maxhp, m=None):
    """Bring a downed player back now: native REVIVE first (proper), raw HP write as a last
    resort. Only called on an actual death tick, so its native-call cost is rare."""
    how = "none"
    try:
        from .pso_gc_extras import Extras
        e = m if (m is not None and hasattr(m, "revive")) else Extras(ad, player_index=player_index, pin_player=True)
        e.check()
        e.revive()
        how = "native_revive"
    except Exception:
        pass
    try:
        from .pso_gc_live import GC
        g = GC(ad)
        if g.u16(p + 0x32C) == 0:
            g.write(p + 0x32C, struct.pack(">H", maxhp or 0x14))
            how = "ram_backstop" if how == "none" else how
    except Exception:
        pass
    return how


def apply_survival(ad, player_index, m=None, p=None, inv_rows=None):
    """Keep `player_index` stocked + unkillable and log any death. Fail-soft, never raises.

    SELF-THROTTLING so it is safe to call every bot tick (~20 Hz x2 players): the HP-zero
    revive runs EVERY call (instant recovery), while the heavy native work (inventory read,
    Scape Doll restock, Virtual Scape Doll flag, scape-consumption death detection) runs at
    most every HEAVY_INTERVAL_S. A death is logged only on the TRANSITION into HP==0 (never
    every tick while down). `m`/`p` are reused from the caller when given, else acquired
    cheaply (one PLAYER-slot read). Idempotent if called twice a tick (throttle dedups)."""
    out = {"scapedoll": None, "scapedoll_ok": False, "downed": False, "revives": 0}
    run = getattr(ad, "session_id", None) or getattr(ad, "sid", None)
    try:
        from .pso_gc_live import GC, PLAYER
        g = m if m is not None else GC(ad)
        if p is None:
            slots = g.read(PLAYER, 8)
            p = struct.unpack_from(">I", slots, player_index * 4)[0]
            if not (0x80000000 <= p < 0x81800000):
                return out | {"ok": False, "reason": "no player"}
        hp = g.u16(p + 0x32C)
        maxhp = g.u16(p + 0x2B8)
        out["downed"] = hp == 0
        st = _state(ad)
        pst = st["players"].setdefault(player_index, {})

        # 3x-attack-speed phase (a): run the read-only attack-state probe on THIS hot path
        # (apply_survival is called every tick from pso_coop, which IS hot-reloadable, so the
        # probe runs + locks live even though pso_master_build is not reloaded on the worker).
        try:
            from . import pso_speed
            out.update(pso_speed.probe_tick(ad, player_index, g, p))
        except Exception:
            pass

        # --- every tick: RAISE MAX HP then PIN current HP to it, so a level 1-2 glass cannon (maxHP
        # ~40) can actually TANK boss hits instead of being one-shot. A 40-HP pool heals to 40 and a
        # >40 boss hit still zeroes it; raising maxHP (+0x2B8) to a big floor and topping current HP
        # (+0x32C) into that pool every tick is the real never-die. Both are cheap u16 writes; we
        # rewrite them every tick so an engine recompute of maxHP from level can't hold it low. A
        # true death still logs on the transition and uses the native revive to clear the downed
        # actor state. (If a live re-read shows +0x2B8 reverting next tick, maxHP is recomputed every
        # frame and the level route is needed - see apply_master_build / the coordinator.)
        floor = SURVIVAL_HP_FLOOR if maxhp < SURVIVAL_HP_FLOOR else maxhp
        try:
            if maxhp < floor:
                g.write(p + 0x2B8, struct.pack(">H", floor))      # raise MAX HP
            if hp == 0:
                if not pst.get("was_dead"):
                    _record_death(ad, _make_record(g, p, player_index, 0, maxhp, "hp_zero", run))
                _do_revive(ad, player_index, p, floor, m=m)       # native revive clears the downed state
            if g.u16(p + 0x32C) < floor:
                g.write(p + 0x32C, struct.pack(">H", floor))      # pin CURRENT HP into the big pool
        except Exception as e:
            out.setdefault("errors", {})["hp_pin"] = str(e)[:80]
        pst["was_dead"] = hp == 0

        # --- throttled: native inventory / restock / Virtual Scape Doll / scape-consumption log ---
        now = time.monotonic()
        if now - pst.get("heavy_t", 0.0) >= HEAVY_INTERVAL_S:
            pst["heavy_t"] = now
            try:
                from .pso_gc_extras import Extras
                e = m if (m is not None and hasattr(m, "inventory")) else Extras(ad, player_index=player_index, pin_player=True)
                e.check()
                rows = inv_rows if inv_rows is not None else e.inventory()
                count = _scape_count(rows)
                prev = pst.get("scape")
                if prev is not None and count < prev and hp > 0:
                    # a Scape Doll auto-fired since the last heavy tick -> log that death
                    _record_death(ad, _make_record(e, p, player_index, 0, maxhp, "scape_doll_consumed", run))
                pst["scape"] = count
                if player_index == 0:                           # Virtual Scape Doll (per-frame revival, P1 only)
                    from .pso_gc_live import SURVIVAL
                    if not e.u32(SURVIVAL):
                        e.survival(True)
                if count <= LOW_DOLLS:                           # keep stocked so the auto-revive never runs dry
                    made = e.give(SCAPE_DOLL, max(1, min(20, TARGET_DOLLS - count)))
                    if made.get("verified"):
                        pst["scape"] = count + made.get("created", 0)
            except Exception as error:
                out["stock_reason"] = str(error)[:80]
        out["scapedoll"] = pst.get("scape")
        out["scapedoll_ok"] = bool(pst.get("scape"))
        out["revives"] = st["revives"].get(player_index, 0)
        out["ok"] = True
    except Exception as e:
        out["ok"] = False
        out["reason"] = str(e)[:120]
    return out
