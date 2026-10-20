"""Resident Evil 4 (GameCube G4BE08): the game's own action-button prompts, QTEs and area events, read from RAM
(operator 2026-10-20: "Surely when it comes to the dialogue of A needing to be pressed, that there are hex keys or
codes in the RAM that come up that basically tell us this information" ... "Vision analysis to me should be the last
level that we have to fall back to").

    from gbox import re4_ram_prompts as R
    R.prompt_from_ram(mem)       # "a" | "b" | "x" | "y" | "a+b" | "l+r" | "wiggle" | None: what the game asks for now
    R.action_from_ram(mem)       # {"button", "action": "JUMP OVER", "aev": {...} | None, "zones": [...], ...}
    R.source(mem)()              # the same as a prompt source for gbox.re4_merc_bot.play (RAM first, vision after)

Both raise Unknown when RAM can't tell (another game in the drive, a torn read, a button kind the tables below don't
know): the caller asks vision (gbox.screen_prompt) instead. mem is anything with rd(address, n) -> bytes over MEM1
(re4_merc_bot.ShmMem / AdMem).

Where it lives (G4BE08 main.dol, decoded with capstone 2026-10-20). Checked in game on the Spark the same day, read
only beside the screen detector: TAKE, OPEN, JUMP DOWN, KICK, SHAKE OFF, a door opening, Leon's zones and the items;
the rest is static (docs/evidence/re4-ram-prompts/README.md).
  ActMgr 0x80278AE4     the action-button manager. Every frame each source of an action calls register 0x800B207C
                        (mgr, label, priority, callback, data, flags, kind, dispatch, owner): the player's context
                        checks 0x8013D4E8 (PUSH, JUMP DOWN, JUMP OVER x2, JUMP OUT / JUMP IN at windows, CLIMB UP /
                        CLIMB DOWN / HOP DOWN at ladders), the area events 0x8014BE50 (doors OPEN, ladders CLIMB UP /
                        DOWN, items TAKE, typewriters SAVE, ...), objects (doors 0x800DD64C, levers 0x800EC33C), a
                        stunned Ganado (KICK, from its code module: priority 0xB, data = the Ganado), the QTEs (DODGE /
                        JUMP with L+R or A+B) and a grab (SHAKE OFF 0x801413D8). process 0x800B1950 (once a frame) walks
                        the lists from priority 15 down, takes the first node whose check 0x800B1F90 passes (Leon alive
                        and free to act: 0x8013E3D0), draws it (0x800B1AFC), runs its callback when its button is
                        pressed (0x800B1D24) and empties the lists (0x800B18DC).
      +0x00 16 x u32    list heads, priority 0..15 (a node has the top bit set, else it links to the next list)
      +0x40 u8          nodes taken this frame (0 after the reset)
      +0x41 u8          1 = actions are off (pG+0x170 & 0x100)
      +0x42 u8          1 = an action passed its check this frame
      +0x44 8 x 0x18    nodes: +0 next, +4 callback, +8 data (the AEV entry, item or object), +0xC u8 label,
                        +0xD u8 priority, +0xE u8 dispatch (0 call, 1 event, 2 area event), +0xF u8 kind (the button,
                        KINDS), +0x10 owner (em), +0x14 flags (8 = not drawn, 0x80 = drawn in the door colour)
  ACT_KIND 0x80279320   u8: the kind of the prompt drawn this frame, 0 = none (cleared by process, stored by the draw)
  MesMgr 0x80213D74     the message manager, 16 slots of 0xEC from +4. Slot 1 (0x80213E64) is the prompt's label:
      +0x04 u32         bit 0 = on screen, bit 1 = drawn this frame (the manager clears bit 0 when bit 1 stays clear)
      +0x98 u32         the slot's read cursor in the message drawn (entry label + 0x16 of bank 0)
  MesBanks 0x802152E4   +0 language, +4 bank 0 (etc/core.das MDT #6): language block = bank + u32[bank + 4 + 4 x lang],
                        message id i at block + u32[block + 8 + 4 x i]; LABELS = ids 0x16.. (TALK, CHECK, ..., ROTATE)
  AevMgr 0x80289B3C     the area events (the pointer at 0x802B3178 = r13-0x6608): +0 AEV file, +4 its entries,
                        +8 ITA (items) file, +0xC its entries (0x9C bytes each, count = u16 at file+6); +0x10 32-byte
                        bitset: entries whose zone holds an em this frame (word index >> 5, bit 0x80000000 >> (index &
                        31)); +0x30 bitset: entries that fired this frame. Entry: +0x08 floor y, +0x0C height, +0x14 four
                        (x, z) corners, +0x34 bit 0 enabled, +0x35 type (AEV_TYPES), +0x36 index (ITA entries + 0x80),
                        +0x38 trigger (TRIGGERS), +0x39 who (1 Leon, 2 enemies, 8 partner),
                        +0x44 priority, +0x4A label, +0x5C type data (door: destination x y z facing, +0x6C stage,
                        +0x6D room; ladder: stand x y z facing, +0x6C s8 rungs; item: x y z, +0x78 item id).
  pG 0x802B2280 ->      +0x20..0x23 the game's routine bytes (+0x20 = 3 while playing a room; 4: a door's room change
                        is under way, set by the door handler 0x8014CA4C with the destination in +0x28 stage / +0x29
                        room), +0x4FA8 room, +0x4FAC the room before.
  Leon (0x802B3044 ->)  +0xFC..0xFF his routine bytes (+0xFC 0 = under the player's control: 0x8013E3D0 refuses
                        actions unless it is, and while +0xFD is 5, 7, 8, 9, 0xC, 0xE or 0x10; +0xFC 1 = hit or held
                        (01 00 01 00 through a SHAKE OFF grab); +0xFC 4 = working on an object, set by 0x80141794 with
                        the object at +0x3B8 and its routine at ACTION_FN: a door, a kick), +0x518 the grab struggle
                        counter (SHAKE OFF).
"""
from __future__ import annotations

