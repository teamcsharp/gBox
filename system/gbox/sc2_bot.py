"""Soul Calibur II (GameCube GRSEAF) autoplay playbook: player 1 is never hit.

Operator 2026-10-20: "for soul caliber. The autoplayer for player 1 should know how to parry / soul block every attack
and never be able to get hit as a result." The opponent's attack is read from the game's own fighter state in RAM, not
from the picture (operator: "Vision analysis to me should be the last level ... the primary levels being you being able
to see the very code of the game itself as it's being executed in the RAM"). The fields are the RAM map's
(profiles/gamedata/GRSEAF-ram.json; docs/soulcalibur2_gc.md "Perfect defence"):

  * the two fighter structs sit at fixed addresses (P1 0x8034D4C0, P2 0x8036E560: main.dol's move loader
    FUN_800948a0 and the hit resolver FUN_8009be38 are called with &DAT_8034d4c0 / &DAT_8036e560);
  * a fighter's current attack is the 0x60-byte record its +0x1690 points to (set by FUN_800948a0 when a move with
    an attack starts: moveset bank +0x10 + index * 0x60, cleared by FUN_80096ce8 when it ends). The record's +0x32 is
    the hit level as bits (FUN_8009be38 / FUN_8009c8b4): 0x01 hits a standing fighter, 0x02 a crouching one, 0x04 an
    airborne one, 0x08 standing guard blocks it, 0x10 crouching guard blocks it, 0x80 a throw, 0x100 no Guard
    Impact. So a high is 0x49, a mid 0x4B / 0x6F, a low 0x37, a special mid 0x1B, a throw 0x81, an unblockable has
    neither guard bit. +0x36 / +0x38 are its first / last active frame on the attacker's action-layer clock (layer
    1, +0x1FA8; its current frame is the f32 at +0x1FC8: the CPU's own AI computes "frames to impact" as
    rec+0x36 - (int)frame in FUN_800cfa40), +0x3A the damage;
  * +0x15F8 is what the hit resolver decided for a fighter this frame (0 nothing, 1 guarded, 4-7 hit, 11 / 12 it
    Guard Impacted the attack), +0x155C the health (f32, 240 at full), +0x1660 the distance between the two, +0x07
    the side (1: forward is screen-right, flipped while +0xAA "back turned" is set), +0x262 the active Guard Impact
    type (state var 12: 2 on frames 0-8 of 6G, 40 during 4G).

SC2's Guard Impacts (FUN_8009c8b4, checked live): Repel 6G takes highs, mids and plain throws (0x81 / 0xC1); Parry 4G
takes mids and lows. Measured on the Spark's Dolphin (Talim vs Raphael, Practice, 2026-10-20): the GI comes out on the
game frame after its input and catches an impact on its frames 0-8; it needs a fresh G press (6 with G already held
only guards) and the direction no later than G (G first, even by 12 ms, reads as a guard: 3 / 12 GIs; direction first
32 / 32). The repelled fighter staggers 40 frames and can GI again from frame ~27; the repeller can act again from
frame 24 of its follow-through (move 0x8C), a button pressed from frame ~15 of it is buffered until then.

The play: P1 stands ready with nothing held. When P2's attack starts, its frames-to-impact are known; P1 Guard Impacts
it with the GI that fits its height so the command reaches the game GI_AT frames before the first active frame (the
lead adds the measured send latency, and G's release when G is held), if P1 is free to act, the attack is close
enough and the move book has not seen GIs miss it; otherwise P1 guards it the right way (crouch guard against lows,
standing guard against the rest); standing throws are ducked; unblockables are sidestepped; a GI that does not show
within GI_CONFIRM_S falls back to the guard. After a GI lands P1 punishes (B, no G until it is out: G cancels attack
startup) once it can act, so rounds are won, not only survived; when P1's own attack is Guard Impacted it impacts the
follow-up from its stagger. Between rounds and in menus it presses A now and then so Arcade / Survival go on.

Memory: the session's own Dolphin view (gbox.ram_dump.ShmRam, /proc/<pid>/mem read-only) when the worker runs it on
this host, else the adapter's read_memory. Input: the adapter's send_input with gBox pad names, from a thread of its own
(Sender: xdotool on Linux takes 17-35 ms a call, a hit result lasts one frame); the game's Type A layout (Options >
Controller Settings, checked live) is GC A = A (horizontal), GC Y = B (vertical), GC X = K, GC B / L / R = G, so in
gBox names: A "a", B "y", K "x", G "b" (DolphinAdapter.keys: a -> GC A, y -> GC Y, x -> GC X, b -> GC B).
"""
from __future__ import annotations

import json
import struct
import threading
import time
from pathlib import Path

GAME_IDS = {"201629ad498aba7b", "e08e8a0c1b3c9060"}   # Soul Calibur II (USA): the HyperSpin GCZ and the ISO
DISC_ID = "GRSEAF"
P1, P2 = 0x8034D4C0, 0x8036E560                      # the fighter structs (0x210A0 apart)
FRAME = 0x802B608C                                    # u32 game frame counter (+1 per frame)
FIGHT = 0x8038F650                                    # u16: nonzero while the hit resolver runs (a fight is on)
CAMERA = 0x80460B68                                   # ptr -> +0x10 ptr -> camera; its x / z at +0x10 / +0x18
POS = 0x2950                                          # fighter: f32 x, y, z (FUN_800dac3c reads x and z)

# fighter struct offsets
SIDE = 0x07
CTL = 0x50                                            # u32: who drives the fighter: 0 / 1 the pad, else the CPU
FIGHTER, COSTUME = 0x62, 0x64
F_CROUCH, F_AIR, F_DOWN, F_BACK = 0xA2, 0xA3, 0xA4, 0xAA      # u8 state flags (FUN_80093368: flag i at +0xA0 + i)
F_ATTACKING, F_ACTIVE, F_CONNECTED = 0xBB, 0xC1, 0xC2
GI_TYPE = 0x262                                       # u16 state var 12: the Guard Impact the fighter is in (0 none)
ROUNDS = 0x154D                                       # u8 rounds won this match
HP = 0x155C                                           # f32 health (240 full)
RESULT = 0x15F8                                       # s32 hit result this frame
DIST = 0x1660                                         # f32 distance between the fighters
ATTACK = 0x1690                                       # ptr to the current attack record
LAYER0, LAYER1 = 0x1C28, 0x1FA8                       # motion layers (0x380 each): stance / actions
L_MOVE, L_NEXT, L_NOW = 0x02, 0x08, 0x20              # in a layer: s16 move id, f32 next frame, f32 current frame
L_QUEUED, L_QUEUED_AT = 0x52, 0x60                    # in a layer: s16 the move queued after this one (-1 none; the
                                                      # string's next part, FUN_80093e08 starts it), f32 the frame of
                                                      # this move it takes over at
