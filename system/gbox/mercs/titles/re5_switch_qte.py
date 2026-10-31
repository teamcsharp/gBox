"""RE5 Switch (main EBFFDB223149A725A93CD9B60979F6AA) native QTE progress completion: the PS3's re5_qte on this build.

Modes 4 (button accumulation) and 6 (stick wiggle) compare the shown display unit's +0x40 progress float with its
+0x44 target. The evaluator's true return reaches the ButtonMgr's success path, which runs the real event callback.
Only that progress float is written. The success bytes (+0x13 / +0x14) are never written: setting them would skip the
callback.

Static (main's NSO, Eden dump_nso, read with capstone 2026-10-31; every range in SIGNATURES read back byte-identical
from the live MercMode process the same day). Offsets are from main's base:
  0x15A848..0x15A898  ButtonMgr update: each shown display unit (mgr +0x3E8 / +0x448, the higher button +0x24 first)
                      goes to the evaluator 0x15D130(unit, mgr +0x10 the pad, mgr +0xC the player index). A true return
                      with a live cActionButton reaches 0x15A8A0.
  0x15A9C8..0x15AAAC  the success path: it needs button +0x12 (available), sets +0x13 and +0x14 to 1 (sturh 0x101),
                      runs the owner / player notifications and tail-calls the event callback button +0x50 (owner +0x8,
                      player, +0x58, +0x60, s0 +0x64). This is the PS3's 8CD694.
  0x15A778..0x15A7DC  selection fill: unit +0x18 mode = button +0x20, +0x20 mask = KEY_TABLE[+0x28],
                      +0x44 target = float(button +0x30), +0x40 progress = min(target, 0), +0x48 = button +0x9C (serial).
  0x15D164..0x15D1E4  evaluator entry: a muted button (+0x14) returns 0; a new one (+0x15) resets the unit the same way
                      and clears +0x15. Key index 0 returns 0. Then 0x15D2F4 dispatches unit +0x18 through main+0x17504CC.
  mode 4 -> 0x15D430 -> 0x15F470: a new press of the unit's mask adds 1.0 to +0x40, clamped at +0x44. Every call
                      returns +0x40 >= +0x44, with no press too (0x15F5DC / 0x15F610).
  mode 6 -> 0x15D564 -> 0x15F840: a new stick direction adds max(sFps +0x2C, 1) (horizontal) or a quarter of it
                      (vertical) to +0x40, clamped at +0x44. Every call returns +0x40 >= +0x44 (0x15F97C). Target <= 0
                      returns the direction flag instead, so a target must be positive.
The other modes have no unit accumulator. 1 press: (new & mask) == mask in one frame. With button +0xA0 set, a wrong key
puts the player's bit into +0xA4 (excluded: the press fails). 2 release, 3 chord within 3.0 (unit +0x58 / +0x30),
7 rotation (fires per step), 8 / 9 stick axes, 5 the dying "Resuscitate" (a continuous-mash gate, state +0x1C, gap
+0x30 under 9.0; the recovery itself accumulates in the player, not in the unit). Completing them would mean writing
pad input or the success bytes, so they keep the bot's ordinary input. PressWatch only reads their outcome.

Live (read-only, MercMode's session on lilspark, Citron, base 0x3CA7C04000, 2026-10-31): the unit / button layout
above, with unit +0x48 = button +0x9C. A mode-1 Y press (label 58) the bot answered went from +0x10..+0x15 =
01 01 01 00 00 00 to 01 01 01 01 01 00 (the success path's +0x13 / +0x14), and its unit then hid. sInfoMan's per-slot
option (+0x94) read 1, so the evaluator's automatic-success branch (0x15D9EC) is off.

Readback means progress was submitted, not that an event succeeded. Native acceptance (+0x13 and +0x14) and a held
player's release are separate observations. External process writes cannot be made atomic with the game's thread.
"""
from __future__ import annotations

import math
import struct
import time

from . import re5_switch as R
from . import re5_switch_prompt as P