import bisect
import struct

GAME_ID = b"G4BE08"
ACT_MGR, ACT_KIND = 0x80278AE4, 0x80279320
ACT_COUNT, ACT_OFF, ACT_VALID, ACT_NODES, NODE, NODES = 0x40, 0x41, 0x42, 0x44, 0x18, 8
MES_SLOT1, SLOT_FLAGS, SLOT_MSG = 0x80213E64, 0x04, 0x98
MES_BANKS, LABEL_BASE = 0x802152E4, 0x16
AEV_MGR, P_AEV_MGR, AEV_ENTRY = 0x80289B3C, 0x802B3178, 0x9C
P_GLOBAL, P_PLAYER = 0x802B2280, 0x802B3044
G_ROUTINE, G_DEST, G_ROOM, G_ROOM_BEFORE = 0x20, 0x28, 0x4FA8, 0x4FAC
PL_ROUTINE, PL_STRUGGLE, PL_ACTION_OBJ, EM_ID = 0xFC, 0x518, 0x3B8, 0x100
ROOM_JUMP = 4                                    # pG+0x20 while a door takes Leon to another room
# an object action (a door, a kick): 0x80141794 sets Leon's routine to 4 0 0 0, the object at +0x3B8 and the routine
# it runs at ACTION_FN; the door object's OPEN callbacks (0x800DD8C4 / 0x800DD964) pick one of DOOR_ROUTINES.
# A door is em id (+0x100) 0x41 (the Village has six: EmMgr slots 2-4, 7, 22, 23, live 2026-10-20)
PL_OBJECT_ACTION, ACTION_FN, EM_DOOR = 4, 0x801F4C14, 0x41
DOOR_ROUTINES = (0x800DDA0C, 0x800DDDC8)

# The game's pad (0x80288830: +0x10 / +0x14 held, +0x18 / +0x1C pressed this frame, 64 bits) is built every frame by
# 0x80135250 from the GameCube pad through the control type's table 0x80207380 (type 0, the default: one raw mask per
# logical bit). The low word's bits (PAD_BITS):
PAD_BITS = {0x1: "up", 0x2: "down", 0x4: "right", 0x8: "left", 0x10: "R", 0x20: "L", 0x40: "B", 0x80: "A", 0x200: "X",
            0x400: "A", 0x800: "L", 0x1000: "START", 0x2000: "START", 0x4000: "C", 0x8000: "C", 0x10000: "Y",
            0x20000: "X", 0x40000: "B", 0x80000: "A", 0x100000: "Y", 0x200000: "Z", 0x400000: "L", 0x800000: "R",
            0x1000000: "up", 0x2000000: "down", 0x4000000: "right", 0x8000000: "left", 0x10000000: "Z",
            0x20000000: "START", 0x40000000: "B", 0x80000000: "A"}
