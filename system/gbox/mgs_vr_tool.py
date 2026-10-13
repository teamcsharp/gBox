"""`mgs_vr`: Metal Gear Solid: VR Missions (PS1, USA SLUS-00957) live mission tool.

ops: status | complete | unlock_all | stages

Everything here was read from the owned US disc (Redump "Metal Gear Solid - VR Missions (USA)", boot SLUS_009.57,
MGS/STAGE.DIR 72,593,408 bytes) with capstone and checked against pcsx_rearmed save states of a real run (in-mission
Level 03 -> its "LEVEL 03 CLEARED" result screen).  docs/mgs_vr_decomp.md has the full map and the evidence.

How a VR mission ends (stage overlay, e.g. vr_sud03.stg 24428.bin, loaded at 0x800C4350 for every stage):
  * Each mission stage runs one mission-manager actor, created by the overlay's GCL actor table, whose source file
    name string is "vr.c" (GV_NewActor level 5, 0x11C bytes; actor +0x14 = &"vr.c", +0x08 act, +0x0C die).
  * A word in the overlay's BSS holds the mission state (0x800E2BB0 in vr_sud03): 1 running, 2 cleared, 5 over
    (time up / caught / failed).  The manager tests the goal every frame: player position GM_PlayerPosition
    (0x800AC820, SVECTOR) within +-500 x/z of its goal point (actor +0x24) -> its clear routine.
  * The clear routine (0x800D87A8 in vr_sud03) is also what the stage script's "clear" message runs:
        state = 2;  GM_GameStatus (0x800AC1E4) |= 0x10000000;  if (actor[+0x10B] == 0) actor[+0x10B] = 1;
    +0x10B is the step counter of the clear sequence (0x800D9384: 8 steps through a jump table), which plays the
    clear jingle, freezes the run and loads the result screen ("LEVEL %s  CLEARED", vrclear.c).  The result actor
    then records the clear (clearflags[stage][area] in the VRAM block at x=160 y=224 12x16 and the record table).
  * op=complete performs exactly that clear routine on the live manager: nothing the game would not do itself,
    so the result screen, the record and the unlocks follow from the game's own code.
Overlay addresses differ per stage (each stage ships its own build), so the state word and the step offset are read
from the live overlay by matching the clear routine's instructions (find_clear_handler), never hard-coded.

PS1 RAM is reached as RetroArch/pcsx_rearmed exposes it: main RAM at offset 0 (address & 0x1FFFFF, as ac_mods_tool).
"""
from __future__ import annotations

import re
import struct
import time

from pydantic import BaseModel

from .models import Permission as P
from .registry import tool

GAME_IDS = {"afd2fc507bb69843", "f55555ee6513391b"}
SERIAL = "SLUS-00957"

# ---------------------------------------------------------------------------------------------- executable (fixed)
OVERLAY_BASE = 0x800C4350        # every STAGE.DIR stage overlay (*.bin, entry 0 of the .stg) loads here unrelocated
STAGE_NAME = 0x800B5B98          # current stage name, 8 chars ("vr_sud03"); the save loader copies it from the save body
GAME_STATUS = 0x800AC1E4         # GM_GameStatus bit word; bit 0x10000000 = mission ended (clear or over)
CLEAR_BIT = 0x10000000
PLAYER_POS = 0x800AC820          # GM_PlayerPosition SVECTOR (x, y, z) the goal test reads
ACTOR_LEVELS = 0x800ADA28        # GV actor system: 9 levels x 0x44 bytes, each a head sentinel; node +4 = next
ACTOR_LEVEL_SIZE = 0x44
ACTOR_LEVEL_COUNT = 9
MANAGER_NAME = b"vr.c\0"
MANAGER_LEVEL = 5
GAME_STATE = 0x800B5BA8          # GCL game-state shorts (0xC0 bytes; copy at 0x800B52D8), saved to the memory card
RECORDS = 0x800B5398             # GCL variable block (0x800 bytes; copy at 0x800B4AD8): per-mission records, s16
SAVE_BODY = 0xA38                # memory-card save body: version 0x60, ..., stage name, state, vars, 0x140 tail

STATES = {0: "not started", 1: "running", 2: "cleared", 4: "result (clear sequence done)", 5: "over"}