MOVESET = 0x2764                                      # fighter: ptr to the moveset (FUN_800948a0): bank = moveset +
                                                      # (id >> 12) * 0xA4 + 0x28; moves *(bank + 8) (0x60 each, +0x58
                                                      # s16 attack index), attacks *(bank + 0x10) (0x60 each)
HEAD, MID = (0x0, 0x280), (0x1540, 0x160)             # what one poll reads of a fighter, besides the two layers
# attack record (0x60 bytes)
R_FLAGS, R_KIND, R_START, R_END, R_DAMAGE = 0x32, 0x34, 0x36, 0x38, 0x3A
HITS_STAND, HITS_CROUCH, HITS_AIR, GUARD_STAND, GUARD_CROUCH, THROW, NO_GI = 0x01, 0x02, 0x04, 0x08, 0x10, 0x80, 0x100
GI_THROWS = (0x81, 0xC1)                              # the throws FUN_8009c8b4 lets a Guard Impact catch
# hit results (+0x15F8, FUN_8009be38)
GUARDED, HIT, IMPACTED = {1}, {4, 5, 6, 7}, {11, 12}
NEUTRAL = 0xFFFF                                      # layer 1 with no action
GI_FOLLOW = 0x8C                                      # the repeller's move after a Guard Impact lands
GI_ACT_FRAME = 24                                     # ... from this frame of it the fighter can act again
STAGGERS = set(range(0x23A0, 0x23B0))                 # Guard Impacted (0x23A4 repelled, 0x23AB / 0x23AD parried):
                                                      # no guard, but a GI pressed now comes out as soon as the
                                                      # stagger allows it (frame ~27 / ~38)

# pad (gBox names; the game's Type A layout)
G, A, B, K, START = "b", "a", "y", "x", "start"
DIRECTIONS = ("up", "down", "left", "right")
FRAME_S = 1 / 60
GI_AT = 5              # frames before the first active frame the GI command should reach the game: the GI starts on the
                       # next frame, so the hit lands on its frame ~4-6 of 0-8 (impact = first .. third active frame)
GI_LEAD = GI_AT + 2    # with no measured send latency: decide this many frames ahead (G up and the press each take one)
GI_LATE = 2            # a GI that could not reach the game this many frames before impact is not tried: guard instead
GI_WINDOW_S = 0.20     # a GI's active frames (0-8) are over this long after its command reached the game
GI_KEYS_S = 0.12       # hold the GI command this long (then G alone)
GI_CONFIRM_S = 0.07    # the GI move (0x8A / 0x92) must show this soon after the command, else guard after all
GI_MOVES = {0x8A, 0x92}                               # Repel, Parry (P1's layer-1 move while its GI is out)
REGRAB_S = 0.034       # G up this long before dir + G when G was held: a GI needs a fresh G, and two frames keep a slow
                       # xdotool call from merging the release and the press into one frame
STEP_LEAD = 14         # unblockables: sidestep this many frames before impact
STEP_S = 0.6           # ... for at most this long
DUCK_LEAD = 10         # throws: crouch this many frames before the grab
GI_RANGE = 2.3         # GI only when P2 is this close at GI_LEAD (ULTRA HARD Raphael, 10 min: 282 GIs landed, 98%
                       # of them closer than this; the GIs that missed further out let the CPU's next attack in)
BOOK_MISSES = 2        # a move whose GIs missed this often (and a quarter of the time) is guarded, not impacted
NEAR = 0.35            # the book judges a move by what it did from within this distance of now (when it has seen it)
HELD_SLACK = 1.5       # with G held, a GI is only started within this many frames of its ideal moment
LONG_ACTIVE = 4.5      # an attack active longer than this (frames) can land anywhere in it (Mitsurugi's 24-34 sweep hit on
                       # frame ~31): guarded, as a GI covers only about 4 frames either side of the first active frame
SLOW_MOVE = 0.5        # an attack winding up slower than this (its clock at a tenth of the speed: Kilik 0xF8) has no
                       # impact frame to time a GI on: it is guarded
PUNISH_RANGE = 2.2     # punish after a GI only from this close
PUNISH_KEYS = (B,)     # a vertical: reaches a staggered fighter right in front of P1
PUNISH_S = 0.08
PUNISH_WAIT_S = 1.0    # give up a punish this long after the GI
MENU_AFTER, MENU_EVERY = 4.0, 1.2      # out of a fight this long: press A this often (next round / next fight)
SEED_BOOK = Path(__file__).resolve().parent.parent / "profiles" / "gamedata" / "GRSEAF-movebook.json"   # what the
                                       # tests met (a worker's own book is read over it)


def ptr_ok(p: int) -> bool:
    return 0x80000000 <= p < 0x81800000


def fighter(rd, base: int) -> dict:
    """One fighter's state from RAM (rd(address, n) -> bytes)."""
    head = rd(base + HEAD[0], HEAD[1])
    mid = rd(base + MID[0], MID[1])
    l0 = rd(base + LAYER0, 0x30)
    l1 = rd(base + LAYER1, 0x64)
    o = lambda off: off - MID[0]
    now, nxt = struct.unpack_from(">f", l1, L_NOW)[0], struct.unpack_from(">f", l1, L_NEXT)[0]
    st = {"side": head[SIDE], "back": head[F_BACK], "crouch": head[F_CROUCH], "air": head[F_AIR], "down": head[F_DOWN],
          "attacking": head[F_ATTACKING], "active": head[F_ACTIVE], "connected": head[F_CONNECTED],
          "gi": struct.unpack_from(">H", head, GI_TYPE)[0], "fighter": struct.unpack_from(">h", head, FIGHTER)[0],
          "ctl": struct.unpack_from(">I", head, CTL)[0],
          "rounds": mid[o(ROUNDS)], "hp": struct.unpack_from(">f", mid, o(HP))[0],
          "result": struct.unpack_from(">i", mid, o(RESULT))[0], "dist": struct.unpack_from(">f", mid, o(DIST))[0],
          "m0": struct.unpack_from(">H", l0, L_MOVE)[0], "m1": struct.unpack_from(">H", l1, L_MOVE)[0], "f": now,
          "speed": nxt - now if 0.05 < nxt - now < 4 else 1.0, "atk": None,
          "queued": struct.unpack_from(">H", l1, L_QUEUED)[0], "queued_at": struct.unpack_from(">f", l1, L_QUEUED_AT)[0],
          "queued_alt": [m for m in struct.unpack_from(">3H", l1, L_QUEUED + 2) if m != NEUTRAL],
          "next_atk": None}
    a = struct.unpack_from(">I", mid, o(ATTACK))[0]
    if ptr_ok(a):
        r = rd(a, 0x40)
        st["atk"] = attack_record(r, a)
    return st


