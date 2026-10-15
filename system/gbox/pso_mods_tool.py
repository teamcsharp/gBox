"""Phantasy Star Online Ver. 2 (Dreamcast, US 2OEF) live mods: max meseta, always-critical, equip anything, give items,
floor items, attack speed. Register with:  from . import pso_mods_tool  # noqa: F401

How it works
- Plain RAM: meseta = u32 at TObjPlayer+0xC20 (TObjPlayer = *(u32*)0x8C42D92C). The in-game menu reads this one; the
  saved-character copy (*(u32*)0x8C4EC4E0 + 0x36C) is written too so it survives a save.
- Code patches (16-bit SH-4 instructions, the original bytes are checked before patching and restored on off):
    crit_always: 0x8C047BC0  bt (891A) -> nop  (player damage routine: crit roll rand*500 vs min(LCK,100), then x1.5)
    equip_any  : 0x8C1638CC  mov.b @r12,r0 (60C0) -> mov #5,r0 (E005)  (equip check: item-type switch -> no restriction
                 flags; same idea as the GameCube "God of equip" code)
- Game-function calls: a tiny SH-4 dispatcher is written into an online-only network handler (0x8C02DD30.., never
  run offline; newserv's DC patches use the same area) and TObjPlayer's vtable update slot (0x8C26C848) is pointed at
  it. Each frame the dispatcher runs up to 8 queued calls {fn, r4..r7} and then jumps to the original update
  (0x8C0216F4). gBox uses it to call the game's own routines:
    floor item:   0x8C1631C8(FloorItem*, 0)    (what the 6x5F "drop item" handler calls)
    give item:    6x2B "create inventory item" sequence: 0x8C1CA46C(item,0), 0x8C1C9C98(item), obj=0x8C0735D8(item),
                  player->vtable[0x130](player, obj)
- move_speed: the CAVE2 TObjPlayer::update wrapper (same cave as attack_speed) runs the player's own update an extra
  N-1 times per frame, so the per-frame move routine (the step it adds to the player's position at TObjPlayer +0x3C/+0x44
  = analog magnitude x a speed constant, applied through 0x8C02AE70) advances N x per frame: the player moves N x faster.
  SPEED_VARS+0x10 = move extra updates (0 = off).
- key_bypass: the Hunter's License serial/access-key check. Two near-identical validators (0x8C1E73E4 and 0x8C26705C)
  count the 8 serial characters and then call the key verifier at a jsr (0x8C1E743E and 0x8C2670B6, both 400B jsr @r0).
  Patching that jsr -> mov #1,r0 (E001) forces the verifier result to 1 (valid) and the title accepts any key. No live
  player object is needed, so it applies on the key-entry screen itself; original bytes are restored on off.
- rare_drops: the loaded ItemRT rare-drop table in RAM (found by its ItemRT.afs content signature) is rewritten so every
  monster and box slot drops an item from a configurable list of the rarest items at the format's maximum chance. Offline
  enemy kills then roll from this copy and the game's own offline drop path (which ends in the floor-item create at
  0x8C1631C8) drops a rare. The original 640-byte table is kept and restored on off.
"""
import struct
import time

from pydantic import BaseModel, Field

from .models import Permission as P
from .registry import Unsupported, tool
from .pso_controls import serialized

PLAYER_TBL = 0x8C42D92C
CHAR_PTR = 0x8C4EC4E0
MESETA_OFF, CHAR_MESETA_OFF = 0xC20, 0x36C
FLOOR_NOW = 0x8C45C904
PATCHES = {   # name: (address or (addresses,), original, patched); every listed site is checked and written together
    "crit_always": (0x8C047BC0, bytes.fromhex("1a89"), bytes.fromhex("0900")),
    "equip_any": (0x8C1638CC, bytes.fromhex("c060"), bytes.fromhex("05e0")),
    "key_bypass": ((0x8C1E743E, 0x8C2670B6), bytes.fromhex("0b40"), bytes.fromhex("01e0")),
}
NO_PLAYER_OPS = {"key_bypass"}                   # applied at the title/key screen, before a TObjPlayer exists
SIGNATURE = (0x8C2F3014, b"TObjPlayer")          # same check as the pso-v2-dc-us profile
VT_UPDATE, ORIG_UPDATE = 0x8C26C848, 0x8C0216F4
CAVE, QUEUE, BUF = 0x8C02DD30, 0x8C02DE00, 0x8C02DED0
CAVE_ORIG_HEAD = bytes.fromhex("e62f224f")
CAVE2, CAVE2_END = 0x8C02DF90, 0x8C02E098            # second online-only handler: speed / rapid-fire wrapper + vars
CAVE2_ORIG_HEAD = bytes.fromhex("e62fd62f")
SPEED_VARS = 0x8C02E080                              # u32 rapid-fire mask, period (frames), counter, attack extra, move extra
MOVE_EXTRA_OFF = 0x10                                # SPEED_VARS + 0x10: u32 extra player updates per frame (move_speed)
SPEED_VARS_LEN = 0x14                                # 5 u32 in the 0x8C02E080..0x8C02E098 var block
PAD_HELD = 0x8C42D6C0                                # port A: +0 buttons held, +8 pressed this frame (0x400 = attack 'y')
ACTION_STATE = 0x30E                                 # TObjPlayer u16: 1 while an attack is running (5 standing)       # first bytes of the online handler we overwrite (sanity check)
QMAX, BUF_END = 8, 0x8C02DF90
NEXT_ID = 0x8C02DDF8                              # u32 in the cave: next gBox item id (ids must be unique or the game
ID_BASE = 0x00F00000                              # refuses to create the item)
F_FLOOR_CREATE = 0x8C1631C8
F_ITEM_FIX, F_ITEM_NORM, F_ITEM_OBJ = 0x8C1CA46C, 0x8C1C9C98, 0x8C0735D8
F_EQUIP = 0x8C022428                              # (player, TItem*, slot): what the 6x25 "equip item" handler calls
EQUIPPED = {"mag": 0xBD0, "armor": 0xBD4, "weapon": 0xBE4}   # TObjPlayer -> equipped TItem*
EQUIP_SLOTS = 0xBCC                               # 7 equip slot pointers (index = item vtable+0x80()); 6 = weapon
ITEM_FLAGS = 0xE4                                 # TItem u32: 1 = in inventory, |2 = equipped (E marker)
ITEM_RECORD = 0x134                               # TItem: the 20-byte item data record, data bytes spaced 2 apart
BASE_STATS = 0xC00                                # TObjPlayer: character base stats u16 atp mst evp hp dfp ata lck
STATS = ["atp", "mst", "evp", "hp", "dfp", "ata", "lck"]
LIVE = {"atp": (0x1A2, 0x1AA), "evp": (0x1A6, 0x1AE), "dfp": (0x1A8, 0x1B0), "ata": (0x1B2,), "lck": (0x1B4,),
        "hp": (0x198,)}                           # hp: max HP (current HP u16 at +0x330, TP +0x332, max TP +0x19A)