# Stage families on the disc (STAGE.DIR names).  Display names come from the overlay's own mode strings; the
# family -> mode mapping is read from the file names and the result-screen strings (docs/mgs_vr_decomp.md).
FAMILIES = {
    "vr_sud": "Sneaking mode (15 levels; No Weapon / SOCOM share these maps)",
    "vr_scm": "Weapon mode: SOCOM", "vr_fms": "Weapon mode: FA-MAS", "vr_grn": "Weapon mode: Grenade",
    "vr_nkt": "Weapon mode: Nikita", "vr_psg": "Weapon mode: PSG-1", "vr_stg": "Weapon mode: Stinger",
    "vr_cfr": "Weapon mode: C4", "vr_clm": "Weapon mode: Claymore",
    "vab_": "Advanced mode", "vcd_n": "Mystery / variety (vcd)", "vefgh_": "Variety (vefgh)",
    "vijkl_": "Puzzle / variety (vijkl)", "photo_": "Photograph mode",
    "vrtitle": "title", "selectvr": "mission select menu", "select": "menu", "vrsave": "save screen",
    "opening": "opening", "option": "options", "camera": "camera", "movie": "movie",
}


def family(stage: str) -> str:
    for k in sorted(FAMILIES, key=len, reverse=True):
        if stage.startswith(k):
            return FAMILIES[k]
    return "unknown"


def is_mission(stage: str) -> bool:
    return bool(re.match(r"^(vr_[a-z]{3}\d\d|vab_[a-z]{3}|vcd_n\d\d|vefgh_\d\d|vijkl_\d\d|photo_[mn]\d)$", stage))


# ---------------------------------------------------------------------------------------------- disc (offline)
def stage_dir(data: bytes) -> dict[str, int]:
    """MGS/STAGE.DIR: u32 header size, then {char name[8], u32 sector} per stage -> {name: byte offset}."""
    size = struct.unpack_from("<I", data, 0)[0]
    out = {}
    for o in range(4, size, 12):
        name = data[o:o + 8].split(b"\0")[0].decode("latin-1")
        if name:
            out[name] = struct.unpack_from("<I", data, o + 8)[0] * 2048
    return out


def stg_entry(data: bytes, off: int, index: int) -> tuple[str, bytes]:
    """Entry *index* of the .stg at *off*: header u8 1, u8 0, u16 sectors, then 8-byte entries {u16 hash, u8 mode,
    u8 ext, u32 size}; the leading non-cached entries are stored in order from +0x800, each sector aligned
    (init.stg: 0 = model DAR 0_0.dar, 1 = texture DAR 1_0.dar; a mission stage: 0 = code overlay .bin)."""
    pos = off + 0x800
    for i in range(index + 1):
        _hash, mode, ext, size = struct.unpack_from("<HBBI", data, off + 4 + 8 * i)
        if chr(mode) == "c":
            raise ValueError(f"entry {i} is cached; only the leading streamed entries are addressable here")
        if i == index:
            return chr(ext), data[pos:pos + size]
        pos += (size + 2047) // 2048 * 2048
    raise IndexError(index)


def stage_overlay(data: bytes, name: str) -> bytes:
    """A stage's code overlay: entry 0 of its .stg when that is a 'b' (.bin) file."""
    ext, body = stg_entry(data, stage_dir(data)[name], 0)
    return body if ext == "b" else b""


# ---------------------------------------------------------------------------------------------- memory
class Mem:
    """PS1 main RAM through a session adapter (RetroArch READ/WRITE_CORE_MEMORY with offsets 0..0x1FFFFF)."""

    def __init__(self, ad):
        self.ad, self.log = ad, []

    def rd(self, a: int, n: int) -> bytes:
        return bytes(self.ad.read_memory(a & 0x1FFFFF, n))

    def u8(self, a):
        return self.rd(a, 1)[0]

    def u32(self, a):
        return struct.unpack("<I", self.rd(a, 4))[0]

    def wr(self, a: int, data: bytes):
        before = self.rd(a, len(data))
        if before != data:
            self.ad.write_memory(a & 0x1FFFFF, data)
        self.log.append({"addr": f"{a:#x}", "before": before.hex(), "after": data.hex()})


def in_ram(p: int) -> bool:
    return 0x80000000 <= p < 0x80200000


def stage_name(mem: Mem) -> str:
    return mem.rd(STAGE_NAME, 8).split(b"\0")[0].decode("latin-1")


