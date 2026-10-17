"""DOA2 LE (JP, Dreamcast): pick a random costume each time a player confirms a fighter (inbox #1652).

Reverse-engineered from the owned 1ST_READ.BIN (sha256 27a014ae...c97e1, load address 0x8c010000):

  0x8c0262e0..0x8c02631e  the select screen's "fighter confirmed" handler. r14 is the player's cursor record
                          (select base r12 + player << 7; +1 render slot, +2 costume). It plays the confirm sound
                          (0x8c01235a, 36), then calls the commit routine through the literal-pool word at
                          0x8c02638c (= 0x8c02a1ca) with r4 = select base and r5 = player.
  0x8c02a1ca              commit(base, player): copies cursor +1 / +2 into the selection tables 0x8c239d50 (slots)
                          and 0x8c239d64 (costumes), the u16 [side][5] arrays every mode's loader and actor set-up
                          read (actor +1 / +2 at 0x8c2376b8 + 0x68 * n, see doa2_context).
  0x8c02ac04..0x8c02aca8  the CPU's own random pick: rand() (0x8c120cf0, an LCG: seed at 0x8c1e64e0,
                          returns (seed * 0x41c64e6d + 12345) >> 16 & 0x7fff in r0, saves macl, clobbers r1..r4).

The patch keeps every native routine and table. It writes a 112-byte SH-4 routine (HOOK) and a costume-pool table
(TABLE: per render slot a count byte and up to 15 render-costume indices) into the zero-filled gap of the boot
header (0x8c010080..0x8c011000: after the 0x80 bytes the startup's section table names, before the code at
0x8c011000; no literal in the executable points into it), and redirects only the pool word at 0x8c02638c to HOOK.
On every human confirmation HOOK:

    cursor = base + (player << 7); slot = cursor[1]
    if slot < 25 and TABLE[slot].count:
        r = (rand() ^ TCNT0) & 0x7fff               # game LCG mixed with the free-running TMU0 counter (0xffd8000c)
        cursor[2] = TABLE[slot].costume[(r * count) >> 15]
    tail-jump to commit(base, player)            # registers, pr and macl as the caller left them

so the costume that is committed, loaded and drawn is drawn at random from that fighter's pool each time it is
selected. The cursor costume is changed before the commit, so the select tables, the loader (file table 0x8c17f5f4)
and the render script (0x8c1c85f4) all see the same index. CPU picks keep the game's own random costume choice.
"""
from __future__ import annotations

import hashlib
import struct

BASE = 0x8C010000
EXECUTABLE_SHA256 = "27a014aeda35983df749f7d575bbddbea3f1ffd1f7776194ef503108c20c97e1"
POOL_WORD = 0x8C02638C            # literal the confirm handler loads the commit routine from (jsr @r2 at 0x8c02631c)
COMMIT = 0x8C02A1CA
RAND = 0x8C120CF0
TCNT0 = 0xFFD8000C
GAP = (0x8C010080, 0x8C011000)    # zero-filled boot-header gap
HOOK = 0x8C010100
TABLE = 0x8C010200
SLOTS = 25
STRIDE = 16                       # count byte + up to 15 costumes
SIGNATURE = b"GBOXRND1"
SIGNATURE_AT = HOOK + 0x80

