"""Verified 3OE2 crit-always: every melee hit by a local player is a critical (x1.5).

Static RE (offline, against the owned PsoV3.dol SHA 1f80fb82..., converted to a
PPC ELF and cross-checked byte-for-byte against live RAM):

The melee damage-application routine is FUN_80014108. It loops the attacker's
44-byte hit records (counter r30 vs *(r28+0xA8)); r28 is the attacker entity (HP at
+0x32c, hit list at +0xA4/+0xA8, result flags at +0x30 - the same fields the accuracy
hook's attacker uses). Per hit it computes damage in f27, rolls the critical
(threshold = min(const, (float)*(r29+0x2D2)) at 0x80014678-0x80014684, the GC analog
of the DC "rand*500 vs min(LCK,100)"), and at

    0x8001468C: bne cr0, 0x800146BC     (40 82 00 30)

chooses the path: fall-through 0x80014690 = CRITICAL (plays the crit fx then
`lfs 1.5 ; fmuls f27,f27,f0` at 0x800146B0 = x1.5 damage), taken 0x800146BC = normal.

A blind nop of that branch would make ENEMIES crit too. So this installs a cave hook
at 0x8001468C that forces the critical path ONLY when the attacker (r28) is PLAYER
slot 0 or slot 1 and the offline free-play phase is active; every other attacker runs
the stock branch unchanged. One site, fully reversible, fingerprint-guarded, flushed.

Mirrors gbox.pso_accuracy exactly (CODE/SITES/METADATA/owned/check-every-touched-byte/
flush/refuse-and-write-nothing). Cave at 0x80005000 (free scratch between the live
dispatcher end 0x80005000 and the adventure cave 0x80006000)."""
import struct

from .pso_gc_live import GC, PLAYER, PHASE, FLUSH, d
from .pso_gc_adventure import branch
from .pso_accuracy import running
from .registry import Unsupported

CAVE, HEADER, END = 0x80005000, 0x800050E0, 0x80005100
SITE = 0x8001468C
SITE_ORIGINAL = bytes.fromhex('40820030')          # bne cr0, 0x800146BC
CRIT = 0x80014690                                  # critical path (fall-through: x1.5)
NONCRIT = 0x800146BC                               # normal-damage path (branch taken)

# Exact bytes that must be present for this to be the owned 3OE2 melee-damage routine.
# No write happens unless every one matches (and the site is original-or-our-branch).
GUARDS = {
    0x80014108: bytes.fromhex('9421ff30'),                          # FUN_80014108 prologue
    0x80014604: bytes.fromhex('ef610772'),                          # fmuls f27,f1,f29 (per-hit damage)
    0x80014684: bytes.fromhex('fc0308404c401382'),                  # fcmpu cr0,f3,f1 ; cror (crit decision)
    0x800146AC: bytes.fromhex('482120b1c0028088ef7b0032'),          # bl ; lfs 1.5f ; fmuls f27,f27,f0 (x1.5)
}


N_PLAYER_SLOTS = 4                                     # PLAYER slot array; absent slots are 0 (never match)


def code():
    """Cave entered in place of the crit branch (cr0 holds the stock decision). Forces the
    critical path when the attacker r28 is ANY local player (PLAYER slots 0-3: host + up to 3
    accompanying) and offline; else replays the stock branch. Preserves cr0 (uses cr1/r11/r12
    only; no CTR, because the damage routine itself uses CTR here). Absent co-op slots read 0
    and never match. The stock replay is a short bne into two in-range unconditional branches
    (0x800146BC is out of conditional-branch range from the cave)."""
    C = CAVE
    def A(i):
        return C + i * 4
    FORCE, NONCRIT_W = 18, 19
    w = [d(15, 12, 0, (PHASE + 0x8000) >> 16),             # 0  lis   r12,PHASE@ha
         d(32, 12, 12, PHASE & 0xFFFF),                    # 1  lwz   r12,PHASE@l(r12)
         d(11, 4, 12, 14),                                 # 2  cmpwi cr1,r12,14
         0x40860000 | ((A(17) - A(3)) & 0xFFFC),           # 3  bne   cr1,do_orig (not offline)
         d(15, 11, 0, (PLAYER + 0x8000) >> 16)]            # 4  lis   r11,PLAYER@ha
    for s in range(N_PLAYER_SLOTS):                        # 5..16: 4 slots x (lwz; cmplw cr1; beq cr1,force)
        base = 5 + s * 3
        w.append(d(32, 12, 11, (PLAYER + s * 4) & 0xFFFF))  # lwz   r12,*(PLAYER+s*4)(r11)
        w.append(0x7C9C6040)                                # cmplw cr1,r28,r12
        w.append(0x41860000 | ((A(FORCE) - A(base + 2)) & 0xFFFC))  # beq cr1,force_crit
    w.append(0x40820008)                                   # 17 do_orig: bne cr0,+8 -> noncrit
    w.append(branch(A(FORCE), CRIT))                       # 18 force_crit: b 0x80014690
    w.append(branch(A(NONCRIT_W), NONCRIT))                # 19 b 0x800146BC (normal)
    return struct.pack('>%dI' % len(w), *w)


