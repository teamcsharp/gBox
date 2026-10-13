"""Dead Or Alive ++ (arcade, Tecmo TPS) motion banks and the game's own skeleton evaluator (ticket #1340).

Motion bank (files 27-37, one per fighter, loaded for player p at *(0x80087288 + 4p) = 0x80196800 / 0x80226800):

  +0x0000  4 x 0x404 bytes   IK bend tables, s16[0x202] each (arm, arm, leg, leg; limb record +0x54). The limb solver
                             0x800ace28 reads entry ((distance + 3) * 512) // 1000 as the elbow / knee bend angle.
  +0x1010  4 x u32           offsets of the four tables (the fight loader 0x8006c300 adds the load address)
  +0x1020  u32 list, 0-ended offsets of the motion records (several entries may share a record), 265 for Tina
  record   9 x u32           offsets (relocated the same way when below the load address):
             [0..2]  rotation tracks, one u32 per frame: x = (w >> 20) & 0xffe, y = (w >> 9) & 0xffc,
                     z = (w << 1) & 0xffe (12-bit angles, 4096 = 360 degrees). Track 0 -> rotation slot 0 (upper
                     body, bone 0), 1 -> slot 1 (head), 2 -> slot 2 (pelvis, bone 2).
             [3..6]  limb tracks, 5 bytes per frame = four big-endian 10-bit fields, each << 2: the end bone's
                     rotation (x, y, z) and the limb twist (pole) angle. Facing +1 the game's limbs 0..3 (right arm,
                     left arm, right leg, left leg) read words 6, 4, 5, 3 (table 0x80100118; mirrored 0x80100128).
             [7]     curve block: 15 s16 halfword offsets, then curves (below). Header curves 0..2 = root x, y, z;
                     3+3k..5+3k = the IK target (x, y, z) of limb k (facing +1, table 0x80100138; 0x80100174 mirrored).
             [8]     0 or another block (not used by the pose path; not decoded here).
  curve    halfword segments, type = low 3 bits of the first halfword (handlers 0x80100210 / 0x801001d0 /
           0x801001b0 / 0x801001f0, lengths 0x80100230):
             type 0  [h0 h1 h2]  frames = bits 3..11 of h0, accel a = ((h0 & 0xf000) << 4 | h2) (signed), start = h1
             type 4  [h0 h1]     frames = bits 3..11 of h0, a = 0, start = h1
             type 2/6 [h0 h1]    frames = (h1 & 7) + 3, a = (h1 & ~7) >> 1, start = h0 & ~3
             type 1/5 [h0]       one frame, value = h0 & ~3 (no slope)
             type 3/7 [h0]       end: value = h0 & ~3 from here on
           A segment's end value is the next segment's start (h1 for types 0 / 4, h0 & ~3 otherwise);
           b = ((end - start) << 8) / frames - a * frames (truncating division; type 4: no a term), and frame t of the
           segment is ((a * t + b) * t >> 10) + (start >> 2), so the curve lands exactly on end / 4.

Per game frame (speed 0x1000, one motion frame per tick; the stance move's script sets it): the stepper 0x8009adbc reads
one word of each rotation track and 5 bytes of each limb track (facing +1: x, -y, z), 0x80099b30 evaluates the 15 curves
(root y absolute, root x / z as deltas), then the per-player build 0x800a4848 composes the player transform with the
pelvis rotation (bone 2), the per-fighter torso offset (0x801011d8 + 8 * s16 0x80102248[fighter]) and the upper-body
rotation (bone 0), the head look (0x800a6cb4, bone 1), the shoulder / hip positions, then the two-bone IK 0x800ace28 for
the four limbs (upper, lower and end bones from the table at 0x80103f44: 14/10/11, 8/4/5, 12/13/9, 6/7/3, lengths from
0x80101b80 + 32 * fighter), and the accessory chain solver 0x800aa1c0 (bones 15+, hair / ribbons, physics with state).
The result is 32-byte PS1 MATRIX records (s16 3x3 rotation 4.12, s32 translation) at 0x8011ca60 + 0x340 * player,
in world space (y down).

Rig runs exactly that code (the decoded program from gbox.zn_tps_boot, with a GTE model, gbox.psx_gte) on a
fight state built the way the fight loader leaves it: both players' per-fighter data, motion bank and model in place,
then the fight init 0x800a860c. Nothing of the evaluator is re-implemented; the Python decoders in this module
(parse_bank, channels) describe the format and are checked against the game's own state by the owned-ROM tests.
"""
from __future__ import annotations

