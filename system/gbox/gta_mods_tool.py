"""`gta_mods`: live mods for the PS2 GTAs (III, Vice City, San Andreas, Liberty City Stories, Vice City Stories).

ops: games | status | install | punch_launch | exploding_punch | tank_rain | fast_cars | flying_cars | super_jump |
     heli | ped_density | car_density | giant | spawn_vehicle | car_jump | ped_rain | uninstall
Each op takes on=true/false and/or value (see GtaIn). Per-game addresses: gbox/gta_games.py; a game gets the ops its
table has keys for (GTA III: all; Liberty City Stories: car_jump, ped_rain).

How it works (PS2 EE, MIPS R5900, through pcsx2_libretro's READ/WRITE_CORE_RAM view of EE RAM):
- Writing from outside into a page the EE recompiler has compiled crashes pcsx2_libretro, so code is never patched from
  outside. Instead a small "cave" (code at CAVE, data/mailbox at DATA, both in the unused 0xF9000-0xFFFFF RAM below the
  ELF) is written once, and ONE vtable slot (data memory) is pointed at the cave's boot stub. The EE calls it within a
  frame; the stub calls the original method, restores the slot and applies the queued code patches with EE stores
  (which pcsx2 handles like any self-modifying code):
    * CGame::Process `jal CPad::DoCheats` -> dispatcher: runs DoCheats, then every frame: applies queued patches,
      runs the call queue (generic `fn(a0..a3, t0, f12..f14)` calls the tool queues: model loads, vehicle spawn,
      warp into car, explosions), updates launched peds (explode on impact) and tank rain, then
      * car jump: reads CPad::Pads[0]'s stick-click (L3/R3) NewState/OldState shorts; on the press edge, if the player
        is in a vehicle (FindPlayerVehicle), sets the vehicle's move speed z to v = sqrt(2*g*h) (speed unit = m per
        1/50 s step, gravity g = 0.008 per step^2 -> apex h metres, independent of the frame rate). Works with any pad.
      * ped rain: every PERIOD frames spawns BATCH peds with CPopulation::AddPed (civilian type + a model some ped in
        the pool already uses, so it's loaded) at player + (random offset within RADIUS) + HEIGHT, and gives each an
        outward move speed (BURST * offset/RADIUS) + an upward kick: rain = wide radius, staggered, no burst; splash =
        one point, all at once, burst outward. Keeps RESERVE ped-pool slots free; when short, removes (RemovePed) the
        oldest ped it spawned that has been around RECYCLE frames, so a 100-ped rain fits the 70-slot LCS pool.
    * a later per-frame `jal` (after peds are processed) -> post stub: giant player scale.
    * CPed::FightStrike `jal CPhysical::ApplyMoveForce` (the punched ped's knock-back) -> punch stub: when the attacker
      is the player and punch launch is on, sets the victim's move speed to N units/frame away from the player (plus
      lift) and records it; the dispatcher explodes it when its speed collapses (it hit something).
- Options live in the DATA page (plain data writes, effective next frame). Every write is read back.

Register with:  from . import gta_mods_tool  # noqa: F401
"""
import re
import struct
import time
import threading
import weakref
from functools import wraps

from pydantic import BaseModel

from .models import Permission as P
from .registry import tool
from .gta_games import GAMES

CAVE = 0x000FA000          # code (executed by the EE -> never rewritten from outside once installed)
DATA = 0x000F9000          # data / mailbox page (never executed)
MAGIC = 0x33584247         # 'GBX3'
VERSION = 2
_TRANSACTION_GUARD = threading.Lock()
_TRANSACTIONS = weakref.WeakKeyDictionary()


def transaction(adapter):
    """One shared native mailbox transaction for every GTA tool on this adapter."""
    with _TRANSACTION_GUARD:
        lock = _TRANSACTIONS.get(adapter)
        if lock is None:
            lock = threading.RLock()
            _TRANSACTIONS[adapter] = lock
        return lock


def _mem_serialized(fn):
    @wraps(fn)
    def locked(mem, *args, **kwargs):
        with transaction(mem.ad):
            return fn(mem, *args, **kwargs)
    return locked


def _adapter_serialized(fn):
    @wraps(fn)
    def locked(adapter, *args, **kwargs):
        if adapter is None:return fn(adapter,*args,**kwargs)  # read-only game catalogue needs no session
        with transaction(adapter):
            return fn(adapter, *args, **kwargs)
    return locked

# DATA layout
D_MAGIC, D_BOOT, D_FRAME, D_VER = 0x000, 0x004, 0x008, 0x00C
D_PQ_N, D_PQ = 0x010, 0x014                      # 16 x (addr, value)
C_PUNCH, C_PUNCH_SPEED, C_PUNCH_UP = 0x100, 0x104, 0x108
C_EXPLODE, C_EXPLODE_TYPE = 0x10C, 0x110
C_TANK, C_TANK_PERIOD, C_TANK_CNT, C_TANK_H, C_TANK_R, C_TANK_MODEL, C_TANK_MAXV = 0x114, 0x118, 0x11C, 0x120, 0x124, 0x128, 0x12C
C_SCALE = 0x130
S_PUNCHED, S_EXPLODED, S_TANKS = 0x134, 0x138, 0x13C
C_CJ, C_CJ_V, C_CJ_NEW, C_CJ_OLD, S_CJ = 0x140, 0x144, 0x148, 0x14C, 0x150          # car jump
C_PR_LEFT, C_PR_PERIOD, C_PR_TICK, C_PR_BATCH = 0x154, 0x158, 0x15C, 0x160          # ped rain
C_PR_H, C_PR_R, C_PR_BURST, C_PR_UP = 0x164, 0x168, 0x16C, 0x170
C_PR_RESERVE, C_PR_RECYCLE, S_PR, S_PR_FAIL, S_PR_FULL, S_PR_RECYCLED = 0x174, 0x178, 0x17C, 0x180, 0x184, 0x188
D_PR_HEAD = 0x18C
C_CFG_N, C_CFG_B, C_CFG_H, C_CFG_R = 0x190, 0x194, 0x198, 0x19C   # ped_rain settings the sidebar sliders keep (python only)
C_PR_MODELS = 0x1A0                              # 8 x (ped type, model id)
D_CQ_N, D_CQ_DONE, D_CQ = 0x200, 0x204, 0x210    # 8 x 0x30
CQ_SIZE, CQ_MAX = 0x30, 8
D_LAUNCH, LAUNCH_N = 0x400, 16                   # 16 x (ped, age, prev speed^2, pad)
D_SCR = 0x500                                    # scratch vectors: +0 player coords, +0x10 explosion pos, +0x20.. queue args
D_TRACK, TRACK_N = 0x600, 100                    # ped rain: 100 x (ped, gen<<16 | pool index, spawn frame, pad)


# --- tiny MIPS (R5900) assembler -----------------------------------------------------------------------------------------

_R = {n: i for i, n in enumerate("zero at v0 v1 a0 a1 a2 a3 t0 t1 t2 t3 t4 t5 t6 t7 s0 s1 s2 s3 s4 s5 s6 s7 t8 t9 k0 k1 gp sp fp ra".split())}


def _reg(s):
    s = s.strip().lstrip("$")
    if s in _R:
        return _R[s]
    if s[0] == "f" and s[1:].isdigit():
        return int(s[1:])
    return int(s)


def _hi(v):
    return ((v + 0x8000) >> 16) & 0xFFFF


