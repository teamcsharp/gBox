"""RE5 (PS3 BLUS30491) solo-DYING recovery-progress candidate -- OFFLINE, DISABLED and UNWIRED (request #2984).

Mechanism (build-specific evidence, see the request's research notes; no game code is reproduced here):
the game's recovery routine treats player+0x1CEC as countdown *and* accumulated progress.  When HP==1 and a finite
progress value is strictly above the selected parameter threshold, the engine itself clears the progress and calls
player virtual+0x128(3) (its HP/recovery notification).  This helper only *plans* one bounded nudge of that float.
It never writes HP, never sets cActionButton completion bits and never restores an old countdown.

NOT verified live: that the nudge revives the player.  ``Outcome.RECOVERED`` is reported only from observed state
(HP>1 and the recovery request gone); anything else is PENDING or TIMEOUT -- an honest failure.
Nothing imports this module; wiring needs an independent root review and a separately authorised live observation.
"""
from __future__ import annotations

import enum
import math
import struct
from dataclasses import dataclass

S_PLAYER, S_MAIN, S_PARAMETER, S_TIMESTEP, S_PROFILE = 0x017FEB34, 0x0191CEE4, 0x017FEB08, 0x017FDC24, 0x017FDCE4
MAIN_GAMESYS, GAMESYS_MODE, MAIN_FLAGS, MAIN_FLAG_MASK = 0x182D4, 0x58, 0x182E0, 0x2000_0000
SPLAYER_FLAGS = 0x5DC
SUPPORTED_MODES = (1, 2, 5)
P_HP, P_PROGRESS, P_BUTTON, P_PARTNER, P_PARTNER2, P_FLAGS, P_MODE, P_SCALE = \
    0x14A4, 0x1CEC, 0x22DC, 0x2BF4, 0x2BFC, 0x2F10, 0x2F20, 0x1114
P_RECOVER_FLAG, P_CONTROLLER, CONTROLLER_BUSY = 0x1D0B, 0x2EE4, 0x634
PARAM_THRESHOLD, PARAM_INCREMENT = 0x3D0, 0x414
PROFILE_INDEX = 0x24
BUTTON_VT = 0x016332A8
BUTTON_ACTIVE, BUTTON_SUCCESS, BUTTON_CONSUMED, BUTTON_PLAYER, BUTTON_MODE, BUTTON_INDEX, BUTTON_GEN = \
    0x0A, 0x0B, 0x0C, 0x10, 0x18, 0x20, 0x68
EXPECTED_PLAYER_INDEX, EXPECTED_BUTTON_INDEX, EXPECTED_BUTTON_MODE = 0, 25, 5
ACTION_EXCLUDED = range(0x7B, 0x81)
P_ACTION = 0x845
MARGIN_STEPS = 3          # decay steps of safety beyond the native next-frame subtraction
MAX_PROGRESS_SPAN = 600.0  # never write a value this far above the threshold: a wild value is rejected, not clamped

# Immutable current-build anchors (address -> exact bytes); a mismatch means an unsupported build.
SIGNATURES = {
    0x864250: bytes.fromhex("ec000372efecf83ad3ff1cec809f2bf42f840000419e0024"),
    0x8642BC: bytes.fromhex("811f2bf481690000c1aa03d0812b00241d2959403d290002"),
    0x864328: bytes.fromhex("ff80f800409c028438000000901f1cec837b00007b7d0020"),
    0x86432C: bytes.fromhex("409c028438000000901f1cec837b00007b7d0020881d0020"),
    0x8643BC: bytes.fromhex("981f1d0b38800003812b012880090000f84100287c0903a6"),
    0x8645C0: bytes.fromhex("82fe80344bfffc98c00a03cc4bfffd2cfc0068904bfffd54"),
}


class Outcome(enum.Enum):
    REJECTED = "rejected"      # unsafe / unsupported / not applicable: nothing written
    NOT_NEEDED = "not_needed"  # progress already beyond threshold: wait for the engine, no rewrite
    WRITTEN = "written"        # one nudge issued; revival NOT yet observed
    PENDING = "pending"        # waiting for the engine
    RECOVERED = "recovered"    # HP>1 and request gone, observed
    TIMEOUT = "timeout"        # deadline passed without observed recovery: a failure
    WRITE_FAILED = "write_failed"


