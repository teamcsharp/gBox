"""Dead or Alive 2 Limited Edition (Dreamcast, Flycast): title #1 of the fighting engine (gbox.doa2_bot plays it).

Game state from RAM (found 2026-10-20 by diffing RAM in the attract demo vs a fight the player controls; the map
profiles/gamedata/1de2e7634f3161ff-ram.json carries the same fields with their evidence):
  0x8C200848  u8   1 = attract demo / title, 0 = a fight the player controls
  0x8C2376D8  u16  P1 health (0..240 in a fight; the attract demo shows 320)
  0x8C237740  u16  P2 health
  0x8C23A37D  u8   1 while the opponent's attack input is down: rises 100-170 ms before 88% of the hits P1 takes and is
                   up only 6% of the time otherwise (60 Hz full-RAM recording of 3 minutes of fights, 65 hits on P1)
Holds: on that edge P1 presses Free (retropad a = Dreamcast B) with a direction (the engine's onset reflex). Measured
against the CPU (45 s each): no reaction lost 450-520 health/min and dealt 0; Free+back lost 344-385/min and dealt
193-293/min through holds alone. Which direction pays depends on the attack (high / mid punch / mid kick / low) and the
side P1 is on, so the reflex learns it: each try is scored by damage dealt minus damage taken in the next 0.8 s.
No frame clock or attack signatures are mapped yet, so DOA2 runs the reflex (fightbot.reflex), not the frame engine.

Towards the frame engine (2026-10-21, from the 60 Hz recording ~/gBox_alt/scratch/agent/doa_rec1.npz on the Spark,
180 s of fights): DOA2 LE lays its fighters out like DOA3 (gbox/fightbot/titles/doa3_xbox.py), two 0x68-byte blocks:
  0x8C2376B8  fighter 0 (P1)      0x8C237720  fighter 1 (P2)
  +0x20  u16 health (the mapped P1_HP / P2_HP are these: 0x8C2376D8 / 0x8C237740)
  +0x2E  u16 move id   (0x8C2376E6 / 0x8C23774E: 108 / 96 distinct values, 496 / 390 changes in 180 s)
  +0x33  u8  move class (0x8C2376EB / 0x8C237753: values 0..16, as DOA3's 0x484C7B: attacker 4 / 6, victim 0xA / 0xB there)
  +0x32  u8  paired flag (DOA3: 1 for the victim of a hold / throw) and +0x00 active: constant in that recording.
Next: a private RetroArch + flycast_libretro on the Spark (nice'd, its own Xvfb, vglrun -d egl, network_cmd_port for
READ_CORE_RAM, network_remote_base_port for the UDP retropad, gbox/adapters.py 1536-1562 and 2002-2050 show both),
a frame counter (dc_framectr.py over a new recording), then a Doa2 Title with p2.move / p2.move_class signatures and
the attack-input edge as warn, like Doa3, and the same holds (Free + up/back, back, down/back, forward)."""
from __future__ import annotations

import struct

from ..reflex import OnsetReflex

MAP_ID = "1de2e7634f3161ff"
GAME_IDS = {"1de2e7634f3161ff"}                 # Dead or Alive 2 - Limited Edition (Japan)
DEMO, P1_HP, P2_HP, HP_MAX = 0x8C200848, 0x8C2376D8, 0x8C237740, 240
SAFETY_HP = 100                                   # P1 below this is topped up to HP_MAX
WATCH = (0x8C237000, 4096)                        # fighter data: changes every frame in play (hang check)
ROUTE = (("start", 3.0), ("start", 3.0), ("right", 1.5), ("right", 1.5), ("b", 3.0), ("b", 3.0))   # title -> Survival -> fighter
OUT_JUMP = 12.0                                   # out of a fight this long (results, continue): jump back in
JUMP_REFRESH = 180.0                              # take a new jump state from a newer fight at most this often
JUMP_LAND = 8.0                                   # a jump that shows no fight within this long did not land
MAX_FAILED_JUMPS = 2
STILL_FOR, NUDGE_WAIT = 8.0, 10.0
NUDGE_KEYS = ("start", "b")
WARN = 0x8C23A37D                                 # the opponent's attack input (see above)
FREE = "a"                                        # retropad a = Dreamcast B = Free (hold / guard)
HOLDS = (("left",), ("right",), ("up", "left"), ("up", "right"), ("down", "left"), ("down", "right"))
HOLD_S, JUDGE_S, EXPLORE = 0.1, 0.8, 0.2


def matches(ad, g: dict) -> bool:
    return g.get("game_id") in GAME_IDS and g.get("platform") == "dreamcast"