# ---------------------------------------------------------------------------------------------- code signature
def _w(code: bytes, i: int) -> int:
    return struct.unpack_from("<I", code, i)[0]


def _s16(v: int) -> int:
    return v - 0x10000 if v & 0x8000 else v


def find_clear_handler(code: bytes, base: int) -> list[dict]:
    """Locate the manager's clear routine in overlay *code* loaded at *base*.

    Matches (registers as the compiler emits them in every mission overlay on the disc):
        lui   rS, HI              ; state word high half
        addiu rV, $zero, 2        ; state = 2 (cleared)
        lui   rG, 0x800B
        sw    rV, LO(rS)          ; state word = HI<<16 + LO
        lw    rT, -0x3E1C(rG)     ; GM_GameStatus
        lui   rU, 0x1000
        or    rT, rT, rU
        sw    rT, -0x3E1C(rG)
        lbu   rX, STEP(rA)        ; clear-sequence step byte of the manager actor
    Returns [{handler, state, step, status}] (one per match; a valid overlay has exactly one).
    """
    out = []
    for i in range(16, len(code) - 20, 4):
        w = _w(code, i)
        if w >> 26 != 0x23 or (w & 0xFFFF) != 0xC1E4:                     # lw rT, -0x3E1C(rG)
            continue
        rg, rt = (w >> 21) & 31, (w >> 16) & 31
        lui_u, orr, sw2, lbu = (_w(code, i + 4 * k) for k in (1, 2, 3, 4))
        ru = (lui_u >> 16) & 31
        if lui_u >> 26 != 0x0F or (lui_u & 0xFFFF) != 0x1000:
            continue
        if orr & 0xFC0007FF != 0x25 or {(orr >> 21) & 31, (orr >> 16) & 31} != {rt, ru} or (orr >> 11) & 31 != rt:
            continue
        if sw2 != (0x2B << 26 | rg << 21 | rt << 16 | 0xC1E4) or lbu >> 26 != 0x24:
            continue
        sw1, lui_g, addiu, lui_s = (_w(code, i - 4 * k) for k in (1, 2, 3, 4))
        rs, rv = (sw1 >> 21) & 31, (sw1 >> 16) & 31
        if sw1 >> 26 != 0x2B or lui_g != (0x0F << 26 | rg << 16 | 0x800B):
            continue
        if addiu != (0x09 << 26 | rv << 16 | 2) or lui_s >> 26 != 0x0F or (lui_s >> 16) & 31 != rs:
            continue
        state = ((lui_s & 0xFFFF) << 16) + _s16(sw1 & 0xFFFF)
        # the routine starts one instruction earlier ("move a1, a0") when the compiler keeps the actor in a1
        out.append({"handler": base + i - 20, "state": state & 0xFFFFFFFF, "step": lbu & 0xFFFF,
                    "status": (0x800B << 16) + _s16(0xC1E4)})
    return out


# ---------------------------------------------------------------------------------------------- actors
def walk_actors(mem: Mem, levels=range(ACTOR_LEVEL_COUNT), limit: int = 400):
    """Yield (level, actor address, 0x20-byte header) for every live GV actor."""
    for lv in levels:
        node = mem.u32(ACTOR_LEVELS + lv * ACTOR_LEVEL_SIZE + 4)
        seen = 0
        while in_ram(node) and seen < limit:
            head = mem.rd(node, 0x20)
            if struct.unpack_from("<I", head, 8)[0]:                       # the tail sentinel has no act function
                yield lv, node, head
            node = struct.unpack_from("<I", head, 4)[0]
            seen += 1


def find_manager(mem: Mem) -> dict | None:
    """The live mission manager (the actor whose source file name is "vr.c")."""
    order = [MANAGER_LEVEL] + [x for x in range(ACTOR_LEVEL_COUNT) if x != MANAGER_LEVEL]
    for lv, node, head in walk_actors(mem, order):
        act, die, _free, fname = struct.unpack_from("<4I", head, 8)
        if in_ram(fname) and fname >= OVERLAY_BASE and mem.rd(fname, len(MANAGER_NAME)) == MANAGER_NAME:
            return {"actor": node, "level": lv, "act": act, "die": die}
    return None