@dataclass(frozen=True)
class Plan:
    player: int
    button: int
    generation: int
    progress: float
    threshold: float
    target: float
    decay: float
    increment: float
    identity: bytes


class Reject(Exception):
    pass


def _ptr(p) -> bool:
    return isinstance(p, int) and 0x30000000 <= p < 0x40000000 and p % 4 == 0


def _u32(m, a) -> int:
    return struct.unpack(">I", m.rd(a, 4))[0]


def _f32(m, a) -> float:
    return struct.unpack(">f", m.rd(a, 4))[0]


def _pos(x) -> bool:
    return math.isfinite(x) and x > 0


def _snapshot(m) -> dict:
    """Read every field the guards use; raises Reject for any unsafe state.  Pure reads."""
    for address, expected in SIGNATURES.items():
        if m.rd(address, len(expected)) != expected:
            raise Reject("unsupported build: signature mismatch at %#x" % address)
    sp = _u32(m, S_PLAYER)
    if not _ptr(sp):
        raise Reject("no sPlayer")
    pl = _u32(m, sp + 0x28)
    if not _ptr(pl):
        raise Reject("no current player")
    main = _u32(m, S_MAIN)
    if not _ptr(main):
        raise Reject("no game heap")
    gs = _u32(m, main + MAIN_GAMESYS)
    if not _ptr(gs):
        raise Reject("no game system")
    mode = _u32(m, gs + GAMESYS_MODE)
    if mode not in SUPPORTED_MODES:
        raise Reject("unsupported game mode %d" % mode)
    if _u32(m, main + MAIN_FLAGS) & MAIN_FLAG_MASK:
        raise Reject("game flag blocks recovery")
    if _u32(m, sp + SPLAYER_FLAGS) & 4:
        raise Reject("sPlayer flag blocks recovery")
    hp, hp_max = struct.unpack(">hh", m.rd(pl + P_HP, 4))
    if hp != 1:
        raise Reject("HP is %d, not 1 (healthy and terminal HP0 are never touched)" % hp)
    if hp_max < 3:
        raise Reject("max HP too small for the recovery transition")
    progress = _f32(m, pl + P_PROGRESS)
    if not _pos(progress):
        raise Reject("progress not finite positive")
    if m.rd(pl + P_RECOVER_FLAG, 1)[0] != 0:
        raise Reject("recovery already flagged")
    if m.rd(pl + P_ACTION, 1)[0] in ACTION_EXCLUDED:
        raise Reject("excluded action")
    if _u32(m, pl + P_PARTNER) != 0 or _u32(m, pl + P_PARTNER2) != 0:
        raise Reject("partner path: threshold override not proven")
    if _u32(m, pl + P_FLAGS) & 4:
        raise Reject("player flag blocks recovery")
    if _u32(m, pl + P_MODE) != 0:
        raise Reject("player recovery mode is not the plain solo path")
    controller = _u32(m, pl + P_CONTROLLER)
    if controller != 0 and (not _ptr(controller) or _u32(m, controller + CONTROLLER_BUSY) != 0):
        raise Reject("controller present/busy")
    profile = _u32(m, S_PROFILE)
    if not _ptr(profile) or _u32(m, profile + PROFILE_INDEX) != 0:
        raise Reject("profile index is not 0")
    param, step_obj = _u32(m, S_PARAMETER), _u32(m, S_TIMESTEP)
    if not _ptr(param) or not _ptr(step_obj):
        raise Reject("no parameter/timestep object")
    threshold, increment = _f32(m, param + PARAM_THRESHOLD), _f32(m, param + PARAM_INCREMENT)
    timestep, scale = _f32(m, step_obj + 0x2C), _f32(m, pl + P_SCALE)
    if not (_pos(threshold) and _pos(increment) and _pos(timestep) and _pos(scale)):
        raise Reject("invalid threshold/timestep/time scale")
    btn = _u32(m, pl + P_BUTTON)
    if not _ptr(btn):
        raise Reject("no recovery button")
    raw = m.rd(btn, 0x70)
    vt, owner = struct.unpack_from(">2I", raw)
    if vt != BUTTON_VT or owner != pl:
        raise Reject("button identity mismatch (stale button / mismatched owner)")
    if not raw[BUTTON_ACTIVE] or raw[BUTTON_CONSUMED]:
        raise Reject("button inactive or consumed")
    if struct.unpack_from(">I", raw, BUTTON_PLAYER)[0] != EXPECTED_PLAYER_INDEX \
            or struct.unpack_from(">I", raw, BUTTON_MODE)[0] != EXPECTED_BUTTON_MODE \
            or struct.unpack_from(">I", raw, BUTTON_INDEX)[0] != EXPECTED_BUTTON_INDEX:
        raise Reject("button is not the player-0 circle edge recovery request")
    return {"sp": sp, "pl": pl, "btn": btn, "gen": struct.unpack_from(">I", raw, BUTTON_GEN)[0],
            "progress": progress, "threshold": threshold, "increment": increment,
            "decay": timestep * scale, "identity": raw[:8], "raw": raw, "hp": hp}