# the button kind (node +0xF) -> what to press: the press check 0x800B1D24 tests 0x80000 (A) for kinds 1 / 2 / 0xE,
# 0x40000 (B) for 5, 0x20000 (X) for 6, 0x10000 (Y) for 7, 0xC0000 (A and B) for 4, 0xC00000 (L and R) for 3: the
# QTEs (both pressed this frame, or one held and the other pressed). Kind 0xB (SHAKE OFF, a Ganado's grab) is no
# button: 0x8014141C adds one to Leon +0x518 for every new stick direction (bits 0xF / 0x0C000000) and every new A or B
# (0xC0000000). Kinds 9 / 0xA (story QTEs in the stage RELs) are pressed by their own code: Unknown here.
KINDS = {1: "a", 2: "a", 0xE: "a", 3: "l+r", 4: "a+b", 5: "b", 6: "x", 7: "y", 0xB: "wiggle"}
# a button string -> the gBox pad keys to press: chords (keys pressed together), one after the other
KEYS = {"a": [("a",)], "b": [("b",)], "x": [("x",)], "y": [("y",)], "a+b": [("a", "b")], "l+r": [("l", "r")],
        "wiggle": [("left", "a"), ("right", "b")] * 3}

# label (node +0xC, AEV +0x4A) -> the text the game draws: message bank 0 (etc/core.das MDT #6, English) ids 0x16..
LABELS = {
    0x00: "TALK", 0x01: "CHECK", 0x02: "JUMP OUT", 0x03: "JUMP IN", 0x04: "JUMP DOWN", 0x05: "JUMP OVER",
    0x06: "PUSH", 0x07: "KICK", 0x08: "CLIMB UP", 0x09: "CLIMB DOWN", 0x0A: "KNOCK DOWN", 0x0B: "RAISE UP",
    0x0C: "JUMP", 0x0D: "LOOK", 0x0E: "LOOK DOWN", 0x0F: "BACK TO THE WALL", 0x10: "OPEN", 0x11: "SWIM",
    0x12: "JUMP OVER", 0x13: "CROUCH", 0x14: "OPERATE", 0x15: "HELP", 0x16: "PIGGYBACK", 0x17: "THROW",
    0x18: "SPRINT", 0x19: "CLIMB", 0x1A: "JUMP", 0x1B: "SLIDE DOWN", 0x1C: "CATCH", 0x1D: "PULL UP", 0x1E: "WAIT",
    0x1F: "STAND BACK", 0x20: "HIDE", 0x21: "FOLLOW ME", 0x22: "GIVE ME A HAND", 0x23: "GET ON", 0x24: "GET OFF",
    0x25: "DODGE", 0x26: "HIDE", 0x27: "CRAWL", 0x28: "TAKE", 0x29: "CUT", 0x2A: "ROTATE", 0x2B: "SHAKE OFF",
    0x2C: "SUPLEX", 0x2E: "BEGIN", 0x2F: "SAVE", 0x31: "ACCELERATE", 0x32: "ACCELERATE", 0x33: "SEND ASHLEY",
    0x35: "KNOCK OVER", 0x36: "RESPOND", 0x37: "INFILTRATE", 0x38: "FAN KICK", 0x39: "BACK KICK", 0x3A: "KNEE",
    0x3B: "NECK BREAKER", 0x3C: "THRUST PUNCH", 0x3D: "CHIKYO CHAGI", 0x3E: "JUMP", 0x3F: "RING", 0x40: "HOP DOWN",
    0x41: "FIRE", 0x42: "ROTATE",
}
# AEV trigger bits (+0x38), as the check 0x8014BE50 uses them: 1 fires while an em is inside, 2 / 4 when Leon presses /
# holds A inside (pG+0x5018 0x40000000 / 0x20000000, set by 0x8013E240), 8 registers an action prompt (label +0x4A),
# 0x80 turns the entry off once it fired
TRIGGERS = {1: "inside", 2: "A pressed", 4: "A held", 8: "prompt", 0x80: "once"}
# AEV type (+0x35) -> what it is (the handler table 0x8020CAD4 and the set-up 0x8014F420 that labels them)
AEV_TYPES = {1: "door", 3: "item", 4: "area", 5: "check", 8: "typewriter", 0xE: "crouch", 0x10: "ladder",
             0x12: "hide"}


