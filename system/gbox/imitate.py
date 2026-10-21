"""Autoplay that learns from the operator's own play (gameplay memory).

While the operator plays, padstate.watch_xinput reports their controller at 30 Hz and gameplay memory keeps each report
as a 'pad' event (buttons pressed/released plus both sticks, server-time stamped). Two autoplay modes are built from it:

  replay   one recorded run played back on the operator's timing from the moment its session started: title screen,
           menus, loading and the run itself. Idle gaps longer than IDLE_CAP (the operator away) are shortened.
           Open-loop and approximate (server receipt times, not core frames): not a TAS.
  learned  a style model for any game with enough recorded play: the operator's input bursts (a combo, a dash, a guard,
           a jump) with their own hold times, and which burst tends to follow which. Played as a loop; it never presses
           Start/Select. Fighting games (SoulCalibur survival) play best with it.

Screen anchors keep a replay in step with loading times: while the operator plays, every press after a pause
(ANCHOR_IDLE) saves a 32x24 grey thumbnail of the screen they reacted to (gameplay memory 'frame'). Replay waits at
each anchor until the live screen matches it (or SYNC_TIMEOUT passes) and shifts the rest of the run by the wait.

The operator touching their pad hands control back (tools._takeover). Nothing here reads or writes game memory.
"""
from __future__ import annotations

import base64
import io
import math
import random
import time
from collections import Counter, defaultdict

IDLE_CAP = 20.0          # s: a longer gap in a recording plays as this long
BURST_GAP = 0.25         # s: idle this long ends an input burst
MAX_BURST = 2.0          # s: a longer burst (holding a direction while attacking) is cut into moves this long
NO_LEARN = frozenset({"start", "select", "l3", "r3"})   # pause / menus / camera clicks: the learned loop never presses them
MIN_REPLAY_PADS = 200    # a run with fewer pad reports is a test poke, not a run worth replaying
MIN_LEARN_BURSTS = 20
STICK_ON = 0.3           # stick deflection that counts as a direction (same threshold as gameplay_demo)
THUMB = (32, 24)         # anchor thumbnail size (grey)
ANCHOR_IDLE = 0.7        # s: a press after this long without input saves an anchor (the screen the operator reacted to)
MATCH = 14.0             # mean absolute grey difference (0-255) under which the live screen matches an anchor
SYNC_TIMEOUT = 15.0      # s: an anchor that never matches holds the replay this long, then it carries on
STILL = 12.0             # consecutive thumbnails closer than this: nothing is happening on screen (gameplay is 24+)
STILL_FOR = 4.0          # s of that = stuck (title screen, "press start", a dialogue box, a results screen)
MENU_IDLE = 0.8          # s without input before a lone press: how the operator works menus

# Dolphin on Windows (SendInput keyboard binding) wants GameCube names; physical XInput reports are positional RetroPad
# labels (Xbox A = 'b'). gameplay_demo.pad_events learned this mapping on the observed PSO demos.
DOLPHIN_GC = {"a": "b", "b": "a", "x": "y", "y": "x", "r": "z", "l2": "l", "r2": "r",
              "up": "t", "down": "g", "left": "f", "right": "h"}


def _stick_keys(stick, names) -> set[str]:
    if not isinstance(stick, dict):
        return set()
    neg_x, pos_x, neg_y, pos_y = names
    out = set()
    x, y = stick.get("x", 0), stick.get("y", 0)
    if type(x) in (int, float):
        out |= {neg_x} if x < -STICK_ON else {pos_x} if x > STICK_ON else set()
    if type(y) in (int, float):
        out |= {neg_y} if y < -STICK_ON else {pos_y} if y > STICK_ON else set()
    return out


