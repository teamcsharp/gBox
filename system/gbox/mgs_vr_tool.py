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

STATES = {0: "not started", 1: "running", 2: "cleared", 3: "clear (scripted)", 4: "ending", 5: "over"}

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
    elapsed, limit = struct.unpack_from("<2h", raw, 0x34)
    px, py, pz = struct.unpack(f"<3h", mem.rd(PLAYER_POS, 6))
    return {"state": state, "state_name": STATES.get(state, f"unknown {state}"), "clear_step": raw[lay["step"]],
            "goal": [gx, gy, gz], "player": [px, py, pz],
            "at_goal": abs(px - gx) <= 500 and abs(pz - gz) <= 500,
            "elapsed_frames": elapsed & 0xFFFF, "limit_frames": limit,
            "actor": f"{a:#x}", "state_address": f"{lay['state']:#x}", "clear_routine": f"{lay['handler']:#x}"}


# ---------------------------------------------------------------------------------------------- records
def records(mem: Mem) -> dict:
    """The record table (GCL variables): negative = the stock record of an uncleared slot, positive = the player's."""
    raw = mem.rd(RECORDS, 0x800)
    vals = struct.unpack("<1024h", raw)
    slots = vals[11:0x44A // 2]
    return {"slots": len(slots), "player_records": sum(1 for v in slots if v > 0),
            "stock_records": sum(1 for v in slots if v < 0)}


# ---------------------------------------------------------------------------------------------- engine
OPS = ("status", "complete", "unlock_all", "stages")
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
    if before["state"] == 2:
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


def run(ad, title: str, op: str = "status", wait_s: float = 2.0) -> dict:
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
    return unlock_all(mem)


def unlock_all(mem: Mem) -> dict:
    from . import mgs_vr_unlock
    return mgs_vr_unlock.unlock_all(mem)


# ---------------------------------------------------------------------------------------------- gBox tool
class MgsVrIn(BaseModel):
    session_id: str
    op: str = "status"        # status | complete | unlock_all | stages
    wait_s: float = 2.0       # complete: how long to watch the clear sequence advance


class MgsVrOut(BaseModel):
    result: dict


@tool("mgs_vr", "1.0", MgsVrIn, MgsVrOut, capabilities=["runtime", "memory"], permissions=[P.MEMORY_WRITE],
      side_effects=["ends the running VR mission as cleared, as reaching its goal would"], timeout_s=60)
def mgs_vr(inp: MgsVrIn, ctx):
    """Metal Gear Solid: VR Missions (PS1) on the live session. op=complete marks the current mission complete: it
    runs the mission manager's own clear routine (what reaching the goal does), so the CLEARED result screen, the
    record and the unlocks follow from the game itself; verified by read-back. op=status shows the stage, mission
    state (running / cleared / over), timer, goal and player position. op=unlock_all opens every mission.
    op=stages lists the stage families."""
    from .tools import SESSIONS
    ad, g = SESSIONS[inp.session_id]
    return {"result": run(ad, g.get("title", ""), inp.op, inp.wait_s)}