def assemble(lines, base, syms):
    syms, pc, items = dict(syms), base, []
    for ln in lines:
        ln = ln.split("#")[0].strip()
        if not ln:
            continue
        if ln.endswith(":"):
            syms[ln[:-1]] = pc
            continue
        items.append((pc, ln))
        pc += 8 if ln.split()[0] == "la" else 4

    def val(x):
        x = x.strip()
        if x in syms:
            return syms[x]
        m = re.fullmatch(r"(\w+)\+(\w+)", x)
        if m and not x.startswith("0x"):
            return val(m.group(1)) + val(m.group(2))
        return int(x, 0)

    def mem(x):
        m = re.fullmatch(r"(.*)\((\$?\w+)\)", x.strip())
        return (val(m.group(1)) if m.group(1).strip() else 0) & 0xFFFF, _reg(m.group(2))

    out = bytearray()
    for pc, ln in items:
        op, _, rest = ln.partition(" ")
        a = [x.strip() for x in rest.split(",")] if rest.strip() else []
        I = lambda o, rs, rt, imm: (o << 26) | (rs << 21) | (rt << 16) | (imm & 0xFFFF)
        Rr = lambda rs, rt, rd, sh, fn: (rs << 21) | (rt << 16) | (rd << 11) | (sh << 6) | fn
        br = lambda t: ((val(t) - (pc + 4)) >> 2) & 0xFFFF
        F = lambda fn, ft, fs, fd: (0x11 << 26) | (0x10 << 21) | (ft << 16) | (fs << 11) | (fd << 6) | fn
        if op == "nop":
            w = [0]
        elif op == "la":
            v = val(a[1]) & 0xFFFFFFFF
            w = [I(0x0F, 0, _reg(a[0]), _hi(v)), I(0x09, _reg(a[0]), _reg(a[0]), v & 0xFFFF)]
        elif op == "li":
            w = [I(0x09, 0, _reg(a[0]), val(a[1]))]
        elif op == "lui":
            w = [I(0x0F, 0, _reg(a[0]), val(a[1]))]
        elif op in ("addiu", "slti", "sltiu", "andi", "ori", "xori"):
            w = [I({"addiu": 9, "slti": 10, "sltiu": 11, "andi": 12, "ori": 13, "xori": 14}[op], _reg(a[1]), _reg(a[0]), val(a[2]))]
        elif op in ("lb", "lh", "lw", "lbu", "lhu", "sb", "sh", "sw", "lwc1", "swc1", "lq", "sq"):
            o = {"lb": 0x20, "lh": 0x21, "lw": 0x23, "lbu": 0x24, "lhu": 0x25, "sb": 0x28, "sh": 0x29, "sw": 0x2B,
                 "lwc1": 0x31, "swc1": 0x39, "lq": 0x1E, "sq": 0x1F}[op]
            imm, b = mem(a[1])
            w = [I(o, b, _reg(a[0]), imm)]
        elif op in ("addu", "subu", "and", "or", "slt", "sltu"):
            fn = {"addu": 0x21, "subu": 0x23, "and": 0x24, "or": 0x25, "slt": 0x2A, "sltu": 0x2B}[op]
            w = [Rr(_reg(a[1]), _reg(a[2]), _reg(a[0]), 0, fn)]
        elif op == "move":
            w = [Rr(_reg(a[1]), 0, _reg(a[0]), 0, 0x2D)]                     # daddu rd, rs, zero
        elif op in ("sll", "srl", "sra"):
            w = [Rr(0, _reg(a[1]), _reg(a[0]), val(a[2]), {"sll": 0, "srl": 2, "sra": 3}[op])]
        elif op == "jr":
            w = [Rr(_reg(a[0]), 0, 0, 0, 8)]
        elif op == "jalr":
            w = [Rr(_reg(a[0]), 0, 31, 0, 9)]
        elif op in ("j", "jal"):
            w = [((2 if op == "j" else 3) << 26) | ((val(a[0]) >> 2) & 0x3FFFFFF)]
        elif op in ("beq", "bne"):
            w = [I(4 if op == "beq" else 5, _reg(a[0]), _reg(a[1]), br(a[2]))]
        elif op in ("beqz", "bnez"):
            w = [I(4 if op == "beqz" else 5, _reg(a[0]), 0, br(a[1]))]
        elif op == "b":
            w = [I(4, 0, 0, br(a[0]))]
        elif op in ("blez", "bgtz"):
            w = [I(6 if op == "blez" else 7, _reg(a[0]), 0, br(a[1]))]
        elif op in ("bltz", "bgez"):
            w = [I(1, _reg(a[0]), 0 if op == "bltz" else 1, br(a[1]))]
        elif op in ("mtc1", "mfc1"):
            w = [(0x11 << 26) | ((4 if op == "mtc1" else 0) << 21) | (_reg(a[0]) << 16) | (_reg(a[1]) << 11)]
        elif op in ("add.s", "sub.s", "mul.s", "div.s"):
            w = [F({"add.s": 0, "sub.s": 1, "mul.s": 2, "div.s": 3}[op], _reg(a[2]), _reg(a[1]), _reg(a[0]))]
        elif op == "sqrt.s":
            w = [F(4, _reg(a[1]), 0, _reg(a[0]))]
        elif op in ("mov.s", "neg.s", "abs.s"):
            w = [F({"mov.s": 6, "neg.s": 7, "abs.s": 5}[op], 0, _reg(a[1]), _reg(a[0]))]
        elif op == "cvt.s.w":
            w = [(0x11 << 26) | (0x14 << 21) | (_reg(a[1]) << 11) | (_reg(a[0]) << 6) | 0x20]
        elif op in ("c.lt.s", "c.le.s", "c.eq.s"):
            w = [F({"c.lt.s": 0x34, "c.le.s": 0x36, "c.eq.s": 0x32}[op], _reg(a[1]), _reg(a[0]), 0)]
        elif op in ("bc1t", "bc1f"):
            w = [(0x11 << 26) | (8 << 21) | ((1 if op == "bc1t" else 0) << 16) | br(a[0])]
        else:
            raise ValueError(f"asm: unknown {ln!r}")
        for x in w:
            out += struct.pack("<I", x & 0xFFFFFFFF)
    return bytes(out), syms


def jal_word(target):
    return (3 << 26) | ((target >> 2) & 0x3FFFFFF)


def _f(x):
    return struct.unpack("<I", struct.pack("<f", x))[0]


# --- the cave -------------------------------------------------------------------------------------------------------------

def features(g):
    """Which cave parts / ops this game's table supports."""
    f = g["fn"]
    return {"launch": "AddExplosion" in f and "punch_site" in g, "punch": "punch_site" in g,
            "vehicles": "VehicleNew" in f and "info_base" in g, "post": "hook_post" in g and "UpdateRwFrame" in f,
            "car_jump": "pads" in g and "FindPlayerVehicle" in f,
            "ped_rain": "AddPed" in f and "RemovePed" in f and "ped_pool_ptr" in g and "rand" in f}