CODE = code()


def _code_v1():
    """Superseded two-slot (player 1+2) crit stub; kept so a running GBPSOCR1 two-slot hook
    is recognised as gBox-owned and migrated in place to the 4-slot CODE."""
    C = CAVE
    def A(i):
        return C + i * 4
    w = [0] * 15
    w[0] = d(15, 12, 0, (PHASE + 0x8000) >> 16)
    w[1] = d(32, 12, 12, PHASE & 0xFFFF)
    w[2] = d(11, 4, 12, 14)
    w[3] = 0x40860000 | ((A(12) - A(3)) & 0xFFFC)
    w[4] = d(15, 12, 0, (PLAYER + 0x8000) >> 16)
    w[5] = d(32, 12, 12, PLAYER & 0xFFFF)
    w[6] = 0x7C9C6040
    w[7] = 0x41860000 | ((A(13) - A(7)) & 0xFFFC)
    w[8] = d(15, 12, 0, (PLAYER + 0x8000) >> 16)
    w[9] = d(32, 12, 12, (PLAYER + 4) & 0xFFFF)
    w[10] = 0x7C9C6040
    w[11] = 0x41860000 | ((A(13) - A(11)) & 0xFFFC)
    w[12] = 0x40820008
    w[13] = branch(A(13), CRIT)
    w[14] = branch(A(14), NONCRIT)
    return struct.pack('>15I', *w)


PRIOR_CODES = (_code_v1(),)                            # migrate a running two-slot crit hook in place
METADATA = b'GBPSOCR1' + struct.pack('>II', SITE, CRIT)
PATCH = struct.pack('>I', branch(SITE, CAVE))          # b CAVE, installed at SITE


class GameCube(GC):
    def __init__(self, ad):
        super().__init__(ad)
        self.adapter = ad

    def check(self, player=True):
        p = super().check(player)
        for address, expected in GUARDS.items():
            if self.read(address, len(expected)) != expected:
                raise Unsupported(f'PSO crit fingerprint differs at {address:#x}; no crit patch applied')
        if self.read(SITE, 4) not in (SITE_ORIGINAL, PATCH):
            raise Unsupported('PSO crit site is modified by another patch; leave it intact')
        if self.read(SITE, 4) == PATCH and not self.owned_known():
            raise Unsupported('PSO crit hook ownership does not match; leave it intact')
        return p

    def owned(self):
        return self.read(HEADER, 16) == METADATA and self.read(CAVE, len(CODE)) == CODE

    def owned_known(self):
        if self.read(HEADER, 16) != METADATA:
            return False
        return any(self.read(CAVE, len(v)) == v for v in (CODE,) + PRIOR_CODES)

    def status(self):
        self.check()
        return {'crit_always': self.read(SITE, 4) == PATCH, 'verified': True,
                'scope': 'every melee hit by a local player (slot 0 or slot 1) is a critical; enemies unchanged'}

    def flush(self, addresses):
        lines = sorted({address & ~31 for address in addresses})
        if lines:
            self.call([(FLUSH, address) for address in lines])

    def set_enabled(self, on):
        self.check()
        running(self.adapter)
        owned = self.owned()
        install = bool(on) and not owned
        if install and not self.owned_known() and any(self.read(CAVE, END - CAVE)):
            raise Unsupported('PSO crit scratch region is occupied; leave it intact')
        want = PATCH if on else SITE_ORIGINAL
        changed = self.read(SITE, 4) != want
        if not changed and not install:
            return self.status()
        self.hook()
        if install:
            self.write(CAVE, CODE)
            self.write(HEADER, METADATA)
            self.flush(range(CAVE, CAVE + len(CODE), 32))
        if changed:
            self.write(SITE, want)
            self.flush([SITE])                         # guest icbi: Dolphin recompiles the patched block
        result = self.status()
        if result['crit_always'] != bool(on):
            raise RuntimeError('PSO crit patch read-back differs from the requested setting')
        return result | {'code_cache_flushed': True,
                         'message': 'Every local-player melee hit is now a critical.' if on
                         else 'Normal critical rolls restored.'}


def status(ad, platform):
    if platform != 'gamecube':
        raise Unsupported('Crit-always is verified for the GameCube 3OE2 build only')
    return GameCube(ad).status()


def set_enabled(ad, platform, on):
    if platform != 'gamecube':
        raise Unsupported('Crit-always is verified for the GameCube 3OE2 build only')
    return GameCube(ad).set_enabled(bool(on))
