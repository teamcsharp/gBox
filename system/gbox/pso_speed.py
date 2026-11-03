"""3x ATTACK SPEED for PSO GC 3OE2 — prepared offline, INERT until verified.

Status: `set_enabled`/`status` REFUSE and this is NOT wired into pso_master_build.
Deeper static RE (below) found that the correct mechanism is a DISPATCHER-LEVEL change,
not a sub-function multiply, and that it must be live-write-verified before shipping —
which the degraded/operator-gated i9 blocks right now. Nothing here touches the game.

CORRECTED MECHANISM FINDING (supersedes the sub-function-multiply sketch below):
  The DC speed wrapper (pso_mods_tool.speed_code) gets attack speed by re-running the
  WHOLE player update N times while attacking (it advances the attack STATE MACHINE, not
  just a visual clock). The GC whole-update is ORIGINAL_UPDATE (0x801BB330). There is no
  clean standalone sub-function to multiply: ORIGINAL_UPDATE's first-level callees are
  wrappers/registration — 0x80154E3C is the attack-HITBOX update, and 0x801564A0 /
  0x801563D0 / 0x8015659C are attack TARGET/hit-REGISTRATION (they iterate entity lists
  and set hit-eligibility bits), NOT the animation/state clock. So the right GC
  implementation is the DC model: re-run ORIGINAL_UPDATE (N-1) extra times for a local
  player in an attack state. But ORIGINAL_UPDATE is GUARDED by pso_gc_live.check() AND is
  the tail target of the shared VT_UPDATE dispatcher (pso_gc_live.CODE). The clean place
  to add the extra update is therefore the DISPATCHER ITSELF (which this task owns, in
  pso_gc_live.py) — bump its metadata (GBPSOGC4 -> GBPSOGC5) with a migration path like
  pso_accuracy's, and have it call ORIGINAL_UPDATE extra times when r3 is a local player
  in an attack state. That is a change to the core live component every PSO control
  depends on; it must be live-write-verified (re-running the update must be side-effect
  safe on GC as it is on DC), so it is NOT shipped blind on the degraded/gated i9.

ATTACK-STATE GATE (still unresolved, needs correlated live confirmation):
  Read-only live sampling (2026-11): both players simultaneously showed control mode
  (player+0x324) == 1, with differing player+0x2E4 (P1=0x24, P2=0x01) and P1 hit-count
  (player+0xA8) == 1. So +0x324==1 is a general active state, NOT a clean "attacking"
  flag; gating on it would also 3x normal movement. The true swing gate is likely
  player+0x2E4 (an action/phase id) or the presence of active attack hit-records
  (*(player+0xA4)!=0 && *(player+0xA8)>0), but confirming which value means "mid-swing"
  needs a snapshot correlated with a visible attack — a clean, write-testable i9.

Superseded earlier sketch (kept for the cave mechanics only; do NOT use the sub-function
hook): trampoline-wrap a per-frame player ANIMATION-ADVANCE function (HOOK_FUNC). The cave
runs the real body FACTOR (=3) times instead of once ONLY when (offline free-play) AND
(entity r3 == PLAYER slot 0 or slot 1) AND (in an
  attack-animation state); otherwise runs it exactly once (stock). The body is reached
  through a STUB = [HOOK_FUNC's displaced first instruction] + [b HOOK_FUNC+4]; the final
  body call is a tail-branch with the original LR restored so it returns to HOOK_FUNC's
  caller. The extra-iteration counter and saved LR/player live in the VARS block because
  the body clobbers volatiles. Gates use cr1/r11/r12 only.

  Cave: 0x80005400-0x80005600 (nav agent a22d56d84e2197ff6 pre-confirmed this gap clear,
  2026-11; separate from the crit cave 0x80005000-0x80005100 and the dispatcher below
  0x80005000). VARS at 0x800054C0, METADATA 'GBPSOSP1' at HEADER. Safety copies
  pso_crit/pso_accuracy exactly: exact-build fingerprint on HOOK_FUNC's prologue,
  owned()/owned_known(), check()-every-touched-byte, flush, reversible, refuse-and-write-
  nothing on any mismatch. ONE site patched (HOOK_FUNC entry -> b CAVE). HOOK_FUNC must
  NOT be ORIGINAL_UPDATE (0x801BB330): pso_gc_live.check() guards that address.

OFFLINE FINDINGS (from PsoV3.dol SHA 1f80fb82..., verified vs live RAM):
  - ORIGINAL_UPDATE = 0x801BB330. It reads the control mode at player+0x324 (lha
    r0,0x324) and also player+0x326, and per control-mode value (1/3/6 = the attack-ish
    states) calls the motion/action callees: 0x80154E3C, 0x801564A0, 0x801563D0,
    0x8015659C, then tail 0x801AF1B8 and 0x801B4B70.
  - 0x80154E3C is the attack-HITBOX update (loops the attacker's 44-byte hit-records at
    player+0xA4/+0xA8) — attack-related but NOT the animation-timer advance, so it is the
    WRONG function to multiply.
  - => HOOK_FUNC is the animation-clock advance among {0x801564A0, 0x801563D0,
    0x8015659C, 0x801AF1B8, 0x801B4B70}: the one that increments a float frame/timer
    field on the player. Pin it by disassembling those for a `lfs/fadds/stfs` on a
    per-player animation-time field, then set HOOK_FUNC + HOOK_ORIGINAL (its first instr).

LIVE WORK (held until the clean i9 restart, per the coordinator):
  - ATTACK_STATE_OFF / ATTACK_STATE_MATCH: the TObjPlayer u16 (near +0x324 control mode /
    +0x32c HP) that marks "an attack swing is playing", and the value meaning attacking
    (DC analog: TObjPlayer+0x30E == 1). Find by memory_search diff: snapshot idle -> start
    a normal attack -> snapshot -> the u16 near +0x300..+0x330 that flips during the swing.

TO FINISH (after both are known): set the four constants + PATCH/code generation, add a
tests/test_pso_speed.py mirroring tests/test_pso_crit.py (refuse-foreign/paused/occupied,
reversible+idempotent, cave gates both slots + attack-state + preserves cr0, body reached
FACTOR times), ping nav the final HOOK_FUNC + cave base/extent for a last clear-check,
then add `pso_speed.set_enabled(ad,'gamecube',True)` to pso_master_build._apply_globals.
"""
import threading