def attack_record(r: bytes, ptr: int) -> dict:
    return {"ptr": ptr, "flags": struct.unpack_from(">H", r, R_FLAGS)[0], "kind": struct.unpack_from(">H", r, R_KIND)[0],
            "start": struct.unpack_from(">h", r, R_START)[0], "end": struct.unpack_from(">h", r, R_END)[0],
            "damage": struct.unpack_from(">h", r, R_DAMAGE)[0]}


def move_attack(rd, moveset: int, move: int) -> dict | None:
    """The attack record of one of a fighter's moves, from its moveset (the tables FUN_800948a0 starts moves from)."""
    if not ptr_ok(moveset) or move in (0xFFFF, NEUTRAL) or move & 0x8000:
        return None
    bank = moveset + ((move >> 12) & 0xF) * 0xA4 + 0x28
    b = rd(bank + 8, 12)
    moves, attacks = struct.unpack_from(">I", b, 0)[0], struct.unpack_from(">I", b, 8)[0]
    if not (ptr_ok(moves) and ptr_ok(attacks)):
        return None
    index = struct.unpack(">h", rd(moves + (move & 0xFFF) * 0x60 + 0x58, 2))[0]
    if index < 0 or index & 0x1000:                   # no attack (0x1000: another kind of record)
        return None
    a = attacks + index * 0x60
    return attack_record(rd(a, 0x40), a)


def screen_side(rd) -> int | None:
    """P1's side as the game derives it each frame (FUN_800bbe68 -> FUN_800dac3c: which side of the line from P2 to
    the camera P1 stands on): 1 = forward is screen-right. +0x07 holds the same once the game has updated it; this
    one is ahead of it while a stagger spins P1 round."""
    try:
        cam = struct.unpack(">I", rd(CAMERA, 4))[0]
        if not ptr_ok(cam):
            return None
        cam = struct.unpack(">I", rd(cam + 0x10, 4))[0]
        if not ptr_ok(cam):
            return None
        cx, _, cz = struct.unpack(">3f", rd(cam + 0x10, 12))
        x1, _, z1 = struct.unpack(">3f", rd(P1 + POS, 12))
        x2, _, z2 = struct.unpack(">3f", rd(P2 + POS, 12))
    except (struct.error, OSError, ValueError, KeyError):
        return None
    return 0 if (x1 - x2) * (cz - z2) - (z1 - z2) * (cx - x2) > 0.0 else 1


def snapshot(rd, sides: bool = True) -> dict:
    """Both fighters, the frame counter and whether a fight is on."""
    p1, p2 = fighter(rd, P1), fighter(rd, P2)
    if p2["queued"] != NEUTRAL or p2["queued_alt"]:   # the string's next part, before it starts
        try:
            ms = struct.unpack(">I", rd(P2 + MOVESET, 4))[0]
            p2["next_atk"] = move_attack(rd, ms, p2["queued"]) if p2["queued"] != NEUTRAL else None
            # the continuations the game picks instead when the attack connects / in other states (FUN_80093e08):
            # only their unblockables matter (a step must start before them)
            p2["alt_unblockable"] = [a for a in (move_attack(rd, ms, m) for m in p2["queued_alt"])
                                     if a is not None and classify(a["flags"]) == "unblockable"]
        except (struct.error, OSError, ValueError, KeyError):
            p2["next_atk"], p2["alt_unblockable"] = None, []
    p1["screen_side"] = screen_side(rd) if sides and p1["m1"] in STAGGERS else None
    return {"p1": p1, "p2": p2, "frame": struct.unpack(">I", rd(FRAME, 4))[0],
            "fight": struct.unpack(">H", rd(FIGHT, 2))[0] != 0 and 0 < p1["hp"] <= 400 and 0 < p2["hp"] <= 400
            and p1["ctl"] in (0, 1)}                  # the attract demo's fights are the CPU's (control 3)


def classify(flags: int) -> str:
    """The way an attack has to be met: high / mid / low / special_mid / throw / unblockable, or none (a record that
    hits nothing: no hit bits, as some of Ivy's string continuations carry)."""
    if flags & THROW:
        return "throw"
    if not flags & (HITS_STAND | HITS_CROUCH | HITS_AIR):
        return "none"
    stand, crouch = bool(flags & GUARD_STAND), bool(flags & GUARD_CROUCH)
    if stand and crouch:
        return "special_mid"
    if stand:
        return "mid" if flags & HITS_CROUCH else "high"
    if crouch:
        return "low"
    return "unblockable"


def threat(p2: dict) -> dict | None:
    """P2's attack still to come: {kind, flags, t (game frames to its first active frame), te (to its last), queued}.
    The current move's attack while it is still to come; else the queued next move's (a string's next part), which
    starts at frame queued_at of the current move (at once from neutral) and hits at its own first active frame."""
    a = p2["atk"]
    sp = p2["speed"] or 1.0
    if a is not None and classify(a["flags"]) == "none":
        a = None
    if a is not None and not p2["connected"]:
        t, te = (a["start"] - p2["f"]) / sp, (a["end"] - p2["f"]) / sp
        if te >= -0.5:
            return {"kind": classify(a["flags"]), "flags": a["flags"], "t": t, "te": te, "span": te - t,
                    "ptr": a["ptr"], "start": a["start"], "end": a["end"], "move": p2["m1"], "queued": False}
    n = p2.get("next_atk")
    wait = 0.0 if p2["m1"] == NEUTRAL else max(0.0, (p2.get("queued_at", 0.0) - p2["f"]) / sp)
    if n is None or classify(n["flags"]) != "unblockable":
        n = next(iter(p2.get("alt_unblockable") or []), n)   # an unblockable continuation outranks the rest
    if n is None or classify(n["flags"]) == "none":
        return None
    t, te = wait + n["start"], wait + n["end"]
    return {"kind": classify(n["flags"]), "flags": n["flags"], "t": t, "te": te, "span": te - t, "ptr": n["ptr"],
            "start": n["start"], "end": n["end"], "move": p2["queued"], "queued": True}


