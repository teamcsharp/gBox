"""PSO GC 3OE2 progression helpers: clean native FLOOR WARP (area-to-area perpetual
play) and, as a fallback, a forced-collision patch that drops laser fences.

=== PRIMARY: clean floor warp (area transition) ========================================
The real native floor-load path (verified live + in the owned ELF; the same path the
boss-warp uses, so it LOADS the map — it does not snap position and will not snap back):
  current floor  : *(0x805D5FC0)   episode: *(0x805D6060)   travelling: *(0x805D49B8)
  SET_TARGET  0x80228540 (TRAVEL_STATE=0x80515BA0, floor) -> stores floor at +0xC, resolves map
  BEGIN_TRAVEL 0x8000F998 ()                              -> sets the load-request flag
  WARP        0x801BAB1C (player, floor)                  -> executes the party transition
These addresses/fingerprints live in gbox.pso_gc_adventure (Adventure, revision-guarded);
this module reuses them so there is a single verified source. `warp_to_floor` /
`advance_floor` give the navigation agent a one-call, fail-soft area transition.

Ep1 floor ids: 0 Pioneer2(town), 1 Forest1, 2 Forest2, 3 Cave1, 4 Cave2, 5 Cave3,
6 Mine1, 7 Mine2, 8 Ruins1, 9 Ruins2, 10 Ruins3, 11 Dragon, 12 DeRolLe, 13 VolOpt,
14 DarkFalz. (Ep2 numbering differs; branch on episode.)

=== SECONDARY: forced fence drop (fallback) ============================================
Laser fences (TObjLazerFenceNorm) drop/raise from a per-frame state machine. The fence
update (0x80192DC4) reads state at fence+0xB4: state 0 -> FENCE_STATE0 0x80192CCC (when
the stage flag at fence+0xB0 is set, call DROP then set state 1); state 1 -> FENCE_STATE1
0x80192D70 (when the flag clears, call RAISE then set state 0). DROP 0x80154764 does
`andc` on *(fence+0xA4)[0]+0x18 bit0 (clears the laser collision); RAISE 0x80154788 does
`or` (sets it). So the REAL collision-enable field is laser[0]+0x18 bit0, re-asserted every
frame from the stage flag - which is why a one-shot write (e.g. the probed laser+0x14,
the wrong field) never persisted. Forcing fences down = make FENCE_STATE0 always drop and
FENCE_STATE1 never raise (two class-wide instruction patches); fingerprint-guarded,
reversible. INERT by default (FENCE_FORCE_DOWN=False) until live-tested.
"""
import struct
import time

from .pso_gc_live import GC, FLOOR, FLUSH
from .registry import Unsupported

# ---- primary: floor warp ---------------------------------------------------------------
EPISODE_FLOOR = 0x805D6060
ROUTE_EP1 = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14)   # Forest -> ... -> Ruins -> bosses
FLOOR_NAMES_EP1 = {0: 'Pioneer2', 1: 'Forest1', 2: 'Forest2', 3: 'Cave1', 4: 'Cave2',
                   5: 'Cave3', 6: 'Mine1', 7: 'Mine2', 8: 'Ruins1', 9: 'Ruins2',
                   10: 'Ruins3', 11: 'Dragon', 12: 'DeRolLe', 13: 'VolOpt', 14: 'DarkFalz'}


def warp_to_floor(ad, floor, *, player_index=0):
    """Clean native area transition to `floor` for the host party. Fail-soft: returns a
    dict, never raises into the bot loop. Reuses the verified pso_gc_adventure primitives."""
    try:
        from .pso_gc_adventure import Adventure, WARP, SET_TARGET, BEGIN_TRAVEL, TRAVEL_STATE, TRAVELLING
        if not isinstance(floor, int) or not 0 <= floor <= 17:
            return {'ok': False, 'reason': 'floor must be 0..17'}
        m = Adventure(ad)
        p = m.check()                                    # revision + adventure fingerprints
        cur = m.u32(FLOOR)
        if cur == floor:
            return {'ok': True, 'warped': False, 'floor': floor, 'message': 'already in this area'}
        if not m.u16(p + 0x32C):
            return {'ok': False, 'reason': 'host is not alive'}
        if m.u32(TRAVELLING):
            return {'ok': False, 'reason': 'an area transition is already in progress'}
        # Native porter: set destination, begin loading, broadcast the player's destination.
        m.call([(SET_TARGET, TRAVEL_STATE, floor), (BEGIN_TRAVEL,), (WARP, p, floor)])
        if m.u32(TRAVEL_STATE + 12) != floor:
            return {'ok': False, 'reason': 'native loader did not acknowledge the destination'}
        ad._pso_floor_trip = {'floor': floor, 'from': cur, 'started': time.monotonic()}
        return {'ok': True, 'warped': True, 'from': cur, 'floor': floor,
                'name': FLOOR_NAMES_EP1.get(floor, str(floor)),
                'message': 'loading area %s' % FLOOR_NAMES_EP1.get(floor, floor)}
    except Unsupported as e:
        return {'ok': False, 'reason': str(e)[:160]}
    except Exception as e:                               # never crash the caller
        return {'ok': False, 'reason': str(e)[:160]}