FLOOR_TBL, FLOOR_CNT, FLOOR_REC = 0x8C4ECDC4, 0x8C4ECDC8, 36   # per-floor sorted FloorItem arrays (id at +28)
F_FLOOR_DELETE = 0x8C192FDC                       # 6x63 handler (packet: hdr, u32 item_id, u32 floor): unlist + vanish
F_DELETE_INV = 0x8C023484                         # (player, item_id, amount): what the 6x29 "delete inventory item" handler calls
PLY_ITEM = 0xBC8                                  # TObjPlayer -> TPlyItem; its child TItemList's children = inventory nodes
F_RECALC = 0x8C025570                             # (player): recompute live stats from base stats + equipment, clamp HP/TP
ATP_SPREAD = 0x1A4                                # shown ATP = live atp + this (weapon part)
# ItemRT rare-drop table (PSO V2 DC): the game copies the on-disc ItemRT.afs table for the current difficulty+section
# into RAM. Each 640-byte table = 101 monster slots then a 30-byte box-area map then 30 box rare slots; a slot is a
# packed probability byte + a 3-byte item code. rare_drops rewrites every slot to a rare from a list at the max chance.
RT_ENTRY, RT_MON_SLOTS = 640, 101
RT_BOX_AREAS_AT, RT_BOX_SLOTS, RT_BOX_RARES_AT = 404, 30, 434
RT_MAX_PROB = 0xFF                                 # the format's maximum packed probability
ITEMRT_AFS_SHA = "57591915246c6b60fd5cb2348091ce57b7bbeee4aaf05b2529fc24e4b60132da"   # pso-v2-dc-us profile drop_tables
# Defaults: the rarest weapons, frames, barriers and units for 2OEF (real PSO item codes).
RARE_DROPS = ["000107", "000207", "001000", "001100", "001200", "001d00", "001e00", "001f00", "003200",   # weapons
              "010133", "010128", "010131",                                                               # frames
              "010227", "010226", "01022c", "010229",                                                     # barriers
              "010320", "010335", "010341", "01033b"]                                                     # units


# --- minimal SH-4 assembler (only what the stubs need) ---------------------------------------------------------------
def _asm(lines: list, base: int, want_labels: bool = False):
    """lines: ("op", args...) tuples or "label:" strings or (".long", value|label). Two passes for labels/literals."""
    def size(x):
        return 0 if isinstance(x, str) else 4 if x[0] == ".long" else 0 if x[0] == ".align" else 2
    labels, pc = {}, base
    for x in lines:
        if isinstance(x, str):
            labels[x.rstrip(":")] = pc
        elif x[0] == ".align":
            pc = (pc + 3) & ~3
        else:
            pc += size(x)
    out, pc = bytearray(), base

    def r(s):
        return int(s[1:])
    for x in lines:
        if isinstance(x, str):
            continue
        op, *a = x
        if op == ".align":
            while pc & 3:
                out += b"\x09\x00"; pc += 2                  # nop padding
            continue
        if op == ".long":
            v = labels[a[0]] if isinstance(a[0], str) else a[0]
            out += struct.pack("<I", v); pc += 4; continue
        if op == "push":   w = 0x2006 | r(a[0]) << 4 | 15 << 8          # mov.l Rm,@-r15
        elif op == "pop":  w = 0x6006 | 15 << 4 | r(a[0]) << 8          # mov.l @r15+,Rn
        elif op == "pushpr": w = 0x4F22
        elif op == "poppr":  w = 0x4F26
        elif op == "ldl":   # mov.l label,Rn (PC-relative literal)
            t = labels[a[0]]; d = (t - ((pc + 4) & ~3)) // 4
            assert 0 <= d < 256 and t % 4 == 0, (a, hex(t), hex(pc))
            w = 0xD000 | r(a[1]) << 8 | d
        elif op == "ld":    w = 0x6002 | r(a[0]) << 4 | r(a[1]) << 8    # mov.l @Rm,Rn
        elif op == "st":    w = 0x2002 | r(a[0]) << 4 | r(a[1]) << 8    # mov.l Rm,@Rn
        elif op == "ldd":   w = 0x5000 | r(a[1]) << 4 | r(a[2]) << 8 | a[0] // 4    # mov.l @(d,Rm),Rn
        elif op == "std":   w = 0x1000 | r(a[0]) << 4 | r(a[2]) << 8 | a[1] // 4    # mov.l Rm,@(d,Rn)
        elif op == "ldr0":  w = 0x000E | r(a[0]) << 4 | r(a[1]) << 8    # mov.l @(r0,Rm),Rn
        elif op == "tst":   w = 0x2008 | r(a[0]) << 4 | r(a[1]) << 8
        elif op == "and":   w = 0x2009 | r(a[0]) << 4 | r(a[1]) << 8
        elif op == "or":    w = 0x200B | r(a[0]) << 4 | r(a[1]) << 8
        elif op == "cmpge": w = 0x3003 | r(a[0]) << 4 | r(a[1]) << 8     # cmp/ge Rm,Rn: T = Rn >= Rm
        elif op == "cmpeq0": w = 0x8800 | (a[0] & 0xFF)                   # cmp/eq #imm,r0
        elif op == "ldwr0": w = 0x000D | r(a[0]) << 4 | r(a[1]) << 8    # mov.w @(r0,Rm),Rn
        elif op == "mov":   w = 0x6003 | r(a[0]) << 4 | r(a[1]) << 8
        elif op == "movi":  w = 0xE000 | r(a[1]) << 8 | (a[0] & 0xFF)
        elif op == "addi":  w = 0x7000 | r(a[1]) << 8 | (a[0] & 0xFF)
        elif op == "jsr":   w = 0x400B | r(a[0]) << 8
        elif op == "jmp":   w = 0x402B | r(a[0]) << 8
        elif op == "rts":   w = 0x000B
        elif op == "nop":   w = 0x0009
        elif op in ("bt", "bf", "bra"):
            d = (labels[a[0]] - (pc + 4)) // 2
            if op == "bra":
                assert -2048 <= d < 2048; w = 0xA000 | (d & 0xFFF)
            else:
                assert -128 <= d < 128; w = (0x8900 if op == "bt" else 0x8B00) | (d & 0xFF)
        else:
            raise ValueError(op)
        out += struct.pack("<H", w); pc += 2
    return (bytes(out), labels) if want_labels else bytes(out)


