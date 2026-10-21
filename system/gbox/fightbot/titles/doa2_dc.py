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
No frame clock or attack signatures are mapped yet, so DOA2 runs the reflex (fightbot.reflex), not the frame engine."""
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