MODES = {4: "button accumulation", 6: "stick wiggle"}
PROGRESS, TARGET = P.UNIT_PROGRESS, P.UNIT_TARGET           # unit +0x40 / +0x44 (f32)
UNIT_SIZE, BTN_SIZE = 0x60, 0xB0
UNIT_SLOT, UNIT_SERIAL = 0x0C, 0x48
BTN_ACCEPTED, BTN_NEW = 0x13, P.BTN_NEW                       # +0x13 set with +0x14 by the success path; +0x15 reset
BTN_CALLBACK, BTN_SERIAL, BTN_STRICT, BTN_EXCLUDED = 0x50, 0x9C, 0xA0, 0xA4
TARGET_MAX = 1_000_000
OBSERVE_S = 3.0
SIGNATURES = {
    0x0015A778: bytes.fromhex("424c109b6f00003941fc01f94fc40f393f54003941fc41f9232040b9430004b95f0404b9232840b9237a63b8"
                              "430402f95f0802f95f1804b9213040bd21d8215e412c04bd2178201e412804bd239c40b9433004b9212840b9"
                              "416a6138413404b95f2002f9"),
    0x0015A848: bytes.fromhex("62ce40b875120091e00316aae10315aa360a009460000036d60a40f9f60100b588224039c800003590000014"
                              "75420091733200918822403988110034620240b9e00314aae10315aa280a0094e0100036960a40f9b61000b4"),
    0x0015A9C8: bytes.fromhex("740240b9c84a403908070034282080529f0e0071c8320178"),
    0x0015AA80: bytes.fromhex("c00640f9600100b4c42a40f9240100b4c06640bdc22e40f9e103142ac36240b9fd7b42a9f44f41a9f657c3a8"
                              "80001fd6"),
    0x0015D164: bytes.fromhex("680a40f9f50301aa7f260039680000b409514039e9010034e0031f2ae9234e6d00000012eb2b4d6ded334c6d"
                              "ef3b4b6dfd7b54a9f44f53a9f65752a9f85f51a9fa6750a9fc6f4fa9ff430591c0035fd609554039a9010034"
                              "7f1e00b97f1600f9e103271e7f3200b97f7e05a9003140bd00d8215e604600bd0078211e604200bd1f550039"),
    0x0015D2F4: bytes.fromhex("691a40b92a0500515f210071e81200548baf00f06b3113916a79aab84a010b8b40011fd6"),
    0x0015D430: bytes.fromhex("e00313aae10315aae2031f2ae30314aa0c0800944f010014"),
    0x0015D564: bytes.fromhex("a12640f9e00313aae2031f2ae30314aab308009402010014"),
    0x0015F5D4: bytes.fromhex("0803178a880000b56102482d0c0000147f2e00b96202482d01102e1e4128211ee203271e2148221e2020201e"
                              "614200bd6d000054604200bd011ca04e2020201ee0b79f1a"),
    0x0015F900: bytes.fromhex("e803003488dc00b0085144f9012d40bd02102e1e2148221eca0000b50d0000141f2c00b9612d40bd02102e1e"
                              "2148221e024040bd2228221ee303271e4248231e4020201e024000bd4d000054004000bd690100b402102a1e"
                              "2108221e024040bd2128221ee203271e2148221e2020201e014000bd4d000054004000bd014040bd2020201e"
                              "e8b79f1ae003082a"),
    0x017504CC: bytes.fromhex("7ccfa0fe7cd0a0fe88cea0fe64cfa0fe70cea0fe98d0a0feb0d0a0fe4ccea0fe4ccea0fe"),
}
ERRORS = (OSError, ValueError, OverflowError, struct.error, IndexError, RuntimeError)


class Reject(ValueError):
    pass


def _q(m, a) -> int:
    return struct.unpack("<Q", m.rd(a, 8))[0]


def _u32(m, a) -> int:
    return struct.unpack("<I", m.rd(a, 4))[0]


def _ptr(p, align=8) -> bool:
    return R.ptr_ok(p) and p % align == 0


