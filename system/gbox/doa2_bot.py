"""Dead or Alive 2 Limited Edition (Dreamcast, Flycast) autoplay playbook: always in a fight, never on a title screen.

Game state from RAM (found 2026-10-20 by diffing RAM in the attract demo vs a fight the player controls):
  0x8C200848  u8   1 = attract demo / title, 0 = a fight the player controls
  0x8C2376D8  u16  P1 health (0..240 in a fight; the attract demo shows 320)
  0x8C237740  u16  P2 health
  0x8C23A37D  u8   1 while the opponent's attack input is down: rises 100-170 ms before 88% of the hits P1 takes and is
                   up only 6% of the time otherwise (60 Hz full-RAM recording of 3 minutes of fights, 65 hits on P1)
Holds (Reflex): on that edge P1 presses Free (retropad a = Dreamcast B) with a direction. Measured against the CPU
(45 s each): no reaction lost 450-520 health/min and dealt 0; Free+back lost 344-385/min and dealt 193-293/min through
holds alone. Which direction pays depends on the attack (high / mid punch / mid kick / low) and the side P1 is on, so
the reflex learns it: each try is scored by damage dealt minus damage taken in the next 0.8 s.
The loop: in a fight, the operator's learned style plays P1 (imitate.Style), with P1's health topped up when it runs low
so autoplay never loses on screen (Survival then runs endlessly: one opponent after another). Between fights the game
brings in the next opponent itself; only on the title / attract demo, or after OUT_JUMP seconds out of a fight
(results, continue screens), does it load the jump state: an emulator save state taken in a confirmed fight and
refreshed from a newer fight every JUMP_REFRESH seconds, so jumps land in different matchups. Until a jump state exists
it presses through the menus (Start, Start, Survival, fighter). Two jumps in a row that don't land in a fight drop the
jump state (a 2026-10-20 run loaded one 412 times and the game ended up stuck). RAM that stops changing for STILL_FOR
seconds gets Start / B once (a prompt or a still menu); still nothing NUDGE_WAIT seconds later = a hang: the run ends
so the caller relaunches. Works on any build of this disc (the operator's MarioVSonic cast build included).
"""
from __future__ import annotations

import random
import struct
import threading
import time

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
WARN = 0x8C23A37D                                 # the opponent's attack input (see above)
FREE = "a"                                        # retropad a = Dreamcast B = Free (hold / guard)
HOLDS = (("left",), ("right",), ("up", "left"), ("up", "right"), ("down", "left"), ("down", "right"))
HOLD_S, JUDGE_S, EXPLORE = 0.1, 0.8, 0.2


def matches(ad, g: dict) -> bool:
    return g.get("game_id") in GAME_IDS and g.get("platform") == "dreamcast"


def setup(ad) -> list[str]:
    return []


def state(rd) -> dict:
    """{'fighting', 'demo', 'p1', 'p2'} from RAM (rd(address, length) -> bytes)."""
    demo = rd(DEMO, 1)[0]
    p1, p2 = (struct.unpack("<H", rd(a, 2))[0] for a in (P1_HP, P2_HP))
    return {"demo": demo, "p1": p1, "p2": p2,
            "fighting": demo == 0 and 0 < p1 <= HP_MAX and 0 < p2 <= HP_MAX}


class Reflex:
    """Hold the opponent's attacks: on the attack-input edge press Free + the direction that has paid best so far
    (untried ones first, then 20% exploring). step(now) is one poll; the caller runs it every ~10 ms in a fight."""

    def __init__(self, rd, send, stats: dict, rng=None):
        self.rd, self.send, self.stats, self.rng = rd, send, stats, rng or random.Random()
        self.score = {h: [0, 0.0] for h in HOLDS}        # direction -> [tries, total reward]
        self.prev, self.down, self.release_at, self.judge = 0, None, None, None
        stats.update(holds=0, hold_dealt=0, hold_taken=0)

    def _hp(self):
        return tuple(struct.unpack("<H", self.rd(a, 2))[0] for a in (P1_HP, P2_HP))

    def choose(self):
        untried = [h for h in HOLDS if self.score[h][0] == 0]
        if untried:
            return untried[0]
        if self.rng.random() < EXPLORE:
            return self.rng.choice(HOLDS)
        return max(HOLDS, key=lambda h: self.score[h][1] / self.score[h][0])

    def step(self, now):
        if self.release_at is not None and now >= self.release_at:
            self.send([{"key": k, "down": False} for k in (FREE, *self.down)])
            self.release_at = None
        if self.judge is not None and now >= self.judge[0]:
            _, h, p1, p2 = self.judge
            n1, n2 = self._hp()
            dealt, taken = max(0, p2 - n2) if n2 <= HP_MAX else 0, max(0, p1 - n1) if n1 <= HP_MAX else 0
            self.score[h][0] += 1
            self.score[h][1] += dealt - taken
            self.stats["hold_dealt"] += dealt
            self.stats["hold_taken"] += taken
            self.stats["hold_best"] = "+".join(max((x for x in HOLDS if self.score[x][0]),
                                                   key=lambda x: self.score[x][1] / self.score[x][0]))
            self.judge = None
        w = self.rd(WARN, 1)[0]
        if w and not self.prev and self.judge is None and self.release_at is None:
            h = self.choose()
            p1, p2 = self._hp()
            self.send([{"key": k, "down": True} for k in (FREE, *h)])
            self.down, self.release_at, self.judge = h, now + HOLD_S, (now + JUDGE_S, h, p1, p2)
            self.stats["holds"] += 1
        self.prev = w