from .registry import Unsupported

CAVE, VARS, HEADER, END = 0x80005400, 0x800054C0, 0x800054E0, 0x80005500
METADATA = b'GBPSOSP1'
FACTOR = 3                                              # 3x attack speed

# --- set after the post-restart RE + live snapshot (see module docstring) -------------
HOOK_FUNC = None            # the per-frame player animation-advance function to wrap
HOOK_ORIGINAL = None        # its first instruction, e.g. bytes.fromhex('9421ffd0')
ATTACK_STATE_OFF = None     # TObjPlayer offset of the attack-animation state u16
ATTACK_STATE_MATCH = None   # the value at that offset meaning "attacking"


# NAV_SIGNOFF gates every live action. nav (a22d56d84e2197ff6) signed off the GBPSOGC5 extra-update
# block on 2026-11-03 (+0xA8 gate, the deterministic variant; the +0x326 probe never locked). The
# live swap (pso_gc_live.GC.set_speed) is self-protecting: it swaps the dispatcher in place, flushes,
# read-back-verifies and rolls back to the prior variant on any mismatch, so enabling is reversible
# and the coordinator's few-frame monitored reload is the behavioral net.
NAV_SIGNOFF = True


def configured():
    """True once phase (b) is cleared to go live (nav sign-off). The live swap self-verifies and
    auto-rolls-back, so there is no separate pre-enable flag."""
    return bool(NAV_SIGNOFF)


# --- phase (a): in-bot attack-state probe (read-only, safe; resolves ATTACK_STATE_OFF/MATCH) ---
_probe_guard = threading.Lock()
PROBE_SAMPLE_GOAL = 300          # ticks observed before a gate is considered "locked"
ATTACK_FRACTION = 0.8            # a value is an "attack" value if >=80% of its samples are while attacking