def plan_nudge(m, player=None) -> Plan:
    """Return a one-write plan, or raise Reject (unsafe) / NotNeeded (progress already above threshold)."""
    a = _snapshot(m)
    if player is not None and player != a["pl"]:
        raise Reject("stale player")
    # The native decay for the next tick runs before the compare, so the value must survive it, plus margin.
    # A native accepted increment would only add, so ignoring it is the conservative direction.
    decay = a["decay"]
    if a["progress"] > a["threshold"]:
        raise NotNeeded("progress already above threshold; waiting for the engine")
    target = struct.unpack(">f", struct.pack(">f", a["threshold"] + decay * (1 + MARGIN_STEPS)))[0]
    if not math.isfinite(target) or target - a["threshold"] <= decay or target - a["threshold"] > MAX_PROGRESS_SPAN:
        raise Reject("cannot derive a safe margin")
    # Lifetime check: every identity must be unchanged after the whole read sequence.
    b = _snapshot(m)
    if (b["sp"], b["pl"], b["btn"], b["gen"], b["identity"]) != (a["sp"], a["pl"], a["btn"], a["gen"], a["identity"]):
        raise Reject("lifetime changed between reads")
    return Plan(a["pl"], a["btn"], a["gen"], a["progress"], a["threshold"], target, decay, a["increment"],
                a["identity"])


class NotNeeded(Exception):
    pass


class RecoveryNudge:
    """One-shot driver.  ``step(m, write, now)`` writes at most once per instance; ``now`` is a monotonic seconds value."""

    def __init__(self, timeout_s: float = 3.0):
        if not _pos(timeout_s):
            raise ValueError("timeout must be finite positive")
        self.timeout_s, self.plan, self.t0, self.done = timeout_s, None, None, False

    def step(self, m, write, now: float, player=None) -> Outcome:
        if not math.isfinite(now):
            return Outcome.REJECTED
        if self.plan is None:
            if self.done:
                return Outcome.REJECTED
            try:
                plan = plan_nudge(m, player)
            except NotNeeded:
                return Outcome.NOT_NEEDED
            except (Reject, struct.error, ValueError, OSError):
                return Outcome.REJECTED
            self.done = True                       # one shot, even if the write fails
            if not write(plan.player + P_PROGRESS, struct.pack(">f", plan.target)):
                return Outcome.WRITE_FAILED
            self.plan, self.t0 = plan, now
            return Outcome.WRITTEN
        return self._observe(m, now)

    def _observe(self, m, now) -> Outcome:
        p = self.plan
        assert p is not None
        try:
            sp = _u32(m, S_PLAYER)
            pl = _u32(m, sp + 0x28) if _ptr(sp) else 0
            if pl == p.player:
                hp = struct.unpack(">h", m.rd(pl + P_HP, 2))[0]
                btn = _u32(m, pl + P_BUTTON)
                raw = m.rd(btn, 0x70) if _ptr(btn) else b"\0" * 0x70
                request_live = btn == p.button and raw[BUTTON_ACTIVE] and \
                    struct.unpack_from(">I", raw, BUTTON_GEN)[0] == p.generation
                if hp > 1 and not request_live:
                    return Outcome.RECOVERED
        except (struct.error, ValueError, OSError):
            pass
        return Outcome.TIMEOUT if now - self.t0 >= self.timeout_s else Outcome.PENDING