class Unknown(Exception):
    """RAM can't tell what the prompt is (another game, a torn read, an unknown kind): fall back to vision."""


def _u32(b: bytes, o: int = 0) -> int:
    return struct.unpack_from(">I", b, o)[0]


def _ptr(p: int) -> bool:
    return 0x80000000 <= p < 0x81800000


_LABEL_CACHE: dict = {}


def _message_starts(mem) -> list:
    """[(address, message id)] of message bank 0 in the game's language, by address (read once per bank and
    language)."""
    lang, bank = struct.unpack(">II", mem.rd(MES_BANKS, 8))
    key = (lang, bank)
    if key in _LABEL_CACHE:
        return _LABEL_CACHE[key]
    if not _ptr(bank) or lang > 8:
        raise Unknown(f"message bank 0 at {bank:#x}, language {lang}")
    block = bank + _u32(mem.rd(bank + 4 + 4 * lang, 4))
    count = _u32(mem.rd(block + 4, 4))
    if not _ptr(block) or not 0 < count < 0x400:
        raise Unknown(f"message block {block:#x} with {count} messages")
    offs = struct.unpack(f">{count}I", mem.rd(block + 8, 4 * count))
    table = sorted((block + o, i) for i, o in enumerate(offs))
    _LABEL_CACHE.clear()
    _LABEL_CACHE[key] = table
    return table


def label_of(mem, msg: int) -> int | None:
    """The label slot 1's message pointer belongs to. The pointer is the slot's read cursor (live 2026-10-20: it sat
    0xC bytes into TAKE after the label was drawn), so the message is the last one starting at or before it."""
    starts = _message_starts(mem)
    k = bisect.bisect_right(starts, (msg, 0x7FFFFFFF)) - 1
    if k < 0 or msg - starts[k][0] > 0x100:
        return None
    i = starts[k][1]
    return i - LABEL_BASE if i >= LABEL_BASE else None


def _nodes(act: bytes) -> list[dict]:
    out = []
    for i in range(NODES):
        o = ACT_NODES + i * NODE
        nxt, cb, data, label, prio, dispatch, kind, owner, flags = struct.unpack_from(">3I4B2I", act, o)
        out.append({"i": i, "label": label, "priority": prio, "dispatch": dispatch, "kind": kind, "data": data,
                    "callback": cb, "owner": owner, "flags": flags})
    return out


def aev_entries(mem) -> list[dict]:
    """The room's area events and items as the game holds them now: the AEV / ITA tables (AevMgr +4 / +0xC) and the
    ones made at run time (an enemy's dropped item: 0x80151544) - every entry linked into the 16 priority lists
    (AevMgr +0x50; the walk of 0x8014BB14: +0 links an entry to the next, a link without the top bit is the next list)."""
    p = _u32(mem.rd(P_AEV_MGR, 4))
    if not _ptr(p):
        return []
    out, seen, link = [], set(), _u32(mem.rd(p + 0x8C, 4))
    while link != 0xFFFFFFFF and len(seen) < 512:
        if not link & 0x80000000:                    # the next priority list's head
            link = _u32(mem.rd(link | 0x80000000, 4))
            continue
        if link in seen or not _ptr(link):
            break
        seen.add(link)
        e = mem.rd(link, AEV_ENTRY)
        out.append(_aev(e, link))
        link = _u32(e)
    return out