def validate(m, base: int) -> None:
    """main's evaluator, success path, selection fill and key table are the ones this module was written against."""
    if not isinstance(base, int) or not R.ptr_ok(base):
        raise Reject("main's base is unknown.")
    for off, expected in SIGNATURES.items():
        if bytes(m.rd(base + off, len(expected))) != expected:
            raise Reject("Native QTE code signatures do not match this build.")
    if not P.table_ok(m, base):
        raise Reject("Native QTE key table does not match this build.")


def _descriptor(raw: bytes) -> bytes:
    # vtable and owner; player, kind, mode, priority, key, label, count; target and the callback with its arguments;
    # the serial. Not the per-frame flags (+0x10..+0x15), player bits (+0x40) or frames alive (+0x98).
    return raw[0x00:0x10] + raw[0x18:0x34] + raw[0x48:0x68] + raw[BTN_SERIAL:BTN_SERIAL + 4]


def _unit_key(raw: bytes) -> bytes:
    # shown, HUD slot, button, mode, target and the serial copy. Not +0x09 (the evaluator rewrites it every frame),
    # the mask (+0x20: remapped in place for some control types) or the progress itself.
    return raw[P.UNIT_SHOWN:P.UNIT_SHOWN + 1] + raw[UNIT_SLOT:P.UNIT_MODE + 4] + raw[TARGET:TARGET + 4] \
        + raw[UNIT_SERIAL:UNIT_SERIAL + 4]


def _manager(m, base: int, index: int = 0):
    ab = _q(m, base + P.S_ACTION)
    if not _ptr(ab) or _q(m, ab) != base + P.AB_VT or not m.rd(ab + P.AB_ENABLED, 1)[0]:
        raise Reject("sActionButton is unavailable.")
    mgr = ab + P.AB_MGR + P.MGR_STRIDE * index
    if not m.rd(mgr + P.MGR_ENABLED, 1)[0] or struct.unpack("<i", m.rd(mgr + P.MGR_INDEX, 4))[0] != index:
        raise Reject("The first player's ButtonMgr is unavailable.")
    return ab, mgr


def shown_units(m, base: int) -> list:
    """[(unit address, mode, button)] of the first player's shown display units: two small reads, no validation."""
    ab = _q(m, base + P.S_ACTION)
    if not _ptr(ab):
        return []
    mgr = ab + P.AB_MGR
    out = []
    for uo in P.MGR_UNITS:
        raw = bytes(m.rd(mgr + uo, 0x1C))
        if raw[P.UNIT_SHOWN]:
            out.append((mgr + uo, struct.unpack_from("<I", raw, P.UNIT_MODE)[0],
                        struct.unpack_from("<Q", raw, P.UNIT_BTN)[0]))
    return out