def manager_layout(mem: Mem, mgr: dict) -> dict:
    """Read the overlay around the manager's act function and find its clear routine."""
    lo = max(OVERLAY_BASE, mgr["act"] - 0x3000)
    code = mem.rd(lo, 0x4000)
    hits = find_clear_handler(code, lo)
    if len(hits) != 1:
        raise RuntimeError(f"the clear routine of this stage's overlay was not found uniquely ({len(hits)} matches)")
    return hits[0]


def read_manager(mem: Mem, mgr: dict, lay: dict) -> dict:
    a = mgr["actor"]
    raw = mem.rd(a, 0x11C)
    state = mem.u32(lay["state"])
    gx, gy, gz = struct.unpack_from("<3h", raw, 0x24)
    px, py, pz = struct.unpack("<3h", mem.rd(PLAYER_POS, 6))
    return {"state": state, "state_name": STATES.get(state, f"unknown {state}"), "clear_step": raw[lay["step"]],
            "goal": [gx, gy, gz], "player": [px, py, pz],
            "at_goal": abs(px - gx) <= 500 and abs(pz - gz) <= 500,
            "actor": f"{a:#x}", "state_address": f"{lay['state']:#x}", "clear_routine": f"{lay['handler']:#x}"}


# ---------------------------------------------------------------------------------------------- records
def records(mem: Mem) -> dict:
    """The record table (GCL variables): negative = the stock record of an uncleared slot, positive = the player's."""
    raw = mem.rd(RECORDS, 0x800)
    vals = struct.unpack("<1024h", raw)
    slots = vals[11:0x44A // 2]
    return {"slots": len(slots), "player_records": sum(1 for v in slots if v > 0),
            "stock_records": sum(1 for v in slots if v < 0)}


# ---------------------------------------------------------------------------------------------- pick (pick whip)
# The renderer's view matrix: 0x8001F1C4 loads it into the GTE (ctc2 to rotation 0-4 and translation 5-7) right before
# RTPS; s16 m[3][3] (4096 = 1.0), pad, s32 t[3] at +0x14.  Checked on four pcsx_rearmed save states (vr_sud01/03/05,
# side and top-down cameras): a root at world P lands on the 320x240 picture at (0.5 + v.x/v.z, 0.5 + v.y/v.z) of
# its width / height, v = m P + t (state 25: Snake 0.83 across, the soldier 0.40; state 62: the two near soldiers
# at 0.35 / 0.65, 0.11 down, Snake 0.50 / 0.61 under the pause menu).
VIEW_MATRIX = 0x800B280C
ACTOR_POS = 0x20                 # GV actor + 0x20: CONTROL.mov, the model root (hip) in world units (SVECTOR)
FIGURE_UP, FIGURE_DOWN = 570, 1150   # a 16-object figure's top above / soles below its root (Snake: +566 / -1154)
FIGURE_HALF_WIDTH = 260
ACTOR_SLOTS = {"../snake_vr/sna_init.c": ("player", "Snake"), "watcher.c": ("enemy:soldier", "soldier")}


def view_matrix(mem: Mem):
    m = struct.unpack("<9h", mem.rd(VIEW_MATRIX, 18))
    t = struct.unpack("<3i", mem.rd(VIEW_MATRIX + 0x14, 12))
    return [m[0:3], m[3:6], m[6:9]], t


def project(view, p) -> tuple[float, float, float] | None:
    """World point -> (fraction across, fraction down, depth) of the 4:3 picture; None behind the camera."""
    m, t = view
    v = [sum(m[r][c] * p[c] for c in range(3)) / 4096 + t[r] for r in range(3)]
    if v[2] <= 16:
        return None
    return 0.5 + v[0] / v[2], 0.5 + v[1] / v[2], v[2]


def figures(mem: Mem) -> list[dict]:
    """The player and soldier actors with their world root and picture box (top, root, soles)."""
    view = view_matrix(mem)
    out = []
    for _lv, node, head in walk_actors(mem):
        fname = struct.unpack_from("<I", head, 0x14)[0]
        if not in_ram(fname):
            continue
        name = mem.rd(fname, 32).split(b"\0")[0].decode("latin-1", "replace")
        if name not in ACTOR_SLOTS:
            continue
        pos = struct.unpack("<3h", mem.rd(node + ACTOR_POS, 6))
        slot, label = ACTOR_SLOTS[name]
        root = project(view, pos)
        top = project(view, (pos[0], pos[1] + FIGURE_UP, pos[2]))
        sole = project(view, (pos[0], pos[1] - FIGURE_DOWN, pos[2]))
        out.append({"name": label, "slot": slot, "actor": f"{node:#x}", "source": name, "pos": list(pos),
                    "screen": [round(root[0], 3), round(root[1], 3)] if root else None,
                    "top": [round(top[0], 3), round(top[1], 3)] if top else None,
                    "sole": [round(sole[0], 3), round(sole[1], 3)] if sole else None,
                    "depth": round(root[2]) if root else None})
    return out


def picture_xy(x: float, y: float, window_aspect: float = 4 / 3) -> tuple[float, float]:
    """A click in the game window -> the 4:3 picture centred in it (letterbox / pillarbox)."""
    if window_aspect > 4 / 3:
        w = (4 / 3) / window_aspect
        x = (x - (1 - w) / 2) / w
    elif window_aspect < 4 / 3:
        h = window_aspect / (4 / 3)
        y = (y - (1 - h) / 2) / h
    return x, y


def _miss(f: dict, x: float, y: float) -> float | None:
    """Distance (picture pixels, 320x240) from the click to the figure's top-sole segment minus its half width."""
    if not f["top"] or not f["sole"]:
        return None
    ax, ay, bx, by = f["top"][0] * 320, f["top"][1] * 240, f["sole"][0] * 320, f["sole"][1] * 240
    px, py = x * 320, y * 240
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / max(dx * dx + dy * dy, 1e-9)))
    d = ((ax + t * dx - px) ** 2 + (ay + t * dy - py) ** 2) ** 0.5
    half = FIGURE_HALF_WIDTH / max(f["depth"] or 1, 1) * 320
    return max(0.0, d - half)


