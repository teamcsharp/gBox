"""Roulette: every demo shows a different cast (operator 2026-10-20: "any character that we have extracted, I want to see
randomly inserted into video games during demonstration sequences chosen at random via a roulette system ... mainly
focused on Sonic and Mario characters ... Dead or Alive with Grand Theft Auto pedestrians as the characters instead,
or Super Smash Bros characters").

Two halves:
  pick (demo_build): when a demo (the autoplay screensaver, gbox.screensaver) launches a game, it launches one of the
      game's built casts instead of the stock game. The operator's starred builds, roulette builds and Sonic / Mario
      casts weigh most; developer test builds (kind "file", *_test_*, *_chk, .tmp_*), broken ones and builds only one
      PC holds are left out. A game with no demo build plays stock.
  build (Builder.tick): a background cast build every BUILD_EVERY seconds. A target game (a favorite or a played game
      whose cast writer is routed and not marked in progress) x a donor pool (POOLS, weighted to Sonic and Mario) x a
      fresh seed, as one `characters op=cast_swap launch=false` job on the Linux control plane at low priority. At most
      MAX_PER_GAME roulette builds per game, one roulette job at a time, and a (game, pool) pair that failed FAIL_LIMIT
      times is not tried again. Each attempt is kept in the store (KIND) with its job and outcome. A game whose builds
      wait for the operator's build reports to be reviewed (gbox.build_feedback: 409 build_feedback_review_required)
      is blocked for BLOCK_TTL and shown with the report numbers; the roulette never acknowledges reports itself.
"""
from __future__ import annotations

import random
import re
import time

KIND = "roulette_build"                    # mod name -> {game_id, title, pool, seed, job, state, at, error}
ACTOR = "autoplay-roulette"
BUILD_EVERY = 10 * 60
MAX_PER_GAME = 3
FAIL_LIMIT = 2
TARGETS_TTL = 6 * 3600
BLOCK_TTL = 6 * 3600
GATES = ("build_feedback_review_required", "build_feedback_game_id_required")
ACTIVE = ("queued", "running", "claimed", "pending")
DONE_OK = ("succeeded", "completed", "done")

# (characters cast_swap source, assign, weight, label). Sources resolve through gbox.cast_swap.resolve_source (groups,
# game titles); "alternate" round-robins the comma-joined pools so a Sonic vs Mario cast stays even.
POOLS = (
    ("sonic,mario", "alternate", 8, "Sonic vs Mario"),
    ("sonic", "random", 4, "Sonic"),
    ("mario", "random", 4, "Mario"),
    ("Super Smash Bros. Melee (USA)", "random", 2, "Smash Bros. Melee"),
    ("Grand Theft Auto - Liberty City Stories", "random", 2, "GTA pedestrians"),
    ("Metal Gear Solid - The Twin Snakes", "random", 1, "MGS The Twin Snakes"),
    ("Metal Gear Solid 2: Substance (USA)", "random", 1, "MGS2"),
    ("Jet Grind Radio (USA)", "random", 1, "Jet Grind Radio"),
    ("wrestlers", "random", 1, "Wrestlers"),
    ("007 - Agent Under Fire (USA)", "random", 1, "007 Agent Under Fire"),
    ("Marvel vs. Capcom 2", "random", 1, "Marvel vs. Capcom 2"),
    ("John Woo Presents Stranglehold", "random", 1, "Stranglehold"),
    ("Final Fantasy VII (USA) (Disc 1)", "random", 1, "Final Fantasy VII"),
    ("Resident Evil 2 (USA)", "random", 1, "Resident Evil 2"),
)
TEST_BUILD = re.compile(r"(^\.tmp_|_test_|_test$|_chk$|_chk_|^test_)", re.I)
SONIC_MARIO = re.compile(r"sonic|mario|luigi|peach|wario|yoshi|bowser|tails|knuckles|shadow|amy|eggman|toad", re.I)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:24]