def cave_source(g):
    f, o, has = g["fn"], g["off"], features(g)
    S = {"DATA": DATA, "ORIG_BOOT": g["boot_fn"], "VT_SLOT": g["boot_vt"], "FRAME_FN": g["hook_frame_fn"],
         "POST_FN": g.get("hook_post_fn", 0), "INFO_LS": g.get("info_base", 0) + g.get("info_loadstate", 0),
         "VEHPOOL": g.get("veh_pool_ptr", 0), "PEDPOOL": g.get("ped_pool_ptr", 0),
         **{k.upper(): v for k, v in f.items()}}
    pos, spd = o["pos"], o["speed"]
    st = o.get("veh_status", 0)
    calls = "".join(f"        jal {n}\n        nop\n" for n, k in (("launched_update", "launch"), ("tank_update", "vehicles"),
                                                                    ("carjump", "car_jump"), ("pedrain", "ped_rain")) if has[k])
    src = f"""
    boot:
        addiu sp, sp, -0x20
        sq ra, 0x10(sp)
        la t9, ORIG_BOOT
        jalr t9
        nop
        la t0, VT_SLOT
        la t1, ORIG_BOOT
        sw t1, 0(t0)
        la t0, DATA
        li t1, 1
        sw t1, {D_BOOT}(t0)
        jal apply_patches
        nop
        lq ra, 0x10(sp)
        jr ra
        addiu sp, sp, 0x20

    apply_patches:
        la t0, DATA
        lw t1, {D_PQ_N}(t0)
        beqz t1, ap_end
        addiu t2, t0, {D_PQ}
    ap_loop:
        lw t3, 0(t2)
        lw t4, 4(t2)
        sw t4, 0(t3)
        addiu t1, t1, -1
        bnez t1, ap_loop
        addiu t2, t2, 8
        sw zero, {D_PQ_N}(t0)
    ap_end:
        jr ra
        nop

    dispatch:
        addiu sp, sp, -0x80
        sq ra, 0x70(sp)
        sq s0, 0x60(sp)
        sq s1, 0x50(sp)
        sq s2, 0x40(sp)
        sq s3, 0x30(sp)
        jal FRAME_FN
        nop
        la s0, DATA
        lw t0, {D_FRAME}(s0)
        addiu t0, t0, 1
        sw t0, {D_FRAME}(s0)
        jal apply_patches
        nop
        lw s1, {D_CQ_N}(s0)
        beqz s1, cq_end
        addiu s2, s0, {D_CQ}
        move s3, zero
    cq_loop:
        lw t9, 0(s2)
        lw a0, 4(s2)
        lw a1, 8(s2)
        lw t1, 0x28(s2)
        andi t2, t1, 1
        beqz t2, cq_a1
        nop
        move a0, s3
    cq_a1:
        andi t2, t1, 2
        beqz t2, cq_args
        nop
        move a1, s3
    cq_args:
        lw a2, 0xC(s2)
        lw a3, 0x10(s2)
        lw t0, 0x14(s2)
        lwc1 f12, 0x18(s2)
        lwc1 f13, 0x1C(s2)
        lwc1 f14, 0x20(s2)
        jalr t9
        nop
        sw v0, 0x24(s2)
        move s3, v0
        addiu s1, s1, -1
        bnez s1, cq_loop
        addiu s2, s2, {CQ_SIZE}
        sw zero, {D_CQ_N}(s0)
        lw t0, {D_CQ_DONE}(s0)
        addiu t0, t0, 1
        sw t0, {D_CQ_DONE}(s0)
    cq_end:
{calls}        lq ra, 0x70(sp)
        lq s0, 0x60(sp)
        lq s1, 0x50(sp)
        lq s2, 0x40(sp)
        lq s3, 0x30(sp)
        jr ra
        addiu sp, sp, 0x80
"""
    if has["launch"]:
        src += f"""
    launched_update:
        addiu sp, sp, -0x40
        sq ra, 0x30(sp)
        sq s0, 0x20(sp)
        sq s1, 0x10(sp)
        la s0, DATA+{D_LAUNCH}
        li s1, {LAUNCH_N}
    lu_loop:
        lw a0, 0(s0)
        beqz a0, lu_next
        nop
        lw t0, 4(s0)
        addiu t0, t0, 1
        sw t0, 4(s0)
        lwc1 f0, {spd}(a0)
        lwc1 f1, {spd + 4}(a0)
        mul.s f0, f0, f0
        mul.s f1, f1, f1
        add.s f0, f0, f1
        lwc1 f1, 8(s0)
        swc1 f0, 8(s0)
        slti t1, t0, 3
        bnez t1, lu_age
        nop
        lui t1, 0x3E80
        mtc1 t1, f2
        mul.s f1, f1, f2
        c.lt.s f0, f1
        bc1f lu_age
        nop
        la t2, DATA
        lw t3, {C_EXPLODE}(t2)
        beqz t3, lu_free
        nop
        lwc1 f0, {pos}(a0)
        swc1 f0, {D_SCR + 0x10}(t2)
        lwc1 f0, {pos + 4}(a0)
        swc1 f0, {D_SCR + 0x14}(t2)
        lwc1 f0, {pos + 8}(a0)
        swc1 f0, {D_SCR + 0x18}(t2)
        lw t3, {S_EXPLODED}(t2)
        addiu t3, t3, 1
        sw t3, {S_EXPLODED}(t2)
        jal FINDPLAYERPED
        nop
        move a1, v0
        move a0, zero
        la t2, DATA
        lw a2, {C_EXPLODE_TYPE}(t2)
        addiu a3, t2, {D_SCR + 0x10}
        jal ADDEXPLOSION
        move t0, zero
        b lu_free
        nop
    lu_age:
        lw t0, 4(s0)
        slti t1, t0, 200
        bnez t1, lu_next
        nop
    lu_free:
        sw zero, 0(s0)
    lu_next:
        addiu s1, s1, -1
        bnez s1, lu_loop
        addiu s0, s0, 16
        lq ra, 0x30(sp)
        lq s0, 0x20(sp)
        lq s1, 0x10(sp)
        jr ra
        addiu sp, sp, 0x40
"""
    if has["punch"]:
        src += f"""
    punch:
        addiu sp, sp, -0x40
        sq ra, 0x30(sp)
        sq s0, 0x20(sp)
        move s0, a0
        swc1 f12, 0(sp)
        swc1 f13, 4(sp)
        swc1 f14, 8(sp)
        la t0, DATA
        lw t1, {C_PUNCH}(t0)
        beqz t1, p_orig
        nop
        jal FINDPLAYERPED
        nop
        bne v0, {g["punch_attacker_reg"]}, p_orig
        nop
        lwc1 f0, 0(sp)
        lwc1 f1, 4(sp)
        mul.s f2, f0, f0
        mul.s f3, f1, f1
        add.s f2, f2, f3
        sqrt.s f2, f2
        mtc1 zero, f3
        c.eq.s f2, f3
        bc1t p_orig
        nop
        la t0, DATA
        lwc1 f3, {C_PUNCH_SPEED}(t0)
        div.s f3, f3, f2
        mul.s f0, f0, f3
        mul.s f1, f1, f3
        swc1 f0, {spd}(s0)
        swc1 f1, {spd + 4}(s0)
        lwc1 f2, {C_PUNCH_UP}(t0)
        swc1 f2, {spd + 8}(s0)
        lw t1, {S_PUNCHED}(t0)
        addiu t1, t1, 1
        sw t1, {S_PUNCHED}(t0)
        addiu t1, t0, {D_LAUNCH}
        li t2, {LAUNCH_N}
    p_find:
        lw t3, 0(t1)
        beqz t3, p_put
        nop
        beq t3, s0, p_put
        nop
        addiu t2, t2, -1
        bnez t2, p_find
        addiu t1, t1, 16
        b p_done
        nop
    p_put:
        sw s0, 0(t1)
        sw zero, 4(t1)
        mul.s f0, f0, f0
        mul.s f1, f1, f1
        add.s f0, f0, f1
        swc1 f0, 8(t1)
        b p_done
        nop
    p_orig:
        move a0, s0
        lwc1 f12, 0(sp)
        lwc1 f13, 4(sp)
        jal APPLYMOVEFORCE
        lwc1 f14, 8(sp)
    p_done:
        lq ra, 0x30(sp)
        lq s0, 0x20(sp)
        jr ra
        addiu sp, sp, 0x40
"""
    if has["vehicles"]:
        src += f"""
    spawn_vehicle:
        addiu sp, sp, -0x40
        sq ra, 0x30(sp)
        sq s0, 0x20(sp)
        sq s1, 0x10(sp)
        sq s2, 0(sp)
        move s0, a0
        move s1, a1
        move s2, a2
        jal VEHICLENEW
        li a0, {g["veh_size"]}
        beqz v0, sv_end
        nop
        move a0, v0
        move a1, s0
        jal AUTOMOBILECTOR
        move a2, s2
        move s0, v0
        lwc1 f0, 0(s1)
        swc1 f0, {pos}(s0)
        lwc1 f0, 4(s1)
        swc1 f0, {pos + 4}(s0)
        lwc1 f0, 8(s1)
        swc1 f0, {pos + 8}(s0)
        lbu t0, {st}(s0)
        andi t0, t0, {g["status_mask"]}
        ori t0, t0, {g["status_abandoned"]}
        sb t0, {st}(s0)
        li t0, 1
        sw t0, {o["veh_doorlock"]}(s0)
        jal WORLDADD
        move a0, s0
        move v0, s0
    sv_end:
        lq ra, 0x30(sp)
        lq s0, 0x20(sp)
        lq s1, 0x10(sp)
        lq s2, 0(sp)
        jr ra
        addiu sp, sp, 0x40

    tank_update:
        addiu sp, sp, -0x40
        sq ra, 0x30(sp)
        sq s0, 0x20(sp)
        la s0, DATA
        lw t0, {C_TANK}(s0)
        beqz t0, tu_end
        nop
        lw t0, {C_TANK_CNT}(s0)
        addiu t0, t0, 1
        sw t0, {C_TANK_CNT}(s0)
        lw t1, {C_TANK_PERIOD}(s0)
        slt t2, t0, t1
        bnez t2, tu_end
        nop
        lw a0, {C_TANK_MODEL}(s0)
        sll t3, a0, {(g["info_stride"]).bit_length() - 1}
        la t4, INFO_LS
        addu t3, t3, t4
        lbu t3, 0(t3)
        li t4, 1
        beq t3, t4, tu_loaded
        nop
        jal REQUESTMODEL
        li a1, 0
        b tu_end
        nop
    tu_loaded:
        sw zero, {C_TANK_CNT}(s0)
        la t0, VEHPOOL
        lw t0, 0(t0)
        lw t1, 4(t0)
        lw t2, 8(t0)
        move t3, zero
    tp_loop:
        lb t4, 0(t1)
        bltz t4, tp_free
        nop
        addiu t3, t3, 1
    tp_free:
        addiu t2, t2, -1
        bgtz t2, tp_loop
        addiu t1, t1, 1
        lw t4, {C_TANK_MAXV}(s0)
        slt t5, t3, t4
        beqz t5, tu_end
        nop
        jal FINDPLAYERCOORS
        addiu a0, s0, {D_SCR}
        jal RAND
        nop
        andi v0, v0, 0xFF
        addiu v0, v0, -128
        mtc1 v0, f0
        cvt.s.w f0, f0
        lwc1 f1, {C_TANK_R}(s0)
        mul.s f0, f0, f1
        lui t0, 0x3C00
        mtc1 t0, f1
        mul.s f0, f0, f1
        lwc1 f1, {D_SCR}(s0)
        add.s f0, f0, f1
        swc1 f0, {D_SCR}(s0)
        jal RAND
        nop
        andi v0, v0, 0xFF
        addiu v0, v0, -128
        mtc1 v0, f0
        cvt.s.w f0, f0
        lwc1 f1, {C_TANK_R}(s0)
        mul.s f0, f0, f1
        lui t0, 0x3C00
        mtc1 t0, f1
        mul.s f0, f0, f1
        lwc1 f1, {D_SCR + 4}(s0)
        add.s f0, f0, f1
        swc1 f0, {D_SCR + 4}(s0)
        lwc1 f0, {D_SCR + 8}(s0)
        lwc1 f1, {C_TANK_H}(s0)
        add.s f0, f0, f1
        swc1 f0, {D_SCR + 8}(s0)
        lw a0, {C_TANK_MODEL}(s0)
        addiu a1, s0, {D_SCR}
        jal spawn_vehicle
        li a2, 1
        beqz v0, tu_end
        nop
        lw t0, {S_TANKS}(s0)
        addiu t0, t0, 1
        sw t0, {S_TANKS}(s0)
    tu_end:
        lq ra, 0x30(sp)
        lq s0, 0x20(sp)
        jr ra
        addiu sp, sp, 0x40
"""
    if has["post"]:
        src += f"""
    post:
        addiu sp, sp, -0x40
        sq ra, 0x30(sp)
        sq s0, 0x20(sp)
        jal POST_FN
        nop
        la t0, DATA
        lwc1 f0, {C_SCALE}(t0)
        mtc1 zero, f1
        c.eq.s f0, f1
        bc1t post_end
        nop
        jal FINDPLAYERPED
        nop
        beqz v0, post_end
        move s0, v0
        la t0, DATA
        lwc1 f4, {C_SCALE}(t0)
        li t1, 3
        move t2, s0
    ps_loop:
        lwc1 f0, 0(t2)
        lwc1 f1, 4(t2)
        lwc1 f2, 8(t2)
        mul.s f5, f0, f0
        mul.s f6, f1, f1
        add.s f5, f5, f6
        mul.s f6, f2, f2
        add.s f5, f5, f6
        sqrt.s f5, f5
        mtc1 zero, f6
        c.eq.s f5, f6
        bc1t ps_next
        nop
        div.s f5, f4, f5
        mul.s f0, f0, f5
        mul.s f1, f1, f5
        mul.s f2, f2, f5
        swc1 f0, 0(t2)
        swc1 f1, 4(t2)
        swc1 f2, 8(t2)
    ps_next:
        addiu t1, t1, -1
        bnez t1, ps_loop
        addiu t2, t2, 0x10
        jal UPDATERWFRAME
        move a0, s0
    post_end:
        lq ra, 0x30(sp)
        lq s0, 0x20(sp)
        jr ra
        addiu sp, sp, 0x40
"""
    if has["car_jump"]:
        src += f"""
    carjump:
        addiu sp, sp, -0x20
        sq ra, 0x10(sp)
        la t0, DATA
        lw t1, {C_CJ}(t0)
        beqz t1, cj_end
        nop
        lw t1, {C_CJ_NEW}(t0)
        lh t2, 0(t1)
        beqz t2, cj_end
        nop
        lw t1, {C_CJ_OLD}(t0)
        lh t2, 0(t1)
        bnez t2, cj_end
        nop
        jal FINDPLAYERVEHICLE
        nop
        beqz v0, cj_end
        nop
        la t0, DATA
        lwc1 f0, {C_CJ_V}(t0)
        swc1 f0, {spd + 8}(v0)
        lw t1, {S_CJ}(t0)
        addiu t1, t1, 1
        sw t1, {S_CJ}(t0)
    cj_end:
        lq ra, 0x10(sp)
        jr ra
        addiu sp, sp, 0x20
"""
    if has["ped_rain"]:
        src += f"""
    pedrain:
        addiu sp, sp, -0x60
        sq ra, 0x50(sp)
        sq s0, 0x40(sp)
        sq s1, 0x30(sp)
        sq s2, 0x20(sp)
        la s0, DATA
        lw t0, {C_PR_LEFT}(s0)
        blez t0, pr_end
        nop
        lw t0, {C_PR_TICK}(s0)
        addiu t0, t0, 1
        sw t0, {C_PR_TICK}(s0)
        lw t1, {C_PR_PERIOD}(s0)
        slt t2, t0, t1
        bnez t2, pr_end
        nop
        sw zero, {C_PR_TICK}(s0)
        lw s1, {C_PR_BATCH}(s0)
    pr_loop:
        blez s1, pr_end
        nop
        lw t0, {C_PR_LEFT}(s0)
        blez t0, pr_end
        nop
        jal pool_free
        nop
        lw t0, {C_PR_RESERVE}(s0)
        slt t1, t0, v0
        bnez t1, pr_spawn
        nop
        jal pr_recycle
        nop
        bnez v0, pr_loop
        nop
        lw t0, {S_PR_FULL}(s0)
        addiu t0, t0, 1
        b pr_end
        sw t0, {S_PR_FULL}(s0)
    pr_spawn:
        jal player_pos
        nop
        beqz v0, pr_end
        nop
        jal rnd_off
        nop
        swc1 f0, {D_SCR + 0x30}(s0)
        jal rnd_off
        nop
        swc1 f0, {D_SCR + 0x34}(s0)
        lwc1 f0, {D_SCR}(s0)
        lwc1 f1, {D_SCR + 0x30}(s0)
        add.s f0, f0, f1
        swc1 f0, {D_SCR}(s0)
        lwc1 f0, {D_SCR + 4}(s0)
        lwc1 f1, {D_SCR + 0x34}(s0)
        add.s f0, f0, f1
        swc1 f0, {D_SCR + 4}(s0)
        lwc1 f0, {D_SCR + 8}(s0)
        lwc1 f1, {C_PR_H}(s0)
        add.s f0, f0, f1
        swc1 f0, {D_SCR + 8}(s0)
        jal RAND
        nop
        andi v0, v0, 7
        sll v0, v0, 3
        addu t0, s0, v0
        lw a0, {C_PR_MODELS}(t0)
        lw a1, {C_PR_MODELS + 4}(t0)
        addiu a2, s0, {D_SCR}
        jal ADDPED
        move a3, zero
        beqz v0, pr_fail
        move s2, v0
        lw t0, {C_PR_LEFT}(s0)
        addiu t0, t0, -1
        sw t0, {C_PR_LEFT}(s0)
        lw t0, {S_PR}(s0)
        addiu t0, t0, 1
        sw t0, {S_PR}(s0)
        lwc1 f1, {C_PR_R}(s0)
        lwc1 f2, {C_PR_BURST}(s0)
        div.s f2, f2, f1
        lwc1 f0, {D_SCR + 0x30}(s0)
        mul.s f0, f0, f2
        swc1 f0, {spd}(s2)
        lwc1 f0, {D_SCR + 0x34}(s0)
        mul.s f0, f0, f2
        swc1 f0, {spd + 4}(s2)
        lwc1 f0, {C_PR_UP}(s0)
        swc1 f0, {spd + 8}(s2)
        jal pr_track
        move a0, s2
        b pr_loop
        addiu s1, s1, -1
    pr_fail:
        lw t0, {S_PR_FAIL}(s0)
        addiu t0, t0, 1
        sw t0, {S_PR_FAIL}(s0)
        sw zero, {C_PR_LEFT}(s0)
    pr_end:
        lq ra, 0x50(sp)
        lq s0, 0x40(sp)
        lq s1, 0x30(sp)
        lq s2, 0x20(sp)
        jr ra
        addiu sp, sp, 0x60

    pool_free:
        la t0, PEDPOOL
        lw t0, 0(t0)
        lw t1, 4(t0)
        lw t2, 8(t0)
        move v0, zero
    pf_loop:
        lb t3, 0(t1)
        bgez t3, pf_used
        nop
        addiu v0, v0, 1
    pf_used:
        addiu t2, t2, -1
        bgtz t2, pf_loop
        addiu t1, t1, 1
        jr ra
        nop

    player_pos:
        addiu sp, sp, -0x20
        sq ra, 0x10(sp)
        jal FINDPLAYERPED
        nop
        beqz v0, pp_end
        nop
        lbu t0, {o["ped_in_veh"]}(v0)
        beqz t0, pp_ped
        nop
        lw t1, {o["ped_veh"]}(v0)
        beqz t1, pp_ped
        nop
        move v0, t1
    pp_ped:
        la t0, DATA
        lwc1 f0, {pos}(v0)
        swc1 f0, {D_SCR}(t0)
        lwc1 f0, {pos + 4}(v0)
        swc1 f0, {D_SCR + 4}(t0)
        lwc1 f0, {pos + 8}(v0)
        swc1 f0, {D_SCR + 8}(t0)
    pp_end:
        lq ra, 0x10(sp)
        jr ra
        addiu sp, sp, 0x20

    rnd_off:
        addiu sp, sp, -0x20
        sq ra, 0x10(sp)
        jal RAND
        nop
        andi v0, v0, 0xFF
        addiu v0, v0, -128
        mtc1 v0, f0
        cvt.s.w f0, f0
        la t0, DATA
        lwc1 f1, {C_PR_R}(t0)
        mul.s f0, f0, f1
        lui t0, 0x3C00
        mtc1 t0, f1
        mul.s f0, f0, f1
        lq ra, 0x10(sp)
        jr ra
        addiu sp, sp, 0x20

    pr_track:
        la t0, PEDPOOL
        lw t0, 0(t0)
        lw t1, 0(t0)
        lw t2, 4(t0)
        lw t3, 8(t0)
        move t4, zero
    pt_find:
        beq t1, a0, pt_found
        nop
        addiu t4, t4, 1
        slt t5, t4, t3
        beqz t5, pt_end
        nop
        b pt_find
        addiu t1, t1, {g.get("ped_stride", 0)}
    pt_found:
        addu t2, t2, t4
        lbu t5, 0(t2)
        la t6, DATA
        lw t7, {D_PR_HEAD}(t6)
        sll t8, t7, 4
        addu t8, t8, t6
        sw a0, {D_TRACK}(t8)
        sll t5, t5, 16
        or t5, t5, t4
        sw t5, {D_TRACK + 4}(t8)
        lw t9, {D_FRAME}(t6)
        sw t9, {D_TRACK + 8}(t8)
        addiu t7, t7, 1
        slti t9, t7, {TRACK_N}
        bnez t9, pt_wr
        nop
        move t7, zero
    pt_wr:
        sw t7, {D_PR_HEAD}(t6)
    pt_end:
        jr ra
        nop

    pr_recycle:
        addiu sp, sp, -0x40
        sq ra, 0x30(sp)
        sq s0, 0x20(sp)
        sq s1, 0x10(sp)
        sq s2, 0(sp)
        la s0, DATA
        move v0, zero
        lw t0, {C_PR_RECYCLE}(s0)
        blez t0, rc_end
        nop
        lw s1, {D_PR_HEAD}(s0)
        li s2, {TRACK_N}
    rc_loop:
        sll t0, s1, 4
        addu t0, t0, s0
        lw a0, {D_TRACK}(t0)
        beqz a0, rc_next
        nop
        lw t1, {D_TRACK + 4}(t0)
        andi t2, t1, 0xFFFF
        srl t3, t1, 16
        la t4, PEDPOOL
        lw t4, 0(t4)
        lw t4, 4(t4)
        addu t4, t4, t2
        lbu t4, 0(t4)
        bne t4, t3, rc_clear
        nop
        lw t5, {D_FRAME}(s0)
        lw t6, {D_TRACK + 8}(t0)
        subu t5, t5, t6
        lw t6, {C_PR_RECYCLE}(s0)
        slt t7, t5, t6
        bnez t7, rc_end
        move v0, zero
        sw zero, {D_TRACK}(t0)
        lw t1, {S_PR_RECYCLED}(s0)
        addiu t1, t1, 1
        jal REMOVEPED
        sw t1, {S_PR_RECYCLED}(s0)
        b rc_end
        li v0, 1
    rc_clear:
        sw zero, {D_TRACK}(t0)
    rc_next:
        addiu s1, s1, 1
        slti t0, s1, {TRACK_N}
        bnez t0, rc_wrap
        nop
        move s1, zero
    rc_wrap:
        addiu s2, s2, -1
        bgtz s2, rc_loop
        nop
        move v0, zero
    rc_end:
        lq ra, 0x30(sp)
        lq s0, 0x20(sp)
        lq s1, 0x10(sp)
        lq s2, 0(sp)
        jr ra
        addiu sp, sp, 0x40
"""
    return src.splitlines(), S