def _aev(e: bytes, addr: int) -> dict:
    typ, label = e[0x35], e[0x4A]
    d = {"addr": addr, "index": e[0x36], "type": typ, "kind": AEV_TYPES.get(typ, f"type {typ:#x}"),
         "enabled": bool(e[0x34] & 1), "trigger": [n for bit, n in TRIGGERS.items() if e[0x38] & bit],
         "who": e[0x39], "label": label if e[0x38] & 8 else None,
         "action": LABELS.get(label) if e[0x38] & 8 else None,
         "y": [round(v, 1) for v in struct.unpack_from(">2f", e, 0x08)],
         "poly": [[round(v, 1) for v in struct.unpack_from(">2f", e, 0x14 + 8 * k)] for k in range(4)]}
    if typ == 1:
        d["to"] = {"pos": [round(v, 1) for v in struct.unpack_from(">3f", e, 0x5C)], "room": e[0x6C] << 8 | e[0x6D]}
    elif typ == 0x10:
        d["stand"] = [round(v, 1) for v in struct.unpack_from(">3f", e, 0x5C)]
        d["rungs"] = struct.unpack_from(">b", e, 0x6C)[0]
    elif typ == 3:
        d["pos"] = [round(v, 1) for v in struct.unpack_from(">3f", e, 0x5C)]
        d["item_id"] = struct.unpack_from(">H", e, 0x78)[0]
    return d


def zones(mem, entries: list[dict] | None = None) -> list[dict]:
    """The area events whose zone holds Leon now (AevMgr +0x10, the zones the game found an em in this frame,
    kept to the ones Leon can trigger: who & 1)."""
    p = _u32(mem.rd(P_AEV_MGR, 4))
    if not _ptr(p):
        return []
    bits = mem.rd(p + 0x10, 0x20)
    inside = {w * 32 + b for w in range(8) for b in range(32) if _u32(bits, 4 * w) & (0x80000000 >> b)}
    if not inside:
        return []
    entries = aev_entries(mem) if entries is None else entries
    return [e for e in entries if e["index"] in inside and e["who"] & 1]


def items_from_ram(mem, entries: list[dict] | None = None) -> list[dict]:
    """The room's item entries (ITA: the Mercenaries' hourglasses 0x73 / 0x75 and the pickups) with "enabled": still
    there to TAKE (the item-get clears +0x34 bit 0 through 0x8014FC40)."""
    entries = aev_entries(mem) if entries is None else entries
    return [e for e in entries if e["type"] == 3]


def leon_from_ram(mem) -> dict | None:
    """Leon's routine bytes (+0xFC..0xFF, hex) and, while he works on something (routine 4: a door, a kick -
    0x80141794), "object" (the em), "object_em" (its em id +0x100: 0x41 door, a Ganado's for a kick) and "fn" (the
    routine it runs, ACTION_FN: 0x800DDA0C / 0x800DDDC8 for a door, the Ganado code module's for a kick)."""
    pl = _u32(mem.rd(P_PLAYER, 4))
    if not _ptr(pl):
        return None
    r = mem.rd(pl + PL_ROUTINE, 4)
    out = {"routine": r.hex()}
    if r[0] == PL_OBJECT_ACTION:
        obj = _u32(mem.rd(pl + PL_ACTION_OBJ, 4))
        out.update(object=obj, object_em=mem.rd(obj + EM_ID, 1)[0] if _ptr(obj) else None,
                   fn=_u32(mem.rd(ACTION_FN, 4)))
    return out


def door_from_ram(mem, leon: dict | None = None) -> dict | None:
    """A door opening: {"kind": "room change", "to_room", "from_room", "room"} while an area-event door takes Leon to
    another room (pG+0x20 = 4), {"kind": "door", "object", "routine"} while Leon opens a door object (his routine 4 on
    an em id 0x41 with one of DOOR_ROUTINES); None otherwise."""
    pg = _u32(mem.rd(P_GLOBAL, 4))
    if _ptr(pg):
        r = mem.rd(pg + G_ROUTINE, 0x10)
        if r[0] == ROOM_JUMP:
            room, before = struct.unpack(">HxxH", mem.rd(pg + G_ROOM, 6))
            return {"kind": "room change", "to_room": r[G_DEST - G_ROUTINE] << 8 | r[G_DEST - G_ROUTINE + 1],
                    "from_room": before, "room": room}
    leon = leon_from_ram(mem) if leon is None else leon
    if leon and leon.get("fn") in DOOR_ROUTINES and leon.get("object_em") == EM_DOOR:
        return {"kind": "door", "object": leon["object"], "routine": leon["fn"]}
    return None


