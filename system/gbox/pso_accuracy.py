"""Verified 3OE2 local-player hit rolls. No ATA edits or global enemy accuracy changes."""
import struct

from .pso_gc_live import GC, PLAYER, PHASE, QUEUE, QMAX, QSZ, FLUSH, d
from .pso_gc_adventure import branch
from .registry import Unsupported

# Independently disassembled from the owned PsoV3.dol SHA256
# 1f80fb82b41c05b26b6d0545b1ba9c0aa60b52e6589cf32fbb2ffe644692a61a.
# Both receiver routines take the attacker in r4, retained in r28/r29.
# The hooks enter only AFTER native null, immunity, hitbox and distance checks.
# Native success paths set the hit-record flags and return 1. Their ordinary
# miss paths return 0. Preserve both native paths for every other attacker.
CAVE, HEADER, END = 0x80006800, 0x800068E0, 0x80006900
SITES = (
    (0x80015F00, 28, 0x80015F20, bytes.fromhex('c0028024')),
    (0x80016384, 29, 0x800163A0, bytes.fromhex('fc00f840')),
)
GUARDS = {
    0x80015DE8: bytes.fromhex('9421ffb07c0802a690010054dbe10040f3e10048bf8100307c9c2379'),
    0x80015E2C: bytes.fromhex('7f83e3784800361da81f02cc'),
    0x80015E80: bytes.fromhex('ec220072ec432028ec3f08b8efe00072'),
    0x80015F04: bytes.fromhex('fc00f840408000447fe3fb784bffb105fc01f8404c40138240820030'),
    0x80015F20: bytes.fromhex('801d00187fe3fb787f84e37864000400901d00184bffb099'),
    0x80015F38: bytes.fromhex('801f02dc3860000160000002901f02dc4800002c'),
    0x800162E0: bytes.fromhex('9421ffc07c0802a690010044dbe10030f3e10038bfa100247c9d2379'),
    0x80016314: bytes.fromhex('3c80040038840800480032892c030000408200b4'),
    0x80016328: bytes.fromhex('7fa3eb7848003121a81f02cc'),
    0x80016370: bytes.fromhex('ec420032c0028024ec632028ec5f10f8efe100b2'),
    0x80016388: bytes.fromhex('408000447fe3fb784bffac85fc01f8404c40138240820030'),
    0x800163A0: bytes.fromhex('1c1e002c809f00a4386000017c840214800400186400040090040018'),
    0x800163BC: bytes.fromhex('801f02dc60000001901f02dc48000014'),
}


def code():
    out = bytearray()
    for index, (site, attacker, success, original) in enumerate(SITES):
        address = CAVE + index * 0x40
        out.extend(bytes(address - CAVE - len(out)))
        words = [
            d(15, 12, 0, (PHASE + 0x8000) >> 16),
            d(32, 12, 12, PHASE & 0xFFFF),
            d(11, 0, 12, 14),
            0x40820018,                    # bne stock (online/title modes)
            d(15, 12, 0, (PLAYER + 0x8000) >> 16),
            d(32, 12, 12, PLAYER & 0xFFFF),
            0x7C006040 | (attacker << 16),  # cmplw r<attacker>,r12
            0x40820008,                    # bne stock
            branch(address + 32, success),
            int.from_bytes(original, 'big'),
            branch(address + 40, site + 4),
        ]
        out.extend(struct.pack('>11I', *words))
    return bytes(out)


CODE = code()
METADATA = b'GBPSOAH1' + struct.pack('>II', SITES[0][0], SITES[1][0])
PATCHES = {site: struct.pack('>I', branch(site, CAVE + i * 0x40))
           for i, (site, _, _, _) in enumerate(SITES)}


def running(ad):
    """Fail before publishing commands while an emulator is paused or busy."""
    if getattr(ad, 'paused_tids', None) or getattr(ad, 'paused', False):
        raise RuntimeError('Resume PSO before applying its live defaults or accuracy hook')
    query = getattr(ad, 'query_runtime', None)
    if query:
        state = query()
        if state.get('state') == 'PAUSED' or state.get('paused'):
            raise RuntimeError('Resume PSO before applying its live defaults or accuracy hook')
    m = GC(ad)
    if any(m.u32(QUEUE + i * QSZ) for i in range(QMAX)):
        raise RuntimeError('A PSO native command is pending; resume the game and wait for it to finish')


class GameCube(GC):
    def __init__(self, ad):
        super().__init__(ad)
        self.adapter = ad

    def check(self, player=True):
        p = super().check(player)
        for address, expected in GUARDS.items():
            if self.read(address, len(expected)) != expected:
                raise Unsupported(f'PSO accuracy fingerprint differs at {address:#x}; no accuracy patch applied')
        for site, _, _, original in SITES:
            if self.read(site, 4) not in (original, PATCHES[site]):
                raise Unsupported('PSO accuracy code is modified by another patch; leave it intact')
        if any(self.read(site, 4) == PATCHES[site] for site, *_ in SITES) and not self.owned():
            raise Unsupported('PSO accuracy hook ownership does not match; leave it intact')
        return p

    def owned(self):
        return self.read(HEADER, 16) == METADATA and self.read(CAVE, len(CODE)) == CODE

    def status(self):
        self.check()
        values = [self.read(site, 4) == PATCHES[site] for site, *_ in SITES]
        if any(values) and not all(values):
            raise Unsupported('PSO accuracy hook is partly applied; reconnect to repair its two verified sites')
        return {'always_hit': all(values), 'verified': True,
                'scope': 'local offline player accuracy rolls; targets must still be in range and hittable'}

    def flush(self, addresses):
        lines = sorted({address & ~31 for address in addresses})
        if lines:
            self.call([(FLUSH, address) for address in lines])

    def set_enabled(self, on):
        self.check()
        running(self.adapter)
        owned = self.owned()
        if on and not owned and any(self.read(CAVE, END-CAVE)):
            raise Unsupported('PSO accuracy scratch region is occupied; leave it intact')
        changed = [site for site, _, _, original in SITES
                   if self.read(site, 4) != (PATCHES[site] if on else original)]
        if not changed:
            return self.status()
        self.hook()
        if on and not owned:
            self.write(CAVE, CODE)
            self.write(HEADER, METADATA)
            self.flush(range(CAVE, CAVE+len(CODE), 32))
        for site, _, _, original in SITES:
            if site in changed:
                self.write(site, PATCHES[site] if on else original)
        self.flush(changed)
        result = self.status()
        if result['always_hit'] != bool(on):
            raise RuntimeError('PSO accuracy patch read-back differs from the requested setting')
        return result | {'code_cache_flushed': True,
                         'message': 'Player accuracy rolls always succeed.' if on else 'Normal player accuracy rolls restored.'}


def status(ad, platform):
    if platform != 'gamecube':
        raise Unsupported('Always-hit needs a separately verified Dreamcast Ver. 2 hit-resolution patch')
    return GameCube(ad).status()


def set_enabled(ad, platform, on):
    if platform != 'gamecube':
        raise Unsupported('Always-hit needs a separately verified Dreamcast Ver. 2 hit-resolution patch')
    return GameCube(ad).set_enabled(bool(on))