def build_cave(g):
    lines, S = cave_source(g)
    code, syms = assemble(lines, CAVE, S)
    return code, syms


# --- memory ---------------------------------------------------------------------------------------------------------------

class Mem:
    def __init__(self, ad):
        self.ad, self.log = ad, []

    def rd(self, a, n):
        return bytes(self.ad.read_memory(a & 0x1FFFFFF, n))

    def u32(self, a):
        return struct.unpack("<I", self.rd(a, 4))[0]

    def f32(self, a):
        return struct.unpack("<f", self.rd(a, 4))[0]

    def wr(self, a, data: bytes):
        if CAVE <= a < CAVE + 0x6000:
            raise RuntimeError("refusing to write the installed cave code from outside (it is EE-compiled)")
        before = self.rd(a, len(data))
        if before != data:
            self.ad.write_memory(a & 0x1FFFFFF, data)
            if self.rd(a, len(data)) != data:
                raise RuntimeError(f"write to {a:#x} not confirmed by read-back")
        self.log.append({"addr": hex(a), "before": before.hex(), "after": data.hex()})

    def w32(self, a, v):
        self.wr(a, struct.pack("<I", v & 0xFFFFFFFF))

    def wf(self, a, v):
        self.wr(a, struct.pack("<f", v))


def detect(title: str, mem: Mem | None = None):
    t = (title or "").lower().replace(":", " ").replace("-", " ")
    t = re.sub(r"\s+", " ", t)
    order = ["lcs", "vcs", "gtasa", "gtavc", "gta3"]
    for key in order:
        g = GAMES.get(key)
        if g and re.search(g["match"], t):
            return key, g
    raise ValueError(f"no GTA table for {title!r}; supported: " + ", ".join(g["name"] for g in GAMES.values()))


