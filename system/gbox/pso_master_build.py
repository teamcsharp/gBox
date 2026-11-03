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
    "crit_always": "Applied (verified by static RE + live-RAM cross-check): gbox.pso_crit hooks the "
                   "melee damage routine FUN_80014108 at its crit branch 0x8001468C with a cave at "
                   "0x80005000 that forces the x1.5 critical path when the attacker (r28) is PLAYER "
                   "slot 0 or slot 1 and offline, else replays the stock roll - so the bot's players "
                   "crit on EVERY melee hit and enemies are unchanged. Reversible, fingerprint-guarded.",
    "crit_rate": "Also applied as a backstop: LCK raised to the crit cap (min(LCK,100)). Redundant "
                 "once crit_always is on; it keeps a high natural crit rate if the crit hook refuses.",
    "crit_followups": "crit_always covers the MELEE damage path (FUN_80014108). A ranged/technique "
                      "crit path, if separate, is not yet hooked - the same 1.5f (0x3FC00000) + "
                      "per-hit-record structure in a sibling damage routine would be the lead. For a "
                      "melee swarm bot this is the primary path.",
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


# Long-range weapons for boss floors: a boss (e.g. De Rol Le across the water, Dragon at
# arena range) can't be hit with a melee saber, so on a boss floor the random cycle is
# restricted to guns (Handgun/Rifle/Mechgun/Shot) so shots actually reach. never-miss + crit
# still only land once nav positions the bot within weapon range (positioning is the nav lane).
RANGED_WEAPON_CODES = ("000700", "000900", "000800", "000600")   # Rifle, Shot, Mechgun, Handgun
# On a boss floor force a gun (not a random ranged weapon), chosen per floor from the owned ItemPMT
# effective reaches (base x 0.85) and cone half-angles:
#   Shot 000900 = 110.5u / 45deg cone  -> default: wide cone lands on close/stationary bosses
#                                         (De Rol Le head ~29u, Vol Opt monitors ~38u, Dark Falz).
#   Rifle 000700 = 178.5u / 10deg cone -> Dragon floor only: the Dragon is grounded+vulnerable and
#                                         ORBITS the arena at ~93-160u; nav holds the center, so the
#                                         Rifle's 178.5u covers the FULL orbit (the Shot's 110u only
#                                         reaches the near arc). Narrow cone needs nav to aim-track.
BOSS_WEAPON_CODE = "000900"
BOSS_WEAPON_BY_FLOOR = {11: "000700"}            # floor 11 (Ep1 Dragon) -> Rifle; others -> Shot
_BOSS_FLOORS_BY_EP = {0: frozenset({11, 12, 13, 14}), 1: frozenset({12, 13, 14, 15})}


def _boss_floor(m):
    try:
        from .pso_fence import FLOOR, EPISODE_FLOOR
        return m.u32(FLOOR) in _BOSS_FLOORS_BY_EP.get(m.u32(EPISODE_FLOOR), frozenset())
    except Exception:
        return False


def _boss_weapon_code(m):
    """The gun to force on the current boss floor: Rifle on the Dragon floor (per-floor override),
    Shot everywhere else. Fail-soft to the Shot default."""
    try:
        from .pso_fence import FLOOR
        return BOSS_WEAPON_BY_FLOOR.get(m.u32(FLOOR), BOSS_WEAPON_CODE)
    except Exception:
        return BOSS_WEAPON_CODE


def _reroll_weapon(m, p, state, report, interval):
    """Equip a random weapon, re-rolling on an interval (the 'random weapons' cycle). On a
    boss floor the pool is restricted to ranged weapons so the bot can reach the boss."""
    now = time.monotonic()
    boss = _boss_floor(m)
    report["boss_ranged"] = boss                     # flat: mb_boss_ranged_p1/p2 (Shot forced on a boss floor)
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
    code = _boss_weapon_code(m) if boss else random.choice(WEAPON_CODES)
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
    try:
        from . import pso_crit
        res = pso_crit.set_enabled(ad, "gamecube", True)
        report["crit_always"] = bool(res.get("crit_always"))
    except Exception as error:
        report.setdefault("errors", {})["crit_always"] = str(error)[:140]
    # Forced fence drop is wired but INERT until FENCE_FORCE_DOWN is flipped after a live test.
    try:
        from . import pso_fence
        if pso_fence.FENCE_FORCE_DOWN:
            res = pso_fence.set_enabled(ad, "gamecube", True)
            report["fence_force_down"] = bool(res.get("fence_force_down"))
    except Exception as error:
        report.setdefault("errors", {})["fence_force_down"] = str(error)[:140]


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
        # Never-die backstop must still run even if the full build can't verify this
        # player (e.g. P2 not yet co-op-verified): revive via the raw RAM path + log.
        try:
            from . import pso_survival
            surv = pso_survival.apply_survival(ad, player_index)
            report["revives"] = surv.get("revives")
            report["downed"] = surv.get("downed")
            report["scapedoll"] = surv.get("scapedoll")
            report["scapedoll_ok"] = surv.get("scapedoll_ok")
        except Exception:
            pass
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

    # Survival FIRST (before the alive-gate): infinite Scape Dolls + never-die revive
    # backstop + death logging, so a downed player is recovered this tick and never stalls.
    try:
        from . import pso_survival
        surv = pso_survival.apply_survival(ad, player_index, m=m, p=p)
        report["scapedoll"] = surv.get("scapedoll")
        report["scapedoll_ok"] = surv.get("scapedoll_ok")
        report["revives"] = surv.get("revives")
        report["downed"] = surv.get("downed")
    except Exception as error:
        report["errors"]["survival"] = str(error)[:140]

    # 3x-attack-speed phase (a): read-only in-bot attack-state probe (learns the gate; harmless).
    try:
        from . import pso_speed
        report.update(pso_speed.probe_tick(ad, player_index, m, p))
    except Exception as error:
        report["errors"]["speed_probe"] = str(error)[:120]

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


def present_players(ad):
    """PLAYER slots 0-3 that currently hold a live player pointer (robust to 2/3/4 players)."""
    try:
        from .pso_gc_live import GC, PLAYER
        slots = struct.unpack(">4I", GC(ad).read(PLAYER, 16))
        present = [i for i, ptr in enumerate(slots) if 0x80000000 <= ptr < 0x81800000]
        return present or [0, 1]                      # empty read -> safe 2-player default
    except Exception:
        return [0, 1]


def apply_master_build_all(ad, **kwargs):
    """Apply the full master build to every present player (slots 0-3: host + up to 3
    accompanying). Globals (never-miss, crit-always, equip-anything) are applied on the
    first pass and already gate on all PLAYER slots. An accompanying slot fails soft until
    it is the verified co-op slot."""
    out = {}
    for index in present_players(ad):
        out[index] = apply_master_build(ad, player_index=index, **kwargs)
    return out