def held_timeline(events: list[dict], adapter: str = "retroarch", platform: str | None = None) -> list[tuple[float, frozenset]]:
    """[(at, held)] after every pad report: the buttons and stick directions the operator held, named for `adapter`.

    RetroArch takes the physical labels as they are (network RetroPad) and the left stick as lleft/lright/lup/ldown.
    Dolphin on Windows takes the GameCube keyboard names (main stick = arrows, D-pad = t/g/f/h, C-stick = c*)."""
    gc = adapter == "dolphin" and platform == "gamecube"
    stick_names = ("left", "right", "up", "down") if gc else ("lleft", "lright", "lup", "ldown")
    buttons: set[str] = set()
    out = []
    for e in events:
        if e.get("kind") != "pad":
            continue
        p = e.get("payload") or {}
        for row in p.get("events") or []:
            if not isinstance(row, dict) or not isinstance(row.get("key"), str):
                continue
            k = row["key"].lower()
            buttons.add(k) if row.get("down", True) else buttons.discard(k)
        keys = set(buttons)
        if gc:
            keys = {DOLPHIN_GC.get(k, k) for k in keys if k != "l"}
        keys |= _stick_keys(p.get("stick"), stick_names)
        if gc:
            keys |= _stick_keys(p.get("rstick"), ("cleft", "cright", "cup", "cdown"))
        out.append((float(e["at"]), frozenset(keys)))
    return out


def diff(before: frozenset, after: frozenset) -> list[dict]:
    """Input rows from one held set to the next: releases first (a stick axis shares one RetroPad value)."""
    return [{"key": k, "down": False} for k in sorted(before - after)] + [{"key": k, "down": True} for k in sorted(after - before)]


def thumb(image: bytes) -> str:
    """A frame (PNG/JPEG) as a 32x24 grey thumbnail, base64: small enough for a gameplay-memory event."""
    from PIL import Image
    im = Image.open(io.BytesIO(image)).convert("L").resize(THUMB, Image.BILINEAR)
    return base64.b64encode(im.tobytes()).decode()


def distance(a: str, b: str) -> float:
    """Mean absolute grey difference of two thumbnails (0 = same screen, 255 = inverse)."""
    x, y = base64.b64decode(a), base64.b64decode(b)
    if len(x) != len(y) or not x:
        return 255.0
    return sum(abs(p - q) for p, q in zip(x, y)) / len(x)


def anchors(events: list[dict]) -> list[tuple[float, str]]:
    """[(at, thumbnail)] saved while the operator played (kind 'frame')."""
    return [(float(e["at"]), e["payload"]["thumb"]) for e in events
            if e.get("kind") == "frame" and isinstance((e.get("payload") or {}).get("thumb"), str)]


def replay_plan(timeline: list[tuple[float, frozenset]], started: float, idle_cap: float = IDLE_CAP,
                marks: list[tuple[float, str]] | None = None) -> list[tuple]:
    """[(t, rows)]: t seconds after the recorded session started, gaps over idle_cap shortened to idle_cap.
    With marks (anchors), each entry is (t, rows, thumbnail or None): an anchor sits on the first input change at or
    after it (within a second), so replay checks the screen right before pressing."""
    plan, held, shift, last = [], frozenset(), 0.0, started
    marks = sorted(marks or [])
    mi = 0
    for at, keys in timeline:
        if at < started:
            continue
        gap = at - last
        if gap > idle_cap:
            shift += gap - idle_cap
        last = at
        rows = diff(held, keys)
        if rows:
            item = (round(at - started - shift, 3), rows)
            if marks:
                mark = None
                while mi < len(marks) and marks[mi][0] <= at:
                    if at - marks[mi][0] <= 1.0:
                        mark = marks[mi][1]
                    mi += 1
                item += (mark,)
            plan.append(item)
            held = keys
    if held:
        plan.append((plan[-1][0] + 0.1, diff(held, frozenset())) + ((None,) if marks else ()))
    return plan


def wait_for_screen(mark: str, grab, stopped, *, clock=time.time, sleep=time.sleep, timeout: float = SYNC_TIMEOUT,
                    match: float = MATCH) -> float:
    """Hold until the live screen (grab() -> thumbnail) matches the anchor, or timeout. Returns the seconds held."""
    t0 = clock()
    while not stopped() and clock() - t0 < timeout:
        try:
            if distance(grab(), mark) <= match:
                break
        except Exception:
            pass
        sleep(0.2)
    return clock() - t0