# --- install --------------------------------------------------------------------------------------------------------------

def installed(m: Mem, g) -> bool:
    return m.u32(DATA + D_MAGIC) == MAGIC and m.u32(DATA + D_BOOT) == 1 and m.u32(g["hook_frame"]) == jal_word(build_cave(g)[1]["dispatch"])


def _frame(m):
    return m.u32(DATA + D_FRAME)


def wait_frames(m: Mem, n=2, timeout=5.0):
    f0, t = _frame(m), time.time()
    while time.time() - t < timeout:
        if (_frame(m) - f0) & 0xFFFFFFFF >= n:
            return True
        time.sleep(0.03)
    return False


@_mem_serialized
def queue_patches(m: Mem, patches: list, timeout=5.0):
    """Have the EE store words into code (applied by the dispatcher next frame)."""
    waiting = time.monotonic()
    while m.u32(DATA + D_PQ_N):
        if time.monotonic() - waiting >= timeout:
            raise RuntimeError("another native patch batch is still pending; no new patches were queued")
        time.sleep(0.03)
    for i in range(0, len(patches), 16):
        chunk = patches[i:i + 16]
        m.wr(DATA + D_PQ, b"".join(struct.pack("<II", a, v) for a, v in chunk))
        m.w32(DATA + D_PQ_N, len(chunk))
        t = time.time()
        while m.u32(DATA + D_PQ_N):
            if time.time() - t > timeout:
                raise RuntimeError("the game did not run the patch queue (paused / in a menu / not in gameplay?)")
            time.sleep(0.03)
    for a, v in patches:
        if m.u32(a) != v:
            raise RuntimeError(f"code patch at {a:#x} not applied")