def _derive_gate(ps):
    """A candidate field+value-set that occurs while attacking (player+0xA8 hit-records > 0)
    but NEVER while idle, with enough samples on both sides, is a confident attack gate."""
    best = None
    # +0x326 is the TObject action-state (confirmed as the Dragon's phase field, and the
    # DC attack-state analog); primary candidate, +0x2E4 / +0x324 are fallbacks. Use an
    # attack-FRACTION test (not strict attack-only): a value seen while the hit-record count
    # is active >= ATTACK_FRACTION of its occurrences is an attack value - this is robust to
    # the swing's wind-up/recovery frames (which have +0xA8==0 but the same +0x326 value),
    # which would otherwise land the attack value in the idle bucket and never lock.
    for field, off in (("s326", 0x326), ("s2e4", 0x2E4), ("s324", 0x324)):
        atk, idle = ps.get(f"{field}_atk", {}), ps.get(f"{field}_idle", {})
        if sum(atk.values()) < 30 or sum(idle.values()) < 30:
            continue
        vals = [v for v in set(atk) | set(idle)
                if atk.get(v, 0) >= 15 and atk.get(v, 0) / (atk.get(v, 0) + idle.get(v, 0)) >= ATTACK_FRACTION]
        if not vals:
            continue
        # require at least one value that is predominantly idle too, so a field that is the
        # same value all the time (e.g. +0x324==1 always) is not mistaken for an attack gate.
        if not any(idle.get(v, 0) >= 15 and atk.get(v, 0) / (atk.get(v, 0) + idle.get(v, 0)) <= (1 - ATTACK_FRACTION)
                   for v in set(atk) | set(idle)):
            continue
        locked = ps["n"] >= PROBE_SAMPLE_GOAL and sum(atk[v] for v in vals) >= 20
        cand = {"off": off, "values": sorted(vals),
                "desc": f"player+0x{off:X} in {sorted(vals)}", "locked": locked}
        if best is None or (cand["locked"] and not best["locked"]):
            best = cand
    return best


def probe_tick(ad, player_index, m, p):
    """Read-only in-bot attack-state probe. The confirmed 'attack active' signal is
    player+0xA8 (the live attack hit-record count the hitbox updater 0x80154E3C iterates
    during a swing); this samples candidate gate fields against it and learns which values
    mean 'attacking'. Primary candidate is player+0x326 (the TObject action-state), with
    +0x2E4 / +0x324 as fallbacks. Fail-soft; returns flat telemetry. Resolves the attack
    gate (ATTACK_STATE_OFF/MATCH) for the phase-(b) dispatcher-v5 extra-update."""
    try:
        a8 = m.u32(p + 0xA8)
        fields = (("s326", m.u16(p + 0x326)), ("s2e4", m.u16(p + 0x2E4)), ("s324", m.u16(p + 0x324)))
        attacking = a8 > 0
        with _probe_guard:
            st = getattr(ad, "_pso_speed_probe", None)
            if st is None:
                st = {}
                ad._pso_speed_probe = st
            ps = st.setdefault(player_index, {"n": 0, "atk": 0})
            for fld, _ in fields:                        # ensure buckets (persisted dicts may predate +0x326)
                ps.setdefault(f"{fld}_atk", {})
                ps.setdefault(f"{fld}_idle", {})
            ps["n"] += 1
            ps["atk"] += int(attacking)
            for field, val in fields:
                b = ps[f"{field}_atk" if attacking else f"{field}_idle"]
                b[val] = b.get(val, 0) + 1
            gate = _derive_gate(ps)
            ps["gate"] = gate
            return {"speed_probe_n": ps["n"], "speed_probe_atk": ps["atk"],
                    "speed_probe_gate": gate["desc"] if gate else None,
                    "speed_probe_locked": bool(gate and gate["locked"])}
    except Exception as e:
        return {"speed_probe_err": str(e)[:80]}