def queued_unblockable(p2: dict) -> dict | None:
    """An unblockable among the string's queued continuations, with the frames to its first active frame."""
    cands = [a for a in [p2.get("next_atk"), *(p2.get("alt_unblockable") or [])]
             if a is not None and classify(a["flags"]) == "unblockable"]
    if not cands:
        return None
    sp = p2["speed"] or 1.0
    wait = 0.0 if p2["m1"] == NEUTRAL else max(0.0, (p2.get("queued_at", 0.0) - p2["f"]) / sp)
    n = min(cands, key=lambda a: a["start"])
    return {"kind": "unblockable", "flags": n["flags"], "t": wait + n["start"], "te": wait + n["end"], "ptr": n["ptr"]}


def directions(p1: dict) -> tuple[str, str]:
    """The screen keys for P1's forward and back. Normally the side (+0x07) turned round while P1 faces away (+0xAA),
    the game's own rule (FUN_8009a618). A Guard Impacted P1 is spun round and faces away, yet a GI pressed in the
    stagger reads the stick by the side alone (live: 6G with the side's forward came out as a Repel at frames 20-48
    of the parried stagger, the turned key as a Parry); the side is taken from where P1 stands (screen_side), as
    the game will once the stagger lets it go."""
    if p1["m1"] in STAGGERS:
        side = p1.get("screen_side")
        fwd = "right" if (p1["side"] if side is None else side) else "left"
    else:
        fwd = "right" if bool(p1["side"]) != bool(p1["back"]) else "left"
    return fwd, ("left" if fwd == "right" else "right")


def reacting(move: int) -> bool:
    """A common reaction (bank 2: 0x20xx hit, 0x21xx guard stun, 0x22xx thrown, 0x23xx Guard Impacted)."""
    return 0x2000 <= move < 0x3000


def can_gi(p1: dict) -> bool:
    """P1 can start a Guard Impact now (or has it buffered for the first frame it can): standing with no action of its
    own and facing the opponent, at the end of its own GI's follow-through, or staggered by the opponent's GI (where
    guarding is impossible). Facing away, a press of G turns P1 round instead (live: dir + G back-turned gave a
    backstep and the low hit)."""
    m = p1["m1"]
    if m == NEUTRAL:
        return not p1["crouch"] and not p1["back"]   # from a crouch the stick reads 1 / 3 and the GI does not come out
    if m == GI_FOLLOW:
        return p1["f"] >= GI_ACT_FRAME - 4
    return m in STAGGERS


class MoveBook:
    """What the opponent's moves (fighter id, move id) did to P1: GIs that landed / missed, and every attack seen from
    within GI_RANGE that touched P1 (guarded, hit, impacted) or met nothing, with the distance it was decided at.
    A move the CPU feints or that falls short (a stance cancel, a poke at the edge of its reach) is guarded, not
    impacted, once it has met nothing BOOK_MISSES times and a quarter of the time, or when it comes from further than
    it ever reached P1: a GI that meets nothing leaves P1 in ~30 frames of recovery, and the CPU's strings use them.
    Saved under the worker's runtime folder (sc2_learned/movebook.json), so every fight starts from what the last
    ones taught."""

    def __init__(self, path: Path | None = None, seed: Path | None = None, cautious: bool = True):
        """path: this worker's book (read, then saved to); seed: a book shipped in the repo, read first (the moves
        the playbook met while it was tested); cautious: a move is impacted only once it has reached P1 from this far
        (its first sight is guarded and learned from)."""
        self.path, self.moves, self.cautious = path, {}, cautious
        for f in (seed, path):
            if f is None:
                continue
            try:
                self.moves.update(json.loads(Path(f).read_text(encoding="utf-8")).get("moves", {}))
            except (OSError, ValueError):
                pass

    @staticmethod
    def key(fighter: int, move: int) -> str:
        return f"{fighter}:{move:#06x}"

    def ok(self, fighter: int, move: int, dist: float) -> bool:
        m = self.moves.get(self.key(fighter, move))
        if not m:
            return not self.cautious                 # never seen: guard it and learn its reach
        near = [t for d, t in m.get("d") or [] if abs(d - dist) <= NEAR]
        if near:                                     # what it did from about here decides (whips miss up close)
            hits = sum(near)
            return hits >= 1 and len(near) - hits <= hits // 3
        touched = m.get("land", 0) + m.get("contact", 0)
        empty = m.get("miss", 0) + m.get("none", 0)
        if empty >= BOOK_MISSES and empty * 3 >= touched:
            return False
        if self.cautious:                            # only from as far as it has reached P1 before
            return touched > 0 and dist <= m.get("reach", 0.0) + 0.1
        return not (empty and touched and dist > m.get("reach", 0.0) + 0.15)

    def _entry(self, fighter: int, move: int) -> dict:
        return self.moves.setdefault(self.key(fighter, move),
                                     {"land": 0, "miss": 0, "contact": 0, "none": 0, "reach": 0.0})

    def _sample(self, m: dict, dist: float, touched: bool):
        m["d"] = (m.get("d") or [])[-23:] + [[round(float(dist), 2), int(bool(touched))]]

    def record(self, fighter: int, move: int, landed: bool, dist: float):
        """A GI against the move landed / met nothing."""
        m = self._entry(fighter, move)
        self._sample(m, dist, landed)
        k = "land" if landed else "miss"
        m[k] = m.get(k, 0) + 1
        if landed:
            m["reach"] = round(max(m.get("reach", 0.0), dist), 2)

    def observe(self, fighter: int, move: int, touched: bool, dist: float, at: float | None = None):
        """The move (not impacted) touched P1 (guarded / hit) or ended without touching it; at = its frame at the
        contact counted from its first active frame."""
        m = self._entry(fighter, move)
        self._sample(m, dist, touched)
        k = "contact" if touched else "none"
        m[k] = m.get(k, 0) + 1
        if touched:
            m["reach"] = round(max(m.get("reach", 0.0), dist), 2)
        self.contact(fighter, move, at)

    def contact(self, fighter: int, move: int, at: float | None):
        """Where in its active window the move reached P1 (the last 8 times)."""
        if at is None:
            return
        m = self._entry(fighter, move)
        m["at"] = (m.get("at") or [])[-7:] + [round(float(at), 1)]

    def offset(self, fighter: int, move: int) -> float | None:
        """The frame after its first active one the move reaches P1 at (the median of the times seen), or None."""
        at = sorted((self.moves.get(self.key(fighter, move)) or {}).get("at") or [])
        return at[len(at) // 2] if at else None

    def save(self):
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"format": "sc2-movebook/1", "moves": self.moves}, indent=0),
                                 encoding="utf-8")
        except OSError:
            pass


