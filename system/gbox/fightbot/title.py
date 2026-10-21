"""A fighting game for the engine: its RAM map plus what RAM can't say (the buttons, the menus)."""
from __future__ import annotations

from dataclasses import dataclass

from .. import ram_map
from . import vocab, world

DIRS = ("up", "down", "left", "right")


@dataclass(frozen=True)
class Answer:
    """One way to answer an attack, or one punish / attack: keys held together for `frames` (or `seq`, a string of
    (keys, frames) steps), pressed `lead` frames before the attack's first active frame (the answer's own startup),
    judged `judge` frames after the press at the latest."""
    name: str
    keys: tuple
    frames: int = 6
    lead: int = 0
    judge: int = 48
    kind: str = "answer"                          # answer / punish / attack
    seq: tuple = ()                               # ((keys, frames), ...): a string (P, P, K) instead of one chord
    confirm_f: int = 0                            # > 0: Title.confirm must say it came out within this many frames
    fallback: "Answer | None" = None              # pressed instead when it didn't (SC2: no GI move -> guard)
    hold_off: tuple = ()                          # keys kept up while P1's own attack is out (SC2: G cancels startup)

    @property
    def length(self) -> int:
        return sum(n for _, n in self.seq) if self.seq else self.frames

    def at(self, k: int) -> tuple:
        """The keys held k frames into the answer, directions first: a button that lands a few ms before its
        direction reads as another move (SC2: G before 4 is a guard, not a Guard Impact)."""
        keys = self.keys
        if self.seq:
            keys = ()
            for step, n in self.seq:
                if k < n:
                    keys = step
                    break
                k -= n
        return tuple(sorted(keys, key=lambda x: (x not in DIRS, x)))

    def ordered(self) -> tuple:
        return self.at(0)


class Title:
    """Subclasses set map_id and fill answers() / punish() / menu(); the rest comes from the map's fight block."""
    map_id = ""
    name = ""
    fps = 60
    frame_ms: float | None = None                # the frame field is a millisecond tick, not a frame counter
    warn_lead = 8                                # frames from a `warn` onset to the hit when nothing better is known
    warn_settle = 0                              # frames to wait after a warn edge for the move it starts (per-move book)
    long_window = 4                              # an attack active longer than this lands where the book saw it land
    lag_f = 1                                    # the engine's measured input lag (frames), for answers that need it
    reach: float | None = None                   # world units: farther apart, an attack can't land (no answer)
    fight_screens = vocab.FIGHT_SCREENS          # the fight runner keeps ticking on these screens

    def __init__(self, rmap=None):
        self.map = rmap or ram_map.load(self.map_id)
        self.block = self.map.spec.get("fight") or {}
        self.vocab = self.block.get("vocab") or {}
        self.fps = float(self.block.get("fps", self.fps))
        self.frame_ms = self.block.get("frame_ms", self.frame_ms)
        names = [v for v in self.vocab.values() if isinstance(v, str) and v in self.map.fields]
        self.fields = list(dict.fromkeys(names + list(self.extra_fields())))

    # -- reading --
    def extra_fields(self) -> list[str]:
        return []

    def frame_of(self, value) -> int | None:
        if value is None or isinstance(value, bool):
            return None
        return int(round(value / self.frame_ms)) if self.frame_ms else int(value)

    def frame(self, mem) -> int | None:
        """The game frame now: one small read of the frame field."""
        name = self.vocab.get("frame")
        if not name:
            return None
        v = self.map.read(mem, names=[name]).get(name)
        return self.frame_of(v)

    def screen(self, values) -> str:
        name = self.vocab.get("screen")
        if name and name in self.map.fields:
            raw = values.raw.get(name)
            t = vocab.tags(self.map.fields[name], raw if raw is not None else values.get(name))
            return t.get("screen") or "unknown"
        return "unknown"

    def read(self, mem, t: float = 0.0) -> world.World:
        values = self.map.read(mem, names=self.fields)
        frame = self.frame_of(values.get(self.vocab.get("frame"))) if self.vocab.get("frame") else None
        w = world.read(self.map, values, frame, t, self.screen(values))
        self.finish(w)
        return w

    def finish(self, w: world.World) -> None:
        """Title-specific touches after the generic read (side from positions by default)."""
        for me, other in ((w.p1, w.p2), (w.p2, w.p1)):
            if me.side is None and me.pos and other.pos:
                me.side = 1 if me.pos[0] <= other.pos[0] else -1

    # -- answering --
    def back(self, w: world.World) -> str:
        return "left" if (w.p1.side or 1) > 0 else "right"

    def forward(self, w: world.World) -> str:
        return "right" if (w.p1.side or 1) > 0 else "left"

    def answers(self, attack: world.Attack, w: world.World) -> list[Answer]:
        return []

    def punish(self, w: world.World, outcome: str) -> Answer | None:
        return None

    def confirm(self, answer: Answer, w: world.World) -> bool:
        """For answers with confirm_f: did it come out (P1's move shows it)? Default: yes."""
        return True

    def input_bits(self, answer: Answer, w: world.World) -> int:
        """The bits the game's own input word (pN.input) shows when it read this answer's keys (0 = can't tell)."""
        return 0

    def outcome(self, before: world.World, after: world.World, answer: Answer) -> tuple[float, bool, str]:
        """(reward, met, label) of the window after an answer: health dealt minus taken by default."""
        dealt = max(0, (before.p2.hp or 0) - (after.p2.hp or 0)) if before.p2.hp is not None and after.p2.hp is not None else 0
        taken = max(0, (before.p1.hp or 0) - (after.p1.hp or 0)) if before.p1.hp is not None and after.p1.hp is not None else 0
        label = "dealt" if dealt and not taken else "taken" if taken and not dealt else "traded" if dealt else "nothing"
        return float(dealt - taken), bool(dealt or taken), label

    # -- between fights --
    def menu(self, w: world.World) -> str | None:
        """The pad key to press on a non-fight screen (None: wait)."""
        return None
