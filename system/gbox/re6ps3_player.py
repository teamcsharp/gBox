"""RE6 PS3 (BLUS30855, RPCS3) player-struct locator + decoder — request 3367.

The PS3 build shares the MT Framework uPlayer layout with the verified Xbox 360 map
(docs/re6-ram-map-0871eee3b68cdea3.json, request 3023, evidence live in Xenia):

    sPlayer singleton -> +0x28 = player 1 uPlayer
    uPlayer +0x50    = f32[3] position (cm, units_per_m 100)
    uPlayer +0xF20   = s16 hp, +0xF22 = s16 hp_max
    uPlayer +0x3EE8  = u32 weapon slot

PS3 base addresses are NOT yet measured; EBOOT.BIN (BLUS30855 01.00,
sha256 161788e7c0264b1b9d5cd72ac051c9ce2a64b7c85d04f954b2e35f202834af67) is under
Ghidra analysis to pin the sPlayer singleton statically. Until then, locate it at
runtime: scan the RPCS3 guest heap for the chain pattern below (see locate_splayer).

Everything here is fixture-testable offline (tests/test_re6ps3_player.py).
"""
from __future__ import annotations

import struct

EBOOT_SHA256 = "161788e7c0264b1b9d5cd72ac051c9ce2a64b7c85d04f954b2e35f202834af67"
EBOOT_TITLE = "RE6 PS3 BLUS30855 app 01.00 (SELF KeyRev 0x001C)"

# uPlayer field offsets inherited from the Xbox 360 RE6 map (same MT Framework build family).
OFF_PLAYER_PTR = 0x28      # sPlayer + 0x28 -> player 1 uPlayer
OFF_POS = 0x50             # f32 x,y,z
OFF_HP = 0xF20             # s16 life, s16 life_max
OFF_SLOT = 0x3EE8          # u32 weapon slot (d-pad switch)
HP_MAX_LIMIT = 3000        # RE6 Mercenaries life ceiling sanity bound
POS_ABS_LIMIT = 1.0e6      # any world coordinate must be far below this

# RPCS3 guest memory: the game's main heap allocations live in this window.
SCAN_RANGE = (0x10000000, 0xC0000000)
SCAN_STRIDE = 0x100        # sPlayer is a large singleton; candidates align at least this


class _Reader:
    def __init__(self, rd):
        self.rd = rd


def _read(reader, addr: int, n: int) -> bytes:
    fn = getattr(reader, "read", None)
    if fn is None:
        fn = reader.rd
    return fn(addr, n)


def _u32(reader, addr: int) -> int:
    return struct.unpack(">I", _read(reader, addr, 4))[0]


def _looks_like_uplayer(reader, up: int) -> bool:
    """Cheap predicate: uPlayer+0x50 floats sane and +0xF20 life in range."""
    if not (0x10000 <= up < 0xC0000000) or up % 4:
        return False
    try:
        pos = struct.unpack(">3f", _read(reader, up + OFF_POS, 12))
        hp, hp_max = struct.unpack(">hh", _read(reader, up + OFF_HP, 4))
    except Exception:
        return False
    return (
        all(abs(c) < POS_ABS_LIMIT for c in pos)
        and 0 <= hp <= HP_MAX_LIMIT
        and 0 < hp_max <= HP_MAX_LIMIT
        and hp <= hp_max
    )


def locate_splayer(reader, scan_range=None, stride=SCAN_STRIDE, limit=8):
    """Find the sPlayer singleton in live guest memory.

    Scans for a 4-byte BE value `p` such that p+OFF_PLAYER_PTR points at a plausible
    uPlayer. Returns [(splayer_addr, uplayer_addr), ...] best-effort candidates
    (the singleton also passes the predicate; confirm by reading both player slots).
    """
    lo, hi = scan_range or SCAN_RANGE
    out = []
    step = max(4, stride)
    for addr in range(lo, hi - 8, step):        # addr = candidate sPlayer singleton
        try:
            up = _u32(reader, addr + OFF_PLAYER_PTR)
        except Exception:
            continue
        if _looks_like_uplayer(reader, up):
            out.append((addr, up))
            if len(out) >= limit:
                break
    return out


def read_player(reader, uplayer: int) -> dict:
    """Decode one uPlayer at `uplayer` into named fields (all offsets cited above)."""
    pos = struct.unpack(">3f", _read(reader, uplayer + OFF_POS, 12))
    hp, hp_max = struct.unpack(">hh", _read(reader, uplayer + OFF_HP, 4))
    slot = struct.unpack(">I", _read(reader, uplayer + OFF_SLOT, 4))[0]
    return {
        "address": uplayer,
        "pos": list(pos),
        "hp": hp,
        "hp_max": hp_max,
        "weapon_slot": slot,
        # NOT yet decoded on any build (Xbox map gaps too): yaw, aim pitch, action
        # state, ammo. Tracked for the Ghidra pass over the PS3 EBOOT.
        "pending_fields": ["facing", "aim_pitch", "action_state", "ammo"],
    }