class Brain:
    """P1's defence, one poll at a time: decide(snapshot, now) -> the set of gBox keys to hold now.

    P1 stands with nothing held while nothing comes, so a Guard Impact is one press of dir + G; it guards what it will
    not impact (standing guard against highs and mids, crouching guard against lows), crouches under standing throws
    and sidesteps unblockables. Phases: guard | duck | step | regrab (G let go: a GI needs a fresh G) | press (the GI
    command sent, not yet in the game) | gi (in its window) | punish (a GI landed: wait until P1 can act) |
    punish_hit (the punish's button held, no G until the attack is out).

    out (optional, set by play()): the key sender: .held (keys the emulator has), .applied_at (when the last change
    reached it), .latency_s (how long a send takes). Without one, keys count as applied when decided."""

    STATS = ("attacks", "gi", "gi_tried", "guards", "hits_taken", "damage_taken", "ducks", "steps", "punishes",
             "punish_hits", "rounds_won", "rounds_lost", "fights")

    def __init__(self, stats: dict | None = None, gi_lead: int | None = None, punish: bool = True, log=None,
                 book: MoveBook | None = None, out=None):
        self.stats = stats if stats is not None else {}
        for k in self.STATS:
            self.stats.setdefault(k, 0)
        self.gi_lead_fixed, self.punish, self.log, self.out = gi_lead, punish, log or (lambda *a: None), out
        self.phase, self.until, self.keys_until, self.gi_keys, self.gi_dirs = "guard", 0.0, 0.0, (), "fwd"
        self.gi_kind, self.sent_at = "high", None
        self.inst, self.inst_key, self.inst_f, self.gi_inst = 0, None, 0.0, None   # P2 attack instances
        self.prev, self.punish_from, self.punish_until = None, None, 0.0
        self.book = book if book is not None else MoveBook(cautious=False)   # play() passes the cautious one
        self.gi_ctx, self.gi_touched, self.wanted = None, False, set()
        self.gi_lat, self.gi_sent, self.confirm_by = None, None, 0.0     # frames a GI command takes to show
        self.obs = None                                                  # the P2 attack instance being watched
        self.gi_ptr = None                               # the attack record a GI was pressed for while still queued

    # -- the key sender, when there is one --
    def _held(self) -> set:
        return set(getattr(self.out, "held", self.wanted))

    def _applied(self, keys: set, now: float) -> float | None:
        """When `keys` reached the emulator (None: not yet)."""
        if self.out is None:
            return self.sent_at
        return self.out.applied_at if set(self.out.held) == set(keys) else None

    def gi_lead(self, holding_g: bool) -> float:
        """Frames ahead of the first active frame to decide a GI: GI_AT, plus the frames a GI command takes to show
        as P1's GI move beyond the one frame of the game's own (measured on every GI; at first the send's duration),
        plus G's release when G is held."""
        if self.gi_lead_fixed is not None:
            return self.gi_lead_fixed
        send = getattr(self.out, "latency_s", 0.0) / FRAME_S
        lat = self.gi_lat if self.gi_lat is not None else send
        return GI_AT + lat + ((REGRAB_S / FRAME_S + send) if holding_g else 0)

    # -- bookkeeping from what the game decided --
    def _account(self, s: dict, now: float):
        p1, p2, prev = s["p1"], s["p2"], self.prev
        a = p2["atk"]
        if a:
            key = (a["ptr"], p2["m1"])
            if key != self.inst_key or p2["f"] < self.inst_f - 0.5:          # a new attack (or the same one again)
                self._observe_end()
                self.inst += 1
                self.inst_key = key
                if self.gi_ptr is not None and a["ptr"] == self.gi_ptr:    # impacted (or tried) while queued
                    self.gi_inst, self.gi_ptr = self.inst, None
                self.stats["attacks"] += 1
                self.stats["last_attack"] = f"{classify(a['flags'])} 0x{a['flags']:02X} f{a['start']}-{a['end']}"
                self.obs = {"fighter": p2["fighter"], "move": p2["m1"], "dist": None, "touched": False,
                            "gi": False, "inst": self.inst}
            self.inst_f = p2["f"]
            o = self.obs
            if o is not None:
                if o["dist"] is None and (a["start"] - p2["f"]) <= GI_AT + 2:   # the distance a GI is decided at
                    o["dist"] = p2["dist"]
                contact = p1["result"] in GUARDED | HIT | IMPACTED
                if contact and o.get("at") is None and (prev is None or prev["p1"]["result"] != p1["result"]):
                    o["at"] = max(0.0, p2["f"] - a["start"])          # where in its window it reached P1
                o["touched"] |= contact or bool(p2["connected"])
                o["gi"] |= self.gi_inst == self.inst
        else:
            self._observe_end()
            self.inst_key = None
        if prev is None:
            return
        q1, q2 = prev["p1"], prev["p2"]
        r = p1["result"]
        if r and (r != q1["result"] or s["frame"] - prev["frame"] > 1):
            if r in IMPACTED:
                self.stats["gi"] += 1
            elif r in GUARDED:
                self.stats["guards"] += 1
            elif r in HIT:
                self.stats["hits_taken"] += 1
                self.stats["last_hit"] = self.stats.get("last_attack")
                self.log("hit", self.stats.get("last_attack"), self.phase)
        if s["fight"] and prev["fight"] and 0 < q1["hp"] - p1["hp"] < 400:
            self.stats["damage_taken"] = round(self.stats["damage_taken"] + q1["hp"] - p1["hp"], 2)
        if p2["result"] in HIT and p2["result"] != q2["result"] and now < self.punish_until:
            self.stats["punish_hits"] += 1
            self.punish_until = 0.0
        if p1["rounds"] == q1["rounds"] + 1:
            self.stats["rounds_won"] += 1
        if p2["rounds"] == q2["rounds"] + 1:
            self.stats["rounds_lost"] += 1

    def decide(self, s: dict, now: float) -> set[str]:
        keys = self._decide(s, now)
        if keys != self.wanted:
            self.wanted, self.sent_at = set(keys), now
        return keys

    def _guard(self, th: dict | None) -> set[str]:
        """The guard for an attack: crouching against lows, standing against the rest (and with nothing coming)."""
        return {"down", G} if th is not None and th["kind"] == "low" else {G}

    def _decide(self, s: dict, now: float) -> set[str]:
        self._account(s, now)
        self.prev = s
        p1, p2 = s["p1"], s["p2"]
        if not s["fight"]:
            self.phase = "guard"
            return set()
        fwd, back = directions(p1)
        free = can_gi(p1)
        th = threat(p2)
        if self.phase == "regrab":                       # G is being let go: a GI needs a fresh G
            gone = self._applied(set(), now)
            if gone is None or now < max(gone, self.until - REGRAB_S) + REGRAB_S:
                return set()
            if th is None or th["t"] > self.gi_lead(False) + 1:
                # the attack slowed down meanwhile (some moves wind up at a tenth of the speed, live: Kilik 0xF8) or
                # went away: not yet; decide again from the new timing, with nothing held
                self.phase, self.gi_inst = "guard", None
                self.stats["gi_tried"] -= 1
                return set()
            self.phase = "press"
        if self.phase == "press":
            if not self.gi_keys:                         # the direction from the poll it is pressed on (a fighter
                self.gi_keys = (fwd if self.gi_dirs == "fwd" else back, G)   # spun round by a parry can cross the
            at = self._applied(set(self.gi_keys), now) if set(self.gi_keys) == self.wanted else None   # line), then kept
            if at is None:
                if now - self.until > 0.25:              # the sender never got it out: guard
                    self.phase = "guard"
                else:
                    return set(self.gi_keys)
            else:
                self.phase, self.keys_until, self.until = "gi", at + GI_KEYS_S, at + GI_WINDOW_S
                self.confirm_by, self.gi_sent = at + GI_CONFIRM_S, self.sent_at
        if self.phase == "gi":
            if p1["m1"] in STAGGERS:                     # pressed in a stagger: it comes out when the stagger allows
                self.confirm_by, self.until = max(self.confirm_by, now + GI_CONFIRM_S), max(self.until, now + GI_WINDOW_S)
            elif p1["m1"] in GI_MOVES and self.gi_sent is not None:
                lat = max(0.0, (now - self.gi_sent) / FRAME_S - 1)      # the GI move shows one frame after its input
                self.gi_lat = lat if self.gi_lat is None else 0.8 * self.gi_lat + 0.2 * min(lat, 6.0)
                self.stats["gi_latency_frames"] = round(self.gi_lat, 2)
                self.gi_sent = None
            if p1["result"] in IMPACTED:
                self.phase, self.punish_from = ("punish" if self.punish else "guard"), now
                self._book(True)
            elif p1["m1"] not in GI_MOVES and now > self.confirm_by:
                self.phase = "guard"                     # the GI did not come out (P1 not free after all): guard
                self.stats["gi_failed"] = self.stats.get("gi_failed", 0) + 1
                self.log("gi_failed", self.gi_keys, p1["m0"], p1["m1"])
            elif now < self.until:
                self.gi_touched |= p1["result"] in GUARDED | HIT
                return set(self.gi_keys) if now < self.keys_until else {G}
            else:
                self.phase = "guard"
                self.stats["gi_missed"] = self.stats.get("gi_missed", 0) + 1
                self.log("gi_miss", self.gi_keys, p1["m1"], p1["result"])
                if not self.gi_touched:                  # the attack never reached P1: a feint or out of reach
                    self._book(False)
        if self.phase == "punish_hit":
            if now < self.until:
                return set(PUNISH_KEYS)
            mine = p1["atk"]                             # no G until P1's own attack is out: G cancels its startup
            busy = p1["m1"] != NEUTRAL and not reacting(p1["m1"]) and (mine is None or p1["f"] <= mine["end"])
            if now < self.punish_until and busy:
                return set()
            self.phase = "guard"                         # out, or GI'd / hit: defend
        if self.phase == "punish":
            if p1["result"] in HIT or now - self.punish_from > PUNISH_WAIT_S or (th is not None and p1["m1"] == NEUTRAL):
                self.phase = "guard"                     # hit, too late, or a new attack is on its way: defend
            elif free and p2["m1"] != NEUTRAL and p2["atk"] is None:
                self.log("punish", round(p2["dist"], 2), p2["m1"], round(p2["f"], 1), p1["m1"], round(p1["f"], 1))
                if p2["dist"] <= PUNISH_RANGE:
                    self.stats["punishes"] += 1
                    self.phase, self.until, self.punish_until = "punish_hit", now + PUNISH_S, now + 0.8
                    return set(PUNISH_KEYS)
                self.phase = "guard"                     # too far to reach: back to defending
            else:
                return set()
        if self.phase == "step":
            if th is not None and (th["kind"] == "unblockable" or queued_unblockable(p2)) and now < self.until:
                return {"up"}
            self.phase = "guard"
        if th is None:
            if self.phase == "duck":
                self.phase = "guard"
            # nothing coming: stand ready (no G, so a GI is a single press), or keep guarding in guard stun; knocked
            # down, G gets P1 up (without input a downed fighter stays down: live, Practice)
            return {G} if 0x2100 <= p1["m1"] < 0x2200 or p1["down"] else set()
        if th["span"] > LONG_ACTIVE:                     # a long active window: time on where it reaches P1
            off = self.book.offset(p2["fighter"], th["move"])
            if off is not None:
                th = dict(th, t=th["t"] + off / (p2["speed"] or 1.0), span=0.0, contact=off)
        kind, t = th["kind"], th["t"]
        holding_g = G in self._held()
        lead = self.gi_lead(holding_g)
        if kind == "throw":
            if p1["m1"] in STAGGERS:                     # Guard Impacted: no crouching, but a Repel takes the throw
                if th["flags"] in GI_THROWS and self._gi_ok(th, p2, free, p1, lead):
                    return self._gi(th, "fwd", now, p2, holding_g)
                return {G}
            if not th["flags"] & HITS_CROUCH:            # a standing throw: crouch under it
                if t <= DUCK_LEAD + lead - GI_AT:
                    if self.phase != "duck":
                        self.stats["ducks"] += 1
                        self.phase = "duck"
                    return {"down", G}
                return set()
            if th["flags"] in GI_THROWS and self._gi_ok(th, p2, free, p1, lead):
                return self._gi(th, "fwd", now, p2, holding_g)
            return {G}
        if self.phase == "duck":
            self.phase = "guard"
        ub = queued_unblockable(p2) if not th["queued"] else None
        if ub is not None and ub["t"] <= STEP_LEAD + lead - GI_AT and not self._gi_ok(th, p2, free, p1, lead):
            # this part will be guarded at best, and the guard stun would hold P1 for the unblockable next part
            self.stats["steps"] += 1
            self.phase, self.until = "step", now + STEP_S
            self.log("step_string", th, ub)
            return {"up"}
        if kind == "unblockable" and not th["flags"] & HITS_CROUCH:
            # an unblockable that does not reach a crouching fighter (Astaroth's 0x41 thrust: stand + downed bits
            # only): crouching beats it, and unlike the sidestep it cannot be walked into
            if t <= DUCK_LEAD + lead - GI_AT:
                if self.phase != "duck":
                    self.stats["ducks"] += 1
                    self.phase = "duck"
                return {"down", G}
            return set()
        if kind == "unblockable":
            if t <= STEP_LEAD + lead - GI_AT:
                self.stats["steps"] += 1
                self.phase, self.until = "step", now + STEP_S
                return {"up"}
            return set()
        gi = "back" if kind == "low" else "fwd"          # Parry (4G) takes lows and mids, Repel (6G) highs and mids
        if kind == "low" and (p1["crouch"] or "down" in self._held()):   # 4G from a crouch (or while still
            return {"down", G}                                           # getting up from one) does not come out
        if self._gi_ok(th, p2, free, p1, lead):
            return self._gi(th, gi, now, p2, holding_g)
        if t > lead and self._gi_ok(dict(th, t=lead), p2, free, p1, lead):
            # it will be impacted: wait for it standing, with nothing held (or keep the guard already up)
            return {G} if holding_g else set()
        return self._guard(th)

    def _gi_ok(self, th: dict, p2: dict, free: bool, p1: dict | None = None, lead: float | None = None) -> bool:
        lead = self.gi_lead(False) if lead is None else lead
        staggered = p1 is not None and p1["m1"] in STAGGERS          # no guard there: a GI is the only way out
        late = -2 if staggered else GI_LATE + (lead - GI_AT)
        if not staggered and G in self._held():
            # from a held guard the release and the press are two slow sends (xdotool 20-35 ms each): only at the
            # right moment, else keep guarding (live: a GI decided late from guard stun came out after the hit)
            late = max(late, lead - HELD_SLACK)
        timed = p2["speed"] >= SLOW_MOVE and th.get("span", 0) <= LONG_ACTIVE        # an impact frame to time on
        return (not th["flags"] & NO_GI and free and late <= th["t"] <= lead and self.inst != self.gi_inst
                and (staggered or (p2["dist"] <= GI_RANGE and timed
                                   and self.book.ok(p2["fighter"], th["move"], p2["dist"]))))

    def _observe_end(self):
        """An attack instance is over: tell the book whether it touched P1 (GIs are booked by _book)."""
        o, self.obs = self.obs, None
        if o is not None and o["gi"] and o.get("at") is not None:
            self.book.contact(o["fighter"], o["move"], o["at"])
        if o is None or o["gi"] or o["dist"] is None or o["dist"] > GI_RANGE:
            return
        self.book.observe(o["fighter"], o["move"], o["touched"], round(o["dist"], 2), o.get("at"))

    def _book(self, landed: bool):
        if self.gi_ctx is not None:
            self.book.record(*self.gi_ctx[:2], landed, self.gi_ctx[2])
            self.gi_ctx = None

    def _gi(self, th: dict, dirs: str, now: float, p2: dict | None = None, holding_g: bool = False) -> set[str]:
        """Start a GI: dirs "fwd" (6G Repel) or "back" (4G Parry), turned into keys when it is pressed."""
        self.stats["gi_tried"] += 1
        self.gi_dirs, self.gi_inst, self.gi_touched, self.gi_kind = dirs, self.inst, False, th["kind"]
        self.gi_ptr = th["ptr"] if th.get("queued") else None
        self.gi_keys = ()                                # the press picks the key (and keeps it)
        self.gi_ctx = (p2["fighter"], th["move"], round(p2["dist"], 2)) if p2 is not None else None
        self.log("gi", th, dirs, self.prev["p1"]["m0"] if self.prev else None, round(self.gi_lead(holding_g), 2))
        if holding_g:                                    # G up first: a GI needs a fresh G
            self.phase, self.until = "regrab", now + REGRAB_S
            return set()
        self.phase, self.until = "press", now
        self.gi_keys = ()
        return self._decide_press(now)

    def _decide_press(self, now: float) -> set[str]:
        s = self.prev
        p1 = s["p1"]
        fwd, back = directions(p1)
        self.gi_keys = (fwd if self.gi_dirs == "fwd" else back, G)
        return set(self.gi_keys)


