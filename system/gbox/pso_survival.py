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


def apply_survival(ad, player_index, m=None, p=None, inv_rows=None):
    """Keep `player_index` stocked + unkillable and log any death. Fail-soft; returns a
    dict merged into the master-build report (surfaces as flat mb_* keys via pso_coop).

    `m` (Extras) and `p` (player pointer) and `inv_rows` are reused from the caller when
    available to avoid extra native calls; otherwise acquired here (best-effort)."""
    out = {"scapedoll": None, "scapedoll_ok": False, "downed": False,
           "revives": _state(ad)["revives"].get(player_index, 0)}
    run = getattr(ad, "session_id", None) or getattr(ad, "sid", None)
    pst = _state(ad)["players"].setdefault(player_index, {})
    verified = m is not None and p is not None
    try:
        from .pso_gc_extras import Extras
        from .pso_gc_live import GC
        if not verified:
            try:
                m = Extras(ad, player_index=player_index, pin_player=True)
                p = m.check()
                verified = True
            except Exception:
                m = GC(ad)  # read-only fallback for the RAM backstop
                slots = m.read(PLAYER, 8)
                p = struct.unpack_from(">I", slots, player_index * 4)[0]
                if not (0x80000000 <= p < 0x81800000):
                    return out | {"ok": False, "reason": "no player"}
        hp = m.u16(p + 0x32C)
        maxhp = m.u16(p + 0x2B8)
        out["downed"] = hp == 0

        # --- scape-doll count + death-by-consumption detection (verified path only) ---
        count = None
        if verified:
            try:
                rows = inv_rows if inv_rows is not None else m.inventory()
                count = _scape_count(rows)
            except Exception:
                count = None
        prev = pst.get("scape")
        if count is not None:
            out["scapedoll"] = count
            out["scapedoll_ok"] = count > 0
            if prev is not None and count < prev and hp > 0:
                # a Scape Doll auto-fired between ticks -> a death we must log (post-revive pos)
                _record_death(ad, _make_record(m, p, player_index, 0, maxhp, "scape_doll_consumed", run))
            pst["scape"] = count

        # --- HP-zero death: record then revive ---
        if hp == 0:
            _record_death(ad, _make_record(m, p, player_index, 0, maxhp, "hp_zero", run))
            if verified:
                try:
                    m.revive()
                except Exception:
                    pass
            try:
                if m.u16(p + 0x32C) == 0:                      # last-resort RAM backstop
                    tgt = maxhp if maxhp else 0x14
                    ad.write_memory(p + 0x32C, struct.pack(">H", tgt))
            except Exception:
                pass

        if verified:
            # Virtual Scape Doll (per-frame native revival) — P1 only, idempotent.
            if player_index == 0:
                try:
                    from .pso_gc_live import SURVIVAL
                    if not m.u32(SURVIVAL):
                        m.survival(True)
                except Exception:
                    pass
            # Keep Scape Dolls stocked so the auto-revive never runs dry.
            try:
                if count is None or count <= LOW_DOLLS:
                    need = TARGET_DOLLS - (count or 0)
                    if need > 0:
                        made = m.give(SCAPE_DOLL, max(1, min(20, need)))
                        if made.get("verified"):
                            out["scapedoll"] = (count or 0) + made.get("created", 0)
                            out["scapedoll_ok"] = True
                            pst["scape"] = out["scapedoll"]
            except Exception:
                pass
        out["revives"] = _state(ad)["revives"].get(player_index, 0)
        out["ok"] = True
    except Exception as e:
        out["ok"] = False
        out["reason"] = str(e)[:120]
    return out
