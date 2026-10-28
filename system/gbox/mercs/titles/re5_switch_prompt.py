"""The RE5 Switch context / QTE prompt from RAM: the sActionButton system (the PS3's re5_ps3.selected_prompt, this
build's 64-bit layout). Found statically in main EBFFDB22 and verified read-only against the live MercMode emulator
(2026-10-27 18:15-18:45: the hourglass, Break free, Resuscitate, Pick up, the mine's Place and the stage prompts).

Static (main EBFFDB22, module offsets) with the instructions that show it:
  S_ACTION  main+0x1CEFB78   sActionButton* (its constructor 0x158630 stores itself there: 0x158c1c str x19,[x8,#0xb78])
  sActionButton (vptr main+0x1AA2E70, getDTI 0x159780 -> dti 0x1ce9948, size 0x1680)
     +0x40 u8   enabled (move 0x1597a0: ldrb w8,[x19,#0x40]; cbz -> return)
     +0x48 MtArray of cActionButton*: +0x50 u32 count, +0x54 capacity, +0x60 cActionButton** (0x15fdb8..0x15fdc0)
     +0x68 + 0x4C0 * player: that player's ButtonMgr (move calls 0x15a0f0 / 0x15a3c0 on +0x68, +0x528, +0x9e8, +0xea8)
  ButtonMgr (vptr main+0x1AA2E30, 0x4C0)
     +0x08 u8 enabled, +0x0C s32 player index (0x15a104), +0x10 the player pad state (+0x38 held bits, +0x48 new)
     +0x3E8 / +0x448: two display units (ButtonUnit, 0x60 each), filled at 0x15a744..0x15a7d8 from the selection:
        +0x08 u8 shown (set 1 at 0x15a77c, cleared with +0x09 by strh wzr), +0x0C s32 its HUD slot (< 0x64)
        +0x10 cActionButton* (0x15a780), +0x18 u32 mode (= button +0x20, 0x15a794), +0x1C s32 progress state
        (the evaluator 0x15d130 zeroes it for a new button), +0x20 u64 the key mask (= KEY_TABLE[button +0x28],
        0x15a79c..0x15a7a4), +0x40 f32 progress, +0x44 f32 target (= float(button +0x30), 0x15a7b0..0x15a7c0)
     +0x4A8 cActionButton*[2] the selection, +0x4B8 u32 its count (<= 2: 0x15b15c..0x15b220)
  cActionButton (vptr main+0x1C62908, getDTI 0x824490 -> dti 0x1d73528, size 0xB0; constructor 0x824340)
     +0x08 owner (the actor: uPl00ChrisNormal, uOm0100 the hourglass, uOm1103 ..., sItem), +0x10 u8 on,
     +0x12 u8 available to a player this frame (move: strb [x24,#0x12] = mask != 0), +0x14 u8 muted (the evaluator
     returns at once: 0x15d174), +0x15 u8 new (0x15d1b4), +0x18 u32 player (0-3; 4 = any: cmp #4 at 0x159a98),
     +0x1C u32 kind (0x159b28: 1 / 3 area-triggered stage objects, 2 the player's own actions, 0), +0x20 u32 mode
     (1 press, 2 release, 3 / 4 / 5 mash, 6 stick wiggle, 7 stick rotate, 8 / 9 stick axes: 0x15d2f4 jump table),
     +0x24 u32 priority (the unit order: 0x15a830), +0x28 u32 key index into KEY_TABLE, +0x2C u32 label (which
     action / text: 112 the hourglass), +0x30 s32 the mash target, +0x40 u32 player bits this frame (0x159a4c),
     +0x48 target (a stage object's cAreaHit: +0x30 its position; an enemy for a finisher), +0x88 / +0x90 the
     availability callback (fn, arg), +0x98 frames alive, +0x9C serial, +0xA4 excluded players
  KEY_TABLE main+0x17C2A88: u32[32], the PS3 QTE_INPUT_TABLE's very values (0x8000 square, 0x1000 triangle, 0x4000
     cross, 0x2000 circle, 0x400, 0x800, 0x100, 0x200, ...; read at 0x15a7a0 and 0x15d200).
Switch keys by position (Type D): square -> Y (the ledge's "Jump down" is Y, live), circle -> A ("Resuscitate" is A,
live), cross -> B, triangle -> X; the shoulder bits follow the PS3 bot's names (0x400 l2 -> ZL, 0x800 r2 -> ZR, 0x100
l1 -> L, 0x200 r1 -> R) - UNVERIFIED on Switch.
"""
from __future__ import annotations