import struct

IK_TABLES, IK_TABLE_SIZE = 4, 0x404
IK_OFFSETS, MOTION_LIST = 0x1010, 0x1020
RECORD_WORDS = 9
ROT_TRACKS = 3
LIMB_WORDS = (6, 4, 5, 3)            # limb k (facing +1) <- record word; the rotation slot it writes has the same number
CURVES = 15
LIMB_CURVES = tuple(tuple(3 + 3 * k + i for i in range(3)) for k in range(4))
ROOT_CURVES = (0, 1, 2)
SEGMENT_HALFWORDS = (3, 1, 2, 0, 2, 1, 2, 0)
STANCE_MOTION = 0                    # move 0 (neutral) plays motion 0, a loop (first frame == last frame)

# --- game addresses the Rig uses (decoded doapp program + overlay) --------------------------------------------------
CHAR_DATA = 0x80087280               # per player: small_a load address (its 32 sub-table pointers, relocated)
MOTION_AT = 0x80087288               # per player: motion bank load address
WORK_AT = 0x8008775C                 # per player: model work buffer (14 section pointers at its start)
PLAYER = 0x80096340                  # player records, 0x60 each: +1 fighter id, +2 costume
RELOCATE_CHAR = 0x8006A754           # small_a relocation (a0 = player)
UNPACK = 0x8006C718                  # section expander (a0 player, a1 source, a2 destination) -> next source
FIGHT_INIT = 0x800A860C              # both players: limbs, models, chains
SET_MOTION = 0x8009F0A8              # (player, motion)
MOTION_TICK = 0x800996F4             # (player) one game frame of the motion player
LIMB_TARGETS = 0x800A1710            # (player) curve targets -> world, with the player transform loaded in the GTE
BUILD = 0x800A4848                   # (player, light record) the skeleton build
IDENTITY, TRANSLATE = 0x8002F35C, 0x8002F2FC
LIGHT = 0x8011B0F0
SPEED, START_FRAME = 0x8011B640, 0x8011D408
HALF_RATE, HALF_PHASE = 0x8011D430, 0x8011D7E2   # u8 per player: interpolating stepper on / showing the in-between
ROOT = 0x8011B6E8                    # per player, 3 x s32 (x, z are integrated deltas)
BONES_AT, BONE_STRIDE, BONE_SLOTS = 0x8011CA60, 0x340, 26
HAND_SHAPE = 0x8011D40C              # u8 per slot 4 / slot 2, + 2 * player: which of the three hand shapes is drawn
SECTION_COUNT = 14
PACKED_SECTIONS = frozenset({3, 4, 5, 6, 7, 8, 9, 10, 12})


class MotionError(ValueError):
    pass


def _u32(b: bytes, o: int) -> int:
    if o < 0 or o + 4 > len(b):
        raise MotionError(f"u32 at {o:#x} outside {len(b):#x} bytes")
    return struct.unpack_from("<I", b, o)[0]


def _s16(b: bytes, o: int) -> int:
    if o < 0 or o + 2 > len(b):
        raise MotionError(f"s16 at {o:#x} outside {len(b):#x} bytes")
    return struct.unpack_from("<h", b, o)[0]


def _tdiv(x: int, y: int) -> int:
    """MIPS div: truncate toward zero."""
    q = abs(x) // abs(y)
    return q if (x < 0) == (y < 0) else -q


