"""Learn PSO's menus and get faster at them.

`pso_menu_observer` recognises a screen from a frame and `next_key` picks one conservative press. That is correct but slow: one capture
round-trip per press. This module sits on top and learns:

* **transitions** - `(screen, key) -> screen`, recorded from real runs;
* **latency** - how long the game needs for a key to be reflected in the next screen, learned per edge and *shrunk* while
  verifications keep passing (`shrink`), re-lengthened on the first failure;
* **routes** - the shortest known key sequence between two screens (BFS over learned edges);
* **macros** - a whole route replayed as a burst: no capture between presses, one verification at the end. That is where the speedup
  comes from: a 12-press boot becomes 12 timed presses instead of 12 captures plus 12 presses.

Everything is deterministic and testable without a game: pass any `observe`/`press` pair, including a fake menu machine in the tests.
"""
from __future__ import annotations

import json
import time
from collections import deque
from pathlib import Path


class MenuLearnError(RuntimeError):
    pass


class TransitionGraph:
    """`(screen, key) -> screen` with a learned delay per edge, plus visit/failure counters."""

    def __init__(self, initial: float = 0.45, minimum: float = 0.03, maximum: float = 3.0):
        self.initial = float(initial)
        self.minimum = float(minimum)
        self.maximum = float(maximum)
        self.edges: dict[tuple[str, str], dict] = {}

    # ---------------------------------------------------------------- learning
    def edge(self, screen: str, key: str) -> dict:
        return self.edges.get((screen, key)) or {"delay": self.initial, "visits": 0, "failures": 0, "to": None}

    def record(self, screen: str, key: str, nxt: str, delay: float) -> dict:
        """A key at `screen` produced `nxt` after roughly `delay`; keep the smallest delay that has worked."""
        current = self.edge(screen, key)
        delay = max(self.minimum, min(self.maximum, float(delay)))
        if current["to"] is None:
            current = {"delay": delay, "visits": 1, "failures": 0, "to": nxt}
        elif current["to"] == nxt:
            current["delay"] = min(current["delay"], delay)     # the fastest success so far wins
            current["visits"] += 1
        else:                                                   # a different destination: keep the newest, note the change
            current = {"delay": delay, "visits": current["visits"] + 1, "failures": current["failures"], "to": nxt}
        self.edges[(screen, key)] = current
        return current

    def failed(self, screen: str, key: str, grew: float = 0.18) -> None:
        """A replay with this edge's delay did not reach the recorded screen: lengthen it."""
        current = self.edge(screen, key)
        current["failures"] += 1
        current["delay"] = min(self.maximum, current["delay"] + grew)
        self.edges[(screen, key)] = current

    def shrink(self, factor: float = 0.85) -> None:
        """Try to be faster: every learned edge loses `factor` of its delay, floored at the minimum."""
        for edge in self.edges.values():
            edge["delay"] = max(self.minimum, edge["delay"] * factor)

    # ---------------------------------------------------------------- planning
    def route(self, start: str, goal: str) -> list[str]:
        """The fewest learned key presses from `start` to `goal` (BFS); ValueError when unreachable."""
        if start == goal:
            return []
        seen = {start}
        queue = deque([(start, [])])
        while queue:
            screen, keys = queue.popleft()
            for (src, key), edge in self.edges.items():
                if src != screen or edge["to"] is None:
                    continue
                nxt = edge["to"]
                if nxt in seen:
                    continue
                if nxt == goal:
                    return keys + [key]
                seen.add(nxt)
                queue.append((nxt, keys + [key]))
        raise ValueError(f"no learned route from {start!r} to {goal!r}")

    def timings(self, start: str, keys: list[str]) -> list[float]:
        """The learned delay before each press of a route (from the start screen onward)."""
        out, screen = [], start
        for key in keys:
            out.append(self.edge(screen, key)["delay"])
            screen = self.edge(screen, key)["to"] or screen
        return out

    def known_screens(self) -> list[str]:
        out = set()
        for (screen, _key), edge in self.edges.items():
            out.add(screen)
            if edge["to"]:
                out.add(edge["to"])
        return sorted(out)

    # ---------------------------------------------------------------- persistence
    def as_dict(self) -> dict:
        return {"initial": self.initial, "minimum": self.minimum, "maximum": self.maximum,
                "edges": [{"from": s, "key": k, **v} for (s, k), v in self.edges.items()]}

    @classmethod
    def from_dict(cls, data: dict) -> "TransitionGraph":
        graph = cls(data.get("initial", 0.45), data.get("minimum", 0.03), data.get("maximum", 3.0))
        for row in data.get("edges") or []:
            graph.edges[(row["from"], row["key"])] = {"delay": row.get("delay", graph.initial),
                                                      "visits": row.get("visits", 0),
                                                      "failures": row.get("failures", 0),
                                                      "to": row.get("to")}
        return graph

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.as_dict(), indent=1), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: str | Path) -> "TransitionGraph":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