def state(rd) -> dict:
    """{'fighting', 'demo', 'p1', 'p2'} from RAM (rd(address, length) -> bytes)."""
    demo = rd(DEMO, 1)[0]
    p1, p2 = (struct.unpack("<H", rd(a, 2))[0] for a in (P1_HP, P2_HP))
    return {"demo": demo, "p1": p1, "p2": p2,
            "fighting": demo == 0 and 0 < p1 <= HP_MAX and 0 < p2 <= HP_MAX}


class Reflex(OnsetReflex):
    """Hold the opponent's attacks: on the attack-input edge press Free + the direction that has paid best so far
    (untried ones first, then 20% exploring). step(now) is one poll; the caller runs it every ~10 ms in a fight."""

    def __init__(self, rd, send, stats: dict, rng=None):
        super().__init__(rd, send, stats, warn=WARN, hp=(P1_HP, P2_HP), hp_max=HP_MAX, guard=FREE, options=HOLDS,
                         hold_s=HOLD_S, judge_s=JUDGE_S, explore=EXPLORE, rng=rng)


def reflex(rd, send, stats):
    return Reflex(rd, send, stats)


# --- Parry layer ---------------------------------------------------------------
# GameFAQs (DOA2 LE) pinpoint-hold counter data, mapped to the six HOLDS options
# used by the onset reflex.  P1 on the left (back = "left"):
#   high       -> up + back   ("up", "left")
#   mid punch  -> back        ("left",)
#   mid kick   -> forward     ("right",)
#   low        -> down + back ("down", "left")
# P1 on the right (back = "right"): mirror the horizontal.
PARRY_HIGH   = "high"
PARRY_MID_P  = "mid_punch"
PARRY_MID_K  = "mid_kick"
PARRY_LOW    = "low"

_PARRY_LEFT = {PARRY_HIGH: ("up", "left"), PARRY_MID_P: ("left",),
               PARRY_MID_K: ("right",), PARRY_LOW: ("down", "left")}
_PARRY_RIGHT = {PARRY_HIGH: ("up", "right"), PARRY_MID_P: ("right",),
                PARRY_MID_K: ("left",), PARRY_LOW: ("down", "right")}


def parry_holds(side: int = 1) -> dict:
    """The four attack classes -> the HOLDS tuple they map to, for P1 on the given side."""
    return dict(_PARRY_LEFT if side == 1 else _PARRY_RIGHT)


class ParryReflex(OnsetReflex):
    """Onset reflex with a fixed parry table: each attack class maps to a specific hold
    (no learning, no exploration).  The book still records outcomes so the stats panel
    shows which parries land; but the choice is deterministic from the attack class.
    Override step() to intercept the book.choose call and substitute the parry table."""

    def __init__(self, rd, send, stats: dict, side: int = 1, rng=None):
        super().__init__(rd, send, stats, warn=WARN, hp=(P1_HP, P2_HP), hp_max=HP_MAX, guard=FREE,
                         options=HOLDS, hold_s=HOLD_S, judge_s=JUDGE_S, explore=0.0, rng=rng)
        self.parry = parry_holds(side)
        self.last_cls = None

    def set_attack_class(self, cls: str | None):
        """Called by the caller each poll with the current attack class
        (e.g. 'high', 'mid_punch', 'mid_kick', 'low'), or None if unknown."""
        self.last_cls = cls

    def _pick_name(self) -> str:
        """The hold name to use: parry table if the class is known, else the book."""
        if self.last_cls in self.parry:
            return "+".join(self.parry[self.last_cls])
        return self.book.choose(self.key, None, self.names)

    def step(self, now):
        """Same as OnsetReflex.step but uses the parry table for the hold choice."""
        if self.release_at is not None and now >= self.release_at:
            self.send([{"key": k, "down": False} for k in (self.guard, *self.down)])
            self.release_at = None
        if self.judge is not None and now >= self.judge[0]:
            _, name, p1, p2 = self.judge
            n1, n2 = self._hp()
            dealt = max(0, p2 - n2) if n2 <= self.hp_max else 0
            taken = max(0, p1 - n1) if n1 <= self.hp_max else 0
            self.book.record(self.key, None, name, dealt - taken, met=bool(dealt or taken))
            self.stats["hold_dealt"] += dealt
            self.stats["hold_taken"] += taken
            self.stats["hold_best"] = self.book.best(self.key)
            self.judge = None
        w = self.rd(self.warn, 1)[0]
        if w and not self.prev and self.judge is None and self.release_at is None:
            name = self._pick_name()
            h = self.options[self.names.index(name)]
            p1, p2 = self._hp()
            self.send([{"key": k, "down": True} for k in (self.guard, *h)])
            self.down, self.release_at, self.judge = h, now + self.hold_s, (now + self.judge_s, name, p1, p2)
            self.stats["holds"] += 1
        self.prev = w
