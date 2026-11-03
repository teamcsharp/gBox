"""Master-build COMBAT + GEAR layer for PSO Episode I & II Plus (GameCube, 3OE2).

Operator spec (one idempotent, fail-soft entry point the co-op bot loop calls on
spawn / area change / periodically):
  - never miss          -> the verified native accuracy hook forces every local
                           player hit to connect (gbox.pso_accuracy).
  - critical attacks     -> LCK is raised to the crit cap (max crit RATE). TRUE
                           crit-always (every hit a critical) still needs the GC
                           damage-routine RE; see MASTER_BUILD_NOTES below.
  - random weapons       -> a random real disc weapon is equipped and re-rolled on
                           an interval (cycling), reusing the native give/equip.
  - custom armour, 4 slots, 4 random units -> a frame created with 4 unit slots
                           plus four random enhancement units equipped into it.
  - random maxed mag     -> a mag with its four stats maxed (200 total, random
                           distribution), IQ/synchro maxed, random colour.
  - 3x attack speed      -> NOT applied here; needs the GC attack-timer RE. See
                           MASTER_BUILD_NOTES. A global game-speed path exists
                           (adapter.set_autoplay_speed) but is owned by nav/timing.

Everything is built from the EXISTING verified, revision-guarded primitives in
pso_gc_live / pso_gc_extras / pso_accuracy (exact 3OE2 fingerprint checks, the
native command queue, the game's own create/equip/stat routines). No new raw
memory pokes are introduced except the frame slot-count byte, which is written
into the game's own 20-byte create template (the same mechanism give/floor_spawn
already use), never poked into a live object.

Public API (call site added by the navigation agent in pso_coop):
    from gbox.pso_master_build import apply_master_build
    apply_master_build(ad, player_index=0)            # one player + globals
    apply_master_build_all(ad)                         # both active players

The function NEVER raises; it returns a dict summary with per-feature results and
an 'errors' map. It is cheap and idempotent: patches are re-checked not re-written,
gear is created once and tracked on the adapter, the weapon re-rolls only after
`weapon_interval` seconds, and a state-load / reset (actor pointer change) resets
the tracked identities so stale generated items are never trusted.
"""
import random
import struct
import threading
import time

# --- real GameCube Ep I&II disc item codes (3-byte: see gbox.psoitems) --------------------------------------------
# weapon = 00 <class> <item>; the item-0 of each early weapon class is a basic
# weapon present on every Ep I&II disc. give() creates it; equip_any lets any
# class/level equip it. A bad code just fails soft and is skipped.
WEAPON_CODES = (
    "000100",  # Saber       (class 01)
    "000200",  # Sword       (class 02)
    "000300",  # Dagger      (class 03)
    "000400",  # Partisan    (class 04)
    "000500",  # Slicer      (class 05)
    "000600",  # Handgun     (class 06)
    "000700",  # Rifle       (class 07)
    "000800",  # Mechgun     (class 08)
    "000900",  # Shot        (class 09)
    "000a00",  # Cane        (class 0A)
)
FRAME_CODE = "010100"           # frame = 01 01 <index>; index 0 = basic Frame
FRAME_SLOTS = 4                 # operator spec: 4 unit slots
# unit = 01 03 <index>; the low-index units are basic additions present on disc.
UNIT_CODES = ("010300", "010301", "010302", "010303", "010304", "010305",
              "010306", "010307", "010308", "010309")
UNIT_SLOTS = 4
MAG_CODE = "020000"             # mag = 02 <form> 00; form 0 = basic Mag
MAG_TOTAL = 200                 # the four-stat total is capped at 200 by mag_set
MAG_SYNCHRO = 120               # synchro cap
MAG_COLORS = 19                 # colour values 0..18

WEAPON_INTERVAL_S = 10.0        # how often the random weapon re-rolls
LCK_CRIT_CAP = 100              # crit rate is min(LCK, 100): raising above is pointless

_guard = threading.Lock()