def view(m, base: int, player: int, snapshot=None) -> dict:
    """Fully validate one currently shown, reset-free mode 4 or 6 request of the solo first player."""
    validate(m, base)
    if snapshot is not None and ((snapshot.get("player") or {}).get("ptr") != player
                                 or snapshot.get("player_index", 0) != 0):
        raise Reject("QTE player differs from the current bot snapshot.")
    if not _ptr(player, 4):
        raise Reject("Current player is unavailable.")
    sp = _q(m, base + R.S_PLAYER)
    if not _ptr(sp) or _q(m, sp + R.P_FIRST) != player:
        raise Reject("Native QTE assistance supports the solo first player.")
    if struct.unpack("<h", m.rd(player + R.P_HP, 2))[0] <= 0:
        raise Reject("Terminal player cannot complete a live QTE.")
    ab, mgr = _manager(m, base)
    units, buttons = [], set()
    for uo in P.MGR_UNITS:
        raw = bytes(m.rd(mgr + uo, UNIT_SIZE))
        button = struct.unpack_from("<Q", raw, P.UNIT_BTN)[0]
        if raw[P.UNIT_SHOWN]:
            if button in buttons:
                raise Reject("Both display units name one button.")
            buttons.add(button)
            if struct.unpack_from("<I", raw, P.UNIT_MODE)[0] in MODES:
                units.append((mgr + uo, raw, button))
    if not units:
        raise Reject("Waiting for a verified mode 4 or 6 QTE; other modes keep the bot's ordinary input.")
    if len(units) != 1:
        raise Reject("The shown QTE unit is ambiguous.")
    unit, raw, button = units[0]
    mode = struct.unpack_from("<I", raw, P.UNIT_MODE)[0]
    if not _ptr(button):
        raise Reject("Invalid native button object.")
    braw = bytes(m.rd(button, BTN_SIZE))
    if _q_of(braw, 0) != base + P.BTN_VT:
        raise Reject("The shown unit's button is not a cActionButton.")
    # +0x12 is the success path's gate; +0x13 / +0x14 its marks; +0x15 a pending reset. (+0x10 is no gate: shown Pick up
    # prompts read 0 there live, and neither the evaluator nor the success path reads it.)
    if braw[P.BTN_AVAIL] != 1 or braw[BTN_ACCEPTED] or braw[P.BTN_MUTED] or braw[BTN_NEW]:
        raise Reject("The request is unavailable, accepted, muted, or awaiting native reset.")
    bplayer, _kind, bmode, _priority, key = struct.unpack_from("<5I", braw, P.BTN_PLAYER)
    if bplayer not in (0, 4) or not struct.unpack_from("<I", braw, P.BTN_PLAYERS)[0] & 1 \
            or struct.unpack_from("<I", braw, BTN_EXCLUDED)[0] & 1:
        raise Reject("The request is not the first player's this frame.")
    if bmode != mode or not 0 < key < len(P.MASKS):
        raise Reject("Native mode or key no longer matches the button definition.")
    target_int = struct.unpack_from("<i", braw, P.BTN_COUNT)[0]
    if not 0 < target_int <= TARGET_MAX:
        raise Reject("The event has no bounded positive accumulator target.")
    progress, target = struct.unpack_from("<2f", raw, PROGRESS)
    expected = struct.unpack("<f", struct.pack("<f", float(target_int)))[0]
    if not math.isfinite(target) or target != expected or not math.isfinite(progress) \
            or not 0 <= progress <= target \
            or raw[UNIT_SERIAL:UNIT_SERIAL + 4] != braw[BTN_SERIAL:BTN_SERIAL + 4]:
        raise Reject("Native progress/target/serial no longer matches the button definition.")
    descriptor = _descriptor(braw)
    target_bytes = raw[TARGET:TARGET + 4]
    identity = (base, ab, mgr, unit, button, mode, descriptor, _unit_key(raw), player)
    # Do not commit against a selection that changed during these reads.
    latest, lbtn = bytes(m.rd(unit, UNIT_SIZE)), bytes(m.rd(button, BTN_SIZE))
    if _unit_key(latest) != _unit_key(raw) or _descriptor(lbtn) != descriptor \
            or lbtn[P.BTN_AVAIL:BTN_NEW + 1] != braw[P.BTN_AVAIL:BTN_NEW + 1] \
            or _q(m, sp + R.P_FIRST) != player or _q(m, base + P.S_ACTION) != ab:
        raise Reject("The native QTE changed during observation.")
    return {"identity": identity, "player": player, "unit": unit, "button": button, "mode": mode,
            "descriptor": descriptor, "progress": progress, "target": target, "target_bytes": target_bytes,
            "held": m.rd(player + R.P_MOTION, 1)[0] in R.MOTION_HELD,
            "callback": _q_of(braw, BTN_CALLBACK) - base if _q_of(braw, BTN_CALLBACK) else 0}


def _q_of(raw: bytes, off: int) -> int:
    return struct.unpack_from("<Q", raw, off)[0]