# (offset, halfword) of the routine; branch / PC-relative fields are filled in by routine()
_CODE = [
    0x4F22,  # 00 sts.l pr,@-r15
    0x4F12,  # 02 sts.l macl,@-r15
    0x2F46,  # 04 mov.l r4,@-r15
    0x2F56,  # 06 mov.l r5,@-r15
    0x2F86,  # 08 mov.l r8,@-r15
    0x685C,  # 0a extu.b r5,r8
    0x4808,  # 0c shll2 r8
    0x4808,  # 0e shll2 r8
    0x4808,  # 10 shll2 r8
    0x4800,  # 12 shll r8                      r8 = player << 7
    0x384C,  # 14 add r4,r8                    r8 = cursor record
    0x8481,  # 16 mov.b @(1,r8),r0             render slot
    0x600C,  # 18 extu.b r0,r0
    0xE119,  # 1a mov #25,r1
    0x3012,  # 1c cmp/hs r1,r0                 slot >= 25 -> leave it alone
    "bt skip",  # 1e
    "mov.l TABLE,r1",  # 20
    0x4008,  # 22 shll2 r0
    0x4008,  # 24 shll2 r0                     slot * 16
    0x310C,  # 26 add r0,r1                    entry
    0x6010,  # 28 mov.b @r1,r0                 count
    0x600C,  # 2a extu.b r0,r0
    0x2008,  # 2c tst r0,r0
    "bt skip",  # 2e                            empty pool -> native costume
    0x2F16,  # 30 mov.l r1,@-r15
    0x2F06,  # 32 mov.l r0,@-r15
    "mov.l RAND,r0",  # 34
    0x400B,  # 36 jsr @r0                      rand()
    0x0009,  # 38 nop
    "mov.l TCNT,r2",  # 3a
    0x6222,  # 3c mov.l @r2,r2
    0x202A,  # 3e xor r2,r0
    0x4028,  # 40 shll16 r0
    0x4000,  # 42 shll r0
    0x4029,  # 44 shlr16 r0
    0x4001,  # 46 shlr r0                      low 15 bits: 0..32767
    0x61F6,  # 48 mov.l @r15+,r1               count
    0x0017,  # 4a mul.l r1,r0
    0x001A,  # 4c sts macl,r0
    0x4019,  # 4e shlr8 r0
    0x4009,  # 50 shlr2 r0
    0x4009,  # 52 shlr2 r0
    0x4009,  # 54 shlr2 r0
    0x4001,  # 56 shlr r0                      (r * count) >> 15 < count
    0x61F6,  # 58 mov.l @r15+,r1               entry
    0x310C,  # 5a add r0,r1
    0x8411,  # 5c mov.b @(1,r1),r0             pool costume
    0x8082,  # 5e mov.b r0,@(2,r8)             cursor costume
    0x68F6,  # 60 skip: mov.l @r15+,r8
    0x65F6,  # 62 mov.l @r15+,r5
    0x64F6,  # 64 mov.l @r15+,r4
    0x4F16,  # 66 lds.l @r15+,macl
    0x4F26,  # 68 lds.l @r15+,pr
    "mov.l COMMIT,r0",  # 6a
    0x402B,  # 6c jmp @r0                      the native commit, returning to the confirm handler
    0x0009,  # 6e nop (delay slot)
]
_LITERALS = {"TABLE": 0x70, "RAND": 0x74, "TCNT": 0x78, "COMMIT": 0x7C}
_SKIP = 0x60
ROUTINE_BYTES = 0x80


def routine() -> bytes:
    """The hook routine with its literal pool (0x80 bytes, loaded at HOOK)."""
    out = bytearray()
    for i, op in enumerate(_CODE):
        pc = HOOK + 2 * i
        if isinstance(op, str):
            mnem, arg = op.split(" ", 1)
            if mnem == "bt":
                disp = (HOOK + _SKIP - (pc + 4)) // 2
                assert 0 <= disp < 128
                op = 0x8900 | disp
            else:                                       # mov.l LIT,rN
                name, reg = arg.split(",")
                target = HOOK + _LITERALS[name]
                disp = (target - ((pc & ~3) + 4)) // 4
                assert 0 <= disp < 256 and (pc & ~3) + 4 + 4 * disp == target
                op = 0xD000 | int(reg[1:]) << 8 | disp
        out += struct.pack("<H", op)
    assert len(out) == 0x70
    out += struct.pack("<4I", TABLE, RAND, TCNT0, COMMIT)
    return bytes(out)


def table_bytes(pools: dict[int, list[int]]) -> bytes:
    """{render slot: [render costume, ...]} -> the 25 x 16-byte pool table."""
    out = bytearray(SLOTS * STRIDE)
    for slot, costumes in pools.items():
        if not 0 <= slot < SLOTS:
            raise ValueError(f"render slot {slot} outside 0..24")
        if not 0 < len(costumes) < STRIDE:
            raise ValueError(f"slot {slot}: a pool holds 1..15 costumes, got {len(costumes)}")
        if any(not 0 <= c < 32 for c in costumes):
            raise ValueError(f"slot {slot}: costume index outside 0..31")
        out[slot * STRIDE] = len(costumes)
        out[slot * STRIDE + 1:slot * STRIDE + 1 + len(costumes)] = bytes(costumes)
    return bytes(out)


def _off(address: int) -> int:
    return address - BASE