# ---- container ---------------------------------------------------------------------------------------------------
def parse_bank(data: bytes) -> dict:
    """{'ik_tables': [4 x list of s16], 'motions': [{index, record, rot, limbs, curves, extra, frames}]} with file
    offsets (as stored, before the loader adds the load address)."""
    if len(data) < MOTION_LIST + 4:
        raise MotionError("too short for a motion bank")
    offs = struct.unpack_from("<4I", data, IK_OFFSETS)
    if offs != tuple(IK_TABLE_SIZE * k for k in range(IK_TABLES)):
        raise MotionError(f"IK table offsets {offs} are not 0/0x404/0x808/0xc0c")
    tables = [list(struct.unpack_from(f"<{IK_TABLE_SIZE // 2}h", data, o)) for o in offs]
    motions, a = [], MOTION_LIST
    while True:
        rec = _u32(data, a)
        if rec == 0:
            break
        if not MOTION_LIST < rec <= len(data) - 4 * RECORD_WORDS:
            raise MotionError(f"motion {len(motions)}: record offset {rec:#x} outside the bank")
        w = struct.unpack_from(f"<{RECORD_WORDS}I", data, rec)
        for k in range(8):
            if not 0 < w[k] < len(data):
                raise MotionError(f"motion {len(motions)}: word {k} = {w[k]:#x} outside the bank")
        motions.append({"index": len(motions), "record": rec, "rot": list(w[:3]), "limbs": list(w[3:7]),
                        "curves": w[7], "extra": w[8] or None})
        a += 4
    if not motions:
        raise MotionError("empty motion list")
    starts = sorted({o for m in motions for o in m["rot"] + m["limbs"] + [m["curves"]]} | {m["record"] for m in motions}
                    | {len(data)})
    for m in motions:
        m["frames"] = curve_frames(data, m["curves"])
        nxt = starts[starts.index(m["rot"][2]) + 1]
        m["track_frames"] = (nxt - m["rot"][2]) // 4
        # tracks sampled at half the curve rate: the move script toggles the interpolating stepper (0x6666 opcode,
        # flag 0x8011d430) and 0x80099fa4 shows every track frame, then the midpoint to the next one
        m["half_rate"] = m["frames"] > m["track_frames"] + 1
    return {"ik_tables": tables, "motions": motions}


def decode_rot(word: int) -> tuple[int, int, int]:
    """A rotation-track word -> raw (x, y, z) angle fields (4096 = 360 degrees); facing +1 the game uses (x, -y, z)."""
    return (word >> 20) & 0xFFE, (word >> 9) & 0xFFC, (word << 1) & 0xFFE


def encode_rot(x: int, y: int, z: int) -> int:
    """Inverse of decode_rot for angles already on the field grids (x, z multiples of 2, y of 4)."""
    if x & ~0xFFE or y & ~0xFFC or z & ~0xFFE:
        raise MotionError(f"angles {x, y, z} are not on the track's 11/10/11-bit grid")
    return (x << 20) | (y << 9) | (z >> 1)


def decode_limb(b5: bytes) -> tuple[int, int, int, int]:
    """5 limb-track bytes -> raw (x, y, z, twist) fields; facing +1 the end-bone rotation is (x, -y, z)."""
    if len(b5) != 5:
        raise MotionError("a limb frame is 5 bytes")
    v = int.from_bytes(b5, "big")
    return tuple(((v >> s) & 0x3FF) << 2 for s in (30, 20, 10, 0))


def encode_limb(x: int, y: int, z: int, w: int) -> bytes:
    v = 0
    for a in (x, y, z, w):
        if a & ~0xFFC:
            raise MotionError(f"limb angle {a} is not a multiple of 4 below 4096")
        v = v << 10 | a >> 2
    return v.to_bytes(5, "big")


# ---- curves ------------------------------------------------------------------------------------------------------
def segment(data: bytes, off: int) -> dict:
    """One curve segment at `off`: type, frames, a, start, size (bytes)."""
    h0 = struct.unpack_from("<H", data, off)[0]
    t = h0 & 7
    s0 = _s16(data, off)
    if t == 0:
        a = ((s0 & -0x1000) << 4) | struct.unpack_from("<H", data, off + 4)[0]
        return {"type": t, "frames": (h0 >> 3) & 0x1FF, "a": a, "start": _s16(data, off + 2), "size": 6}
    if t == 4:
        return {"type": t, "frames": (h0 >> 3) & 0x1FF, "a": 0, "start": _s16(data, off + 2), "size": 4}
    if t in (2, 6):
        s1 = _s16(data, off + 2)
        return {"type": t, "frames": (s1 & 7) + 3, "a": (s1 & -8) >> 1, "start": s0 & -4, "size": 4}
    if t in (1, 5):
        return {"type": t, "frames": 1, "a": 0, "start": s0 & -4, "size": 2}
    return {"type": t, "frames": 0, "a": 0, "start": s0 & -4, "size": 2}     # 3 / 7: end


def _end_value(data: bytes, off: int) -> int:
    h0 = struct.unpack_from("<H", data, off)[0]
    return _s16(data, off + 2) if h0 & 3 == 0 else _s16(data, off) & -4      # types 0/4: h1; others h0 & ~3


def curve_offsets(data: bytes, block: int) -> list[int]:
    return [block + 2 * _s16(data, block + 2 * k) for k in range(CURVES)]