class ProgressHook:
    """One bounded write per observed selection, scoped to one adapter / boot / player.

    memory.wr must recheck that scope immediately before writing. A scope change refuses the old helper; a new
    helper is made for the new owner. No old progress is restored.
    """

    def __init__(self, scope):
        self.scope, self.pending, self.last_identity = scope, None, None

    def _result(self, phase, reason, **values):
        pending = self.pending or {}
        return {"phase": phase, "reason": reason, "verified": False, "native_accepted": False,
                "completed": False, "writes": 0, "mode": pending.get("mode"), "kind": MODES.get(pending.get("mode")),
                **values}

    def _observe(self, m, now):
        pending = self.pending
        try:
            raw = bytes(m.rd(pending["button"], BTN_SIZE))
            if _descriptor(raw) != pending["descriptor"]:
                return self._result("ended_unconfirmed", "Button definition changed; no success inferred.")
            if now - pending["at"] >= OBSERVE_S:
                accepted = bool(pending.get("accepted"))
                return self._result("native_accepted" if accepted else "timeout",
                                    "Bounded outcome observation ended; no later action is attributed to this event.",
                                    verified=accepted, native_accepted=accepted)
            accepted = raw[BTN_ACCEPTED] == 1 and raw[P.BTN_MUTED] == 1
            pending["accepted"] = pending.get("accepted", False) or accepted
            sp = _q(m, pending["base"] + R.S_PLAYER)
            if _q(m, sp + R.P_FIRST) != pending["player"]:
                return self._result("ended_unconfirmed", "Player changed; no success inferred.",
                                    verified=bool(pending["accepted"]), native_accepted=bool(pending["accepted"]))
            hp = struct.unpack("<h", m.rd(pending["player"] + R.P_HP, 2))[0]
            motion = m.rd(pending["player"] + R.P_MOTION, 1)[0]
            if pending["accepted"] and pending["held"] and hp > 0 and motion not in R.MOTION_HELD:
                return self._result("completed", "Native acceptance and release from the held motion observed.",
                                    verified=True, native_accepted=True, completed=True)
            if pending["accepted"]:
                return self._result("native_accepted", "Native completion flags observed; the event outcome is not "
                                    "yet confirmed.", verified=True, native_accepted=True)
            return self._result("pending", "Progress submitted; waiting for the native evaluator and callback.")
        except ERRORS:
            return self._result("pending" if now - pending["at"] < OBSERVE_S else "timeout",
                                "Native completion readback is unavailable; no success inferred.")

    def step(self, m, base, player, snapshot, now, *, scope, enabled=True):
        if not enabled:
            return self._result("disabled", "Native QTE assistance is disabled.")
        if scope is None or scope != self.scope or not math.isfinite(now):
            return self._result("rejected", "Adapter/boot/player scope changed; old event writes are forbidden.")
        observed = self._observe(m, now) if self.pending else None
        try:
            current = view(m, base, player, snapshot)
            if current["identity"] == self.last_identity:
                # Only an observed native accepted -> active/reset transition re-arms an identical request.
                if not (self.pending and self.pending.get("accepted") and current["progress"] < current["target"]):
                    return observed or self._result("pending", "This selection has already been handled.")
            if current["progress"] >= current["target"]:
                return self._result("native_ready", "Native progress already meets the event target; no write needed.",
                                    mode=current["mode"], kind=MODES[current["mode"]])
            latest = view(m, base, player, snapshot)          # full second guard right before the 4-byte write
            if latest["identity"] != current["identity"] or latest["progress"] < current["progress"]:
                raise Reject("The event or accumulator reset before the write.")
            if latest["progress"] >= latest["target"]:
                return self._result("native_ready", "Native progress reached its target before the write.",
                                    mode=latest["mode"], kind=MODES[latest["mode"]])
            self.last_identity = current["identity"]
            self.pending = dict(latest, at=now, accepted=False, base=base)
            if not m.wr(latest["unit"] + PROGRESS, latest["target_bytes"]):
                return self._result("write_unconfirmed", "Progress write readback failed; native outcome remains unknown.")
            native = self._observe(m, now)
            if native.get("native_accepted"):
                return dict(native, writes=1)
            after, button = bytes(m.rd(latest["unit"], UNIT_SIZE)), bytes(m.rd(latest["button"], BTN_SIZE))
            if after[PROGRESS:PROGRESS + 4] != latest["target_bytes"] or _unit_key(after) != latest["identity"][7] \
                    or _descriptor(button) != latest["descriptor"] or button[BTN_NEW]:
                return self._result("write_unconfirmed", "Progress changed before readback; no success inferred.",
                                    writes=1)
            return self._result("submitted", "Event progress read back at its target; native callback is still "
                                "pending.", writes=1, progress_verified=True, target=latest["target"])
        except (Reject, *ERRORS) as error:
            return observed or self._result("waiting", str(error))