class MenuLearner:
    """Drive a menu with `press`, recognise screens with `observe`, learn the graph, replay it as a macro.

    `observe()` returns a screen id (a hash, a name from `pso_menu_observer`, anything hashable); `press(key)` sends one input.
    The learner only ever waits *between* presses, so a replay is one capture (the start) plus one verification (the end).
    """

    def __init__(self, observe, press, graph: TransitionGraph | None = None, *,
                 keys: tuple[str, ...] = ("start", "a", "b", "dup", "ddown", "dleft", "dright"),
                 settle: float = 0.45, now=time.monotonic, sleep=time.sleep):
        self.observe = observe
        self.press = press
        self.graph = graph or TransitionGraph()
        self.keys = tuple(keys)
        self.settle = float(settle)
        self._now = now
        self._sleep = sleep

    # ---------------------------------------------------------------- primitive
    def look(self) -> str:
        return str(self.observe())

    def step(self, key: str, *, settle: float | None = None) -> dict:
        """One learned press: observe, press, wait the edge's delay, observe, record."""
        before = self.look()
        want = self.graph.edge(before, key)["delay"] if (before, key) in self.graph.edges else (settle or self.settle)
        self.press(key)
        self._sleep(want)
        after = self.look()
        edge = self.graph.record(before, key, after, want) if after != before else None
        return {"from": before, "key": key, "to": after, "delay": want, "edge": edge}

    def play(self, keys: list[str], *, verify: str | None = None) -> dict:
        """Replay a key sequence as a macro: timed presses, then one verification.

        Each edge's learned delay is used, so a second run of the same route is faster than the first; `verify` is the screen the
        route must end on. A failed verification lengthens the edge where the run diverged and returns `ok: False`.
        """
        started = self._now()
        screen = self.look()
        start_screen = screen
        timings = self.graph.timings(screen, keys)
        for key, delay in zip(keys, timings):
            self.press(key)
            self._sleep(delay)
        ended = self._now()
        final = self.look() if verify is not None else self.look()
        ok = verify is None or final == verify
        if not ok:
            # blame the last edge of the route: the one whose delay most likely ran short
            for key in reversed(keys):
                if (start_screen, key) in self.graph.edges:
                    self.graph.failed(start_screen, key)
                    start_screen = self.graph.edges[(start_screen, key)]["to"] or start_screen
                    break
        return {"ok": ok, "seconds": ended - started, "from": screen, "to": final,
                "keys": list(keys), "delays": timings}

    # ---------------------------------------------------------------- learning
    def explore(self, rounds: int = 40, *, goal: str | None = None, rng=None) -> dict:
        """Try keys and record what they do until `goal` is reached (or `rounds` presses have been made)."""
        import random
        rng = rng or random.Random(1)
        presses = 0
        seen_goal = False
        while presses < rounds:
            screen = self.look()
            if goal is not None and screen == goal:
                seen_goal = True
                break
            key = rng.choice(self.keys)
            self.step(key)
            presses += 1
        return {"presses": presses, "screens": len(self.graph.known_screens()), "goal_reached": seen_goal}

    def learn_route(self, start: str, goal: str, *, rounds: int = 60) -> list[str]:
        """Explore until a route exists, then return it."""
        try:
            return self.graph.route(start, goal)
        except ValueError:
            pass
        self.explore(rounds=rounds, goal=goal)
        return self.graph.route(start, goal)

    def speed_run(self, keys: list[str], verify: str, *, runs: int = 5, shrink: float = 0.85) -> list[dict]:
        """Replay a route `runs` times, shrinking every edge between successful runs ("faster and faster")."""
        results = []
        for index in range(runs):
            result = self.play(keys, verify=verify)
            results.append(result)
            if result["ok"]:
                self.graph.shrink(shrink)
            else:
                self.graph.record  # noqa: B018  (the failure was already charged in play())
        return results