class Keys:
    """Holds a set of keys through send(rows), on the caller's thread: only the changes are sent."""

    def __init__(self, send, clock=time.monotonic):
        self.send, self.held, self.clock = send, set(), clock
        self.applied_at, self.latency_s = clock(), 0.0

    def hold(self, keys: set[str]):
        # directions go down before buttons: G even 12 ms ahead of the direction (xdotool's gap between two keys)
        # is read as a guard and the GI does not come out (live: dir first 32 / 32 GIs, G first 3 / 12)
        rows = [{"key": k, "down": False} for k in sorted(self.held - keys)] + \
               [{"key": k, "down": True} for k in sorted(keys - self.held, key=lambda k: (k not in DIRECTIONS, k))]
        if rows:
            t0 = self.clock()
            self.send(rows)
            self.applied_at = self.clock()
            self.latency_s = 0.7 * self.latency_s + 0.3 * (self.applied_at - t0)
        self.held = set(keys)

    def tap(self, key: str, sleep, s: float = 0.1):
        self.hold(set())
        self.send([{"key": key, "down": True}])
        sleep(s)
        self.send([{"key": key, "down": False}])

    def close(self):
        self.hold(set())


class Sender(Keys):
    """Keys on a thread of its own: the poll loop asks for a key set and goes on reading RAM while the emulator's
    send_input runs (xdotool on Linux: one process per call, 17-35 ms on the Spark, while a hit result lasts one
    frame). Only the newest wanted set is sent; .held / .applied_at say what the emulator has and since when."""

    def __init__(self, send, clock=time.monotonic):
        super().__init__(send, clock)
        self.want, self.cv, self.stopping = set(), threading.Condition(), False
        self.errors = 0
        self.thread = threading.Thread(target=self._run, daemon=True, name="sc2-keys")
        self.thread.start()

    def hold(self, keys: set[str]):
        with self.cv:
            if keys != self.want:
                self.want = set(keys)
                self.cv.notify()

    def _run(self):
        while True:
            with self.cv:
                while self.want == self.held and not self.stopping:
                    self.cv.wait(0.5)
                if self.stopping and self.want == self.held:
                    return
                want = set(self.want)
            try:
                Keys.hold(self, want)
            except Exception:                            # noqa: BLE001 - an emulator that went away: stop sending
                self.errors += 1
                if self.errors > 20:
                    return

    def tap(self, key: str, sleep, s: float = 0.1):
        self.hold(set())
        for _ in range(100):                             # the thread lets go of everything first
            if not self.held:
                break
            sleep(0.01)
        self.send([{"key": key, "down": True}])
        sleep(s)
        self.send([{"key": key, "down": False}])

    def close(self):
        self.hold(set())
        with self.cv:
            self.stopping = True
            self.cv.notify()
        self.thread.join(2.0)