MASTER_BUILD_NOTES = {
    "never_miss": "Verified for BOTH local players: gbox.pso_accuracy's native hook at "
                  "0x80015F00 / 0x80016384 forces every hit by PLAYER slot 0 (P1) and slot 1 "
                  "(P2) to connect, offline free-play only. (The cave stub compares the attacker "
                  "to *(PLAYER) and *(PLAYER+4); confirmed by disassembly against live RAM.)",
    "crit_rate": "Applied: LCK raised to the crit cap (min(LCK,100)). This is max crit RATE, "
                 "NOT crit-always.",
    "crit_always_todo": "TRUE crit-always (every hit a critical) is NOT shipped. RULED OUT of the "
                        "accuracy path: 0x80015DE8 / 0x800162E0 are the to-hit roll (f31 = hit "
                        "margin, fcmpu at the patched site -> bge = miss; success sets hit-record "
                        "bits 0x04000000 at target+0x18 and 0x02/0x01 at attacker+0x2dc) - no x1.5. "
                        "The on-hit callees 0x80010FCC / 0x80011014 are thin wrappers (ruled out). "
                        "The crit multiplier lives in a damage-application routine not yet located. "
                        "Next step: Ghidra xref on PsoV3.dol (SHA 1f80fb82...) for the 1.5f constant "
                        "(0x3FC00000) and the attacker ATP/LCK read in the melee-damage routine, "
                        "then force its crit branch (single-instruction nop like the DC bt->nop at "
                        "0x8C047BC0), fingerprint-guarded. Until then LCK-max gives the best crit "
                        "RATE safely.",
    "attack_speed_todo": "3x attack speed NOT applied. GC path mirrors the DC speed wrapper "
                         "(pso_mods_tool.speed_code): run ORIGINAL_UPDATE N-1 extra times while the "
                         "player is in the attack action-state. TWO unknowns: (1) the GC TObjPlayer "
                         "attack-animation-state offset - DC used +0x30E; on GC +0x32c is HP and "
                         "+0x324 is the control/update-mode selector, NOT the swing state, so the "
                         "animation-state field must be found by live observation (read the player "
                         "object attacking vs idle); (2) the wrapper cave. The live dispatcher cave "
                         "(pso_gc_live.CODE on VT_UPDATE) is SHARED with the nav agent's loop - "
                         "coordinate with agent a22d56d84e2197ff6 and add a SECOND cave with the "
                         "same ownership guards, do not clobber the nav dispatcher. Do NOT fall "
                         "back to the whole-game adapter.set_autoplay_speed - nav owns the timebase.",
    "frame_slots": "The frame is created with slot-count byte = 4 in the game's own 20-byte create "
                   "template (data1[4]); verified by inventory read-back. equip_any is also enabled "
                   "so the four units equip regardless of the slot check as a fallback.",
}


# --- pure, unit-testable helpers ----------------------------------------------------------------------------------
def _is_hex3(code):
    try:
        return len(bytes.fromhex(code)) == 3
    except (ValueError, TypeError):
        return False


def frame_template(frame_code=FRAME_CODE, slots=FRAME_SLOTS, item_id=0):
    """The 20-byte create record for a frame with `slots` unit slots (data1[4]).

    Mirrors the record gbox.pso_gc_live.give/floor_spawn hand to the native item
    creator: code in bytes 0-2, slot count in byte 4, gBox item id big-endian at
    byte 12. No live object is poked; the game builds the item from this template.
    """
    data = bytearray(20)
    data[:3] = bytes.fromhex(frame_code)
    data[4] = int(slots) & 0xFF
    struct.pack_into(">I", data, 12, item_id & 0xFFFFFFFF)
    return bytes(data)


def mag_max_changes(rng=random):
    """Maxed mag with a RANDOM distribution: 200 total across def/pow/dex/mind,
    IQ and synchro maxed, a random colour. Values are what gbox.pso_gc_extras
    .mag_set accepts (each <= 200, sum <= 200, synchro <= 120, colour 0..18)."""
    pts = [0, 0, 0, 0]
    for _ in range(MAG_TOTAL):
        pts[rng.randrange(4)] += 1
    return {"def": pts[0], "pow": pts[1], "dex": pts[2], "mind": pts[3],
            "iq": 200, "synchro": MAG_SYNCHRO, "color": rng.randrange(MAG_COLORS)}


# --- adapter-lifetime state (survives hot reload; keyed per player) -----------------------------------------------
def _state(ad, player_index):
    with _guard:
        store = getattr(ad, "_master_build_state", None)
        if store is None:
            store = {}
            ad._master_build_state = store
        return store.setdefault(player_index, {})


def _alive(m, p):
    try:
        return bool(m.u16(p + 0x32C))
    except Exception:
        return False


def _inv_by_id(m):
    try:
        return {r["id"]: r for r in m.inventory()}
    except Exception:
        return {}


def _free_slots(m):
    try:
        return SLOTS_MAX - len(m.inventory())
    except Exception:
        return 0


SLOTS_MAX = 30