@_mem_serialized
def call(m: Mem, calls: list, timeout=10.0) -> list:
    """Run game functions on the EE in one frame. calls: dicts fn, a0..a3, t0, f12..f14, a0_prev/a1_prev."""
    assert len(calls) <= CQ_MAX
    waiting = time.monotonic()
    while m.u32(DATA + D_CQ_N):
        if time.monotonic() - waiting >= timeout:
            raise RuntimeError("another native call batch is still pending; no new calls were queued")
        time.sleep(0.03)
    blob = b""
    for c in calls:
        fl = (1 if c.get("a0_prev") else 0) | (2 if c.get("a1_prev") else 0)
        blob += struct.pack("<6I3f2I4x", c["fn"], c.get("a0", 0) & 0xFFFFFFFF, c.get("a1", 0) & 0xFFFFFFFF,
                            c.get("a2", 0) & 0xFFFFFFFF, c.get("a3", 0) & 0xFFFFFFFF, c.get("t0", 0) & 0xFFFFFFFF,
                            c.get("f12", 0.0), c.get("f13", 0.0), c.get("f14", 0.0), 0, fl)
    m.wr(DATA + D_CQ, blob)
    done0 = m.u32(DATA + D_CQ_DONE)
    try:
        m.w32(DATA + D_CQ_N, len(calls))
    except RuntimeError:
        # The native dispatcher consumes/clears N in the same frame. Accept a
        # transient read-back mismatch only when this exact batch completed
        # once. The return word is the only field the EE may change in a slot.
        returned = m.rd(DATA + D_CQ, len(blob))
        payload_matches = all(returned[i:i + 0x24] == blob[i:i + 0x24]
                              and returned[i + 0x28:i + CQ_SIZE] == blob[i + 0x28:i + CQ_SIZE]
                              for i in range(0, len(blob), CQ_SIZE))
        if not (payload_matches and m.u32(DATA + D_MAGIC) == MAGIC
                and m.u32(DATA + D_VER) == VERSION and m.u32(DATA + D_BOOT) == 1
                and m.u32(DATA + D_CQ_N) == 0
                and m.u32(DATA + D_CQ_DONE) == ((done0 + 1) & 0xFFFFFFFF)):
            raise
    t = time.time()
    while m.u32(DATA + D_CQ_DONE) == done0:
        if time.time() - t > timeout:
            raise RuntimeError("the game did not run the call queue (paused / menu / not in gameplay?)")
        time.sleep(0.03)
    return [m.u32(DATA + D_CQ + i * CQ_SIZE + 0x24) for i in range(len(calls))]


@_mem_serialized
def install(m: Mem, g) -> dict:
    code, syms = build_cave(g)
    if installed(m, g):
        return {"installed": True, "fresh": False, "cave": hex(CAVE), "code_bytes": len(code)}
    # guard: the hook sites must hold the original instructions (right game / right version)
    has = features(g)
    sites = [(g["hook_frame"], g["hook_frame_fn"])]
    if has["post"]:
        sites.append((g["hook_post"], g["hook_post_fn"]))
    if has["punch"]:
        sites.append((g["punch_site"], g["fn"]["ApplyMoveForce"]))
    for site, fn in sites:
        if m.u32(site) not in (jal_word(fn),):
            raise RuntimeError(f"unexpected code at {site:#x} ({m.u32(site):#010x}): not the expected {g['name']} build")
    if m.u32(g["boot_vt"]) != g["boot_fn"]:
        raise RuntimeError(f"vtable slot {g['boot_vt']:#x} = {m.u32(g['boot_vt']):#x}, expected {g['boot_fn']:#x}")
    if m.u32(DATA + D_MAGIC) != MAGIC:
        if any(m.rd(DATA, 0x1000)) or (any(m.rd(CAVE, len(code))) and m.rd(CAVE, len(code)) != code):
            raise RuntimeError("the cave area 0xF9000-0xFFFFF is in use by something else; not installing")
    cur = m.rd(CAVE, len(code))
    if cur != code:
        if any(cur):
            raise RuntimeError("an older cave is in RAM (EE-compiled, cannot be rewritten from outside): reload the "
                               "game / a savestate from before the install, then install again")
        m.ad.write_memory(CAVE, code)                 # never executed yet -> not write-protected by the recompiler
        if m.rd(CAVE, len(code)) != code:
            raise RuntimeError("cave code write not confirmed")
        m.log.append({"addr": hex(CAVE), "before": "00" * 4, "after": f"<{len(code)} bytes of hook code>"})
    m.wr(DATA, b"\0" * 0x1000)
    m.w32(DATA + D_MAGIC, MAGIC)
    m.w32(DATA + D_VER, VERSION)
    defaults(m, g)
    pq = [(g["hook_frame"], jal_word(syms["dispatch"]))]
    if has["post"]:
        pq.append((g["hook_post"], jal_word(syms["post"])))
    if has["punch"]:
        pq.append((g["punch_site"], jal_word(syms["punch"])))
    m.wr(DATA + D_PQ, b"".join(struct.pack("<II", a, v) for a, v in pq))
    m.w32(DATA + D_PQ_N, len(pq))
    native_restore_ack = False
    try:
        m.w32(g["boot_vt"], syms["boot"])             # the EE runs boot within a frame (player ped processed)
    except RuntimeError:
        # The EE immediately restores this slot. A read-back transport can see
        # that restored value and report a mismatch after a successful boot.
        # Acknowledge only the complete native result; never repeat the write.
        if not (m.rd(CAVE, len(code)) == code
                and m.u32(DATA + D_MAGIC) == MAGIC
                and m.u32(DATA + D_VER) == VERSION
                and m.u32(DATA + D_BOOT) == 1
                and m.u32(DATA + D_PQ_N) == 0
                and m.u32(g["boot_vt"]) == g["boot_fn"]
                and all(m.u32(address) == value for address, value in pq)):
            raise
        native_restore_ack = True
    t = time.time()
    while m.u32(DATA + D_BOOT) != 1:
        if time.time() - t > 8:
            m.w32(g["boot_vt"], g["boot_fn"])
            raise RuntimeError("bootstrap did not run (game paused / not in gameplay?) - vtable restored")
        time.sleep(0.05)
    if not wait_frames(m, 2):
        raise RuntimeError("dispatcher not running after install")
    return {"installed": True, "fresh": True, "cave": hex(CAVE), "code_bytes": len(code),
            **({"bootstrap_ack": "native restored vtable, exact cave/header/hooks and advancing dispatcher"} if native_restore_ack else {}),
            "hooks": {k: hex(g[k]) for k in ("hook_frame", "hook_post", "punch_site") if k in g}}


def defaults(m: Mem, g):
    has = features(g)
    if has["punch"]:
        m.wf(DATA + C_PUNCH_SPEED, mph_to_speed(100))
        m.wf(DATA + C_PUNCH_UP, 0.25)
        m.w32(DATA + C_EXPLODE_TYPE, g["explosion_types"]["car"])
    if has["vehicles"]:
        m.w32(DATA + C_TANK_PERIOD, 60)
        m.wf(DATA + C_TANK_H, 40.0)
        m.wf(DATA + C_TANK_R, 25.0)
        m.w32(DATA + C_TANK_MODEL, g["models"]["rhino"])
        m.w32(DATA + C_TANK_MAXV, 45)
    if has["car_jump"]:
        car_jump_set(m, g, False, 30.0, g.get("pad_default", "l3"))
    if has["ped_rain"]:
        m.w32(DATA + C_PR_RESERVE, 3)


def mph_to_speed(mph):
    """game speed unit = metres per 1/50 s (CTimer step)"""
    return mph * 0.44704 / 50.0


# --- ops -------------------------------------------------------------------------------------------------------------------

def player_ped(m, g):
    return m.u32(g["players"] + m.rd(g["player_focus"], 1)[0] * g["player_stride"] + g["off"]["pl_ped"])