def pick(mem: Mem, x: float, y: float, window_aspect: float = 4 / 3) -> dict:
    """What is under the click: the nearest player / soldier figure within 12 picture pixels of its box."""
    stage = stage_name(mem)
    cx, cy = picture_xy(x, y, window_aspect)
    rows = []
    for f in figures(mem):
        miss = _miss(f, cx, cy)
        if miss is not None:
            rows.append(f | {"miss": round(miss, 1)})
    rows.sort(key=lambda f: (f["miss"], f["depth"] or 0))
    hit = rows[0] if rows and rows[0]["miss"] <= 12 else None
    return {"stage": stage, "click": [round(cx, 3), round(cy, 3)], "picked": hit, "actors": rows,
            "note": None if hit else "no Snake or soldier drawn at that point" if rows else
            "no Snake or soldier actor is running (menu, loading or result screen)"}


# ---------------------------------------------------------------------------------------------- engine
OPS = ("status", "complete", "unlock_all", "stages", "pick")
OP_ALIASES = {"state": "status", "mission_status": "status", "info": "status", "show": "status",
              "complete_mission": "complete", "clear": "complete", "finish": "complete", "win": "complete",
              "mark_complete": "complete", "pass": "complete", "unlock": "unlock_all", "unlockall": "unlock_all",
              "list": "stages", "missions": "stages"}


def status(mem: Mem) -> dict:
    stage = stage_name(mem)
    res = {"stage": stage, "family": family(stage), "mission": is_mission(stage),
           "game_status": f"{mem.u32(GAME_STATUS):#010x}", "records": records(mem)}
    if not is_mission(stage):
        res["note"] = "not in a mission (menu, title or save screen): start a mission first"
        return res
    mgr = find_manager(mem)
    if not mgr:
        res["note"] = "this stage has no running vr.c mission manager (still loading, or a mode without one)"
        return res
    res.update(read_manager(mem, mgr, manager_layout(mem, mgr)))
    return res


