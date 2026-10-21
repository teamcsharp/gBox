"""Dead or Alive 3 (Xbox, USA) on the pinned native runner: title #2 of the fighting engine (gbox.doa3_bot plays it).

Everything comes from the game's own RAM (profiles/gamedata/b8edf7040116f3aa-ram.json, with the routine or the live
check behind each field) through the adapter's verified channel (doa3_memory.Channel), and every press goes through
gBox's virtual pad on the game's 4th port (doa3_pad): no window focus, no driver, the player's own pad untouched.

Frames: the main loop (0x000A06D0) stores the performance counter at its start (game.qpc) and advances a ring index
after the game tasks ran (game.frame_ring, 0x000A0440): a new ring value means that frame's logic is done, so the
world is read right after it and the counter delta says how many frames passed.

Buttons (the game's default button table 0x219798, every port): X = Free (game bit 1), Y = Punch (2), B = Kick (4),
A = Throw (Free + Punch), RT = Free + Kick, Black = P + K + F. gBox pad names are RetroPad positions, so Free is "y",
Punch "x", Kick "a", Throw "b". Directions are the D-pad (the stick only drives a port whose stick option is on,
0x488831). The game's per-player input word (pN.input) shows them as F 1, P 2, K 4, down 0x10, up 0x20, right 0x40,
left 0x80: the reaction latency is measured on it."""
from __future__ import annotations

import struct

from ... import ram_map
from ..title import Answer, Title

MAP_ID = "b8edf7040116f3aa"
GAME_IDS = {"b8edf7040116f3aa", "f03a801797a90506"}      # the catalog DOA3 (USA) and the QuickSwap copy
FREE, PUNCH, KICK, THROW = "y", "x", "a", "b"
BITS = {"y": 0x1, "x": 0x2, "a": 0x4, "b": 0x3, "down": 0x10, "up": 0x20, "right": 0x40, "left": 0x80}
CLOCK = (0x85B988, 0x40)                                   # game.qpc .. game.frame_ring + 4: one read a poll
QPC, QPC_HZ, RING = 0x85B988, 0x85B9E0, 0x85B9C4


class Doa3(Title):
    map_id = MAP_ID
    name = "Dead or Alive 3 (Xbox, USA)"
    warn_lead = 9                                          # P2's P / K edge (p2.attack_input) to the hit, until learned
    warn_settle = 2                                        # then wait for the move it starts: the book learns per move
    attack_gap = 75
    log_moves = True                                       # every P2 move change in the lessons: attack candidates
    hold_lead = 2                                          # a hold pressed this many frames before the hit's first frame

    def __init__(self, rmap=None):
        super().__init__(rmap)
        self._qpc = self._ring = None
        self._hz = None
        self.count = 0                                     # frames since the first poll

    def extra_fields(self):
        return ["game.mode", "game.phase", "game.round_winner", "game.playing_mode", "game.chosen_mode",
                "players.port", "p1.active", "p2.active"]

    def _sig(self, values, name) -> str | None:
        f = self.map.fields.get(name)
        raw = values.raw.get(name) if f else None
        return (f.signatures.get(raw) or {}).get("screen") if f and raw is not None else None

    def screen(self, values) -> str:
        """game.mode says title / menus / in a game; in a game the fight's phase says which part (map signatures)."""
        mode = self._sig(values, "game.mode")
        if mode == "fight":
            return self._sig(values, "game.phase") or "loading"
        return mode or "unknown"

    # -- frames --
    def frame(self, mem) -> int | None:
        """Frames since the first poll: advances when the ring index does (the frame's logic is done), by the counter's
        elapsed frames when the loop missed some."""
        read = ram_map.read_fn(mem)
        raw = bytes(read(CLOCK[0], CLOCK[1]))
        qpc = struct.unpack_from("<Q", raw, 0)[0]
        ring = struct.unpack_from("<I", raw, RING - QPC)[0]
        if self._hz is None:
            self._hz = struct.unpack("<Q", bytes(read(QPC_HZ, 8)))[0] or None
        if self._ring is None:
            self._qpc, self._ring = qpc, ring
            return self.count
        if ring == self._ring:
            return self.count
        steps = (ring - self._ring) % 8
        if self._hz and qpc > self._qpc:
            by_clock = int(round((qpc - self._qpc) * self.fps / self._hz))
            if by_clock >= 8:                              # the ring went all the way round: the counter knows
                steps = by_clock
        self._qpc, self._ring = qpc, ring
        self.count += steps
        return self.count

    def read(self, mem, t: float = 0.0):
        w = super().read(mem, t)
        w.frame = self.count
        return w

    # -- answers --
    def answers(self, attack, w):
        back, fwd = self.back(w), self.forward(w)
        holds = [Answer("hold_high", ("up", back, FREE), frames=4, lead=self.hold_lead),
                 Answer("hold_mid", (back, FREE), frames=4, lead=self.hold_lead),
                 Answer("hold_low", ("down", back, FREE), frames=4, lead=self.hold_lead),
                 Answer("hold_mid_kick", (fwd, FREE), frames=4, lead=self.hold_lead)]
        if attack.height:                                  # the signature says where it hits: those holds first
            holds.sort(key=lambda a: not a.name.startswith(f"hold_{attack.height}"))
        if attack.kind == "throw":
            return [Answer("throw_escape", (FREE, PUNCH), frames=3, lead=1)]
        return holds

    def punish(self, w, outcome):
        return Answer("ppk", (), seq=(((PUNCH,), 3), ((), 6), ((PUNCH,), 3), ((), 6), ((KICK,), 3)),
                      judge=60, kind="punish")

    def attacks(self, w):
        fwd = self.forward(w)
        return [Answer("ppk", (), seq=(((PUNCH,), 3), ((), 6), ((PUNCH,), 3), ((), 6), ((KICK,), 3)), judge=60,
                       kind="attack"),
                Answer("throw", (THROW,), frames=3, judge=60, kind="attack"),
                Answer("fwd_kick", (fwd, KICK), frames=3, judge=45, kind="attack")]

    HELD_REWARD = 30.0                                     # a caught attack counts like this much health

    def outcome(self, before, after, answer):
        """Health dealt minus taken, plus DOA3's own verdict of a hold or throw: the paired-move flag (pN.paired,
        +0x32 of the player block) turns 1 for the fighter caught in the other's hold or throw."""
        reward, met, label = super().outcome(before, after, answer)
        caught = after.p2.has("held") and not before.p2.has("held")
        caught_me = after.p1.has("held") and not before.p1.has("held")
        if caught and not caught_me:
            return (reward or 0.0) + self.HELD_REWARD, True, "held"
        if caught_me and not caught:
            return (reward or 0.0) - self.HELD_REWARD, True, "thrown"
        return reward, met, label

    def input_bits(self, answer, w):
        bits = 0
        for k in answer.at(0):
            bits |= BITS.get(k, 0)
        return bits

    # -- between fights --
    def menu(self, w):
        """The map's fight.menus rules for the screen (Title.menu); without rules: START on the title (the port that
        presses it plays P1), A (gBox "b") through the menus, results and continue prompts."""
        if w.screen in (self.block.get("menus") or {}):
            return super().menu(w)
        if w.screen in ("title", "demo"):
            return "start"
        if w.screen in ("menu", "char_select", "results", "continue", "game_over"):
            return THROW                                   # the Xbox A button: confirm
        return None