def curve_segments(data: bytes, off: int, limit: int = 4096) -> list[dict]:
    out = []
    while len(out) < limit:
        s = segment(data, off)
        s["offset"] = off
        out.append(s)
        if s["frames"] == 0:
            return out
        off += s["size"]
    raise MotionError(f"curve at {off:#x} has no end segment")


def curve_frames(data: bytes, block: int) -> int:
    """Frames of a motion: the root-x curve (header 0, whose end the game watches) up to its end segment, + 1."""
    return sum(s["frames"] for s in curve_segments(data, curve_offsets(data, block)[0])) + 1


def curve_values(data: bytes, off: int, frames: int) -> list[int]:
    """The curve's value per frame, the way 0x800a0108 / 0x800a0aac / 0x80099b30 step it."""
    out, seg = [], segment(data, off)

    def coeffs(seg, off):
        if seg["frames"] == 0:
            return 0
        end = _end_value(data, off + seg["size"])
        b = _tdiv((end - seg["start"]) << 8, seg["frames"])
        return b - seg["a"] * seg["frames"]
    b, t = coeffs(seg, off), 0
    for _ in range(frames):
        out.append(((seg["a"] * t + b) * t >> 10) + (seg["start"] >> 2))
        t += 1
        if seg["frames"] and t == seg["frames"]:
            off += seg["size"]
            seg, t = segment(data, off), 0
            b = coeffs(seg, off)
    return out


class TwistEvents:
    """Record word 8 of a half-rate motion: limb-twist keys (0x8009abac, read by the interpolating stepper only).
    u16 stream: bit 15 = frame marker (frame (h & 0x7fff) + 1 on the game's counter), bit 14 = key for limb h & 0x3fff
    (facing +1) followed by an s16 whose >> 4 replaces that limb's twist on the next in-between frame, anything else
    ends the stream. Keys under a marker already passed are skipped."""

    def __init__(self, data: bytes, off: int):
        self.data, self.off = data, off
        self.cache = struct.unpack_from("<H", data, off)[0]
        self.pending: list[int | None] = [None] * 4

    def advance(self, counter: int) -> None:
        d, mode = self.data, 0
        while self.cache != 0x7777:
            h = self.cache
            if h & 0x8000:
                fr = (((h & 0x7FFF) + 1) ^ 0x8000) - 0x8000
                if counter < fr or mode == 1:
                    return
                mode = 2 if fr < counter else 1
                self.off += 2
            elif h & 0x4000:
                if mode != 1:
                    self.off += 4
                else:
                    limb = h & 0x3FFF
                    if limb > 3:
                        raise MotionError(f"twist key for limb {limb} at {self.off:#x}")
                    self.pending[limb] = _s16(d, self.off + 2) >> 4
                    self.off += 4
            else:
                self.cache = 0x7777
                return
            self.cache = struct.unpack_from("<H", d, self.off)[0]


def channels(data: bytes, motion: dict, frames: int | None = None) -> list[dict]:
    """Per frame, facing +1, the values the stepper and curve evaluator hand the skeleton build: rot (3 x (x, y, z)
    for slots 0..2), limbs (4 x (x, y, z, twist) in the game's limb order), targets (4 x (x, y, z), player space),
    root (x, y, z; x / z relative to frame 0, y absolute)."""
    n = motion["frames"] if frames is None else frames
    offs = curve_offsets(data, motion["curves"])
    cv = [curve_values(data, o, n) for o in offs]

    def rot_at(k, i):
        x, y, z = decode_rot(_u32(data, motion["rot"][k] + 4 * i))
        return x, -y, z

    def limb_at(k, i):
        off = motion["limbs"][LIMB_WORDS[k] - 3] + 5 * i
        x, y, z, w = decode_limb(data[off:off + 5])
        return x, -y, z, w

    def mid(a, b):                    # 0x80099fa4's in-between frame: b + wrapped (a - b) / 2, per component
        out = []
        for u, v in zip(a, b):
            d = (u - v) & 0xFFF
            out.append(v + ((d - 0x1000 if d > 0x800 else d) >> 1))
        return tuple(out)
    out = []
    events = TwistEvents(data, motion.get("extra") or 0) if motion.get("half_rate") else None
    for f in range(n):
        i, between = (f >> 1, f & 1) if motion.get("half_rate") else (f, 0)
        rot = [rot_at(k, i) for k in range(ROT_TRACKS)]
        limbs = [limb_at(k, i) for k in range(4)]
        if events is not None:
            events.advance(f + 2)                 # the game's frame counter during tick f
        if between:
            rot = [mid(rot[k], rot_at(k, i + 1)) for k in range(ROT_TRACKS)]
            limbs = [mid(limbs[k], limb_at(k, i + 1)) for k in range(4)]
            for k in range(4):
                if events.pending[k] is not None:
                    limbs[k] = limbs[k][:3] + (events.pending[k],)
                    events.pending[k] = None
        out.append({"rot": rot, "limbs": limbs,
                    "targets": [tuple(cv[c][f] for c in LIMB_CURVES[k]) for k in range(4)],
                    "root": (cv[0][f] - cv[0][0], cv[1][f], cv[2][f] - cv[2][0])})
    return out