def complete(mem: Mem, wait_s: float = 2.0) -> dict:
    """Run the manager's own clear routine on the live session and confirm the clear sequence started."""
    stage = stage_name(mem)
    if not is_mission(stage):
        return {"stage": stage, "completed": False, "error": "not in a mission: start (or resume) a VR mission first"}
    mgr = find_manager(mem)
    if not mgr:
        return {"stage": stage, "completed": False, "error": "no vr.c mission manager is running on this stage"}
    lay = manager_layout(mem, mgr)
    before = read_manager(mem, mgr, lay)
    res = {"stage": stage, "family": family(stage), "before": before}
    if before["state"] == 2 or (before["state"] == 4 and before["clear_step"] > 0):
        return res | {"completed": True, "verified": True, "note": "the mission was already cleared"}
    if before["state"] != 1:
        return res | {"completed": False,
                      "error": f"the mission is {before['state_name']} (state {before['state']}), not running: "
                               "restart it (pause > restart) and run complete again"}
    # exactly the game's clear routine: state = 2; GM_GameStatus |= 0x10000000; step byte 0 -> 1
    mem.wr(lay["state"], struct.pack("<I", 2))
    mem.wr(GAME_STATUS, struct.pack("<I", mem.u32(GAME_STATUS) | CLEAR_BIT))
    if mem.u8(mgr["actor"] + lay["step"]) == 0:
        mem.wr(mgr["actor"] + lay["step"], b"\x01")
    after = read_manager(mem, mgr, lay)
    res.update(after=after, writes=mem.log)
    deadline = time.time() + max(0.0, wait_s)
    progressed = after
    while time.time() < deadline:
        time.sleep(0.25)
        try:
            if stage_name(mem) != stage or not find_manager(mem):
                progressed = {"left_stage": True}
                break
            progressed = read_manager(mem, mgr, lay)
            if progressed["clear_step"] > 1:
                break
        except Exception:                                                     # noqa: BLE001 - stage is reloading
            progressed = {"left_stage": True}
            break
    ok = after["state"] == 2 and after["clear_step"] >= 1
    res.update(completed=ok, verified=ok, progress=progressed,
               note="the game's own clear sequence is running: the CLEARED result screen follows in a few seconds "
                    "and records the clear like a normal finish" if ok else "the write did not hold")
    return res


def run(ad, title: str, op: str = "status", wait_s: float = 2.0, x: float | None = None, y: float | None = None,
        window_aspect: float = 4 / 3) -> dict:
    op = re.sub(r"[^a-z_]+", "_", (op or "status").lower()).strip("_") or "status"
    op = OP_ALIASES.get(op, op)
    if op not in OPS:
        return {"error": f"unknown op '{op}' (" + " | ".join(OPS) + ")"}
    if op == "stages":
        return {"families": FAMILIES, "note": "stage names as in MGS/STAGE.DIR; status shows the live one"}
    t = (title or "").lower()
    if "metal gear" not in t or "vr" not in t and "integral" not in t:
        return {"error": f"'{title}' is not Metal Gear Solid: VR Missions (USA, {SERIAL})"}
    mem = Mem(ad)
    if op == "status":
        return status(mem)
    if op == "complete":
        return complete(mem, wait_s)
    if op == "pick":
        if x is None or y is None:
            return {"error": "pick needs x and y (fractions of the game window)"}
        return pick(mem, x, y, window_aspect)
    return unlock_all(mem)


def unlock_all(mem: Mem) -> dict:
    from . import mgs_vr_unlock
    return mgs_vr_unlock.unlock_all(mem)


# ---------------------------------------------------------------------------------------------- gBox tool
class MgsVrIn(BaseModel):
    session_id: str
    op: str = "status"        # status | complete | unlock_all | stages | pick
    wait_s: float = 2.0       # complete: how long to watch the clear sequence advance
    x: float | None = None    # pick: the click, fractions of the game window (0..1)
    y: float | None = None
    window_aspect: float = 4 / 3   # pick: width / height of the window the click was in


class MgsVrOut(BaseModel):
    result: dict


@tool("mgs_vr", "1.0", MgsVrIn, MgsVrOut, capabilities=["runtime", "memory"], permissions=[P.MEMORY_WRITE],
      side_effects=["ends the running VR mission as cleared, as reaching its goal would"], timeout_s=60)
def mgs_vr(inp: MgsVrIn, ctx):
    """Metal Gear Solid: VR Missions (PS1) on the live session. op=complete marks the current mission complete: it
    runs the mission manager's own clear routine (what reaching the goal does), so the CLEARED result screen, the
    record and the unlocks follow from the game itself; verified by read-back. op=status shows the stage, mission
    state (running / cleared / over), timer, goal and player position. op=unlock_all opens every mission.
    op=stages lists the stage families. op=pick x y: which figure (Snake = slot player, a soldier = enemy:soldier) is
    drawn at that point of the picture (the actors projected through the game's own view matrix)."""
    from .tools import SESSIONS
    ad, g = SESSIONS[inp.session_id]
    return {"result": run(ad, g.get("title", ""), inp.op, inp.wait_s, inp.x, inp.y, inp.window_aspect)}
