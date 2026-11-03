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
from .registry import Unsupported

CAVE, VARS, HEADER, END = 0x80005400, 0x800054C0, 0x800054E0, 0x80005500
METADATA = b'GBPSOSP1'
FACTOR = 3                                              # 3x attack speed

# --- set after the post-restart RE + live snapshot (see module docstring) -------------
HOOK_FUNC = None            # the per-frame player animation-advance function to wrap
HOOK_ORIGINAL = None        # its first instruction, e.g. bytes.fromhex('9421ffd0')
ATTACK_STATE_OFF = None     # TObjPlayer offset of the attack-animation state u16
ATTACK_STATE_MATCH = None   # the value at that offset meaning "attacking"


def configured():
    """True once the two outstanding unknowns are filled; gates every live action."""
    return None not in (HOOK_FUNC, HOOK_ORIGINAL, ATTACK_STATE_OFF, ATTACK_STATE_MATCH)


def status(ad, platform):
    if platform != 'gamecube':
        raise Unsupported('3x attack speed is for the GameCube 3OE2 build only')
    if not configured():
        return {'attack_speed_3x': False, 'configured': False, 'factor': FACTOR,
                'reason': 'prepared but not configured: HOOK_FUNC + attack-state pending the clean-i9 '
                          'restart live snapshot (see gbox.pso_speed docstring)'}
    raise Unsupported('pso_speed configured but the cave generator/install is not implemented in this '
                      'scaffold build; finish per the module docstring')


def set_enabled(ad, platform, on):
    if platform != 'gamecube':
        raise Unsupported('3x attack speed is for the GameCube 3OE2 build only')
    raise Unsupported('3x attack speed is prepared but not yet enabled: the animation-advance hook point '
                      'and the attack-state offset need the post-restart RE/live snapshot (gbox.pso_speed)')