def demo_builds(builds: list[dict]) -> list[dict]:
    """The builds fit for a demo: built casts and character swaps the central collection holds, not test builds."""
    out = []
    for b in builds:
        name = str(b.get("name") or "")
        if not name or TEST_BUILD.search(name) or b.get("broken") or b.get("local_only"):
            continue
        if (b.get("kind") or "") == "file":
            continue
        out.append(b)
    return out


def weight(b: dict) -> float:
    text = " ".join(str(b.get(k) or "") for k in ("name", "label", "display_name", "summary"))
    w = 1.0
    if b.get("favorite"):
        w += 4
    if str(b.get("name", "")).startswith("roulette_"):
        w += 2
    if SONIC_MARIO.search(text):
        w += 3
    return w


def demo_build(builds: list[dict], rng: random.Random | None = None) -> dict | None:
    """One build for a demo of this game, weighted (weight()); None = play the stock game."""
    rng = rng or random.Random()
    ok = demo_builds(builds)
    if not ok:
        return None
    return rng.choices(ok, [weight(b) for b in ok])[0]


def writer_ok(game: dict) -> bool:
    """A cast swap can build for this game: its writer is routed and not marked in progress / not playable."""
    from . import char_coverage
    try:
        w = char_coverage.writer_for(game)
    except Exception:                                    # noqa: BLE001 - a writer that won't load is no target
        return False
    if not w or not w.get("routed"):
        return False
    what = str(w.get("replaces") or "").lower()
    return "in progress" not in what and "not playable" not in what