def speed_probe_status(ad):
    """The learned attack-state gate per player (for nav / the coordinator to read)."""
    with _probe_guard:
        st = getattr(ad, "_pso_speed_probe", {}) or {}
        return {pi: {"n": d.get("n"), "attacking_samples": d.get("atk"), "gate": d.get("gate")}
                for pi, d in st.items()}


# --- phase (b): the dispatcher-v5 extra-update, PREPARED (both gate variants) but INERT ------------
# Phase (b) gets 3x attack speed by re-running the stock player update (FACTOR-1) extra times for a
# local offline PLAYER that is attacking (the DC speed model), spliced into the shared VT_UPDATE
# dispatcher before its FPR restore (pso_gc_live.dispatcher(speed_gate=...)). Two ready gate variants:
GATE_A8 = {'kind': 'a8',
           'desc': 'player+0xA8 > 0 (active attack hit-records; deterministic, needs no probe lock)'}


def gate_from_326(values):
    """The +0x326 gate: attacking iff the action-state is one of the probe-locked values."""
    vals = sorted({int(v) & 0xFFFF for v in values})
    if not vals:
        raise ValueError('need at least one +0x326 attack value')
    return {'kind': 's326', 'values': vals, 'desc': 'player+0x326 in %s' % vals}


def gate_from_probe(ad):
    """Build the +0x326 gate from the live probe if any player has LOCKED a +0x326 gate, else None.
    When this returns None (the probe did not converge on +0x326), use GATE_A8 — see dispatcher_v5."""
    vals = set()
    for info in speed_probe_status(ad).values():
        g = info.get('gate')
        if g and g.get('locked') and g.get('off') == 0x326:
            vals.update(g.get('values', ()))
    return gate_from_326(vals) if vals else None


def preferred_gate(ad):
    """The gate phase (b) would use: the probe-locked +0x326 if it converged, else the deterministic
    +0xA8>0 fallback (the coordinator's decision: ship the deterministic gate if +0x326 won't lock)."""
    return gate_from_probe(ad) or GATE_A8


def dispatcher_v5(gate, factor=FACTOR):
    """Prepared GBPSOGC5 dispatcher bytes carrying the extra-update gate (DATA ONLY - not installed).
    gate is GATE_A8 or a gate_from_326(...) dict. Identical to the shipped GBPSOGC4 dispatcher plus
    the inert extra-update block; installing it (GBPSOGC4->GBPSOGC5 migration) is the nav-signed-off,
    live-verified step that configured()/set_enabled still refuse until NAV_SIGNOFF and LIVE_VERIFIED."""
    from . import pso_gc_live as L
    return L.dispatcher(speed_gate=gate, speed_factor=factor)


def status(ad, platform):
    if platform != 'gamecube':
        raise Unsupported('3x attack speed is for the GameCube 3OE2 build only')
    if not NAV_SIGNOFF:
        return {'attack_speed_3x': False, 'configured': False, 'factor': FACTOR,
                'nav_signoff': False, 'gate_ready': True, 'gate': GATE_A8['desc'],
                'reason': 'phase (b) prepared (GBPSOGC5 bytes ready) but held for nav sign-off'}
    from .pso_gc_live import GC
    st = GC(ad).speed_status()
    return {'attack_speed_3x': st.get('attack_speed_3x', False), 'configured': True,
            'factor': FACTOR, 'nav_signoff': True, 'installed': st.get('installed', False),
            'gate': GATE_A8['desc']}


def set_enabled(ad, platform, on):
    if platform != 'gamecube':
        raise Unsupported('3x attack speed is for the GameCube 3OE2 build only')
    if not NAV_SIGNOFF:
        raise Unsupported('3x attack speed is prepared but not yet enabled: phase (b) is held for '
                          'nav sign-off on the GBPSOGC4->GBPSOGC5 dispatcher change')
    # Live dispatcher swap on the +0xA8 gate: self-verifying with auto-rollback (pso_gc_live).
    from .pso_gc_live import GC
    return GC(ad).set_speed(bool(on))