def action_from_ram(mem, with_zones: bool = True) -> dict:
    """What the game asks for now: {"button", "action", "label", "kind", "valid", "aev", "zones", "node", "leon",
    "door", "game_routine"}. button / action are None when no prompt is up; aev is the area event behind the prompt
    (a door, a ladder, an item) or None; zones are the area events Leon stands in (with_zones); leon is
    leon_from_ram(), door door_from_ram()."""
    if mem.rd(0x80000000, 6) != GAME_ID:
        raise Unknown("not Resident Evil 4 (G4BE08)")
    kind = mem.rd(ACT_KIND, 1)[0]
    act = mem.rd(ACT_MGR, ACT_NODES + NODE * NODES)
    slot = mem.rd(MES_SLOT1, SLOT_MSG + 4)
    shown = bool(_u32(slot, SLOT_FLAGS) & 1)
    label = label_of(mem, _u32(slot, SLOT_MSG)) if shown else None
    nodes = _nodes(act)
    node = None
    if kind:
        node = next((n for n in nodes if n["kind"] == kind and (label is None or n["label"] == label)), None)
        if label is None and node is not None:
            label = node["label"]                    # the label slot was torn or drawn elsewhere: the node's
    button = KINDS.get(kind) if kind else None
    if kind and button is None:
        raise Unknown(f"button kind {kind:#x} ({LABELS.get(label, label)})")
    out = {"button": button, "kind": kind, "label": label if kind else None,
           "action": LABELS.get(label, f"label {label:#x}" if label is not None else None) if kind else None,
           "valid": bool(act[ACT_VALID]), "off": bool(act[ACT_OFF]), "node": node, "aev": None}
    entries = None
    if node is not None and node["dispatch"] == 2 and _ptr(node["data"]):
        out["aev"] = _aev(mem.rd(node["data"], AEV_ENTRY), node["data"])
    if with_zones:
        entries = aev_entries(mem)
        out["zones"] = [{k: z[k] for k in ("index", "type", "kind", "trigger", "action")} for z in zones(mem, entries)]
    pg = _u32(mem.rd(P_GLOBAL, 4))
    out["game_routine"] = mem.rd(pg + G_ROUTINE, 4).hex() if _ptr(pg) else None
    out["leon"] = leon_from_ram(mem)
    out["door"] = door_from_ram(mem, out["leon"])
    return out


def prompt_from_ram(mem) -> str | None:
    """The button(s) to press now: "a", "b", "x", "y", "a+b", "l+r", "wiggle" (SHAKE OFF: the stick) or None (no prompt
    up). Raises Unknown when RAM can't tell. Two small reads while no prompt is up (a playbook asks every tick)."""
    if mem.rd(0x80000000, 6) != GAME_ID:
        raise Unknown("not Resident Evil 4 (G4BE08)")
    kind = mem.rd(ACT_KIND, 1)[0]
    if not kind:
        return None
    if kind not in KINDS:
        raise Unknown(f"button kind {kind:#x}")
    return KINDS[kind]


def source(mem, stats: dict | None = None):
    """A prompt source for a playbook: () -> button | None, Unknown when RAM can't tell (stats["ram_action"] = the last
    prompt's text)."""
    def ask():
        try:
            button = prompt_from_ram(mem)
            if button and stats is not None:
                stats["ram_action"] = action_from_ram(mem, with_zones=False)["action"]
        except Unknown:
            raise
        except Exception as e:                       # noqa: BLE001 - a read that failed: vision decides
            raise Unknown(f"{type(e).__name__}: {e}") from e
        return button
    return ask


def for_adapter(ad, stats: dict | None = None):
    """source() on the session's memory (Dolphin's shared RAM view on Linux, else the adapter's read_memory)."""
    from .re4_merc_bot import memory
    return source(memory(ad), stats)


def main(argv=None) -> int:
    """python -m gbox.re4_ram_prompts [seconds]: print every change of the prompt and Leon's zones (Dolphin on Linux)."""
    import json
    import sys
    import time
    from .re4_merc_bot import ShmMem
    secs = float((argv if argv is not None else sys.argv[1:] or ["60"])[0])
    mem, last, t0 = ShmMem(), None, time.time()
    while time.time() - t0 < secs:
        try:
            a = action_from_ram(mem)
        except Unknown as e:
            a = {"unknown": str(e)}
        key = json.dumps({k: a.get(k) for k in ("button", "action", "zones", "door", "unknown")}, sort_keys=True)
        if key != last:
            print(f"{time.time() - t0:7.2f}", key, flush=True)
            last = key
        time.sleep(0.05)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