def advance_floor(ad, route=ROUTE_EP1):
    """Warp to the next floor in `route` (wrapping), so the party keeps moving area to
    area. If the current floor is off-route (e.g. town), go to the first route floor."""
    try:
        m = GC(ad)
        m.check(player=False)
        cur = m.u32(FLOOR)
    except Exception as e:
        return {'ok': False, 'reason': str(e)[:160]}
    if cur in route:
        nxt = route[(route.index(cur) + 1) % len(route)]
    else:
        nxt = route[0]
    return warp_to_floor(ad, nxt)


def floor_status(ad):
    """Where the party is and whether a transition is in flight (read-only, fail-soft)."""
    try:
        from .pso_gc_adventure import TRAVELLING
        m = GC(ad)
        m.check(player=False)
        cur = m.u32(FLOOR)
        return {'ok': True, 'floor': cur, 'name': FLOOR_NAMES_EP1.get(cur, str(cur)),
                'episode': m.u32(EPISODE_FLOOR) + 1, 'travelling': bool(m.u32(TRAVELLING))}
    except Exception as e:
        return {'ok': False, 'reason': str(e)[:160]}


# ---- secondary: forced fence drop (fallback; inert by default) -------------------------
FENCE_FORCE_DOWN = False                                 # flip to True only after a live test
FENCE_DROP_SITE = 0x80192D40                             # FENCE_STATE0: bne that skips the drop
FENCE_RAISE_SITE = 0x80192D94                            # FENCE_STATE1: bne that skips the raise
SITE_ORIGINAL = bytes.fromhex('4082001c')                # both sites are this (bne cr0,+0x1c)
DROP_PATCH = bytes.fromhex('60000000')                   # nop -> FENCE_STATE0 always drops
RAISE_PATCH = bytes.fromhex('4800001c')                  # b +0x1c -> FENCE_STATE1 never raises
FENCE_GUARDS = {
    0x80192DC4: bytes.fromhex('9421fff07c0802a6'),                   # fence update prologue
    0x80192DD0: bytes.fromhex('800300b42c000001'),                   # lwz r0,0xB4(r3); cmpwi r0,1
    0x80192D50: bytes.fromhex('4bfc1a1538000001901f00b4'),           # bl DROP; li r0,1; stw r0,0xB4
    0x80192DA4: bytes.fromhex('4bfc19e538000000901f00b4'),           # bl RAISE; li r0,0; stw r0,0xB4
    0x80154778: bytes.fromhex('800300187c00287890030018'),           # DROP: lwz/andc/stw +0x18
    0x8015479C: bytes.fromhex('800300187c002b7890030018'),           # RAISE: lwz/or/stw +0x18
}
_SITES = ((FENCE_DROP_SITE, DROP_PATCH), (FENCE_RAISE_SITE, RAISE_PATCH))


class Fence(GC):
    def __init__(self, ad):
        super().__init__(ad)
        self.adapter = ad

    def check(self):
        self.check_build()
        for address, expected in FENCE_GUARDS.items():
            if self.read(address, len(expected)) != expected:
                raise Unsupported(f'PSO fence fingerprint differs at {address:#x}; no fence patch applied')
        for site, patch in _SITES:
            if self.read(site, 4) not in (SITE_ORIGINAL, patch):
                raise Unsupported('PSO fence code is modified by another patch; leave it intact')

    def check_build(self):
        # build/revision signature only (no live player needed to patch class code)
        super().check(player=False)

    def flush(self, addresses):
        lines = sorted({a & ~31 for a in addresses})
        if lines:
            self.call([(FLUSH, a) for a in lines])

    def status(self):
        self.check()
        return {'fence_force_down': all(self.read(s, 4) == p for s, p in _SITES), 'verified': True,
                'scope': 'all TObjLazerFenceNorm fences drop and stay down (class-wide)'}

    def set_enabled(self, on):
        self.check()
        changed = [(s, p) for s, p in _SITES if self.read(s, 4) != (p if on else SITE_ORIGINAL)]
        if not changed:
            return self.status()
        self.hook()
        for site, patch in changed:
            self.write(site, patch if on else SITE_ORIGINAL)
        self.flush([s for s, _ in changed])
        result = self.status()
        if result['fence_force_down'] != bool(on):
            raise RuntimeError('PSO fence patch read-back differs from the requested setting')
        return result | {'code_cache_flushed': True,
                         'message': 'Laser fences forced down.' if on else 'Normal fence behaviour restored.'}


def set_enabled(ad, platform, on):
    if platform != 'gamecube':
        raise Unsupported('Fence control is for the GameCube 3OE2 build only')
    return Fence(ad).set_enabled(bool(on))