def stub_code(want_labels: bool = False):
    """Dispatcher (entered as TObjPlayer::update, r4 = this) + give(item_data*) helper."""
    return _asm([
        # dispatcher: run queue entries {fn,r4,r5,r6,r7,result} then tail-jump to the original update
        ("push", "r4"), ("pushpr",), ("push", "r8"), ("push", "r9"),
        ("ldl", "Q", "r8"), ("ld", "r8", "r9"), ("tst", "r9", "r9"), ("bt", "done"),
        ("mov", "r8", "r1"), ("addi", 8, "r1"),
        "loop:",
        ("push", "r1"),
        ("ldd", 4, "r1", "r4"), ("ldd", 8, "r1", "r5"), ("ldd", 12, "r1", "r6"), ("ldd", 16, "r1", "r7"),
        ("ld", "r1", "r0"), ("jsr", "r0"), ("nop",),
        ("pop", "r1"), ("std", "r0", 20, "r1"), ("addi", 24, "r1"),
        ("addi", -1, "r9"), ("tst", "r9", "r9"), ("bf", "loop"),
        ("movi", 0, "r0"), ("st", "r0", "r8"),
        ("ldd", 4, "r8", "r0"), ("addi", 1, "r0"), ("std", "r0", 4, "r8"),
        "done:",
        ("pop", "r9"), ("pop", "r8"), ("poppr",), ("pop", "r4"),
        ("ldl", "ORIG", "r0"), ("jmp", "r0"), ("nop",),
        (".align",),
        "Q:", (".long", QUEUE),
        "ORIG:", (".long", CAVE2),                 # -> speed/rapid-fire wrapper, which ends in the original update
        # give(r4 = item data, 20 bytes): the 6x2B "create inventory item" sequence for player 0. Returns the TItem or 0.
        "give:",
        ("push", "r14"), ("push", "r13"), ("pushpr",),
        ("mov", "r4", "r14"),
        ("ldl", "PT", "r0"), ("ld", "r0", "r13"), ("tst", "r13", "r13"), ("bt", "gfail"),
        ("ldl", "FFIX", "r0"), ("mov", "r14", "r4"), ("jsr", "r0"), ("movi", 0, "r5"),
        ("ldl", "FNORM", "r0"), ("jsr", "r0"), ("mov", "r14", "r4"),
        ("ldl", "FOBJ", "r0"), ("jsr", "r0"), ("mov", "r14", "r4"),
        ("tst", "r0", "r0"), ("bt", "gfail"),
        ("mov", "r0", "r5"), ("mov", "r0", "r14"), ("mov", "r13", "r4"),
        ("ldd", 24, "r4", "r1"), ("ldl", "O130", "r0"), ("ldr0", "r1", "r0"), ("jsr", "r0"), ("nop",),
        ("mov", "r14", "r0"), ("bra", "gout"), ("nop",),
        "gfail:", ("movi", 0, "r0"),
        "gout:", ("poppr",), ("pop", "r13"), ("rts",), ("pop", "r14"),
        (".align",),
        "PT:", (".long", PLAYER_TBL),
        "FFIX:", (".long", F_ITEM_FIX),
        "FNORM:", (".long", F_ITEM_NORM),
        "FOBJ:", (".long", F_ITEM_OBJ),
        "O130:", (".long", 0x130),
        # store4(r4 = address, r5 = value): lets a batch of pointer writes land atomically between two game frames
        "store4:", ("st", "r5", "r4"), ("rts",), ("nop",),
    ], CAVE, want_labels)


def speed_code() -> bytes:
    """TObjPlayer::update wrapper (second cave): rapid fire (while the attack button is held, re-press it every PERIOD
    frames in the pad's pressed-this-frame mask); attack speed (while the player is in the attack state, run the original
    update ATTACK-EXTRA more times per frame); move speed (run the original update MOVE-EXTRA more times per frame every
    frame, so the per-frame move step advances that many extra times - the player moves N x faster); then the original
    update once more. The two extra-update counts (attack, move) are independent so each op toggles on its own."""
    return _asm([
        ("push", "r14"), ("push", "r13"), ("pushpr",), ("mov", "r4", "r14"),
        ("ldl", "VARS", "r2"), ("ldd", 0, "r2", "r1"),              # r1 = rapid-fire button mask (0 = off)
        ("tst", "r1", "r1"), ("bt", "spd"),
        ("ldl", "PAD", "r5"), ("ld", "r5", "r3"), ("and", "r1", "r3"), ("tst", "r3", "r3"), ("bt", "rfreset"),
        ("ldd", 8, "r2", "r3"), ("addi", 1, "r3"), ("std", "r3", 8, "r2"),       # count++
        ("ldd", 4, "r2", "r0"), ("cmpge", "r0", "r3"), ("bf", "spd"),            # count >= period ?
        ("movi", 0, "r3"), ("std", "r3", 8, "r2"),
        ("ldd", 8, "r5", "r3"), ("or", "r1", "r3"), ("std", "r3", 8, "r5"),      # pressed |= mask
        ("bra", "spd"), ("nop",),
        "rfreset:", ("movi", 0, "r3"), ("std", "r3", 8, "r2"),
        "spd:", ("ldd", 12, "r2", "r13"),                                         # r13 = attack extra updates
        "sploop:", ("tst", "r13", "r13"), ("bt", "amove"),
        ("ldl", "OST", "r0"), ("ldwr0", "r14", "r0"), ("cmpeq0", 1), ("bf", "amove"),   # attacking?
        ("ldl", "ORIG2", "r0"), ("jsr", "r0"), ("mov", "r14", "r4"),
        ("addi", -1, "r13"), ("bra", "sploop"), ("nop",),
        "amove:", ("ldl", "VARS", "r2"), ("ldd", 16, "r2", "r13"),                # r2 clobbered by the jsr above; reload
        "mvloop:", ("tst", "r13", "r13"), ("bt", "splast"),                       # r13 = move extra updates (every frame)
        ("ldl", "ORIG2", "r0"), ("jsr", "r0"), ("mov", "r14", "r4"),
        ("addi", -1, "r13"), ("bra", "mvloop"), ("nop",),
        "splast:", ("mov", "r14", "r4"), ("poppr",), ("pop", "r13"), ("pop", "r14"),
        ("ldl", "ORIG2", "r0"), ("jmp", "r0"), ("nop",),
        (".align",),
        "PAD:", (".long", PAD_HELD),
        "VARS:", (".long", SPEED_VARS),
        "OST:", (".long", ACTION_STATE),
        "ORIG2:", (".long", ORIG_UPDATE),
    ], CAVE2)


def give_addr() -> int:
    return stub_code(True)[1]["give"]


def store4_addr() -> int:
    return stub_code(True)[1]["store4"]