# --- native actions (all reuse pso_gc_live / pso_gc_extras verified routines) -------------------------------------
def _give_frame_with_slots(m, p, frame_code=FRAME_CODE, slots=FRAME_SLOTS):
    """Create a frame with `slots` unit slots via the game's own create routine.

    Uses the identical native call sequence as GC.give(), reserving a fresh gBox
    item id, so the item is bounded and removable like every other generated item.
    """
    from .pso_gc_live import NEXT_ID, BUF, ID_BASE, F_CREATE  # noqa: F401
    next_id = max(ID_BASE, m.u32(NEXT_ID))
    if next_id + 1 >= ID_BASE + 0x100000:
        raise RuntimeError("gBox item ID range exhausted")
    item = frame_template(frame_code, slots, next_id)
    m.write(NEXT_ID, struct.pack(">I", next_id + 1))
    m.write(BUF, item)
    m.call([(0x8010C740, BUF, 0), (0x8010CCB0, BUF)])
    obj = m.call([(0x80102AC0, BUF)])[0]
    if not obj:
        raise RuntimeError("Game refused the frame item object")
    m.call([(0x801B8E68, p, m.ptr(obj, 0x200))])
    return next_id


def _equip_native(m, p, item_id):
    """Equip any inventory item (including units, which equip_id's guard rejects)
    via the game's own equip routine + stat recompute."""
    from .pso_gc_live import F_EQUIP
    obj = m.item_object(item_id)
    m.call([(F_EQUIP, p, obj, 0), (0x801B63AC, p)])


def _ensure_gear(m, p, state, report):
    """Create (once) and keep equipped: a 4-slot frame, 4 random units, a maxed mag."""
    inv = _inv_by_id(m)

    # --- frame with 4 unit slots ---
    fid = state.get("frame_id")
    if fid is None or fid not in inv:
        if _free_slots(m) > 0:
            try:
                fid = _give_frame_with_slots(m, p, FRAME_CODE, FRAME_SLOTS)
            except Exception as error:
                # fall back to a plain frame so the units still have somewhere to go
                report["frame_error"] = str(error)[:100]
                made = m.give(FRAME_CODE)
                fid = (made.get("ids") or [None])[0]
            state["frame_id"] = fid
            if fid is not None:
                try:
                    m.equip_id(fid)
                except Exception:
                    pass
            inv = _inv_by_id(m)
    if fid is not None and fid in inv:
        row = inv[fid]
        slots_byte = bytes.fromhex(row.get("data", ""))[4] if len(row.get("data", "")) >= 10 else None
        report["frame"] = {"id": fid, "code": row["code"], "equipped": row.get("equipped"),
                           "slots_byte": slots_byte}

    # --- four random enhancement units ---
    units = [u for u in state.get("unit_ids", []) if u in inv]
    attempts = 0
    while len(units) < UNIT_SLOTS and _free_slots(m) > 0 and attempts < UNIT_SLOTS * 3:
        attempts += 1
        code = random.choice(UNIT_CODES)
        try:
            made = m.give(code)
        except Exception:
            continue
        ids = made.get("ids") or []
        if not ids:
            continue
        uid = ids[0]
        try:
            _equip_native(m, p, uid)
        except Exception:
            pass
        units.append(uid)
    state["unit_ids"] = units
    report["units"] = units

    # --- random maxed mag ---
    mid = state.get("mag_id")
    inv = _inv_by_id(m)
    if mid is None or mid not in inv:
        if _free_slots(m) > 0:
            try:
                made = m.give(MAG_CODE)
                ids = made.get("ids") or []
                if ids:
                    mid = ids[0]
                    state["mag_id"] = mid
                    try:
                        m.equip_id(mid)
                    except Exception:
                        pass
                    try:
                        m.mag_set(mid, mag_max_changes())
                        state["mag_maxed"] = True
                    except Exception as error:
                        report["mag_error"] = str(error)[:100]
            except Exception as error:
                report["mag_give_error"] = str(error)[:100]
    report["mag"] = {"id": state.get("mag_id"), "maxed": state.get("mag_maxed", False)}


