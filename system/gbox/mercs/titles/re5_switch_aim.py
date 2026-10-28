"""RE5 Switch's input-side aim state: the player camera's pitch and the player's heading, for the bot's RAM aim lock
(re5_switch.AIM_LOCK; off until a live round shows the writes hold).

Found statically in main EBFFDB22 and read live (read-only, MercMode 2026-10-27 19:44-19:52, 2600 samples, 317 aimed):
sUnit move line 9 holds two uCameraCtrl units (vtable main+0x1ACB410); the player's is the one whose +0x130 points at
the player. Its +0x198 is the ACTIVE camera: the uCameraQFPS embedded at ctrl+0xDB0 (vtable main+0x1ACBCF0, size 0x680:
the class RE6's #1367 locks, there at camera+0x16A0). Its update is main+0x249400.
  QFPS+0x1B0 f32  the PITCH, radians, + = up, clamped to [-1, +1] (0x2499b4..0x2499cc; 1 rad = the aim's +-57 deg
                  limits seen live), integrated from the right stick each frame (0x249970 ldr / 0x249978 fadd /
                  0x24997c str): persistent state. Live: player +0x3F5C = -0.9989 x QFPS+0x1B0 + 0.004 (sd 1.0 deg), and
                  it keeps its value with the gun down - the pitch the next raise starts from (the +57 deg raises).
  QFPS+0x1B4 f32  this frame's yaw delta (recomputed: not a state).
The yaw's state is the player's own heading, the quaternion at +0x70: the aiming motion (0x96cd30) reads the rotation,
adds the frame's turn and sets it back (0x96cf54 / 0x96cf78), so a written heading should persist (one held with the
gun down, 2026-10-27). Live: the laser's yaw - the heading over 139 long rays, median -0.3 deg.
The writes are UNVERIFIED in a round (no private slot): aim_writer reads every write back and the bot falls back to
the stick when a read-back fails.
"""
from __future__ import annotations

import math
import struct

CTRL_VT, QFPS_VT = 0x1ACB410, 0x1ACBCF0
CTRL_PLAYER, CTRL_ACTIVE, CTRL_QFPS = 0x130, 0x198, 0xDB0
QF_PITCH = 0x1B0
PITCH_LIMIT = 1.0                        # rad: the game's clamp
P_ROT = 0x70
CAM_LINE, S_UNIT, UNIT_LINES, LINE_STRIDE, UNIT_NEXT = 9, 0x26A3270, 0x18, 0x30, 0x18
LOCK_TOL = 2e-3                          # rad: a read-back this close is the write
ERRORS = (ValueError, OSError, OverflowError, struct.error, RuntimeError)


def _q(m, a):
    return struct.unpack("<Q", m.rd(a, 8))[0]


def _ok(p):
    return isinstance(p, int) and 0x1000000 <= p < (1 << 40)


def wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def player_qfps(m, base: int, player: int) -> int | None:
    """The player's active uCameraQFPS (ctrl+0xDB0 of line 9's uCameraCtrl whose +0x130 is the player, when it is the
    ctrl's active camera); None otherwise. Never raises."""
    try:
        su = _q(m, base + S_UNIT)
        if not _ok(su):
            return None
        u, n = _q(m, su + UNIT_LINES + LINE_STRIDE * CAM_LINE), 0
        while _ok(u) and n < 16:
            if _q(m, u) == base + CTRL_VT and _q(m, u + CTRL_PLAYER) == player:
                qf = u + CTRL_QFPS
                return qf if _q(m, qf) == base + QFPS_VT and _q(m, u + CTRL_ACTIVE) == qf else None
            u, n = _q(m, u + UNIT_NEXT), n + 1
    except ERRORS:
        return None
    return None


def aim_state(m, base: int, player: int) -> dict | None:
    """{"qfps", "pitch" (rad, + = up), "heading" (rad, from the quaternion)}; None without the player's camera."""
    qf = player_qfps(m, base, player)
    if qf is None:
        return None
    try:
        pitch = struct.unpack("<f", m.rd(qf + QF_PITCH, 4))[0]
        _qx, qy, _qz, qw = struct.unpack("<4f", m.rd(player + P_ROT, 16))
    except ERRORS:
        return None
    if not (math.isfinite(pitch) and abs(pitch) <= PITCH_LIMIT + 1e-3 and math.isfinite(qy) and math.isfinite(qw)):
        return None
    return {"qfps": qf, "player": player, "pitch": pitch, "heading": wrap(2.0 * math.atan2(qy, qw))}


def aim_writer(m):
    """The aim lock's writer for this session: write(state, pitch, heading) -> True once each written value reads back
    (pitch into QFPS+0x1B0, clamped; the heading as the player's quaternion about y; either may be None). None without
    the session's adapter or with modifications off."""
    ad = getattr(m, "adapter", None)
    if ad is None or getattr(m, "mercs_no_modifications", False):
        return None

    def write(st: dict, pitch: float | None, heading: float | None) -> bool:
        try:
            if pitch is not None:
                p = max(-PITCH_LIMIT, min(PITCH_LIMIT, float(pitch)))
                ad.write_memory(st["qfps"] + QF_PITCH, struct.pack("<f", p))
                if abs(struct.unpack("<f", ad.read_memory(st["qfps"] + QF_PITCH, 4))[0] - p) > LOCK_TOL:
                    return False
            if heading is not None:
                h = wrap(float(heading))
                ad.write_memory(st["player"] + P_ROT, struct.pack("<4f", 0.0, math.sin(h / 2), 0.0, math.cos(h / 2)))
                _qx, qy, _qz, qw = struct.unpack("<4f", ad.read_memory(st["player"] + P_ROT, 16))
                if abs(wrap(2.0 * math.atan2(qy, qw) - h)) > LOCK_TOL:
                    return False
        except ERRORS:
            return False
        return True
    return write