class AdMem:
    def __init__(self, ad):
        self.ad = ad

    def rd(self, addr: int, n: int) -> bytes:
        return bytes(self.ad.read_memory(addr, n))


class OwnShm:
    """The session's own Dolphin MEM1 (gbox.ram_dump.ShmRam: found only under the session's process, read-only)."""

    def __init__(self, ram):
        self.ram = ram

    def rd(self, addr: int, n: int) -> bytes:
        return self.ram.read(0x80000000 | (addr & 0x1FFFFFF), n)


def memory(ad):
    """The session's RAM, read-only: its own Dolphin's shared view on this host, else the adapter's read_memory."""
    try:
        from .ram_dump import ShmRam
        ram = ShmRam.find(ad)
        if ram is not None:
            return OwnShm(ram)
    except Exception:                                  # noqa: BLE001 - the adapter's reads still work
        pass
    return AdMem(ad)


def matches(ad, g: dict) -> bool:
    """This playbook plays this session: Soul Calibur II (USA) on Dolphin."""
    if g.get("platform") != "gamecube":
        return False
    if g.get("game_id") in GAME_IDS:
        return True
    try:
        return memory(ad).rd(0x80000000, 6).decode("ascii", "replace") == DISC_ID
    except Exception:                                  # noqa: BLE001
        return False