def play(ad, send, stopped, style=None, clock=time.time, sleep=time.sleep, stats: dict | None = None,
         holds: bool | None = None) -> dict:
    """stats (optional, filled live for the watch panel): fights_s, jumps, routes, saves, safety, hung, plus the
    current p1/p2 health and whether a fight is on."""
    lock = threading.Lock()                       # the reflex thread shares the emulator's memory and input link

    def rd(a, n):
        with lock:
            return bytes(ad.read_memory(a, n))

    raw_send = send                                # send_locked must reach the emulator, not itself (send is rebound below)

    def send_locked(rows):
        with lock:
            raw_send(rows)
    stats = stats if stats is not None else {}
    stats.update({"fights_s": 0.0, "jumps": 0, "routes": 0, "saves": 0, "safety": 0, "hung": False})
    fighting = threading.Event()
    if holds is None:
        holds = clock is time.time                    # real time only: the reflex polls on its own thread
    if holds:
        reflex = Reflex(rd, send_locked, stats)

        def reflex_loop():
            while not stopped() and not stats["hung"]:
                if fighting.wait(0.5):
                    try:
                        reflex.step(time.time())
                    except Exception:                  # noqa: BLE001 - a read during a load: next poll
                        pass
                    time.sleep(0.008)
        threading.Thread(target=reflex_loop, daemon=True, name="doa2-holds").start()
        send = send_locked
    def tap(key):
        send([{"key": key, "down": True}])
        sleep(0.3)
        send([{"key": key, "down": False}])
    jump_ok, fight_since, out_since, last_ram, still_since, nudged_at = False, None, None, None, None, None
    saved_at, jumped_at, failed_jumps = None, None, 0
    stats.update(jumps_dropped=0, nudges=0)
    while not stopped():
        now = clock()
        try:
            st = state(rd)
            ram = rd(*WATCH)
        except Exception:                          # noqa: BLE001 - a read during a load: try again
            sleep(0.5)
            continue
        if ram == last_ram:
            still_since = still_since or now
            if now - still_since > STILL_FOR:
                if nudged_at is None:              # a prompt or a still menu: press through it once
                    tap("start")
                    tap("b")
                    nudged_at = clock()
                    stats["nudges"] += 1
                elif now - nudged_at > NUDGE_WAIT:
                    stats["hung"] = True           # the caller relaunches the game
                    break
        else:
            still_since = nudged_at = None
        last_ram = ram
        if jumped_at is not None and now - jumped_at > JUMP_LAND:
            jumped_at = None                       # the jump showed no fight
            failed_jumps += 1
            if failed_jumps >= MAX_FAILED_JUMPS:
                jump_ok, failed_jumps = False, 0
                stats["jumps_dropped"] += 1
        stats.update(fighting=st["fighting"], p1_hp=st["p1"], p2_hp=st["p2"])
        (fighting.set if st["fighting"] else fighting.clear)()
        if st["fighting"]:
            out_since, jumped_at, failed_jumps = None, None, 0
            fight_since = fight_since or now
            if st["p1"] < SAFETY_HP:
                ad.write_memory(P1_HP, struct.pack("<H", HP_MAX))
                stats["safety"] += 1
            if now - fight_since > 6 and (saved_at is None or now - saved_at > JUMP_REFRESH):
                saved_at = now                     # this fight becomes the jump state (a newer one later)
                try:
                    ad.save_state()
                    jump_ok = True
                    stats["saves"] += 1
                except Exception:                  # noqa: BLE001 - no save state: menus it is
                    pass
            if style is not None:
                from .imitate import play_style
                play_style(style, send=send, stopped=stopped, sleep=sleep, limit=2)
            else:
                sleep(0.3)
            continue
        if fight_since is not None:
            stats["fights_s"] = round(stats["fights_s"] + now - fight_since, 1)
        fight_since = None
        out_since = out_since or now
        title = st["demo"] == 1                    # the title / attract demo: never worth watching
        if jump_ok and jumped_at is None and (title and now - out_since > 1.5 or now - out_since > OUT_JUMP):
            try:
                ad.load_state()
                stats["jumps"] += 1
                jumped_at, out_since = clock(), None
                sleep(2.0)
                continue
            except Exception:                      # noqa: BLE001
                jump_ok = False
        if not jump_ok and now - out_since > 3 and (title or now - out_since > OUT_JUMP):
            for key, wait in ROUTE:
                if stopped():
                    break
                send([{"key": key, "down": True}])
                sleep(0.3)
                send([{"key": key, "down": False}])
                sleep(wait)
            stats["routes"] += 1
            out_since = None
            continue
        sleep(0.5)
    fighting.clear()
    if fight_since is not None:
        stats["fights_s"] = round(stats["fights_s"] + clock() - fight_since, 1)
    return stats