class Builder:
    """The background half: one roulette cast build at a time (see the module docstring)."""

    def __init__(self, store, submit, builds, candidates, rng: random.Random | None = None, clock=time.time):
        # submit(JobRequest-like dict) -> job; builds(game_id) -> [build]; candidates() -> [{game_id, title, favorite}]
        self.store, self.submit, self.builds, self.candidates = store, submit, builds, candidates
        self.rng, self.clock = rng or random.Random(), clock
        self.last_submit = 0.0
        self._targets: list[dict] = []
        self._targets_at = 0.0

    def records(self) -> list[dict]:
        return self.store.all(KIND)

    def _refresh(self) -> list[dict]:
        """Bring each unfinished attempt's state up to date from its job."""
        busy = []
        for r in self.records():
            if r.get("state") not in ACTIVE:
                continue
            job = self.store.get("job", r.get("job", "")) or {}
            st = job.get("state") or r.get("state")
            if st in ACTIVE:
                busy.append(r)
                continue
            upd = {"state": "built" if st in DONE_OK else "failed", "ended": self.clock()}
            if st not in DONE_OK:
                upd["error"] = str(job.get("error") or st or "unknown")[:300]
            self.store.put(KIND, r["mod"], r | upd)
        return busy

    def targets(self) -> list[dict]:
        now = self.clock()
        if not self._targets or now - self._targets_at > TARGETS_TTL:
            out = []
            for c in self.candidates():
                game = self.store.catalog_get(c["game_id"])
                if game and writer_ok(game):
                    out.append(c | {"title": game.get("title") or c.get("title") or c["game_id"]})
            self._targets, self._targets_at = out, now
        return self._targets

    def failures(self) -> dict[tuple, int]:
        out: dict[tuple, int] = {}
        for r in self.records():
            if r.get("state") == "failed":
                out[(r.get("game_id"), r.get("pool"))] = out.get((r.get("game_id"), r.get("pool")), 0) + 1
        return out

    def blocked(self) -> dict[str, dict]:
        """Games whose builds wait for the operator's reports to be reviewed (newer than BLOCK_TTL)."""
        now = self.clock()
        return {r["game_id"]: r for r in self.records()
                if r.get("state") == "blocked" and now - (r.get("at") or 0) < BLOCK_TTL}

    def plan(self) -> dict | None:
        """The next build: {game_id, title, pool, assign, label, seed, mod} or None when nothing is left to build."""
        blocked = self.blocked()
        targets = [t for t in self.targets() if t["game_id"] not in blocked]
        if not targets:
            return None
        fails = self.failures()
        have: dict[str, int] = {}
        for r in self.records():
            if r.get("state") in ACTIVE or r.get("state") == "built":
                have[r["game_id"]] = have.get(r["game_id"], 0) + 1
        open_ = [t for t in targets if have.get(t["game_id"], 0) < MAX_PER_GAME]
        if not open_:
            return None
        t = self.rng.choices(open_, [(3 if t.get("favorite") else 1) / (1 + have.get(t["game_id"], 0))
                                     for t in open_])[0]
        pools = [p for p in POOLS if fails.get((t["game_id"], p[0]), 0) < FAIL_LIMIT]
        if not pools:
            return None
        spec, assign, _w, label = self.rng.choices(pools, [p[2] for p in pools])[0]
        seed = f"{self.rng.randrange(16 ** 6):06x}"
        return {"game_id": t["game_id"], "title": t["title"], "pool": spec, "assign": assign, "label": label,
                "seed": seed, "mod": f"roulette_{slug(label)}_{seed}"}

    def tick(self, enabled: bool = True) -> str:
        busy = self._refresh()
        if busy:
            r = busy[0]
            return f"building {r['label']} in {r['title']}"
        if not enabled:
            return "off"
        if self.clock() - self.last_submit < BUILD_EVERY:
            return "waiting"
        p = self.plan()
        if p is None:
            return "every target has its roulette builds"
        try:
            job = self.submit({"tool": "characters", "input": {
                "op": "cast_swap", "target_game": p["game_id"], "source": p["pool"], "assign": p["assign"],
                "seed": p["seed"], "slots": "all", "mod_name": p["mod"], "launch": False,
                "title": f"Roulette: {p['label']} in {p['title']}"}})
        except Exception as e:                           # noqa: BLE001 - refused at submit (HTTPException from the server)
            self.last_submit = self.clock()
            detail = getattr(e, "detail", None)
            if isinstance(detail, dict) and detail.get("code") in GATES:
                reports = [f.get("number") for f in detail.get("feedback") or [] if f.get("number")]
                key = f"blocked:{p['game_id']}"
                self.store.put(KIND, key, {"mod": key, "game_id": p["game_id"], "title": p["title"], "state": "blocked",
                                           "reports": reports, "error": str(detail.get("message") or detail["code"])[:300],
                                           "at": self.last_submit})
                return f"{p['title']}: review the operator's build reports first ({', '.join(f'#{n}' for n in reports)})"
            self.store.put(KIND, p["mod"], p | {"state": "failed", "error": f"{type(e).__name__}: {e}"[:300],
                                                "at": self.last_submit})
            return f"could not queue {p['label']} in {p['title']}"
        jid = getattr(job, "id", None) or (job.get("id") if isinstance(job, dict) else "") or ""
        state = getattr(job, "state", None) or (job.get("state") if isinstance(job, dict) else "") or "queued"
        self.last_submit = self.clock()
        row = p | {"job": jid, "state": "failed" if state == "rejected" else "queued", "at": self.last_submit}
        if state == "rejected":
            row["error"] = str(getattr(job, "error", None) or (job.get("error") if isinstance(job, dict) else "") or "rejected")[:300]
        self.store.put(KIND, p["mod"], row)
        return f"queued {p['label']} in {p['title']}"

    def status(self) -> dict:
        rows = sorted(self.records(), key=lambda r: -(r.get("at") or 0))
        return {"recent": [{k: r.get(k) for k in ("mod", "title", "label", "state", "error", "at")} for r in rows[:12]],
                "built": sum(r.get("state") == "built" for r in rows), "failed": sum(r.get("state") == "failed" for r in rows),
                "blocked": [{"game_id": r["game_id"], "title": r.get("title"), "reports": r.get("reports") or []}
                            for r in self.blocked().values()]}