def pick_run(runs: list[dict], adapter: str = "", run_id: str = "") -> dict | None:
    """The run to replay: the one asked for, else the newest real run (enough pad reports) on the same emulator."""
    if run_id:
        return next((r for r in runs if r.get("id") == run_id), None)
    real = [r for r in runs if (r.get("events") or {}).get("pad", 0) >= MIN_REPLAY_PADS]
    same = [r for r in real if not adapter or r.get("adapter") == adapter]
    pool = same or real
    return max(pool, key=lambda r: r.get("updated") or 0) if pool else None


def bursts(timeline: list[tuple[float, frozenset]], gap: float | None = None) -> list[tuple[float, list[tuple[float, frozenset]]]]:
    """Split the held timeline into bursts: (start time, [(offset, held)]) from the first press until everything was let
    go for `gap`. Each burst ends with its release step (offset, empty)."""
    gap = BURST_GAP if gap is None else gap
    out, cur, t0, idle_since = [], [], None, None
    for at, keys in timeline:
        keys = keys - NO_LEARN
        if keys:
            if cur and idle_since is not None and at - idle_since >= gap:
                out.append((t0, cur + [(round(idle_since - t0, 3), frozenset())]))
                cur, t0 = [], None
            elif cur and at - t0 > MAX_BURST:                  # still holding: the next move starts here
                out.append((t0, cur + [(round(at - t0, 3), frozenset())]))
                cur, t0 = [], None
            elif cur and idle_since is not None:                # let go briefly (a double tap): keep the release
                cur.append((round(idle_since - t0, 3), frozenset()))
            if t0 is None:
                t0 = at
            idle_since = None
            if not cur or cur[-1][1] != keys:
                cur.append((round(at - t0, 3), keys))
        elif cur and idle_since is None:
            idle_since = at
    if cur:
        end = idle_since if idle_since is not None else t0 + cur[-1][0] + 0.1
        out.append((t0, cur + [(round(end - t0, 3), frozenset())]))
    return out


def _sig(burst) -> tuple:
    return tuple(tuple(sorted(k)) for _, k in burst)


def learn(timeline: list[tuple[float, frozenset]]) -> dict:
    """The operator's style: distinct bursts (with one recorded timing each), how often, what follows what, idle gaps."""
    index, model, follows, gaps = {}, [], defaultdict(Counter), []
    prev_end, prev = None, None
    seq = bursts(timeline)
    for start, b in seq:
        s = _sig(b)
        if s not in index:
            index[s] = len(model)
            model.append({"steps": [[dt, sorted(k)] for dt, k in b], "n": 0})
        i = index[s]
        model[i]["n"] += 1
        if prev is not None:
            follows[prev][i] += 1
        if prev_end is not None and 0 <= start - prev_end < 2.0:
            gaps.append(round(start - prev_end, 3))
        prev, prev_end = i, start + b[-1][0]
    return {"bursts": model, "follows": {str(k): dict(v) for k, v in follows.items()}, "gaps": gaps[-500:],
            "total": len(seq), "menu": menu_keys(timeline)}


def menu_keys(timeline: list[tuple[float, frozenset]], top: int = 2) -> list[str]:
    """The buttons the operator uses to get through menus: lone presses after a pause (MENU_IDLE), most used first.
    Start always leads (title screens); then the confirm button this player and emulator use (RetroPad 'b' = the
    bottom button on a Dreamcast, 'a' on Dolphin GameCube...)."""
    counts, idle_since, prev = Counter(), None, frozenset()
    for at, keys in timeline:
        if not keys:
            if prev:
                idle_since = at
        elif not prev and len(keys) == 1 and idle_since is not None and at - idle_since >= MENU_IDLE:
            counts[next(iter(keys))] += 1
        prev = keys
    moves = {"up", "down", "left", "right", "lup", "ldown", "lleft", "lright", "dup", "ddown", "dleft", "dright",
             "t", "g", "f", "h", "cup", "cdown", "cleft", "cright", "start", "select"}
    out = ["start"] + [k for k, _ in counts.most_common() if k not in moves]
    return out[:top + 1]


