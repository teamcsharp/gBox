"""GoldenEye 007 (PAL, big-endian .z64) cheat-unlock ROM patch (static candidate).

Hooks fileGetIsCheatUnlocked(save, cheat) at ROM 0x50570 (identified by
signature: bounds check cheat<0x14, 3-byte flag assemble, sllv/and mask) so it
returns 1. Save data is never read or written. Not gameplay-verified: run on
i9-NUC/Spark via launch_game before claiming acceptance. Mission/stage unlock
(fileIsStageUnlockedAtDifficulty) is NOT covered yet.
Note: the N64 header CRC is not recomputed (fine for emulators).
"""
from __future__ import annotations
import hashlib

ROM_SHA256 = '40ff3643d3ed0be1b0b88266d298f455c15bd5a6f1a520c9aa2650b5f4b349de'
FUNC_OFFSET = 0x50570
ORIGINAL = bytes.fromhex('04a0001128a100141020000f')  # bltz a1; slti at,a1,0x14; beqz at
PATCH = bytes.fromhex('24020001' '03e00008' '00000000')  # li v0,1; jr ra; nop


def apply(rom: bytes) -> bytes:
    if hashlib.sha256(rom).hexdigest() != ROM_SHA256:
        raise ValueError('not the verified GoldenEye PAL ROM')
    if rom[FUNC_OFFSET:FUNC_OFFSET + len(ORIGINAL)] != ORIGINAL:
        raise ValueError('unexpected bytes at fileGetIsCheatUnlocked')
    return rom[:FUNC_OFFSET] + PATCH + rom[FUNC_OFFSET + len(PATCH):]