def check_executable(exe: bytes, *, pinned: bool = True) -> None:
    if pinned and hashlib.sha256(exe).hexdigest() != EXECUTABLE_SHA256:
        raise ValueError("Unsupported DOA2 executable: the select-screen patch sites are version-specific")
    if struct.unpack_from("<I", exe, _off(POOL_WORD))[0] != COMMIT:
        raise ValueError("The confirm handler's commit literal is not at its verified address")
    end = TABLE + SLOTS * STRIDE
    if any(exe[_off(HOOK):_off(end)]):
        raise ValueError("The boot-header gap the hook uses is not empty")
    if not GAP[0] <= HOOK and end <= GAP[1]:
        raise ValueError("hook outside the gap")


def patch(exe: bytes, pools: dict[int, list[int]], *, pinned: bool = True) -> bytes:
    """The executable with the random-costume hook installed for `pools`."""
    check_executable(exe, pinned=pinned)
    out = bytearray(exe)
    code = routine()
    out[_off(HOOK):_off(HOOK) + len(code)] = code
    out[_off(SIGNATURE_AT):_off(SIGNATURE_AT) + len(SIGNATURE)] = SIGNATURE
    tab = table_bytes(pools)
    out[_off(TABLE):_off(TABLE) + len(tab)] = tab
    struct.pack_into("<I", out, _off(POOL_WORD), HOOK)
    return bytes(out)


def read_back(exe: bytes) -> dict:
    """What a (patched) executable holds: hook present?, the pools, the routine's integrity."""
    word = struct.unpack_from("<I", exe, _off(POOL_WORD))[0]
    code = exe[_off(HOOK):_off(HOOK) + ROUTINE_BYTES]
    sig = exe[_off(SIGNATURE_AT):_off(SIGNATURE_AT) + len(SIGNATURE)]
    pools = {}
    for slot in range(SLOTS):
        row = exe[_off(TABLE) + slot * STRIDE:_off(TABLE) + (slot + 1) * STRIDE]
        if row[0]:
            pools[slot] = list(row[1:1 + row[0]])
    return {"installed": word == HOOK and code == routine() and sig == SIGNATURE, "pool_word": f"{word:#010x}",
            "routine_sha256": hashlib.sha256(code).hexdigest(), "signature": sig.decode("latin-1"),
            "pools": pools}


# ---------------------------------------------------------------- a minimal SH-4 interpreter for the hook