def _reroll_weapon(m, p, state, report, interval):
    """Equip a random weapon, re-rolling on an interval (the 'random weapons' cycle)."""
    now = time.monotonic()
    inv = _inv_by_id(m)
    wid = state.get("weapon_id")
    due = wid is None or wid not in inv or (now - state.get("weapon_t", 0.0)) >= interval
    if not due:
        report["weapon"] = {"id": wid, "code": state.get("weapon_code"), "rerolled": False}
        return
    # Make room if the inventory is full by dropping the current generated weapon first.
    if _free_slots(m) <= 0 and wid is not None and wid in inv:
        try:
            m.remove_generated(wid)
        except Exception:
            pass
        state.pop("weapon_id", None)
        wid = None
    if _free_slots(m) <= 0:
        report["weapon"] = {"id": wid, "code": state.get("weapon_code"), "rerolled": False,
                           "note": "inventory full"}
        return
    code = random.choice(WEAPON_CODES)
    try:
        made = m.give(code)
    except Exception as error:
        report["weapon_error"] = str(error)[:100]
        return
    ids = made.get("ids") or []
    if not ids:
        return
    nid = ids[0]
    try:
        m.equip_id(nid)
    except Exception:
        pass
    old = state.get("weapon_id")
    state["weapon_id"] = nid
    state["weapon_code"] = code
    state["weapon_t"] = now
    if old is not None and old != nid:
        try:
            m.remove_generated(old)
        except Exception:
            pass
    report["weapon"] = {"id": nid, "code": code, "rerolled": True}


def _apply_globals(ad, report):
    """Player-independent executable patches (never-miss, equip-anything). Idempotent."""
    try:
        from . import pso_accuracy
        res = pso_accuracy.set_enabled(ad, "gamecube", True)
        report["never_miss"] = bool(res.get("always_hit"))
    except Exception as error:
        report.setdefault("errors", {})["never_miss"] = str(error)[:140]
    try:
        from .pso_gc_live import GC, EQUIP_PATCH
        g = GC(ad)
        g.check()
        if g.read(EQUIP_PATCH, 4) != bytes.fromhex("38000005"):
            g.equip_any(True)
        report["equip_any"] = True
    except Exception as error:
        report.setdefault("errors", {})["equip_any"] = str(error)[:140]


def apply_master_build(ad, player_index=0, *, weapon_interval=WEAPON_INTERVAL_S, reroll_weapon=True):
    """Enforce the operator's master-build spec for one PSO GC player. Idempotent, never raises.

    Safe to call every loop tick: executable patches are re-checked not re-written,
    gear is created once and tracked on `ad`, and the random weapon re-rolls only
    after `weapon_interval` seconds. When player_index == 0 the player-independent
    patches (never-miss, equip-anything) are (re)applied; for player 2 they are
    assumed already on from the player-1 call.

    Returns a dict summary (per-feature results + an 'errors' map). See
    MASTER_BUILD_NOTES for what is verified vs. still-RE (crit-always, 3x attack
    speed, player-2 never-miss).
    """
    report = {"player_index": player_index, "errors": {}}
    if player_index == 0:
        _apply_globals(ad, report)

    try:
        from .pso_gc_extras import Extras
        m = Extras(ad, player_index=player_index, pin_player=True)
        p = m.check()
    except Exception as error:
        report["errors"]["player"] = str(error)[:160]
        report["ok"] = False
        return report

    state = _state(ad, player_index)
    # A state load / reset moves the actor: drop stale generated-item identities.
    if state.get("actor") != p:
        state.clear()
        state["actor"] = p

    try:
        m.hook()
    except Exception as error:
        report["errors"]["hook"] = str(error)[:140]

    # critical attacks: raise LCK to the crit cap (only upward; never fight gear that is already higher)
    try:
        shown = m.shown_stats().get("lck", 0)
        if shown < LCK_CRIT_CAP:
            m.set_stat("lck", LCK_CRIT_CAP)
        report["lck"] = m.shown_stats().get("lck")
    except Exception as error:
        report["errors"]["lck"] = str(error)[:140]

    if not _alive(m, p):
        report["ok"] = True
        report["note"] = "player not alive; gear deferred to a later tick"
        return report

    try:
        _ensure_gear(m, p, state, report)
    except Exception as error:
        report["errors"]["gear"] = str(error)[:140]
    if reroll_weapon:
        try:
            _reroll_weapon(m, p, state, report, weapon_interval)
        except Exception as error:
            report["errors"]["weapon"] = str(error)[:140]

    report["ok"] = not report["errors"]
    return report


def apply_master_build_all(ad, **kwargs):
    """Apply the master build to both active players (player 1 then player 2).

    Globals are applied on the player-1 pass. Player 2 fails soft if it is not yet
    the verified co-op slot (needs the Pioneer 2 movement verification)."""
    out = {}
    for index in (0, 1):
        out[index] = apply_master_build(ad, player_index=index, **kwargs)
    return out