# ---- the game's evaluator on the interpreter ---------------------------------------------------------------------
class Rig:
    """Fight state for one fighter / costume (both players load it), driven by the game's own motion and skeleton
    code. program_ram: doapp_inventory.decode_owned()[1]; banked: its bankedroms image."""

    STACK = 0x803FFF00
    MODEL_SOURCE = 0x80300000          # free RAM (4 MiB board) where the packed model file is placed for the expander

    def __init__(self, program_ram: bytes, banked: bytes, fighter: dict, costume: int):
        from . import doapp_inventory as D, psx_gte, zn_tps_boot as Z
        self.D, self.fighter, self.costume = D, fighter, costume
        self.mem = Z.ZNMemory(b"\0" * 16, b"", b"\0" * 8, b"\0" * 8, ram_size=0x400000)
        self.mem.ram[:len(program_ram)] = program_ram
        self.cpu = Z.R3000(self.mem, psx_gte.GTE())
        self.banked = banked
        self.model = D.read_file(banked, fighter["models"][costume])
        self.bank = D.read_file(banked, fighter["motion"])
        self.motions = parse_bank(self.bank)["motions"]
        self.section_lengths = {}
        for p in (0, 1):
            self._load(p)
        self.call(FIGHT_INIT)

    # memory helpers
    def r32(self, a: int) -> int:
        return struct.unpack_from("<I", self.mem.ram, a & 0x3FFFFF)[0]

    def s32(self, a: int) -> int:
        return struct.unpack_from("<i", self.mem.ram, a & 0x3FFFFF)[0]

    def w32(self, a: int, v: int) -> None:
        struct.pack_into("<I", self.mem.ram, a & 0x3FFFFF, v & 0xFFFFFFFF)

    def put(self, a: int, data: bytes) -> None:
        o = a & 0x3FFFFF
        self.mem.ram[o:o + len(data)] = data

    def call(self, fn: int, *args) -> int:
        return self.cpu.call(fn, args, sp=self.STACK, limit=20_000_000)

    def _load(self, p: int) -> None:
        D, f = self.D, self.fighter
        rec = PLAYER + 0x60 * p
        self.mem.ram[(rec + 1) & 0x3FFFFF] = f["id"]
        self.mem.ram[(rec + 2) & 0x3FFFFF] = self.costume
        char = self.r32(CHAR_DATA + 4 * p)
        self.put(char, D.read_file(self.banked, f["small_a"]))
        self.call(RELOCATE_CHAR, p)
        base = self.r32(MOTION_AT + 4 * p)
        self.put(base, self.bank)
        for k in range(IK_TABLES):                                  # as the fight loader 0x8006c618.. relocates
            self.w32(base + IK_OFFSETS + 4 * k, self.r32(base + IK_OFFSETS + 4 * k) + base)
        a = base + MOTION_LIST
        while self.r32(a):
            r = self.r32(a) + base
            self.w32(a, r)
            if self.r32(r) < base:
                for j in range(RECORD_WORDS):
                    self.w32(r + 4 * j, self.r32(r + 4 * j) + base)
            a += 4
        self.w32(char + 0x58, base + MOTION_LIST)                 # character data +0x58 / +0x5c (0x8006c6d0)
        self.w32(char + 0x5C, base + IK_OFFSETS)
        work = self.r32(WORK_AT + 4 * p)
        src = self.MODEL_SOURCE + 0x40000 * p
        model = self.model
        self.put(src, model)
        q = 4
        for s in range(SECTION_COUNT):                              # 0x8006c46c..
            q = (q + 3) & ~3
            dest = struct.unpack_from("<i", model, q)[0]
            if dest == 0:
                self.w32(work + 4 * s, 0)
                q += 4
                continue
            length = struct.unpack_from("<I", model, q + 4)[0]
            addr = work + dest if dest > 0 else dest + work - self.r32(WORK_AT)
            self.w32(work + 4 * s, addr)
            q += 8
            if p == 0:
                self.section_lengths[s] = length
            if s in PACKED_SECTIONS:
                q = self.call(UNPACK, p, src + q, addr) - src
            else:
                self.put(addr, model[q:q + length])
                q += length

    def sections(self, p: int = 0) -> dict[int, bytes]:
        """Player p's expanded sections as the fight loader left them."""
        work = self.r32(WORK_AT + 4 * p)
        out = {}
        for s, n in self.section_lengths.items():
            a = self.r32(work + 4 * s) & 0x3FFFFF
            out[s] = bytes(self.mem.ram[a:a + n])
        return out

    def play(self, motion: int, p: int = 0, speed: int = 0x1000) -> None:
        if not 0 <= motion < len(self.motions):
            raise MotionError(f"motion {motion} outside 0..{len(self.motions) - 1}")
        self.w32(SPEED + 4 * p, speed)
        struct.pack_into("<h", self.mem.ram, (START_FRAME + 2 * p) & 0x3FFFFF, 1)
        self.mem.ram[(HALF_RATE + p) & 0x3FFFFF] = 1 if self.motions[motion]["half_rate"] else 0
        self.mem.ram[(HALF_PHASE + p) & 0x3FFFFF] = 0
        self.call(SET_MOTION, p, motion)

    def tick(self, p: int = 0) -> None:
        self.call(MOTION_TICK, p)

    def state(self, p: int = 0) -> dict:
        """The stepper / curve outputs the build reads: rotation slots 0..6, limb twists and targets, root."""
        ram = self.mem.ram
        rot = [struct.unpack_from("<3i", ram, (0x8011C790 + 180 * p + 12 * k) & 0x3FFFFF) for k in range(7)]
        limbs = 0x8011D4E8 + 0x160 * p
        return {"rot": rot,
                "twist": [self.s32(limbs + 0x58 * k + 4) for k in range(4)],
                "targets": [struct.unpack_from("<3i", ram, (limbs + 0x58 * k + 0x48) & 0x3FFFFF) for k in range(4)],
                "root": struct.unpack_from("<3i", ram, (ROOT + 12 * p) & 0x3FFFFF)}

    def pose(self, p: int = 0, root_motion: bool = False) -> list[tuple[tuple, tuple]]:
        """Run the skeleton build for the current frame with the player at the origin facing +1 -> 26 bone matrices
        ((9 s16 row-major 4.12), (3 s32 translation)), world space, y down. root_motion adds the root curves' x / z."""
        rx, ry, rz = struct.unpack_from("<3i", self.mem.ram, (ROOT + 12 * p) & 0x3FFFFF)
        if not root_motion:
            rx = rz = 0
        for fn in (LIMB_TARGETS, BUILD):
            self.call(IDENTITY)
            self.call(TRANSLATE, rx, ry, rz)
            if fn == LIMB_TARGETS:
                self.call(fn, p)
            else:
                self.call(fn, p, LIGHT)
        out = []
        for b in range(BONE_SLOTS):
            a = (BONES_AT + BONE_STRIDE * p + 32 * b) & 0x3FFFFF
            out.append((struct.unpack_from("<9h", self.mem.ram, a), struct.unpack_from("<3i", self.mem.ram, a + 20)))
        return out

    def hand_shapes(self, p: int = 0) -> dict[int, int]:
        """Mesh slot -> the hand-shape part the renderer draws this frame (slot 2 reads +1, slot 4 +0)."""
        a = (HAND_SHAPE + 2 * p) & 0x3FFFFF
        return {2: self.mem.ram[a + 1], 4: self.mem.ram[a]}

    def rest_pose(self, motion: int = STANCE_MOTION, p: int = 0) -> list[tuple[tuple, tuple]]:
        """Frame 0 of the stance loop, after one full loop so the accessory chains (physics) have settled."""
        self.play(motion, p)
        for _ in range(self.motions[motion]["frames"]):
            self.tick(p)
            self.pose(p)
        self.play(motion, p)
        self.tick(p)
        return self.pose(p)

    def clip(self, motion: int, p: int = 0, frames: int | None = None, root_motion: bool = True) -> list[list]:
        """Bone matrices for every frame of a motion (one motion frame per game frame, 60 per second)."""
        n = self.motions[motion]["frames"] if frames is None else frames
        self.play(motion, p)
        out = []
        for _ in range(n):
            self.tick(p)
            out.append(self.pose(p, root_motion))
        return out