class PressWatch:
    """Read-only outcomes of the prompts this module does not complete (modes 1, 2, 3, 5, 7, 8, 9): accepted when the
    success path's +0x13 / +0x14 show, failed when the game puts the first player's bit into +0xA4 (a wrong key on a
    strict press), ended when the unit hides without either. Never writes."""

    def __init__(self):
        self.live, self.counts = {}, {}

    def _count(self, mode, outcome):
        key = f"mode{mode}_{outcome}"
        self.counts[key] = self.counts.get(key, 0) + 1

    def see(self, m, base, shown) -> None:
        seen = {}
        for _unit, mode, button in shown:
            if mode in MODES or not _ptr(button):
                continue
            try:
                raw = bytes(m.rd(button, BTN_SIZE))
            except ERRORS:
                continue
            if _q_of(raw, 0) != base + P.BTN_VT:
                continue
            ident = (button, raw[BTN_SERIAL:BTN_SERIAL + 4])
            st = self.live.get(ident) or {"mode": mode, "outcome": None}
            if st["outcome"] is None:
                if raw[BTN_ACCEPTED] == 1 and raw[P.BTN_MUTED] == 1:
                    st["outcome"] = "accepted"
                elif struct.unpack_from("<I", raw, BTN_EXCLUDED)[0] & 1:
                    st["outcome"] = "failed"
                if st["outcome"]:
                    self._count(mode, st["outcome"])
            seen[ident] = st
        for ident, st in self.live.items():
            if ident not in seen and st["outcome"] is None:
                self._count(st["mode"], "ended")
        self.live = seen


def _invalidate(cfg, reason):
    last = cfg.get("last") or {}
    if last.get("completed") or last.get("verified"):
        cfg["last_outcome"] = dict(last, current=False, writes=0)
    cfg["last"] = {"phase": "waiting" if cfg.get("on") else "disabled", "reason": reason, "current": False,
                   "verified": False, "native_accepted": False, "completed": False, "writes": 0}


def status(cfg) -> dict:
    cfg = cfg or {}
    press = cfg.get("press")
    return {"enabled": bool(cfg.get("on")), "native_modes": sorted(MODES),
            "phase": "waiting" if cfg.get("on") else "disabled",
            "verified": False, "native_accepted": False, "completed": False,
            **(cfg.get("last") or {}),
            "last_outcome": dict(cfg["last_outcome"]) if cfg.get("last_outcome") else None,
            "counts": dict(cfg.get("counts") or {}),
            "press_outcomes": dict(press.counts) if press else {},
            "other_modes": "ordinary bot input: single / chord / release presses, Resuscitate and stick rotations "
                           "have no unit accumulator to complete"}


def capability(m, base) -> dict:
    try:
        validate(m, base)
        return {"available": True, "native_modes": sorted(MODES),
                "reason": "Native progress for button accumulation and stick wiggle; the game's own evaluator fires "
                          "the real callback; other QTEs keep the bot's ordinary input."}
    except (Reject, *ERRORS) as error:
        return {"available": False, "native_modes": [], "reason": f"Native QTE signatures are not verified: {error}"}


def configure(state: dict, m, base, on: bool = True) -> dict:
    """The op: on validates the build first (a mismatch never turns it on); off drops the helper."""
    cfg = state.setdefault("qte", {})
    if on:
        validate(m, base)
        cfg.update(on=True, base=base)
        cfg.setdefault("press", PressWatch())
        _invalidate(cfg, "Waiting for a verified mode 4 or 6 QTE.")
    else:
        cfg["on"] = False
        cfg.pop("helper", None)
        _invalidate(cfg, "Native QTE assistance disabled.")
    return status(cfg)