class Stuck:
    """True once the screen has stayed (nearly) the same for STILL_FOR seconds: autoplay is stuck on a title screen,
    a "press start", a dialogue box or a results screen, and should press through it. It also keeps the run's
    novelty: how often the screen changed between looks and how many distinct screens were seen."""

    def __init__(self, grab, clock=time.time, still: float = STILL, still_for: float = STILL_FOR):
        self.grab, self.clock, self.still, self.still_for = grab, clock, still, still_for
        self.last, self.since = None, None
        self.changed = 0.0                    # when the screen last really changed (reset() does not count)
        self.looks = self.moving = 0
        self.seen: set[bytes] = set()

    def __call__(self) -> bool:
        try:
            t = self.grab()
        except Exception:
            return False
        now = self.clock()
        self.looks += 1
        self.seen.add(coarse(t))
        if self.last is None or distance(t, self.last) >= self.still:
            self.since = self.changed = now
            self.moving += self.last is not None
        self.last = t
        return now - self.since >= self.still_for

    def novelty(self) -> dict:
        """moving: share of looks where the screen had changed; screens: distinct coarse screens; score combines both."""
        moving = self.moving / max(1, self.looks - 1)
        return {"looks": self.looks, "moving": round(moving, 3), "screens": len(self.seen),
                "score": round(moving * math.log1p(len(self.seen)), 3)}

    def reset(self):
        self.since = self.clock()


KNOBS = {"follow": (0.4, 0.7, 0.9),           # how often the next move follows the last the way the operator's did
         "pace": (0.6, 1.0, 1.5),             # gap between moves x pace (lower = faster)
         "favor": (0.5, 1.0, 2.0)}            # move weights ** favor (higher = the operator's most used moves dominate)
DEFAULT_KNOBS = {"follow": 0.7, "pace": 1.0, "favor": 1.0}