import struct

S_ACTION, AB_VT, BTN_VT, KEY_TABLE = 0x1CEFB78, 0x1AA2E70, 0x1C62908, 0x17C2A88
AB_ENABLED, AB_COUNT, AB_ARRAY, AB_MGR, MGR_STRIDE = 0x40, 0x50, 0x60, 0x68, 0x4C0
MGR_ENABLED, MGR_INDEX, MGR_UNITS, MGR_SEL, MGR_SEL_N = 0x08, 0x0C, (0x3E8, 0x448), 0x4A8, 0x4B8
UNIT_SHOWN, UNIT_BTN, UNIT_MODE, UNIT_MASK, UNIT_PROGRESS, UNIT_TARGET = 0x08, 0x10, 0x18, 0x20, 0x40, 0x44
BTN_OWNER, BTN_ON, BTN_AVAIL, BTN_MUTED, BTN_NEW = 0x08, 0x10, 0x12, 0x14, 0x15
BTN_PLAYER, BTN_KIND, BTN_MODE, BTN_PRIORITY, BTN_KEY, BTN_LABEL, BTN_COUNT = 0x18, 0x1C, 0x20, 0x24, 0x28, 0x2C, 0x30
BTN_PLAYERS, BTN_TARGET = 0x40, 0x48
KIND_ENEMY, KIND_STAGE, KIND_PLAYER, KIND_AREA = 0, 1, 2, 3   # kind 0: a Majini's (Break free); 1: a stage object's
                                         # (the hourglass, crates); 2: his own actions (Pick up, Resuscitate, Place, the
                                         # ledges); 3: area pickups (ammo, treasure: the target a cAreaHit)
# Labels seen live (the button +0x2C: which action / text):
LABEL_TIME_BONUS = 112                   # the hourglass statue (uOm0100), press:y: the only way to take it
LABEL_BREAK_FREE = 28                    # a Majini's grab (mode 6, the left stick shaken)
LABEL_RESUSCITATE = 55                   # dying (mash:a)
LABEL_PICKUP = 1                         # "Y Pick up" (a herb: frame 18:20:40)
LABEL_PLACE = 100                        # the bomb's Place (press:zl): the mines module's own
# His own actions seen at fixed stage spots (each label at one place or one kind of place, never beside a staggered
# Majini): 9 at the roof's edge where the round starts (Public Assembly) and on the y 350 ledges, 7 / 14 on the y 350
# ledges, 8 at low walls on the ground, 58 at one fence: the ledges' "Jump down" / climbs / vaults
TRAVERSE_LABELS = frozenset({7, 8, 9, 14, 58})
MASKS = (0, 0x8000, 0x1000, 0x4000, 0x2000, 0x0400, 0x0800, 0x0100,
         0x0200, 0x8000, 0x1000, 0x4000, 0x2000, 0x9000, 0x6000, 0xC000,
         0x3000, 0x0C00, 0x0300, 0x0C00, 0, 0, 0x8000, 0x1000,
         0x4000, 0x2000, 0, 0, 0, 0x8001, 0, 0)
KEYS = ((0x8000, "y"), (0x1000, "x"), (0x4000, "b"), (0x2000, "a"),
        (0x0400, "zl"), (0x0800, "zr"), (0x0100, "l"), (0x0200, "r"))
KNOWN_MASK = sum(bit for bit, _ in KEYS)
MODES = {1: "press", 2: "release", 3: "mash", 4: "mash", 5: "mash"}
STICK_MODES = {6: "mash:wiggle", 7: "stick:rotate", 8: "stick:y", 9: "stick:x"}
ERRORS = (ValueError, OSError, OverflowError, struct.error, IndexError)


def _ok(p) -> bool:
    return isinstance(p, int) and 0x1000000 <= p < (1 << 40)


def _q(m, a) -> int:
    return struct.unpack("<Q", m.rd(a, 8))[0]