def simulate(exe: bytes, *, slot: int, costume: int, player: int = 0, seed: int = 1, tcnt: int = 0,
             base: int = 0x8C300000, max_steps: int = 500) -> dict:
    """Run the confirm handler's call through the pool word: HOOK, the game's own rand() (both interpreted from the
    executable bytes) and up to the jump into the commit routine. Returns the committed costume, the jump target,
    the restored registers and the new LCG seed. Only the instructions these routines use are implemented."""
    mem: dict[int, int] = {}

    def rd8(a):
        if BASE <= a < BASE + len(exe):
            return mem.get(a, exe[a - BASE])
        return mem.get(a, 0)

    def rd(a, n):
        if a == TCNT0 and n == 4:
            return tcnt & 0xFFFFFFFF
        return int.from_bytes(bytes(rd8(a + i) for i in range(n)), "little")

    def wr(a, v, n):
        for i in range(n):
            mem[a + i] = (v >> (8 * i)) & 0xFF

    seed_addr = 0x8C1E64E0
    wr(seed_addr, seed, 4)
    cursor = base + ((player & 0xFF) << 7)
    wr(cursor + 1, slot, 1)
    wr(cursor + 2, costume, 1)
    R = [0] * 16
    R[4], R[5], R[15] = base, player, 0x8C2FF000
    R[8] = 0x12345678
    macl, pr, T = 0xCAFE, 0x8C026320, 0
    pc = struct.unpack_from("<I", exe, _off(POOL_WORD))[0]   # the handler's jsr @r2 target
    delay = pending = None
    m32 = 0xFFFFFFFF
    for _ in range(max_steps):
        delay_slot = pending is not None
        if pc == COMMIT and not delay_slot:
            return {"costume": rd8(cursor + 2), "slot": rd8(cursor + 1), "jumped_to": pc, "r4": R[4], "r5": R[5],
                    "r8": R[8], "r15": R[15], "pr": pr, "macl": macl, "seed": rd(seed_addr, 4)}
        op = rd(pc, 2)
        n, m, d8 = (op >> 8) & 15, (op >> 4) & 15, op & 0xFF
        nxt = pc + 2
        top, low = op >> 12, op & 15
        if op == 0x0009:
            pass
        elif op == 0x000B:                                  # rts
            delay = pr
        elif top == 0 and low == 0xA and m == 1:            # sts macl,rn
            R[n] = macl
        elif top == 0 and low == 7:                         # mul.l rm,rn
            macl = (R[n] * R[m]) & m32
        elif top == 2 and low == 6:                         # mov.l rm,@-rn
            R[n] = (R[n] - 4) & m32
            wr(R[n], R[m], 4)
        elif top == 2 and low == 2:                         # mov.l rm,@rn
            wr(R[n], R[m], 4)
        elif top == 2 and low == 8:                         # tst
            T = int((R[n] & R[m]) == 0)
        elif top == 2 and low == 9:                         # and
            R[n] &= R[m]
        elif top == 2 and low == 0xA:                       # xor
            R[n] ^= R[m]
        elif top == 3 and low == 0xC:                       # add
            R[n] = (R[n] + R[m]) & m32
        elif top == 3 and low == 2:                         # cmp/hs
            T = int(R[n] >= R[m])
        elif top == 4 and op & 0xFF == 0x22:                # sts.l pr,@-rn
            R[n] = (R[n] - 4) & m32
            wr(R[n], pr, 4)
        elif top == 4 and op & 0xFF == 0x12:                # sts.l macl,@-rn
            R[n] = (R[n] - 4) & m32
            wr(R[n], macl, 4)
        elif top == 4 and op & 0xFF == 0x26:                # lds.l @rn+,pr
            pr = rd(R[n], 4)
            R[n] = (R[n] + 4) & m32
        elif top == 4 and op & 0xFF == 0x16:                # lds.l @rn+,macl
            macl = rd(R[n], 4)
            R[n] = (R[n] + 4) & m32
        elif top == 4 and op & 0xFF in (0x00, 0x08, 0x18, 0x28):   # shll / shll2 / shll8 / shll16
            R[n] = (R[n] << {0x00: 1, 0x08: 2, 0x18: 8, 0x28: 16}[op & 0xFF]) & m32
        elif top == 4 and op & 0xFF in (0x01, 0x09, 0x19, 0x29):   # shlr ...
            R[n] = R[n] >> {0x01: 1, 0x09: 2, 0x19: 8, 0x29: 16}[op & 0xFF]
        elif top == 4 and op & 0xFF == 0x0B:                # jsr @rn
            pr = pc + 4
            delay = R[n]
        elif top == 4 and op & 0xFF == 0x2B:                # jmp @rn
            delay = R[n]
        elif top == 6 and low == 0:                         # mov.b @rm,rn
            v = rd8(R[m])
            R[n] = v - 256 if v & 0x80 else v
            R[n] &= m32
        elif top == 6 and low == 2:                         # mov.l @rm,rn
            R[n] = rd(R[m], 4)
        elif top == 6 and low == 3:                         # mov rm,rn
            R[n] = R[m]
        elif top == 6 and low == 6:                         # mov.l @rm+,rn
            R[n] = rd(R[m], 4)
            if n != m:
                R[m] = (R[m] + 4) & m32
        elif top == 6 and low == 0xC:                       # extu.b
            R[n] = R[m] & 0xFF
        elif top == 7:                                      # add #imm
            R[n] = (R[n] + (d8 - 256 if d8 & 0x80 else d8)) & m32
        elif op >> 8 == 0x84:                               # mov.b @(d,rm),r0
            v = rd8(R[m] + (op & 15))
            R[0] = (v - 256 if v & 0x80 else v) & m32
        elif op >> 8 == 0x80:                               # mov.b r0,@(d,rn)
            wr(R[(op >> 4) & 15] + (op & 15), R[0], 1)
        elif op >> 8 == 0x89:                               # bt
            if T:
                nxt = pc + 4 + 2 * (d8 - 256 if d8 & 0x80 else d8)
        elif top == 9:                                      # mov.w @(d,pc),rn
            v = rd(pc + 4 + 2 * d8, 2)
            R[n] = (v - 0x10000 if v & 0x8000 else v) & m32
        elif top == 0xD:                                    # mov.l @(d,pc),rn
            R[n] = rd((pc & ~3) + 4 + 4 * d8, 4)
        elif top == 0xE:                                    # mov #imm,rn
            R[n] = (d8 - 256 if d8 & 0x80 else d8) & m32
        else:
            raise NotImplementedError(f"{pc:#010x}: {op:#06x}")
        if delay_slot:                                      # this was a delay slot: take the branch now
            pc, pending = pending, None
        elif delay is not None:                             # a delayed branch: run the next instruction first
            pending, delay = delay, None
            pc = nxt
        else:
            pc = nxt
    raise RuntimeError("the hook did not reach the commit routine")