def coarse(thumb: str) -> bytes:
    """A screen in 8x6 cells of 4 grey levels: equal for the same place, different for a new one."""
    px = base64.b64decode(thumb)
    w, h = THUMB
    if len(px) != w * h:
        return px[:48]
    out = bytearray()
    for cy in range(6):
        for cx in range(8):
            cell = [px[(cy * 4 + y) * w + cx * 4 + x] for y in range(4) for x in range(4)]
            out.append(sum(cell) // len(cell) // 64)
    return bytes(out)


def choose_knobs(history: list[dict], rng: random.Random | None = None, explore: float = 0.3) -> dict:
    """The knobs for the next run of a game from its earlier runs [{knobs, score}]: mostly the best average so far,
    sometimes (explore) a neighbour of it or an untried setting, so play keeps improving."""
    rng = rng or random.Random()
    totals: dict[tuple, list[float]] = {}
    for h in history:
        k = h.get("knobs") or {}
        if not isinstance(h.get("score"), (int, float)) or set(k) != set(KNOBS):
            continue
        totals.setdefault(tuple(sorted(k.items())), []).append(float(h["score"]))
    if not totals:
        return dict(DEFAULT_KNOBS)
    best = dict(max(totals, key=lambda t: sum(totals[t]) / len(totals[t])))
    if rng.random() >= explore:
        return best
    name = rng.choice(sorted(KNOBS))
    vals = KNOBS[name]
    i = vals.index(best[name]) if best[name] in vals else 1
    return best | {name: vals[max(0, min(len(vals) - 1, i + rng.choice((-1, 1))))]}


class Style:
    """Plays a learned model: the next burst follows the last one the way the operator's did (knobs['follow'], 70% by
    default), else by frequency (weights ** knobs['favor']); gaps scale by knobs['pace']."""

    def __init__(self, model: dict, rng: random.Random | None = None, knobs: dict | None = None):
        self.m, self.rng, self.prev = model, rng or random.Random(), None
        self.knobs = DEFAULT_KNOBS | {k: float(v) for k, v in (knobs or {}).items() if k in KNOBS}
        self.weights = [b["n"] ** self.knobs["favor"] for b in model["bursts"]]

    def next(self) -> list[tuple[float, frozenset]]:
        follow = self.m["follows"].get(str(self.prev)) if self.prev is not None else None
        if follow and self.rng.random() < self.knobs["follow"]:
            ids, w = zip(*((int(k), v) for k, v in follow.items()))
            i = self.rng.choices(ids, w)[0]
        else:
            i = self.rng.choices(range(len(self.weights)), self.weights)[0]
        self.prev = i
        return [(dt, frozenset(k)) for dt, k in self.m["bursts"][i]["steps"]]

    def gap(self) -> float:
        g = self.m.get("gaps") or [0.15]
        return max(0.03, min(0.8, self.rng.choice(g) * self.knobs["pace"]))


def play_plan(plan, *, send, stopped, clock, sleep, offset: float = 0.0, sync=None) -> dict:
    """Send each [(t, rows[, anchor])] at its time (t >= offset; rows before offset are skipped). At an anchor,
    sync(anchor) holds until the screen matches and the rest of the plan shifts by the hold. Stops when stopped()."""
    began, sent, held_for, synced = clock() - offset, 0, 0.0, 0
    for item in plan:
        t, rows = item[0], item[1]
        if t < offset:
            continue
        while clock() - began < t:
            if stopped():
                return {"completed": False, "sent": sent, "at": round(clock() - began, 2), "synced": synced}
            sleep(min(0.05, max(0.0, t - (clock() - began))))
        if len(item) > 2 and item[2] and sync is not None:
            h = sync(item[2])
            began += h
            held_for += h
            synced += 1
        if stopped():
            return {"completed": False, "sent": sent, "at": round(clock() - began, 2), "synced": synced}
        send(rows)
        sent += 1
    return {"completed": True, "sent": sent, "at": round(clock() - began, 2), "synced": synced,
            "held_for_screens": round(held_for, 1)}


FF_AFTER = 2                             # still-screen presses that moved nothing before fast-forward goes on


def play_style(style: Style, *, send, stopped, sleep, limit: int | None = None, stuck=None, ff=None,
               clock=time.time, stats: dict | None = None) -> int:
    """Loop the learned bursts until stopped (or `limit` bursts). Releases everything it holds between bursts.
    With stuck (a Stuck): when the screen stops changing, press the operator's menu buttons (Start, then their
    confirm button, in turn) until it moves again, instead of fighting a title screen. With ff (fast_forward(on)):
    when FF_AFTER presses in a row moved nothing (a loading screen, a dialogue that advances by itself), the emulator
    runs fast until the screen changes, so autoplay doesn't sit through it. stats gets ff_s (seconds fast-forwarded)."""
    n, menu, mi = 0, style.m.get("menu") or ["start"], 0
    useless, ff_since, last_press = 0, None, None
    stats = stats if stats is not None else {}
    stats.setdefault("ff_s", 0.0)

    def ff_off():
        nonlocal ff_since
        if ff_since is not None:
            try:
                ff(False)
            except Exception:                       # noqa: BLE001
                pass
            stats["ff_s"] = round(stats["ff_s"] + clock() - ff_since, 1)
            ff_since = None
    while not stopped() and (limit is None or n < limit):
        if stuck is not None and stuck():
            if last_press is not None and getattr(stuck, "changed", last_press + 1) <= last_press:
                useless += 1                         # the last press moved nothing
            else:
                useless = 0
            if ff is not None and useless >= FF_AFTER and ff_since is None:
                try:
                    ff(True)
                    ff_since = clock()
                except Exception:                    # noqa: BLE001 - no fast-forward here: keep pressing
                    ff = None
            key = menu[mi % len(menu)]
            mi += 1
            send([{"key": key, "down": True}])
            sleep(0.15)
            send([{"key": key, "down": False}])
            last_press = stats["menu_at"] = clock()
            sleep(1.0)
            stuck.reset()
            continue
        if ff_since is not None and stuck is not None and getattr(stuck, "changed", 0) > ff_since:
            ff_off()                                 # the screen moves again: normal speed
            useless = 0
        held, t = frozenset(), 0.0
        for dt, keys in style.next():
            if dt > t:
                sleep(dt - t)
                t = dt
            if stopped():
                break
            rows = diff(held, keys)
            if rows:
                send(rows)
            held = keys
        if held:
            send(diff(held, frozenset()))
        n += 1
        sleep(style.gap())
    ff_off()
    return n