def table_ok(m, base: int) -> bool:
    """The key table is the one this reader was written against (this main build)."""
    try:
        return struct.unpack("<32I", m.rd(base + KEY_TABLE, 128)) == MASKS
    except ERRORS:
        return False


def _button(m, base, b, index):
    raw = m.rd(b, 0xB0)
    if struct.unpack_from("<Q", raw, 0)[0] != base + BTN_VT or raw[BTN_MUTED]:
        return None
    player, kind, mode, priority, key, label = struct.unpack_from("<6I", raw, BTN_PLAYER)
    if player not in (index, 4) or not 0 < key < len(MASKS) or label > 0xFFFF:
        return None
    mask = MASKS[key]
    if mode in STICK_MODES:
        token, chord = STICK_MODES[mode], ()
    elif mode in MODES and mask and not mask & ~KNOWN_MASK:
        chord = tuple(k for bit, k in KEYS if mask & bit)
        token = MODES[mode] + ":" + "+".join(chord)
    else:
        return None
    return {"token": token, "keys": chord, "button": b, "kind": kind, "mode": mode, "priority": priority,
            "key_index": key, "label": label, "owner": struct.unpack_from("<Q", raw, BTN_OWNER)[0],
            "target": struct.unpack_from("<Q", raw, BTN_TARGET)[0], "count": struct.unpack_from("<i", raw, BTN_COUNT)[0]}


def selected_prompt(m, base: int, player_ptr: int, index: int = 0) -> dict | None:
    """The prompt the game shows player `index` now (its display unit up with a live cActionButton), the higher
    priority first; None when nothing is shown or anything reads wrong. Never raises. The token: "press:y",
    "mash:a", "release:b", "mash:wiggle", "stick:rotate" ... ("keys": the Switch keys to press)."""
    try:
        if not _ok(player_ptr) or not 0 <= index < 4:
            return None
        ab = _q(m, base + S_ACTION)
        if not _ok(ab) or _q(m, ab) != base + AB_VT or not m.rd(ab + AB_ENABLED, 1)[0]:
            return None
        mgr = ab + AB_MGR + MGR_STRIDE * index
        if not m.rd(mgr + MGR_ENABLED, 1)[0] or struct.unpack("<i", m.rd(mgr + MGR_INDEX, 4))[0] != index:
            return None
        if struct.unpack("<h", m.rd(player_ptr + 0x1EB8, 2))[0] <= 0:
            return None                                  # a corpse: the dying state keeps 1
        shown = []
        for uo in MGR_UNITS:
            raw = m.rd(mgr + uo, 0x60)
            b = struct.unpack_from("<Q", raw, UNIT_BTN)[0]
            if not raw[UNIT_SHOWN] or not _ok(b):
                continue
            req = _button(m, base, b, index)
            if req is None or struct.unpack_from("<I", raw, UNIT_MODE)[0] != req["mode"]:
                continue
            req["progress"], req["target_count"] = struct.unpack_from("<2f", raw, UNIT_PROGRESS)
            if m.rd(mgr + uo, 0x18) != raw[:0x18]:
                continue                                 # changed under the read: next tick
            shown.append(req)
        if not shown:
            return None
        return max(shown, key=lambda r: r["priority"])
    except ERRORS:
        return None


def available(m, base: int, index: int = 0, limit: int = 256) -> list:
    """Every cActionButton available to player `index` this frame (+0x12 and its player bit), shown or not: the
    hourglasses and ledges in reach. [{label, kind, owner, target, ...}]; [] on any read problem."""
    out = []
    try:
        ab = _q(m, base + S_ACTION)
        if not _ok(ab) or _q(m, ab) != base + AB_VT:
            return out
        n, arr = struct.unpack("<I", m.rd(ab + AB_COUNT, 4))[0], _q(m, ab + AB_ARRAY)
        if not _ok(arr) or not 0 < n <= limit:
            return out
        for b in struct.unpack("<%dQ" % n, m.rd(arr, 8 * n)):
            if not _ok(b):
                continue
            raw = m.rd(b, 0x48)
            if raw[BTN_AVAIL] and struct.unpack_from("<I", raw, BTN_PLAYERS)[0] & (1 << index):
                req = _button(m, base, b, index)
                if req is not None:
                    out.append(req)
    except ERRORS:
        return out
    return out