class PSO:
    """Live PSO DC v2 mods over read(addr, n) / write(addr, bytes)."""

    def __init__(self, read, write):
        self.read, self.write = read, write
        self._rare_orig = {}                       # ItemRT table addr -> original 640 bytes (for rare_drops off)

    def u32(self, a):
        return struct.unpack("<I", self.read(a, 4))[0]

    def check(self, require_player=True):
        a, s = SIGNATURE
        if self.read(a, len(s)) != s:
            raise Unsupported("not Phantasy Star Online Ver. 2 (Dreamcast, US) - signature TObjPlayer missing")
        p = self.u32(PLAYER_TBL)
        if require_player and not 0x8C000000 <= p < 0x8D000000:
            raise RuntimeError("no player object yet: start a game first")
        return p

    # --- plain RAM ---
    def meseta(self, value=None):
        p = self.check()
        if value is not None:
            v = max(0, min(999999, int(value)))
            self.write(p + MESETA_OFF, struct.pack("<I", v))
            c = self.u32(CHAR_PTR)
            if 0x8C000000 <= c < 0x8D000000:
                self.write(c + CHAR_MESETA_OFF, struct.pack("<I", v))
        return self.u32(p + MESETA_OFF)

    # --- code patches ---
    @staticmethod
    def _patch_addrs(name):
        a = PATCHES[name][0]
        return a if isinstance(a, tuple) else (a,)

    def patch(self, name, on: bool):
        addrs, orig, new = self._patch_addrs(name), PATCHES[name][1], PATCHES[name][2]
        for a in addrs:                                # verify every site before touching any
            cur = self.read(a, len(orig))
            if cur not in (orig, new):
                raise Unsupported(f"{name}: unexpected code at {a:#x} ({cur.hex()}) - different game version?")
        want = new if on else orig
        for a in addrs:
            self.write(a, want)
        return all(self.read(a, len(orig)) == want for a in addrs)

    def patch_state(self, name):
        addrs, orig, new = self._patch_addrs(name), PATCHES[name][1], PATCHES[name][2]
        states = {"on" if self.read(a, len(orig)) == new else "off" if self.read(a, len(orig)) == orig else "unknown"
                  for a in addrs}
        return states.pop() if len(states) == 1 else "partial"

    # --- game-function calls ---
    def hook(self):
        """Install the dispatcher (idempotent). Returns True when the player's update runs through it."""
        self.check()
        sc = speed_code()
        assert CAVE2 + len(sc) <= SPEED_VARS
        if self.read(CAVE2, len(sc)) != sc:
            head = self.read(CAVE2, 4)
            if head != CAVE2_ORIG_HEAD and head != sc[:4]:
                raise Unsupported(f"code cave {CAVE2:#x} holds unexpected bytes {head.hex()}")
            self.write(SPEED_VARS, b"\0" * SPEED_VARS_LEN)
            self.write(CAVE2, sc)
        code = stub_code()
        if self.read(CAVE, len(code)) != code:
            head = self.read(CAVE, 4)
            if head != CAVE_ORIG_HEAD and head != code[:4]:
                raise Unsupported(f"code cave {CAVE:#x} holds unexpected bytes {head.hex()}")
            self.write(QUEUE, b"\0" * 8)
            self.write(CAVE, code)
        if self.u32(VT_UPDATE) != CAVE:
            if self.u32(VT_UPDATE) != ORIG_UPDATE:
                raise Unsupported(f"TObjPlayer vtable update is {self.u32(VT_UPDATE):#x}, expected {ORIG_UPDATE:#x}")
            self.write(VT_UPDATE, struct.pack("<I", CAVE))
        return self.u32(VT_UPDATE) == CAVE

    def unhook(self):
        if self.u32(VT_UPDATE) == CAVE:
            self.write(VT_UPDATE, struct.pack("<I", ORIG_UPDATE))

    def call(self, calls: list, timeout: float = 10.0) -> list:
        """calls: [(fn, r4, r5, r6, r7)] (<= 8) run in order on the game thread during the next player update."""
        assert 0 < len(calls) <= QMAX
        self.hook()
        if self.u32(QUEUE):
            raise RuntimeError("a previous call batch is still pending (is the game paused or the player gone?)")
        seq = self.u32(QUEUE + 4)
        ent = b"".join(struct.pack("<6I", *(list(c) + [0] * (5 - len(c))), 0) for c in calls)
        self.write(QUEUE + 8, ent)
        try:
            self.write(QUEUE, struct.pack("<I", len(calls)))
        except RuntimeError:          # read-back raced the game thread, which already ran the batch and cleared the count
            pass
        t = time.time()
        while time.time() - t < timeout:
            if self.u32(QUEUE + 4) != seq:
                return [self.u32(QUEUE + 8 + 24 * i + 20) for i in range(len(calls))]
            time.sleep(0.05)
        self.write(QUEUE, b"\0\0\0\0")
        raise RuntimeError("the game did not run the queued calls (paused, menu open, or no player update)")

    # --- items ---
    @staticmethod
    def item_data(code: str, item_id: int, number: int = 1) -> bytes:
        c = bytes.fromhex(code)[:3]
        d = bytearray(20)
        d[0:len(c)] = c
        if d[0] == 3:
            d[5] = max(1, number)                 # stackable tools keep the count in byte 5
        if d[0] == 2:                              # mags: level 5 defaults like a fresh mag (DEF 5 / def 500 bytes)
            d[3] = 5
        struct.pack_into("<I", d, 12, item_id)
        return bytes(d)

    def next_ids(self, n: int) -> int:
        cur = self.u32(NEXT_ID)
        if not ID_BASE <= cur < ID_BASE + 0xF0000:      # fresh RAM: random start so ids saved with older items don't clash
            cur = ID_BASE + (int(time.time() * 7) % 0xE000) * 16
        self.write(NEXT_ID, struct.pack("<I", cur + n))
        return cur

    def give(self, code: str, count: int = 1, item_id0: int | None = None) -> list:
        """Create `count` real inventory items for player 0 through the game's own 6x2B path. Returns TItem pointers."""
        item_id0 = self.next_ids(count) if item_id0 is None else item_id0
        return self.give_records([self.item_data(code, item_id0 + i) for i in range(count)])

    def give_records(self, records: list[bytes]) -> list:
        """Create one real inventory item per 20-byte item record through the game's own 6x2B path."""
        g = give_addr()
        self.hook()
        made, n = [], 0
        while n < len(records):
            k = min(QMAX, len(records) - n, (BUF_END - BUF) // 24)
            calls = []
            for i in range(k):
                a = BUF + 24 * i
                self.write(a, records[n + i])
                calls.append((g, a))
            made += self.call(calls)
            n += k
        return made

    def item_record(self, obj: int) -> bytes:
        """The 20-byte item data record stored in a TItem (data bytes spaced 2 apart from ITEM_RECORD)."""
        if not 0x8C000000 <= obj < 0x8D000000:
            raise ValueError(f"not an item object: {obj:#x}")
        return bytes(self.read(obj + ITEM_RECORD + 2 * i, 1)[0] for i in range(20))

    def dupe(self, target, count: int = 1, equip: bool = False) -> dict:
        """Clone an inventory item exactly: read its live 20-byte record (stats, percentages, grind and stack count
        all come along) and create `count` copies through the game's own 6x2B create-item path - the classic dupe
        glitch, without the disconnect trick. equip: also equip the first copy (the 6x25 path)."""
        p = self.check()
        x = self._find(target)
        if x is None:
            raise ValueError(f"no inventory item matches {target!r}")
        rec = self.item_record(x["obj"])
        if struct.unpack("<I", rec[12:16])[0] != x["id"]:
            raise RuntimeError(f"item {x['code']} record id mismatch ({rec[12:16].hex()} vs {x['id']:#x}) - "
                               f"different game version or wrong record offset?")
        ids = self.next_ids(count)
        records = []
        for i in range(count):
            r = bytearray(rec)
            struct.pack_into("<I", r, 12, ids + i)          # every copy needs its own unique id
            records.append(bytes(r))
        made = self.give_records(records)
        equipped = False
        if equip:
            first = next((o for o in made if o), None)
            equipped = bool(first) and self.equip(first)
        inv2 = self.inventory()
        return {"source": {"slot": x["slot"], "code": x["code"], "equipped": x["equipped"], "id": hex(x["id"])},
                "created": sum(1 for o in made if o), "requested": count, "objects": [hex(o) for o in made if o],
                "record": rec.hex(), "equipped_first": equipped,
                "slots_with_code_now": [y["slot"] for y in inv2 if y["code"] == x["code"]],
                "verified": sum(1 for o in made if o) == count}

    def equip(self, obj: int, slot: int = 0) -> bool:
        """Equip an inventory TItem the way the 6x25 handler does (the old item in that slot comes off)."""
        if not 0x8C000000 <= obj < 0x8D000000:
            raise ValueError(f"not an item object: {obj:#x}")
        p = self.check()
        self.call([(F_EQUIP, p, obj, slot)])
        return obj in [self.u32(p + o) for o in EQUIPPED.values()]

    def recompute(self):
        """Make the game recompute the live stats from the base stats + equipment (its own routine)."""
        self.call([(F_RECALC, self.check())])
        return "game"

    def shown_stat(self, name: str):
        p = self.check()
        if name not in LIVE:
            return None
        v = struct.unpack("<H", self.read(p + LIVE[name][0], 2))[0]
        return v + (struct.unpack("<H", self.read(p + ATP_SPREAD, 2))[0] if name == "atp" else 0)

    def set_stat(self, name: str, value: int) -> dict:
        """Set a stat so the status screen shows `value`. The character's base stat (which the game recomputes the live
        stats from on every equip/level change, and which is saved) is adjusted and the game's own recompute is run;
        stats with equipment/class factors (ATA, max HP) are converged in a few rounds."""
        name = name.lower()
        if name not in STATS:
            raise ValueError(f"stat must be one of {STATS}")
        p = self.check()
        a = p + BASE_STATS + 2 * STATS.index(name)
        rd = lambda: struct.unpack("<H", self.read(a, 2))[0]
        base0 = base = rd()
        shown0 = shown = self.shown_stat(name)
        target = int(value)
        if shown is None:                          # mst: the status screen shows the base value
            self.write(a, struct.pack("<H", max(0, min(9999, target))))
            self.recompute()
        else:
            slope = 1.0
            for _ in range(6):
                if shown == target:
                    break
                new = max(0, min(9999, round(base + (target - shown) / slope)))
                if new == base:
                    break
                self.write(a, struct.pack("<H", new))
                self.recompute()
                now = self.shown_stat(name)
                if now != shown and new != base:
                    slope = max(0.05, (now - shown) / (new - base))
                base, shown = new, now
        if name == "hp":                            # fill current HP to the new max
            self.write(p + 0x330, self.read(p + 0x198, 2))
        return {"stat": name, "base_was": base0, "base_now": rd(), "shown_was": shown0,
                "shown_now": self.shown_stat(name) if shown0 is not None else rd(), "target": target,
                "verified": (self.shown_stat(name) if shown0 is not None else rd()) == target}

    def inventory(self) -> list:
        """Live inventory in menu order from the game's objects: [{slot, node, obj, id, code, equipped, cls}]."""
        p = self.check()
        root = self.u32(self.u32(p + PLY_ITEM) + 0x14)
        eq = {self.u32(p + o): k for k, o in EQUIPPED.items()}
        out, n = [], self.u32(root + 0x14)
        while 0x8C000000 <= n < 0x8D000000 and len(out) < 40:
            o = self.u32(n + 0x20)
            if 0x8C000000 <= o < 0x8D000000:
                t = self.read(o + 0x134, 6)
                code = bytes([t[0], t[2], t[4]]) if t[0] != 2 else bytes([2, t[2], 0])
                cls = self.read(self.u32(o), 32).split(b"\0")[0].decode("latin-1")
                out.append({"slot": len(out), "node": n, "obj": o, "id": self.u32(o + 0xE8), "code": code.hex(),
                            "equipped": eq.get(o), "cls": cls})
            n = self.u32(n + 0xC)
        return out

    def _move_node(self, node: int, before: int | None):
        """Relink inventory node `node` (currently anywhere) in front of `before` (None = end), in one game frame."""
        p = self.check()
        root = self.u32(self.u32(p + PLY_ITEM) + 0x14)
        order = [x["node"] for x in self.inventory()]
        if node not in order or before == node:
            return
        order.remove(node)
        order.insert(order.index(before) if before in order else len(order), node)
        s4, w = store4_addr(), []
        for i, nd in enumerate(order):                   # only the pointers that change (<= 6 for a move): one batch
            want_prev = order[i - 1]                     # (first node's prev = last node, as the game keeps it)
            want_next = order[i + 1] if i + 1 < len(order) else 0
            if self.u32(nd + 0x8) != want_prev:
                w.append((s4, nd + 0x8, want_prev))
            if self.u32(nd + 0xC) != want_next:
                w.append((s4, nd + 0xC, want_next))
        if self.u32(root + 0x14) != order[0]:
            w.append((s4, root + 0x14, order[0]))
        if len(w) > QMAX:
            raise RuntimeError("inventory relink needs more writes than one frame batch")
        if w:
            self.call(w)

    def _find(self, target, inv=None):
        inv = inv if inv is not None else self.inventory()
        t = str(target).strip().lower()
        if t.isdigit() and len(t) <= 2:
            return next((x for x in inv if x["slot"] == int(t)), None)
        if t in EQUIPPED:
            return next((x for x in inv if x["equipped"] == t), None)
        return next((x for x in inv if x["code"] == t and not self.is_equipped(x["obj"])), None) or             next((x for x in inv if x["code"] == t), None)

    def is_equipped(self, obj: int) -> bool:
        return bool(self.u32(obj + ITEM_FLAGS) & 2)

    def multi_equip(self, target, on: bool = True) -> dict:
        """The multi-equip bug on purpose: run the item's own on-equip (vtable+0x54) without the 6x25 path's unequip of the
        slot's current item, so several weapons/units are equipped (E marker) and their stats stack. on=false: run
        on-unequip (vtable+0x58) on every extra item (equipped flag set but not in an equip slot)."""
        p = self.check()
        slots = {self.u32(p + EQUIP_SLOTS + 4 * i) for i in range(7)}
        inv = self.inventory()
        if on:
            x = self._find(target, inv)
            if x is None:
                raise ValueError(f"no inventory item matches {target!r}")
            if not self.is_equipped(x["obj"]):
                vt = self.u32(x["obj"] + 0x18)
                self.call([(self.u32(vt + 0x54), x["obj"]), (F_RECALC, p)])
            changed = [x]
        else:
            changed = [x for x in inv if self.is_equipped(x["obj"]) and x["obj"] not in slots
                       and (not str(target).strip() or x is self._find(target, inv))]
            calls = [(self.u32(self.u32(x["obj"] + 0x18) + 0x58), x["obj"]) for x in changed]
            for b in range(0, len(calls), QMAX - 1):
                self.call(calls[b:b + QMAX - 1] + [(F_RECALC, p)])
        inv2 = self.inventory()
        eq = [{"slot": x["slot"], "code": x["code"]} for x in inv2 if self.is_equipped(x["obj"])]
        return {"changed": [{"slot": x["slot"], "code": x["code"]} for x in changed], "equipped_now": eq,
                "atp": self.shown_stat("atp"), "dfp": self.shown_stat("dfp"), "ata": self.shown_stat("ata"),
                "verified": all(self.is_equipped(x["obj"]) == on for x in changed)}

    def item_set(self, target, code: str) -> dict:
        """Replace one inventory item by `code`: create the new item through the game's 6x2B path, equip it if the old
        one was equipped, delete the old one (6x29 path) and put the new one into the old slot."""
        inv = self.inventory()
        if isinstance(target, int) or (isinstance(target, str) and target.isdigit() and len(target) <= 2):
            old = next((x for x in inv if x["slot"] == int(target)), None)
        elif target in EQUIPPED:
            old = next((x for x in inv if x["equipped"] == target), None)
        else:
            old = next((x for x in inv if x["code"] == str(target).lower()), None)
        if old is None:
            raise ValueError(f"no inventory item matches {target!r}")
        nxt = next((x["node"] for x in inv if x["slot"] == old["slot"] + 1), None)
        new = self.give(code, 1)[0]
        if not new:
            raise RuntimeError("the game refused to create the new item (inventory full?)")
        if old["equipped"]:
            self.equip(new)
        self.call([(F_DELETE_INV, self.check(), old["id"], 1)])
        inv2 = self.inventory()
        nn = next((x for x in inv2 if x["obj"] == new), None)
        if nn and nxt:
            self._move_node(nn["node"], nxt)
        if old["equipped"]:
            self.recompute()
        inv3 = self.inventory()
        now = next((x for x in inv3 if x["obj"] == new), None)
        return {"before": {k: old[k] for k in ("slot", "code", "equipped", "cls")} | {"id": hex(old["id"])},
                "after": ({k: now[k] for k in ("slot", "code", "equipped", "cls")} | {"id": hex(now["id"])}) if now else None,
                "old_gone": all(x["id"] != old["id"] for x in inv3),
                "verified": bool(now) and now["code"] == code.lower() and now["slot"] == old["slot"]
                and all(x["id"] != old["id"] for x in inv3)}

    def attack_speed(self, factor: int, rapid: bool = True, mask: int = 0x400, period: int = 3) -> dict:
        """factor 1 = off; N = the attack state runs N times per frame. rapid: holding attack re-presses it every
        `period` frames."""
        self.hook()
        f = max(1, min(20, int(factor)))
        self.write(SPEED_VARS, struct.pack("<4I", mask if rapid and f > 1 else 0, max(1, period), 0, f - 1))
        v = struct.unpack("<4I", self.read(SPEED_VARS, 16))
        return {"factor": v[3] + 1, "rapid_fire": bool(v[0]), "rapid_period_frames": v[1]}

    def move_speed(self, factor: int, on: bool = True) -> dict:
        """factor 1 = off; N = the player's update (and so its per-frame move step) runs N times per frame, moving the
        player N x faster. Independent of attack_speed: writing only the move-extra var leaves the attack vars alone."""
        self.hook()
        f = max(1, min(20, int(factor)))
        self.write(SPEED_VARS + MOVE_EXTRA_OFF, struct.pack("<I", (f - 1) if on else 0))
        extra = struct.unpack("<I", self.read(SPEED_VARS + MOVE_EXTRA_OFF, 4))[0]
        return {"factor": extra + 1, "on": extra > 0}

    def floor_items(self) -> list:
        """[(item_id, code_hex)] on the player's current floor (the game's floor-item table)."""
        self.check()
        f = self.read(FLOOR_NOW, 1)[0]
        tb, ct = self.u32(FLOOR_TBL), self.u32(FLOOR_CNT)
        if not (0x8C000000 <= tb < 0x8D000000 and 0x8C000000 <= ct < 0x8D000000):
            return []
        arr, n = self.u32(tb + 4 * f), self.u32(ct + 4 * f)
        if not 0x8C000000 <= arr < 0x8D000000 or n > 500:
            return []
        raw = self.read(arr, FLOOR_REC * n) if n else b""
        return [(struct.unpack_from("<I", raw, FLOOR_REC * i + 28)[0], raw[FLOOR_REC * i + 16:FLOOR_REC * i + 19].hex())
                for i in range(n)]

    def floor_clear(self, only_gbox: bool = False) -> list:
        """Remove floor items on the current floor via the game's 6x63 handler. only_gbox: just the ones gBox spawned."""
        f = self.read(FLOOR_NOW, 1)[0]
        ids = [i for i, _ in self.floor_items() if not only_gbox or ID_BASE <= i < ID_BASE + 0x100000]
        for b in range(0, len(ids), QMAX):
            calls = []
            for k, iid in enumerate(ids[b:b + QMAX]):
                a = BUF + 12 * k
                self.write(a, struct.pack("<BBHII", 0x63, 3, 0, iid, f))
                calls.append((F_FLOOR_DELETE, a))
            self.call(calls)
        return ids

    def floor_spawn(self, codes: list, radius: float = 18.0, item_id0: int | None = None, grinds: dict | None = None) -> list:
        """Drop real floor items in a ring around player 0 via 0x8C1631C8 (the 6x5F drop path)."""
        import math
        p = self.check()
        x, z = struct.unpack("<f", self.read(p + 0x3C, 4))[0], struct.unpack("<f", self.read(p + 0x44, 4))[0]
        room = struct.unpack("<H", self.read(p + 0x2C, 2))[0]
        floor = self.read(FLOOR_NOW, 1)[0]
        self.hook()
        item_id0 = self.next_ids(len(codes)) if item_id0 is None else item_id0
        made = []
        for b in range(0, len(codes), 5):                 # 5 records (36 bytes) fit the buffer
            chunk = codes[b:b + 5]
            calls = []
            for i, code in enumerate(chunk):
                j = b + i
                ang = 2 * math.pi * j / max(1, len(codes))
                r = radius
                data = bytearray(self.item_data(code, item_id0 + j))
                if code.startswith("00") and grinds:
                    data[3] = max(0, min(255, int(grinds.get(code, 0))))
                rec = struct.pack("<BBHffHH", floor, 1, 0, x + r * math.sin(ang), z + r * math.cos(ang), room, j) + \
                    bytes(data)
                a = BUF + 36 * i
                self.write(a, rec)
                calls.append((F_FLOOR_CREATE, a, 0))
            made += self.call(calls)
        return made

    # --- rare drops: rewrite the loaded ItemRT rare table so every enemy/box drops a rare -------------------------------
    def rare_find(self, sigs: list) -> dict:
        """Scan main RAM for the loaded ItemRT table(s) by their on-disc content signatures. sigs: [(index, bytes)].
        Returns {address: table_index}. Only the current difficulty+section table is in RAM at a time."""
        found = {}
        for base, size in ((0x8C000000, 0x01000000),):
            for o in range(base, base + size, 1 << 20):
                try:
                    blk = self.read(o, min((1 << 20) + RT_ENTRY, base + size - o))
                except Exception:
                    continue
                for idx, sig in sigs:
                    k = blk.find(sig)
                    while 0 <= k < (1 << 20):
                        found[o + k] = idx
                        k = blk.find(sig, k + 4)
        return found

    def rare_slots(self, boxes: bool = True) -> list:
        """Byte offsets of the drop slots in a 640-byte ItemRT table: every monster slot (and every box rare slot)."""
        s = [4 * i for i in range(RT_MON_SLOTS)]
        if boxes:
            s += [RT_BOX_RARES_AT + 4 * i for i in range(RT_BOX_SLOTS)]
        return s

    def rare_drops(self, on: bool, codes: list, found: dict, boxes: bool = True) -> dict:
        """Rewrite each located ItemRT table so every monster/box slot drops a code from `codes` (round-robin) at the
        format's maximum chance; on=False restores the saved original bytes. Returns a per-table verify summary."""
        codes = [c.strip().lower() for c in (codes or RARE_DROPS)]
        if any(len(bytes.fromhex(c)) != 3 for c in codes):
            raise ValueError("every rare code must be 3 bytes of hex (e.g. 000107 = DURANDAL)")
        for a in found:
            orig = self._rare_orig.get(a)
            if orig is None:
                orig = self.read(a, RT_ENTRY)
                self._rare_orig[a] = orig
            if on:
                tbl = bytearray(orig)
                slots = self.rare_slots(boxes)
                for n, s_ in enumerate(slots):
                    tbl[s_] = RT_MAX_PROB
                    tbl[s_ + 1:s_ + 4] = bytes.fromhex(codes[n % len(codes)])
                if boxes:                                   # box rares only roll in their slot's area: cover every area
                    for k in range(RT_BOX_SLOTS):
                        tbl[RT_BOX_AREAS_AT + k] = 1 + k % 15
                self.write(a, bytes(tbl))
            else:
                self.write(a, orig)
        want = set(codes)
        bad = []
        for a in found:
            cur = self.read(a, RT_ENTRY)
            if on and any(cur[s_ + 1:s_ + 4].hex() not in want for s_ in self.rare_slots(boxes)):
                bad.append(hex(a))
            if not on and cur != self._rare_orig.get(a, cur):
                bad.append(hex(a))
        return {"tables": {hex(a): f"difficulty {i // 10}, section id {i % 10}" for a, i in found.items()},
                "codes": codes, "verified": not bad, "mismatched": bad}


def rare_signatures(afs: bytes) -> list:
    """[(table_index, 32-byte signature)] from ItemRT.afs: the first 32 bytes of each table's monster-slot block."""
    n = int.from_bytes(afs[4:8], "little")
    ents = [afs[o:o + s] for o, s in (struct.unpack_from("<II", afs, 8 + 8 * i) for i in range(n))]
    return [(i, e[:32]) for i, e in enumerate(ents) if len(e) >= RT_ENTRY]


def _flush_jit(ad) -> bool:
    """Flycast runs recompiled copies of the game's code: a code patch written into RAM is ignored while the old block
    stays cached (crit_always patches the damage routine, which is compiled after the first hit). Loading a state
    resets Flycast's block cache, so: save to gBox's scratch slot 9, load it back (same moment, patches included),
    then step back to the operator's slot. ponytail: costs ~2 s and one hitch; per-block invalidation if that bothers."""
    if getattr(ad, "name", "") != "retroarch" or not hasattr(ad, "_slot"):
        return False
    cur = getattr(ad, "slot", 0)
    ad.save_state(9)
    time.sleep(1.5)                                   # RetroArch writes the state on its own thread
    ad.load_state(9)
    time.sleep(0.5)
    ad._slot(cur)
    return True


# --- the gBox tool ---------------------------------------------------------------------------------------------------
class ModsIn(BaseModel):
    session_id: str
    op: str = "status"          # status | list | item_set | multi_equip | dupe | attack_speed | move_speed | meseta_max | meseta | crit_always | equip_any | key_bypass | give | stat | floor_spawn | floor_rares | floor_clear | floor_list | rare_drops | unhook
    on: bool = True             # crit_always / equip_any / key_bypass / move_speed / rare_drops: on/off
    value: int = 999999         # meseta: amount
    factor: int = 3             # move_speed: the player moves N times faster (1 = off)
    code: str = ""              # give / floor_spawn: item code hex (e.g. 000105 = DB's Saber) or name
    equip: bool = False         # give: also equip the first created item
    name: str = ""              # stat: atp | mst | evp | hp | dfp | ata | lck
    target: str = ""            # item_set: slot index (as the item list shows it, 0 = first), weapon|armor|mag, or a code
    rare: bool = False          # item_set: replace with a random rare of the same kind instead of `code`
    count: int = 1              # give / floor_spawn / floor_rares: how many
    codes: list[str] = []       # floor_rares: explicit codes (default: a rare set)
    character_class: str = ""   # floor_rares: required for class-compatible random rares
    highest: bool = True        # floor_rares: highest base-star rarity tier in that class
    max_grind: bool = False     # ground weapons: their own PMT maximum, never an invented item level
    radius: float = Field(default=18.0, ge=5, le=100, allow_inf_nan=False)

class ModsOut(BaseModel):
    result: dict


def _catalog(ctx) -> dict:
    """code -> name from the control plane's PSO DC v2 item list (read from the disc); {} if unavailable."""
    try:
        import httpx
        return {i["code"]: i["name"] for i in httpx.get(f"{ctx.server}/api/pso/items", params={"version": "dcv2"},
                                                        headers=ctx.headers, timeout=60).json()}
    except Exception:
        return {}


def _catalog_rows(ctx) -> list[dict]:
    from .pso_live import catalog, deadline
    rows = catalog(ctx, 'dcv2')
    deadline(ctx)
    return rows


def _itemrt_sigs(ctx) -> list:
    """ItemRT.afs signatures (read-only artifact GET) to locate the loaded rare table in RAM; [] if unavailable."""
    try:
        import httpx
        r = httpx.get(f"{ctx.server}/api/artifacts/{ITEMRT_AFS_SHA}", headers=ctx.headers, timeout=120)
        r.raise_for_status()
        return rare_signatures(r.content)
    except Exception:
        return []


def _is_rare(name: str) -> bool:
    letters = [c for c in name if c.isalpha()]
    return bool(letters) and all(c.isupper() for c in letters)          # PSO spells rare item names in capitals


def _random_rare(names: dict, code: str) -> str:
    """A random rare of the same kind: weapon -> same weapon class if it has rares, else any rare weapon; frame/barrier/
    unit -> same sub-kind; mag -> any rare mag."""
    import random
    rares = [c for c, n in names.items() if _is_rare(n)] or RARES
    fam = [c for c in rares if c[:4] == code[:4] and c != code]
    kind = [c for c in rares if c[:2] == code[:2] and c != code]
    pool = fam or kind or [c for c in RARES if c != code]
    return random.choice(pool)


RARES = ["000105", "000106", "000107", "000205", "000206", "000207", "000305", "000306", "000405", "000406", "000505",
         "000605", "000705", "000805", "000905", "001000", "001100", "000d00"]


@tool("pso_mods", "1.1", ModsIn, ModsOut, capabilities=["runtime", "memory"], permissions=[P.MEMORY_WRITE], timeout_s=120)
@serialized
def pso_mods(inp: ModsIn, ctx):
    """Phantasy Star Online Ver. 2 (Dreamcast US) live mods: op=meseta_max (999999 meseta) | meseta value=N |
    crit_always on=true/false (every player hit is a critical, x1.5) | equip_any on=true/false (no class/level/stat
    equip restrictions) | give code=000105 count=15 equip=true (real inventory items via the game's own create-item
    routine; equip = also equip the first) | stat name=atp value=900 (status-screen value; moves the saved base stat) |
    list (live inventory in menu order) | item_set target=<slot|weapon|armor|mag|code> code=<code|name> or rare=true (replace
    that item in place; re-equipped if it was equipped) | dupe target=<slot|weapon|armor|mag|code> count=N equip=true
    (exact clones - stats, percentages, grind and stack count all copied; equip = also equip the first copy) |
    floor_spawn code=.. count=N (real floor items around the player) | floor_rares count=N | floor_clear on=true (all floor
    items on this floor; on=false: only gBox-spawned ones) | floor_list | move_speed factor=3 on=true/false (the player
    runs N times faster) | key_bypass on=true/false (skip the serial/access-key entry check at the title) | rare_drops
    on=true/false codes=[..] (every enemy and box drops a rare from the list; defaults to the rarest 2OEF items) | status."""
    from .tools import SESSIONS
    ad, g = SESSIONS[inp.session_id]
    if inp.op == "capabilities":
        from .pso_controls import capabilities
        return {"result": capabilities(g, ad.read_memory)}
    if g.get("platform") == "gamecube":
        from .pso_live import gamecube
        return {"result": gamecube(inp, ctx, ad)}
    if g.get("platform") != "dreamcast":
        raise Unsupported("pso_mods supports Phantasy Star Online Ver. 2 on Dreamcast (US)")
    m = PSO(ad.read_memory, ad.write_memory)
    m.check(require_player=inp.op not in NO_PLAYER_OPS | {"status"})
    code = (inp.code or "").strip().lower().replace("0x", "")
    if code and any(ch not in "0123456789abcdef" for ch in code) and inp.op != "item_set":
        hit = [c for c, n in _catalog(ctx).items() if n.lower() == code]
        code = hit[0] if hit else code
    if code and any(ch not in "0123456789abcdef" for ch in code) and inp.op != "item_set":
        raise ValueError("code must be the item code hex (e.g. 000105 = DB's Saber); look names up in the item catalog")
    res: dict = {}
    if inp.op in ("meseta_max", "meseta"):
        res["meseta"] = m.meseta(999999 if inp.op == "meseta_max" else inp.value)
        res["verified"] = res["meseta"] == (999999 if inp.op == "meseta_max" else max(0, min(999999, inp.value)))
        res["note"] = "the menu shows the new amount the next time it is opened"
    elif inp.op in PATCHES:
        res[inp.op] = "on" if inp.on else "off"
        res["verified"] = m.patch(inp.op, inp.on)
        res["code_cache_flushed"] = _flush_jit(ad)        # or the emulator keeps running the unpatched code
    elif inp.op == "give":
        objs = m.give(code, max(1, min(30, inp.count)))
        res = {"created": sum(1 for o in objs if o), "requested": inp.count, "objects": [hex(o) for o in objs],
               "note": "items the inventory has no room for are not created (30 slots)"}
        if inp.equip and any(objs):
            res["equipped"] = m.equip(next(o for o in objs if o))
    elif inp.op == "multi_equip":
        res = m.multi_equip(inp.target, inp.on)
    elif inp.op == "dupe":
        res = m.dupe(inp.target, max(1, min(30, inp.count)), inp.equip)
    elif inp.op == "attack_speed":
        res = m.attack_speed(inp.value if inp.on and inp.value != 999999 else (10 if inp.on else 1), rapid=inp.on)
        res["code_cache_flushed"] = _flush_jit(ad)
    elif inp.op == "move_speed":
        res = m.move_speed(inp.factor if inp.on and inp.factor > 1 else (3 if inp.on else 1), on=inp.on)
        res["code_cache_flushed"] = _flush_jit(ad)
        res["note"] = "the player's run/walk step advances this many times per frame"
    elif inp.op == "rare_drops":
        sigs = _itemrt_sigs(ctx)
        if not sigs:
            raise Unsupported("could not read the ItemRT drop table (ItemRT.afs) to locate it in RAM")
        found = m.rare_find(sigs)
        if not found:
            raise RuntimeError("the ItemRT rare table is not in RAM now (it loads with a field/quest); enter a field and retry")
        codes = [c.strip().lower().replace("0x", "") for c in inp.codes] or ([code] if code else RARE_DROPS)
        res = m.rare_drops(inp.on, codes, found)
        res["mode"] = "every enemy and box drops a rare" if inp.on else "original drop tables"
        res["note"] = "rares drop on offline kills once the game rolls this copy; a drop still needs the enemy's drop roll"
    elif inp.op == "list":
        names = _catalog(ctx)
        res = {"inventory": [{"slot": x["slot"], "code": x["code"], "name": names.get(x["code"], x["cls"]),
                              "equipped": x["equipped"], "id": hex(x["id"])} for x in m.inventory()]}
    elif inp.op == "item_set":
        names = _catalog(ctx)
        tgt = inp.target.strip().lower() or "weapon"
        new = code
        if inp.rare or not new:
            inv = m.inventory()
            cur = next((x for x in inv if (tgt.isdigit() and len(tgt) <= 2 and x["slot"] == int(tgt)) or x["equipped"] == tgt
                        or x["code"] == tgt), None)
            if cur is None:
                raise ValueError(f"no inventory item matches {tgt!r}")
            new = _random_rare(names, cur["code"])
        elif any(ch not in "0123456789abcdef" for ch in new):
            hit = [c for c, n in names.items() if n.lower() == new.lower()]
            if not hit:
                raise ValueError(f"unknown item {new!r}")
            new = hit[0]
        res = m.item_set(tgt, new)
        tries = 1
        while inp.rare and not res.get("verified") and res.get("after") and tries < 5:   # the game normalised an
            slot = str(res["after"]["slot"])                                               # index it doesn't have
            new = _random_rare(names, res["after"]["code"])
            res = m.item_set(slot, new) | {"before": res["before"]}
            tries += 1
        for k in ("before", "after"):
            if res.get(k):
                res[k]["name"] = names.get(res[k]["code"], res[k]["cls"])
    elif inp.op == "stat":
        res = m.set_stat(inp.name, inp.value)
    elif inp.op in ("floor_spawn", "floor_rares"):
        import random
        from .psoitems import rare_pool
        rows = _catalog_rows(ctx)
        by_code = {i["code"]: i for i in rows}
        count = max(1, min(20, inp.count))
        if inp.op == "floor_rares" and inp.character_class:
            from .psoitems import CLASSES
            if inp.character_class not in list(CLASSES)[:9]:
                raise ValueError("choose a class that exists in Dreamcast Ver. 2")
            pool = rare_pool(rows, inp.character_class, inp.highest)
            codes = [i["code"] for i in random.choices(pool, k=count)]
        elif inp.op == "floor_rares":
            pool = inp.codes or RARES
            codes = random.choices(pool, k=count)
        else:
            codes = (inp.codes[:20] if inp.codes else [code] * count)
        if not codes or any(c not in by_code for c in codes):
            raise ValueError("choose item codes from this Dreamcast disc's item database")
        grinds = {c: by_code[c].get("max_grind", 0) for c in codes} if inp.max_grind else {}
        item_id0 = m.next_ids(len(codes))
        objs = m.floor_spawn(codes, radius=inp.radius, grinds=grinds, item_id0=item_id0)
        actual = dict(m.floor_items())
        confirmed = sum(actual.get(item_id0 + i) == c for i, c in enumerate(codes))
        res = {"spawned": confirmed, "verified": confirmed == len(codes), "codes": codes, "objects": [hex(o) for o in objs],
               "radius": inp.radius, "max_grinds": grinds, "class": inp.character_class or None,
               "floor_codes_after": list(actual.values()),
               "note": "Class-compatible does not bypass ATP/MST/ATA requirements; Equip any handles those separately."}
    elif inp.op == "floor_clear":
        gone = m.floor_clear(only_gbox=not inp.on)
        res = {"removed": len(gone), "ids": [hex(i) for i in gone], "left_on_floor": len(m.floor_items()),
               "scope": "all floor items" if inp.on else "only gBox-spawned items"}
    elif inp.op == "floor_list":
        res = {"floor_items": [{"id": hex(i), "code": c} for i, c in m.floor_items()]}
    elif inp.op == "unhook":
        m.unhook()
        res["hooked"] = False
    elif inp.op != "status":
        raise ValueError(f"unknown op {inp.op}")
    try:                                              # key_bypass runs at the title, before a player object exists
        meseta = m.u32(m.check() + MESETA_OFF)
    except RuntimeError:
        meseta = None
    sv = struct.unpack("<5I", m.read(SPEED_VARS, SPEED_VARS_LEN)) if m.read(CAVE2, 4) == speed_code()[:4] else (0,) * 5
    res["status"] = {"meseta": meseta, **{k: m.patch_state(k) for k in PATCHES},
                     "hooked": m.u32(VT_UPDATE) == CAVE, "attack_speed": sv[3] + 1, "rapid_fire": bool(sv[0]),
                     "move_speed": sv[4] + 1}
    return {"result": res}