def setup(ad) -> list[str]:
    return []


def learn_dir_for(ad) -> Path:
    """Where the move book lives: the worker's runtime folder (or ~/.gbox for a standalone run)."""
    rt = getattr(getattr(ad, "config", None), "runtime", None)
    return (Path(rt) if rt else Path.home() / ".gbox") / "sc2_learned"


def play(ad, send, stopped, sleep=time.sleep, clock=time.monotonic, stats: dict | None = None, m=None,
         poll_s: float = 0.002, brain: Brain | None = None, learn_dir: Path | None = None, threaded: bool = True) -> dict:
    """Defend P1 until stopped(); send(rows) presses keys (on a thread of its own unless threaded=False, so RAM is
    read on while a slow send_input runs). stats (filled live for the watch panel): attacks, gi, gi_tried, gi_missed,
    gi_failed, gi_latency_frames, guards, hits_taken, damage_taken, ducks, steps, punishes, punish_hits, rounds_won,
    rounds_lost, fights, fight (a fight is on), p1_hp, p2_hp, phase."""
    m = m or memory(ad)
    rd = m.rd if hasattr(m, "rd") else m
    stats = stats if stats is not None else {}
    if brain is None:
        book = MoveBook((learn_dir or learn_dir_for(ad)) / "movebook.json", seed=SEED_BOOK)
        brain = Brain(stats, book=book)
    elif brain.stats is not stats:                     # one stats dict: the watch panel's
        stats.update(brain.stats)
        brain.stats = stats
    keys = Sender(send, clock) if threaded else Keys(send, clock)
    brain.out = keys
    try:
        return _loop(rd, keys, brain, stats, stopped, sleep, clock, poll_s)
    finally:
        keys.close()
        brain.book.save()


def _loop(rd, keys, brain, stats, stopped, sleep, clock, poll_s) -> dict:
    out_since, last_menu, was_fight, errors, last_save = None, 0.0, False, 0, clock()
    while not stopped():
        now = clock()
        try:
            s = snapshot(rd)
        except Exception as e:                         # noqa: BLE001 - a read during a load: next poll
            errors += 1
            stats["read_errors"] = errors
            stats["last_error"] = f"{type(e).__name__}: {e}"[:200]
            keys.hold(set())
            sleep(0.05)
            continue
        keys.hold(brain.decide(s, now))
        stats.update(fight=s["fight"], p1_hp=round(s["p1"]["hp"], 1), p2_hp=round(s["p2"]["hp"], 1), phase=brain.phase)
        if s["fight"]:
            if not was_fight:
                stats["fights"] += 1
            was_fight, out_since = True, None
            if now - last_save > 60:                    # a long fight (Practice, Survival): keep the book on disk
                brain.book.save()
                last_save = now
            sleep(poll_s)
            continue
        if was_fight:
            brain.book.save()                           # what this fight taught about the opponent's moves
        was_fight = False
        out_since = out_since or now
        if now - out_since > MENU_AFTER and now - last_menu > MENU_EVERY:
            # results / next stage / continue: on to the next fight; every fourth press is Start (the title's
            # PRESS START, and it ends the attract demo)
            keys.tap(START if stats.get("menu_presses", 0) % 4 == 3 else A, sleep)
            last_menu = clock()
            stats["menu_presses"] = stats.get("menu_presses", 0) + 1
        sleep(0.02)
    return stats