def status(m, g):
    d, has = DATA, features(g)
    cj = {"car_jump": bool(m.u32(d + C_CJ)), "car_jump_height_ft": round(speed_to_feet(g, m.f32(d + C_CJ_V)), 1),
          "car_jumps": m.u32(d + S_CJ)} if has["car_jump"] else {}
    pr = {"ped_rain_left": m.u32(d + C_PR_LEFT), "peds_rained": m.u32(d + S_PR), "ped_rain_waiting_for_pool": m.u32(d + S_PR_FULL),
          "ped_rain_recycled": m.u32(d + S_PR_RECYCLED), "ped_rain_failed": m.u32(d + S_PR_FAIL),
          "ped_pool": ped_pool(m, g)} if has["ped_rain"] else {}
    gta3 = {"punch_launch": bool(m.u32(d + C_PUNCH)), "punch_speed_mph": round(m.f32(d + C_PUNCH_SPEED) * 50 / 0.44704, 1),
            "exploding_punch": bool(m.u32(d + C_EXPLODE)), "tank_rain": bool(m.u32(d + C_TANK)),
            "tank_period_frames": m.u32(d + C_TANK_PERIOD), "giant_scale": m.f32(d + C_SCALE),
            "stats": {"peds_launched": m.u32(d + S_PUNCHED), "impact_explosions": m.u32(d + S_EXPLODED),
                      "tanks_dropped": m.u32(d + S_TANKS)}} if has["punch"] else {}
    return {"installed": installed(m, g), "frame": _frame(m), "ops": supported_ops(g), **cj, **pr, **gta3}


@_adapter_serialized
def run(ad, title, op, on=True, value=None, model=None, radius=None, height=None, explosion=None, button=None,
        count=None, behaviour=None, max_height=None):
    m = Mem(ad)
    if op == "games":
        return {"games": [{"key": k, "name": g["name"], "serial": g["serial"], "ops": supported_ops(g)} for k, g in GAMES.items()]}
    key, g = detect(title)
    res = {"game": g["name"], "op": op}
    if op not in ("status", "install", "uninstall") and op not in supported_ops(g):
        raise ValueError(f"{op} is not mapped for {g['name']} yet; this game supports: {', '.join(supported_ops(g))}")
    if op != "uninstall" and op != "status":
        res["install"] = install(m, g)
    d = DATA
    if op == "status":
        res.update(status(m, g) if m.u32(d + D_MAGIC) == MAGIC else {"installed": False})
    elif op == "install":
        pass
    elif op == "punch_launch":
        if value:
            m.wf(d + C_PUNCH_SPEED, mph_to_speed(float(value)))
        m.w32(d + C_PUNCH, 1 if on else 0)
        res["note"] = "punch a pedestrian: it flies away from the player at the set speed"
    elif op == "exploding_punch":
        if on:
            m.w32(d + C_PUNCH, 1)
        if explosion:
            m.w32(d + C_EXPLODE_TYPE, g["explosion_types"][explosion])
        m.w32(d + C_EXPLODE, 1 if on else 0)
    elif op == "tank_rain":
        if value:
            m.w32(d + C_TANK_PERIOD, max(5, int(float(value) * 50)))     # value = seconds between tanks
        if radius:
            m.wf(d + C_TANK_R, float(radius))
        if height:
            m.wf(d + C_TANK_H, float(height))
        m.w32(d + C_TANK_CNT, 0)
        m.w32(d + C_TANK, 1 if on else 0)
    elif op == "flying_cars":
        m.w32(g["flags"]["flying_cars"], 1 if on else 0)
    elif op == "ped_density":
        m.wf(g["flags"]["ped_density"], float(value if value is not None else 1.0) if on else 1.0)
    elif op == "car_density":
        m.wf(g["flags"]["car_density"], float(value if value is not None else 1.0) if on else 1.0)
    elif op == "super_jump":
        feet = float(value or 100)
        h = feet * 0.3048
        force = (2 * g["gravity"] * h) ** 0.5 * g["ped_mass"] if on else g["jump_default"]
        hi = _f(force) >> 16
        word = (0x0F << 26) | (_R[g["jump_lui_reg"]] << 16) | hi                 # lui reg, hi(force)
        queue_patches(m, [(g["jump_site"], word)])
        res.update(jump_force=round(struct.unpack("<f", struct.pack("<I", hi << 16))[0], 2), feet=feet if on else None)
    elif op == "giant":
        m.wf(d + C_SCALE, float(value or 3.0) if on else 0.0)
    elif op in ("heli", "spawn_vehicle"):
        mdl = int(model or (g["models"]["heli"] if op == "heli" else g["models"]["rhino"]))
        res.update(spawn(m, g, mdl, warp=(op == "heli" or bool(on))))
    elif op == "fast_cars":
        res.update(fast_cars(m, g, float(value or 20) if on else 1.0))
    elif op == "car_jump":                       # value/button left out: keep what is set (the toggle vs the slider)
        cur_v = m.f32(d + C_CJ_V)
        feet = float(value) if value is not None else (speed_to_feet(g, cur_v) if cur_v > 0 else 30.0)
        if max_height:
            feet = min(feet, float(max_height))
        if not button:
            cur = {g["pads"] + n: b for b, (n, _) in g["pad_btn"].items()}.get(m.u32(d + C_CJ_NEW))
            button = cur or g.get("pad_default", "l3")
        res.update(car_jump_set(m, g, bool(on), feet, button))
    elif op == "ped_rain_config":                # sliders: remember count / behaviour / height / radius for the button
        n = count if count is not None else value
        if n is not None:
            m.w32(d + C_CFG_N, int(max(1, min(100, round(float(n))))))
        if behaviour is not None:
            m.wf(d + C_CFG_B, behaviour_value(behaviour))
        if height is not None:
            m.wf(d + C_CFG_H, float(height))
        if radius is not None:
            m.wf(d + C_CFG_R, float(radius))
        res.update(ped_rain_cfg(m))
    elif op == "ped_rain":
        cfg = ped_rain_cfg(m)
        n = count if count is not None else value if value is not None else cfg["count"]
        res.update(ped_rain(m, g, bool(on), n, behaviour if behaviour is not None else cfg["behaviour"],
                            height if height is not None else cfg["height_m"], radius if radius is not None else cfg["radius_m"]))
    else:
        raise ValueError("op: games | status | install | " + " | ".join(supported_ops(g)))
    res["changes"] = [w for w in m.log if w["before"] != w["after"]]
    return res


OPS_NEED = {"punch_launch": "punch", "exploding_punch": "launch", "tank_rain": "vehicles", "spawn_vehicle": "vehicles",
            "heli": "vehicles", "giant": "post", "car_jump": "car_jump", "ped_rain": "ped_rain", "ped_rain_config": "ped_rain",
            "flying_cars": "flags", "ped_density": "flags", "car_density": "flags", "super_jump": "jump_site"}


def supported_ops(g):
    has = features(g)
    return [op for op, k in OPS_NEED.items() if has.get(k) or (k in g and k in ("flags", "jump_site"))]


def car_jump_set(m, g, on, feet, button):
    """car_jump: the vertical launch speed for an apex of `feet` (v^2 = 2 g h in game units), and which stick click."""
    button = str(button).lower().replace(" ", "")
    button = {"left": "l3", "leftstick": "l3", "right": "r3", "rightstick": "r3"}.get(button, button)
    if button not in g["pad_btn"]:
        raise ValueError(f"button: {' | '.join(g['pad_btn'])}")
    feet = max(1.0, min(float(feet), 5000.0))
    v = (2 * g["gravity"] * feet * 0.3048) ** 0.5
    new, old = g["pad_btn"][button]
    m.wf(DATA + C_CJ_V, v)
    m.w32(DATA + C_CJ_NEW, g["pads"] + new)
    m.w32(DATA + C_CJ_OLD, g["pads"] + old)
    m.w32(DATA + C_CJ, 1 if on else 0)
    return {"car_jump": on, "height_ft": round(feet, 1), "button": button.upper(), "launch_speed": round(v, 4),
            "launch_mph": round(v * 50 / 0.44704, 1),
            "note": f"in a vehicle, click {button.upper()}: the vehicle springs straight up ~{feet:.0f} ft (air drag "
                    "takes a little off very high jumps)" if on else "car jump off"}


def speed_to_feet(g, v):
    return v * v / (2 * g["gravity"]) / 0.3048


def ped_pool(m, g):
    p = m.u32(g["ped_pool_ptr"])
    objs, flags, size = struct.unpack("<3I", m.rd(p, 12))
    fl = m.rd(flags, size)
    return {"size": size, "used": sum(1 for b in fl if not b & 0x80), "free": sum(1 for b in fl if b & 0x80)}