class _Guarded:
    """The adapter's memory for one step: reads straight through, the one write only while the scope still holds."""

    def __init__(self, ad, owns):
        self.ad, self.owns = ad, owns

    def rd(self, a, n):
        return self.ad.read_memory(a, n)

    def wr(self, a, data) -> bool:
        if not self.owns():
            return False
        try:
            res = self.ad.write_memory(a, data)
        except ERRORS:
            return False
        if isinstance(res, dict) and not res.get("verified", True):
            return False
        try:
            return bytes(self.ad.read_memory(a, len(data))) == bytes(data)
        except ERRORS:
            return False


def maintain(ad, state: dict, snap, *, enabled: bool = True, clock=time.monotonic) -> dict:
    """Each driver snapshot (re5_switch_mods.maintain, before the bot's tick and its ordinary prompt input): the
    shown units read cheaply; only a shown mode 4 / 6 unit, or a pending observation, runs the full validation.
    The answer is status() with "writes" = this call's writes only."""
    cfg = state.get("qte") or {}
    idle = lambda: dict(status(cfg), writes=0)
    if not cfg.get("on"):
        return idle()
    if not enabled:
        if cfg.get("helper") is not None:
            cfg.pop("helper", None)
            _invalidate(cfg, "No active round.")
        return idle()
    p = (snap or {}).get("player")
    base = state.get("base")
    if not p or not isinstance(p.get("ptr"), int) or (snap or {}).get("player_index", 0) != 0:
        return idle()                                         # no solo first player now (a load, the menus)
    try:
        if base != cfg.get("base") or (snap or {}).get("module_base", base) != base:
            raise Reject("main moved (a new boot): turn instant_qte on again for this boot.")
        player = p["ptr"]
        m = _Guarded(ad, lambda: False)
        shown = shown_units(m, base)
        press = cfg.setdefault("press", PressWatch())
        press.see(m, base, shown)
        helper = cfg.get("helper")
        now = clock()
        observing = helper is not None and helper.pending is not None \
            and 0 <= now - helper.pending["at"] <= OBSERVE_S + 0.5   # one look past the window publishes its outcome
        if not any(mode in MODES for _u, mode, _b in shown) and not observing:
            return idle()
        scope = (id(ad), base, player)
        if helper is None or helper.scope != scope:
            helper = cfg["helper"] = ProgressHook(scope)

        def owns():
            current = state.get("qte")
            if current is not cfg or not cfg.get("on") or state.get("base") != base:
                return False
            try:
                sp = struct.unpack("<Q", bytes(ad.read_memory(base + R.S_PLAYER, 8)))[0]
                return R.ptr_ok(sp) and struct.unpack("<Q", bytes(ad.read_memory(sp + R.P_FIRST, 8)))[0] == player
            except ERRORS:
                return False

        m.owns = owns
        result = helper.step(m, base, player, snap, now, scope=scope)
        if result.get("writes") and not owns():
            result = dict(result, phase="rejected", verified=False, native_accepted=False, completed=False,
                          reason="Scope changed during QTE readback.")
    except (Reject, *ERRORS) as error:
        result = {"phase": "rejected", "reason": str(error), "verified": False, "native_accepted": False,
                  "completed": False, "writes": 0}
    counts = cfg.setdefault("counts", {})
    if result.get("writes"):
        counts["progress_writes"] = counts.get("progress_writes", 0) + int(result["writes"])
    event = getattr(cfg.get("helper"), "pending", None)
    for key in ("native_accepted", "completed"):
        if result.get(key) and event is not None and not event.get("counted_" + key):
            event["counted_" + key] = True                    # once per written event, whatever the later phases
            counts[key] = counts.get(key, 0) + 1
    cfg["last"] = result
    return dict(status(cfg), writes=int(result.get("writes") or 0))
