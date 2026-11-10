"""RE4 Switch (main.bin, mem = file offset - 0x100) grenade / flash-grenade blast anchors (request #9436).

Found by static scan (capstone), mirroring the GC recipe in gbox/re_games.py (GRENADE_AT_CODE / FLASH_AT_CODE).
Static evidence only: nothing here has been run live yet. Offsets are relative to the main module base.
"""
import struct

EFFECT = 0x1F7DC0          # (owner=0, w1=-1, x2=pos, x3=0, w4=0, w5=effect id, w6=0, w7=0, stack 0,0)
SOUND = 0x261C20           # (w0=1, w1=sound id, x2=pos, w3=0, w4=0, x5=0)
AREA_ATTACK = 0x33B770     # (x0=0, x1=pos*, x2=pos*, w3=attack class, w4=0, s0=radius) == GC 0x8003... area hit
BLAST_FLAG_SETS = ((0x5090, 0x800000), (0x5094, 0x20000000))   # ORed into game+off around the blast

# name -> {fn: start, vtable: (rodata slot, ...), effect ids, sound id, attack class, radius const addr, radius}
BLASTS = {
    "grenade": dict(fn=0x2E48B0, vtable=(0x67B3F0,), effects=(0x1A, 0x0D), sound=0x14, area_class=0x13,
                    radius_at=0x6E8BBC, radius=6000.0, area_call=0x2E4A54),
    "simple_blast": dict(fn=0x2E4AA0, vtable=(0x67B408,), effects=(), sound=0x17, area_class=0x13,
                         radius_at=0x6E8BBC, radius=6000.0, area_call=0x2E4AF0),
    "flash": dict(fn=0x2E4E50, vtable=(0x67B5A0,), effects=(0x3F, 0x0C), sound=0x13, area_class=0x17,
                  radius_at=0x6E8A74, radius=15000.0, area_call=0x2E4FA0, pos_y_add_at=0x6E8964),
}
OBJ_POS = 0xA4            # object + 0xa4 = vec3 (x,y,z); y at +0xa8


def _bl_target(text, addr):
    w = struct.unpack_from("<I", text, addr)[0]
    if w >> 26 != 0b100101:
        return None
    off = w & 0x3FFFFFF
    if off & 0x2000000:
        off -= 0x4000000
    return addr + off * 4


def verify(main_bin):
    """Check the anchors against raw main.bin bytes; returns a list of problems (empty == consistent)."""
    t = main_bin[0x100:]
    bad = []
    for name, b in BLASTS.items():
        if _bl_target(t, b["area_call"]) != AREA_ATTACK:
            bad.append(f"{name}: bl at {b['area_call']:#x} is not AREA_ATTACK")
        for slot in b["vtable"]:
            if struct.unpack_from("<Q", t, slot)[0] != b["fn"]:
                bad.append(f"{name}: vtable {slot:#x} != fn {b['fn']:#x}")
        if abs(struct.unpack_from("<f", t, b["radius_at"])[0] - b["radius"]) > 1e-3:
            bad.append(f"{name}: radius const mismatch")
    return bad