def ped_models(m, g):
    """(type, model) of the civilians already in the ped pool: their models are loaded, so AddPed can use them."""
    p = m.u32(g["ped_pool_ptr"])
    objs, flags, size = struct.unpack("<3I", m.rd(p, 12))
    fl, o, found = m.rd(flags, size), g["off"], []
    for i in range(size):
        if fl[i] & 0x80:
            continue
        ped = objs + i * g["ped_stride"]
        typ = m.u32(ped + o["ped_type"])
        mdl = struct.unpack("<h", m.rd(ped + o["model"], 2))[0]
        if typ in (4, 5) and mdl > 0 and (typ, mdl) not in found:
            found.append((typ, mdl))
    return found


def behaviour_value(b):
    """0 = rain .. 1 = splash; accepts 0..1, a 0..100 percentage, or words."""
    if isinstance(b, str):
        t = b.strip().lower().rstrip("%")
        try:
            b = float(t)
        except ValueError:
            b = {"rain": 0.0, "drizzle": 0.0, "shower": 0.3, "mixed": 0.5, "burst": 0.8, "splash": 1.0, "explode": 1.0}.get(t)
            if b is None:
                raise ValueError("behaviour: 0..1 (0 = rain, 1 = splash), a percentage, or rain | splash")
    b = float(b)
    b = b / 100.0 if b > 1.0 else b
    return max(0.0, min(1.0, b))


def ped_rain_cfg(m):
    n, b, h, r = m.u32(DATA + C_CFG_N), m.f32(DATA + C_CFG_B), m.f32(DATA + C_CFG_H), m.f32(DATA + C_CFG_R)
    return {"count": n or 60, "behaviour": round(b, 2), "height_m": h if h > 0 else 25.0, "radius_m": r if r > 0 else 30.0}


def ped_rain(m, g, on, count, behaviour, height, radius):
    """count peds (1-100) fall on the player. behaviour 0 = rain (wide radius, staggered over ~4 s, no push) .. 1 = splash
    (one point above the player, all at once, bursting outward); in between blends the two."""
    d = DATA
    if not on:
        m.w32(d + C_PR_LEFT, 0)
        return {"ped_rain": False, "note": "stopped"}
    b = 0.0 if behaviour is None else behaviour_value(behaviour)
    n = int(max(1, min(100, round(float(count if count is not None else 60)))))
    h = float(height if height is not None else 25.0)
    r_rain = float(radius if radius is not None else 30.0)
    r = max(1.5, r_rain * (1 - b) + 2.0 * b)
    spread_s = 4.0 * (1 - b)                                 # rain: over ~4 s; splash: at once
    fps, period = g.get("fps", 30), 2
    ticks = max(1, int(spread_s * fps / period))
    batch = max(1, min(20, -(-n // ticks)))
    burst = 0.35 * b                                         # m per 1/50 s: 0.35 ~ 17 m/s outward at full splash
    up = 0.12 * b
    models = ped_models(m, g)
    if not models:
        raise RuntimeError("no civilian pedestrians around to copy (their models must be loaded): go somewhere with "
                           "people on the street and try again")
    tbl = b"".join(struct.pack("<II", *models[i % len(models)]) for i in range(8))
    pool = ped_pool(m, g)
    m.wr(d + C_PR_MODELS, tbl)
    m.w32(d + C_PR_PERIOD, period)
    m.w32(d + C_PR_TICK, period)                             # first batch next frame
    m.w32(d + C_PR_BATCH, batch)
    m.wf(d + C_PR_H, h)
    m.wf(d + C_PR_R, r)
    m.wf(d + C_PR_BURST, burst)
    m.wf(d + C_PR_UP, up)
    m.w32(d + C_PR_RESERVE, 3)
    m.w32(d + C_PR_RECYCLE, int(3.0 * fps))                  # peds that have fallen for 3 s make room for new ones
    m.w32(d + C_PR_LEFT, n)                                  # last: starts it
    room = max(0, pool["free"] - 3)
    return {"ped_rain": True, "count": n, "behaviour": round(b, 2),
            "mode": "rain" if b < 0.25 else "splash" if b > 0.75 else "mixed",
            "height_m": h, "radius_m": round(r, 1), "spread_seconds": round(spread_s, 1), "batch_per_2_frames": batch,
            "models": [mdl for _, mdl in models], "ped_pool": pool,
            "note": (f"{n} peds falling from {h:.0f} m" + (f"; the ped pool has room for {room} at once, older fallen peds "
                     "are recycled to make room" if n > room else ""))}


def spawn(m, g, mdl, warp=True):
    f = g["fn"]
    ped = player_ped(m, g)
    pos = struct.unpack("<3f", m.rd(ped + g["off"]["pos"], 12))
    if m.rd(ped + g["off"]["ped_in_veh"], 1)[0]:
        pos = struct.unpack("<3f", m.rd(m.u32(ped + g["off"]["ped_veh"]) + g["off"]["pos"], 12))
    spot = (pos[0] + 4.0, pos[1], pos[2] + 2.0)
    m.wr(DATA + D_SCR + 0x20, struct.pack("<3f", *spot))
    ls = g["info_base"] + mdl * g["info_stride"] + g["info_loadstate"]
    if m.rd(ls, 1)[0] != 1:
        call(m, [{"fn": f["RequestModel"], "a0": mdl, "a1": 0}, {"fn": f["LoadAllRequestedModels"], "a0": 0}])
    calls = [{"fn": CAVE_SYM(g, "spawn_vehicle"), "a0": mdl, "a1": DATA + D_SCR + 0x20, "a2": 2}]
    if warp:
        calls.append({"fn": f["WarpPedIntoCar"], "a0": ped, "a1_prev": True})
    r = call(m, calls)
    if not r[0]:
        raise RuntimeError("vehicle not created (pool full or model not loaded)")
    return {"vehicle": hex(r[0]), "model": mdl, "at": [round(x, 1) for x in spot], "warped": warp,
            "player_in_vehicle": bool(m.rd(ped + g["off"]["ped_in_veh"], 1)[0])}


def CAVE_SYM(g, name):
    return build_cave(g)[1][name]


def fast_cars(m, g, mult):
    raise NotImplementedError


# --- gBox tool ---------------------------------------------------------------------------------------------------------------

class GtaIn(BaseModel):
    session_id: str
    op: str = "status"      # games | status | install | punch_launch | exploding_punch | tank_rain | fast_cars | flying_cars |
                            # super_jump | heli | ped_density | car_density | giant | spawn_vehicle | car_jump | ped_rain
    on: bool = True
    value: float | None = None   # punch_launch: mph (100) | tank_rain: seconds between tanks | fast_cars: multiplier (20) |
                                 # super_jump: feet (100) | ped/car_density: multiplier | giant: scale (3)
    model: int | None = None     # spawn_vehicle / heli: model id
    radius: float | None = None  # tank_rain: drop radius around the player (m)
    height: float | None = None  # tank_rain: drop height above the player (m)
    explosion: str | None = None  # exploding_punch: car | rocket | grenade | ...
    button: str | None = None    # car_jump: l3 | r3 (stick click that launches the car)
    max_height: float | None = None  # car_jump: cap for value (the slider's adjustable maximum, feet)
    count: int | None = None     # ped_rain: how many peds (1-100)
    behaviour: float | str | None = None  # ped_rain: 0 = rain (wide, staggered) .. 1 = splash (one point, burst outward);
                                          # ped_rain_config stores count/behaviour/height/radius for a later plain ped_rain


class GtaOut(BaseModel):
    result: dict


@tool("gta_mods", "1.0", GtaIn, GtaOut, capabilities=["runtime", "memory"], permissions=[P.MEMORY_WRITE], timeout_s=120)
def gta_mods(inp: GtaIn, ctx):
    """PS2 GTA live mods. GTA III: punch launch (peds fly at ~100 mph), exploding impact, tank rain, flying cars, 100-ft
    super jump, spawn into a helicopter, ped/car density, giant player. GTA III + Liberty City Stories: car_jump (click L3/R3
    while driving: the car springs straight up value feet) and ped_rain (count peds fall on the player; behaviour 0 rain ..
    1 splash). Installs a tiny EE hook once per boot; each write read back."""
    from .tools import SESSIONS
    ad, g = SESSIONS[inp.session_id]
    return {"result": run(ad, g.get("title", ""), inp.op, inp.on, inp.value, inp.model, inp.radius, inp.height,
                          inp.explosion, inp.button, inp.count, inp.behaviour, inp.max_height)}
