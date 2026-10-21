"""Autoplay primitives (plan §9-10, Phase 3) over the public gBox API, so the agent, UI and scripts share them.

Deterministic parts live here (input driver, navigation, combat loop, run recording); the LLM plans with them.
Navigation is closed-loop on verified semantic state: the camera direction isn't known, so the controller learns the
world heading of the "up" input from how the player actually moves and keeps correcting it as the camera turns.
"""
import json
import math
import time
from pathlib import Path

import httpx

DIRS = [("up",), ("up", "right"), ("right",), ("down", "right"), ("down",), ("down", "left"), ("left",), ("up", "left")]


def angdiff(a: float, b: float) -> float:
    """Signed smallest difference a-b in degrees (-180, 180]."""
    return (a - b + 180) % 360 - 180


class Driver:
    def __init__(self, server: str, token: str, session_id: str, log=print):
        self.api = httpx.Client(base_url=server, headers={"authorization": f"Bearer {token}", "x-gbox-actor": "autoplay"}, timeout=30)
        self.sid, self.log = session_id, log
        self.cam = None          # world heading (deg) the "up" input currently moves the player
        self.sign = None         # +1: "right" is clockwise from "up" in world heading terms
        self.trace: list[dict] = []
        self.stopped = False     # set by the operator (autoplay op=stop / F3): the next game action aborts the mission

    # --- io ---
    def rpc(self, op, **args):
        if self.stopped:
            raise RuntimeError("autoplay stopped by the operator")
        for attempt in range(8):                           # hiccups under load (busy Spark -> 504) are transient
            try:
                r = self.api.post(f"/api/sessions/{self.sid}/rpc", json={"op": op, "args": args})
            except httpx.TransportError:
                time.sleep(1 + attempt); continue
            if r.status_code == 200:
                return r.json()
            time.sleep(0.5 + attempt)
        r.raise_for_status()

    def state(self) -> dict:
        return self.rpc("state")

    def player(self) -> dict:
        p = self.rpc("state", player_only=True)["player"]     # one entity read: movement loops poll this a lot
        if p is None:
            raise RuntimeError("no player in semantic state")
        return p

    def keys(self, keys, down: bool):
        self.api.post(f"/api/sessions/{self.sid}/input", json={"events": [{"key": k, "down": down} for k in keys]})

    def hold(self, keys, secs: float):
        self.keys(keys, True)
        time.sleep(secs)
        self.keys(keys, False)

    def press(self, key, n=1, gap=0.35):
        for _ in range(n):
            self.hold([key], 0.12)
            time.sleep(gap)

    def _hold_hp(self):
        """Autoplay assist (opt-in): hold the player's HP at max for this run (same mechanism as the infinite-life cheat).
        Returns a release()."""
        p = self.player()
        hp_off = 0x330                                            # profile field "hp" (u16) for PSO DC/GC players
        addr, val = int(p["ptr"], 16) + hp_off, int(p.get("hp_max") or p.get("hp") or 1)
        end = "little" if self.platform_little() else "big"

        def job(enabled):
            j = self.api.post("/api/jobs", json={"tool": "freeze_memory", "input": {"session_id": self.sid, "address": addr,
                              "hex_bytes": val.to_bytes(2, end).hex(), "enabled": enabled}, "require_worker": self.sid.split("-")[0]}).json()
            for _ in range(60):
                if j.get("state") not in ("queued", "running"):
                    break
                time.sleep(0.5)
                j = self.api.get(f"/api/jobs/{j['id']}").json()
            return j
        job(True)
        self.trace.append({"t": time.time(), "assist": "hold_hp", "address": hex(addr), "value": val})
        return lambda: job(False)

    def platform_little(self) -> bool:
        try:
            s = next(x for x in self.api.get("/api/sessions", params={"include_ended": "false"}).json()   # the running
                     if x["session_id"] == self.sid)                 # ones: the full list took minutes under load
            return (s.get("platform") or s.get("detail", {}).get("platform") or "dreamcast") not in ("gamecube", "wii", "ps3", "n64")
        except Exception:
            return True

    def frame(self):
        """One screen frame (PIL image) from the session's live stream."""
        from io import BytesIO
        from PIL import Image
        with self.api.stream("GET", f"/api/sessions/{self.sid}/mjpeg", timeout=20) as r:
            buf = b""
            for ch in r.iter_bytes():
                buf += ch
                a = buf.find(b"\xff\xd8")
                b = buf.find(b"\xff\xd9", a + 2)
                if a >= 0 and b > 0:
                    return Image.open(BytesIO(buf[a:b + 2])).convert("L")

    def dialog_open(self) -> bool:
        """PSO's talk/info box: a large white panel in the upper middle of the screen (game UI, not world)."""
        try:
            im = self.frame()
            w, h = im.size
            box = im.crop((int(w * .2), int(h * .24), int(w * .72), int(h * .36)))
            px = list(box.getdata())
            return sum(v > 225 for v in px) > 0.55 * len(px)
        except Exception:
            return False

    # --- navigation ---
    def dirs(self, k: int):
        """Movement keys for direction k; analog=True drives the left stick (lup/ldown/...) instead of the d-pad."""
        return tuple("l" + d for d in DIRS[k]) if getattr(self, "analog", False) else DIRS[k]

    def _move(self, k: int, secs: float):
        a = self.player()
        self.hold(self.dirs(k), secs)
        time.sleep(0.12)
        b = self.player()
        dx, dz = b["x"] - a["x"], b["z"] - a["z"]
        dist = math.hypot(dx, dz)
        self.trace.append({"t": time.time(), "keys": DIRS[k], "secs": secs, "from": [a["x"], a["z"]], "to": [b["x"], b["z"]],
                           "room": b.get("room")})
        return b, (math.degrees(math.atan2(dx, dz)) % 360 if dist > 1.0 else None), dist

    def goto(self, x: float, z: float, radius: float = 12.0, timeout: float = 90.0, stuck_limit: int = 9) -> dict:
        """Walk the player to (x, z). Returns {"ok", "dist", "steps"}; stops early if stuck repeatedly."""
        t0, stuck, steps = time.time(), 0, 0
        while time.time() - t0 < timeout:
            p = self.player()
            dx, dz = x - p["x"], z - p["z"]
            dist = math.hypot(dx, dz)
            if dist <= radius:
                return {"ok": True, "dist": round(dist, 1), "steps": steps, "pos": [p["x"], p["z"]]}
            bearing = math.degrees(math.atan2(dx, dz)) % 360
            if getattr(self, "cam_reset", None):               # camera snaps behind the player: forward = facing
                self.hold([self.cam_reset], 0.1)
                time.sleep(0.25)
                p = self.player()
                if "heading_deg" in p:
                    self.cam = p["heading_deg"]
                    if self.sign is None and getattr(self, "right_sign", None):
                        self.sign = self.right_sign                 # known handedness: no probing needed
            if self.cam is None or self.sign is None:          # learn camera yaw + handedness from two moves
                self._learn = getattr(self, "_learn", 0) + 1     # (rotating the probe direction if one is walled off)
                k1 = (2 * self._learn) % 8
                _, h1, _ = self._move(k1, 0.4)
                _, h2, _ = self._move((k1 + 2) % 8, 0.4)
                if h1 is not None and h2 is not None:
                    self.sign = 1 if angdiff(h2, h1) > 0 else -1
                    self.cam = (h2 - self.sign * 45 * ((k1 + 2) % 8)) % 360
                continue
            k = round(self.sign * angdiff(bearing, self.cam) / 45) % 8
            secs = max(0.35, min(0.6, dist / 70))          # shorter holds mostly turn the character in place
            _, h, moved = self._move(k, secs)
            steps += 1
            if h is not None:
                obs = (h - self.sign * 45 * k) % 360             # camera estimate implied by this move
                self.cam = (self.cam + 0.6 * angdiff(obs, self.cam)) % 360
            if moved < 1.0:
                stuck += 1
                if stuck >= 2 and getattr(self, "talk_key", None) and self.dialog_open():   # frozen by a dialog: advance it
                    for _ in range(6):
                        self.hold([self.talk_key], 0.1); time.sleep(0.6)
                        if not self.dialog_open():
                            break
                if stuck >= 3:                                  # blocked: sidestep, then try again
                    self._move((k + 2 * (1 if stuck % 2 else -1)) % 8, 0.5)
                if stuck >= stuck_limit:
                    return {"ok": False, "dist": round(dist, 1), "steps": steps, "reason": "stuck", "pos": [p["x"], p["z"]]}
            else:
                stuck = 0
        return {"ok": False, "dist": round(dist, 1), "steps": steps, "reason": "timeout"}

    def navigate(self, x: float, z: float, navmap: "NavMap", radius: float = 12.0, max_legs: int = 80) -> dict:
        """Path-planned walk: A* over the learned grid (unknown = open), mark edges that fail as blocked, replan.
        Every successful step records walkable cells, so the map (room graph) improves with each run."""
        for leg in range(max_legs):
            p = self.player()
            if math.hypot(x - p["x"], z - p["z"]) <= radius:
                navmap.save()
                return {"ok": True, "legs": leg, "pos": [p["x"], p["z"]]}
            start, goal = navmap.cell(p["x"], p["z"]), navmap.cell(x, z)
            path = navmap.astar(start, goal)
            if not path:
                navmap.save()
                return {"ok": False, "reason": "no path left (all routes blocked)", "pos": [p["x"], p["z"]]}
            # walk to the furthest cell of the first straight run (max 4 cells)
            run = 1
            while run < min(4, len(path) - 1) and (path[run + 1][0] - path[run][0], path[run + 1][1] - path[run][1]) ==                     (path[1][0] - path[0][0], path[1][1] - path[0][1]):
                run += 1
            run = min(len(path) - 1, max(run, 2))          # aim >= 2 cells ahead: the next cell's centre can already be "reached"
            tx, tz = navmap.center(path[run]) if path[run] != goal else (x, z)
            r = self.goto(tx, tz, radius=navmap.size * 0.45, timeout=20, stuck_limit=3)
            q = self.player()
            now = navmap.cell(q["x"], q["z"])
            if getattr(self, "verbose", False):
                self.log(f"leg {leg}: {start}->{path[run]} via {len(path)} cells; now {now} ({q['x']:.0f},{q['z']:.0f}) {r.get('reason', 'ok')}")
            for t in self.trace[-6:]:
                navmap.walked(t["from"], t["to"])
            if not r["ok"] and now == start:
                navmap.block(start, path[1])               # no progress at all along this edge
        navmap.save()
        return {"ok": False, "reason": "too many legs"}

    def guardian(self, heal_key, heals: int, below: float = 0.5):
        """Background HP watch: use a healing item the moment HP drops under `below` of max, whatever the main loop is
        doing (a combo + facing can take seconds under load; packs do more damage than that). Returns a stop()."""
        import threading
        stop, left = threading.Event(), [heals]
        self.guard_left = left                                   # the fight loop reads this to know heals remain

        def run():
            while not stop.is_set() and left[0] > 0 and not self.stopped:
                try:
                    p = self.rpc("state", player_only=True)["player"] or {}
                    if p.get("hp_max") and 0 < p["hp"] < below * p["hp_max"] + 6:   # +6: react a hit earlier
                        self.hold([heal_key], 0.12)
                        stop.wait(2.5)                            # item animation; a hit can cancel it
                        after = (self.rpc("state", player_only=True)["player"] or {}).get("hp", 0)
                        if after > p["hp"]:
                            left[0] -= 1                          # only a heal that worked uses up an item
                        self.trace.append({"t": time.time(), "heal": heal_key, "hp_before": p["hp"], "hp_after": after})
                        continue
                except Exception:
                    pass
                stop.wait(0.4)
        threading.Thread(target=run, daemon=True).start()
        return stop.set

    # --- exploring a floor without a scripted route ---
    def explore(self, kills_goal: int = 6, timeout: float = 420.0, radius: float = 220.0, cache_dir=".", heal_key=None, heals=0,
                navmap=None) -> dict:
        """Fight whatever is near; otherwise walk to the nearest door/gate not visited yet (A* that learns blocked cells),
        so the run moves through the floor and wakes the next spawn. Works on any floor the semantic profile reads."""
        t0, kills, visited, legs = time.time(), 0, set(), 0
        nav = navmap or NavMap(Path(cache_dir) / "nav-explore.json", 10.0)   # real collision floor when the mission has one
        stop_guard = self.guardian(heal_key, heals) if heal_key and heals else (lambda: None)
        heals = 0                                                 # the guardian owns the healing items now
        try:
            return self._explore(t0, kills, visited, legs, nav, kills_goal, timeout, radius, heal_key, heals)
        finally:
            stop_guard()

    def _explore(self, t0, kills, visited, legs, nav, kills_goal, timeout, radius, heal_key, heals):
        while time.time() - t0 < timeout and kills < kills_goal:
            st = self.state()
            p = next(e for e in st["entities"] if e["kind"] == "player")
            if heal_key and heals > 0 and p.get("hp_max") and p["hp"] < 0.5 * p["hp_max"]:   # heal between fights too
                self.hold([heal_key], 0.12); heals -= 1; time.sleep(1.2)
                continue
            if time.time() - getattr(self, "ignore_t", 0) > 25:
                self.ignore = set()                              # fences open as rooms clear: look again
            near = [e for e in self.enemies(st) if math.hypot(e["x"] - p["x"], e["z"] - p["z"]) < radius
                    and e["entity_id"] not in getattr(self, "ignore", set())]
            if near:
                r = self.fight(radius=radius, timeout=90, wave_wait=2.0, heal_key=heal_key, heals=heals)
                kills += r.get("kills", 0)
                if r.get("reason") == "low hp":
                    return {"ok": kills > 0, "kills": kills, "reason": "low hp", "legs": legs}
                if r.get("reason") == "behind gate":
                    self.ignore, self.ignore_t = set(r["blocked"]), time.time()
                else:
                    continue
            gates = sorted((e for e in st["entities"] if e["kind"] == "gate" and e["entity_id"] not in visited),
                           key=lambda e: math.hypot(e["x"] - p["x"], e["z"] - p["z"]))
            if not gates:
                break
            g = gates[0]
            visited.add(g["entity_id"])
            r = self.navigate(g["x"], g["z"], nav, radius=30)
            legs += 1
        return {"ok": kills > 0, "kills": kills, "legs": legs, "secs": round(time.time() - t0, 1)}

    def face(self, x: float, z: float, tol: float = 22.0, tries: int = 5) -> bool:
        """Turn toward (x, z) and confirm it from the game's own heading (RAM heading_deg == movement bearing). With the
        camera recentred behind the player (camera_reset_key), up = forward, left = +heading, right = -heading."""
        for _ in range(tries):
            p = self.player()
            want = math.degrees(math.atan2(x - p["x"], z - p["z"])) % 360
            off = (want - (p.get("heading_deg") or 0) + 540) % 360 - 180       # -180..180, + = turn left
            if abs(off) <= tol:
                return True
            if getattr(self, "cam_reset", None):
                self.hold([self.cam_reset], 0.08); time.sleep(0.25)
            k = round(off / 45)                                   # -4..4 in 45 degree steps
            keys = {0: ["lup"], 1: ["lup", "lleft"], 2: ["lleft"], 3: ["ldown", "lleft"], 4: ["ldown"], -4: ["ldown"],
                    -1: ["lup", "lright"], -2: ["lright"], -3: ["ldown", "lright"]}[k]
            if not getattr(self, "analog", False):
                keys = [k_[1:] for k_ in keys]
            self.hold(keys, 0.12)
            time.sleep(0.2)
        return False

    # --- combat ---
    @staticmethod
    def _seg_dist(p, a, b):
        ax, az, bx, bz = a["x"], a["z"], b["x"], b["z"]
        dx, dz = bx - ax, bz - az
        t = max(0.0, min(1.0, ((p["x"] - ax) * dx + (p["z"] - az) * dz) / ((dx * dx + dz * dz) or 1)))
        return math.hypot(p["x"] - (ax + t * dx), p["z"] - (az + t * dz))

    def behind_gate(self, st, p, e, clearance: float = 28.0) -> bool:
        """Is a door / laser fence between the player and this enemy? (melee can't reach through it)"""
        return any(self._seg_dist(g, p, e) < clearance and math.hypot(g["x"] - e["x"], g["z"] - e["z"]) > 6
                   for g in st["entities"] if g["kind"] == "gate")

    def enemies(self, st=None, alive=True) -> list[dict]:
        st = st or self.state()
        return [e for e in st["entities"] if e["kind"] == "enemy" and (not alive or e.get("hp", 1) > 0)]

    def fight(self, radius: float = 400.0, timeout: float = 120.0, attack=None, reach: float = 15.0,
              min_hp_frac: float = 0.25, wave_wait: float = 4.0, heal_key: str | None = None,
              heal_below: float = 0.5, heals: int = 0) -> dict:
        """Melee loop: nearest live enemy within `radius` -> close in -> face it -> 3-hit combo; repeat.
        Stops when none are left, on timeout, or when the player's HP drops below min_hp_frac (retreat signal)."""
        attack = attack or getattr(self, "attack_key", "a")
        reach = getattr(self, "reach", None) or reach               # per game: PSO enemies are big (centre-to-centre ~25-30)      # Flycast: RetroPad "b" is the Dreamcast A (attack) button
        t0, hits, kills, swings = time.time(), 0, set(), 0
        start_hp = self.player().get("hp")
        while time.time() - t0 < timeout:
            st = self.state()
            p = st["player"]
            if heal_key and heals > 0 and p.get("hp_max") and p["hp"] < heal_below * p["hp_max"]:
                # getting hit cancels item use: step away from the nearest enemy first, then heal and check it worked
                near = min(self.enemies(st) or [p], key=lambda e: math.hypot(e["x"] - p["x"], e["z"] - p["z"]))
                if near is not p and self.cam is not None and self.sign is not None:
                    away = math.degrees(math.atan2(p["x"] - near["x"], p["z"] - near["z"])) % 360
                    self.hold(self.dirs(round(self.sign * angdiff(away, self.cam) / 45) % 8), 0.8)
                self.hold([heal_key], 0.12)                      # healing item on the action palette
                heals -= 1
                time.sleep(1.5)
                after = self.player().get("hp")
                self.trace.append({"t": time.time(), "heal": heal_key, "hp_before": p["hp"], "hp_after": after})
                continue
            if p.get("hp_max") and p["hp"] < min_hp_frac * p["hp_max"]:
                if getattr(self, "guard_left", [0])[0] > 0 and p["hp"] > 0:    # guardian still has heals: back off, let it heal
                    near = min(self.enemies(st) or [p], key=lambda e: math.hypot(e["x"] - p["x"], e["z"] - p["z"]))
                    if near is not p:
                        self.goto(p["x"] * 2 - near["x"], p["z"] * 2 - near["z"], radius=5, timeout=1.5, stuck_limit=1)
                    time.sleep(1.0)
                    continue
                return {"ok": False, "reason": "low hp", "kills": len(kills), "swings": swings, "hp": p["hp"]}
            near = [e for e in self.enemies(st) if math.hypot(e["x"] - p["x"], e["z"] - p["z"]) <= radius]
            nodmg = getattr(self, "nodmg", {})                   # enemy -> (misses, since): skip only when hits proved useless
            alive = [e for e in near if math.hypot(e["x"] - p["x"], e["z"] - p["z"]) <= reach * 1.3      # in melee range: always fight back
                     or not (nodmg.get(e["entity_id"], (0, 0))[0] >= 2 and time.time() - nodmg[e["entity_id"]][1] < 20)]
            if near and not alive:                              # all behind fences/doors: let explore route around
                return {"ok": False, "reason": "behind gate", "kills": len(kills), "swings": swings,
                        "blocked": [e["entity_id"] for e in near]}
            for e in self.enemies(st, alive=False):
                if e.get("hp") == 0:
                    kills.add(e["entity_id"])
            if not alive:
                if not getattr(self, "_settled", False):          # waves come in sequence: give the next one a moment
                    self._settled = True
                    time.sleep(wave_wait)
                    continue
                self._settled = False
                return {"ok": True, "kills": len(kills), "swings": swings, "secs": round(time.time() - t0, 1),
                        "damage_taken": (start_hp or 0) - p.get("hp", 0)}
            self._settled = False
            close = [e for e in alive if math.hypot(e["x"] - p["x"], e["z"] - p["z"]) <= reach * 1.6]
            tgt = (min(close, key=lambda e: (e.get("hp") or 0)) if close     # finish the weakest one in reach first
                   else min(alive, key=lambda e: math.hypot(e["x"] - p["x"], e["z"] - p["z"])))
            dist = math.hypot(tgt["x"] - p["x"], tgt["z"] - p["z"])
            if dist > reach:
                self.goto(tgt["x"], tgt["z"], radius=reach * 0.8, timeout=4, stuck_limit=3)
                q = self.player()
                now = math.hypot(tgt["x"] - q["x"], tgt["z"] - q["z"])
                self.nodmg = getattr(self, "nodmg", {})
                if now > dist - 3:                                # no closer: fence / wall between us -> unreachable for now
                    m = self.nodmg.get(tgt["entity_id"], (0, 0))[0] + 1
                    self.nodmg[tgt["entity_id"]] = (m, time.time())
                continue
            # face it (verified against the game's heading), then a 3-hit combo
            self.face(tgt["x"], tgt["z"])
            before = tgt.get("hp")
            combo = getattr(self, "combo", 3)
            for _ in range(combo):                                # timing measured to land (0.08 s taps get dropped under load)
                self.hold([attack], 0.12)
                time.sleep(0.45)
            swings += combo
            if getattr(self, "kite", False):                      # hit-and-retreat: step out of reach before they swing back
                q = self.player()
                self.goto(q["x"] * 2 - tgt["x"], q["z"] * 2 - tgt["z"], radius=4, timeout=0.9, stuck_limit=1)
            after = next((e.get("hp") for e in self.enemies(alive=False) if e["entity_id"] == tgt["entity_id"]), 0)
            self.nodmg = getattr(self, "nodmg", {})
            if before is not None and after == before:          # nothing landed: behind a fence / wall?
                m = self.nodmg.get(tgt["entity_id"], (0, 0))[0] + 1
                self.nodmg[tgt["entity_id"]] = (m, time.time())
            else:
                self.nodmg.pop(tgt["entity_id"], None)
            if before is not None and after is not None and after < before:
                hits += 1
            if after == 0:                                        # dead (or despawned after dying)
                kills.add(tgt["entity_id"])
            self.trace.append({"t": time.time(), "attack": tgt["entity_id"], "class": tgt.get("class"),
                               "hp_before": before, "hp_after": after})
        return {"ok": False, "reason": "timeout", "kills": len(kills), "swings": swings}

    def _session_op(self, op) -> dict:
        j = self.api.post("/api/jobs", json={"tool": "session_op", "input": {"session_id": self.sid, "op": op},
                                             "require_worker": self.sid.split("-")[0]}).json()   # session ids = <worker>-<job>
        for _ in range(120):
            if j.get("state") not in ("queued", "running"):
                break
            time.sleep(0.5)
            j = self.api.get(f"/api/jobs/{j['id']}").json()
        return (j.get("output") or {}).get("result") or {}

    # --- missions (deterministic executor for plans an LLM or a human writes) ---
    def load_navmap(self, spec: dict, cache_dir) -> "NavMap":
        """spec: {"rel_artifact": sha256 of a PSO c.rel, "be": true, "size": 10}; cached as JSON next to the runner."""
        from pathlib import Path
        from . import psomap
        path = Path(cache_dir) / f"nav-{spec['rel_artifact'][:16]}.json"
        if path.exists():
            return NavMap(path)
        data = self.api.get(f"/api/artifacts/{spec['rel_artifact']}").content
        fl, wl = psomap.walkable_cells(psomap.collision(data, spec.get("be", True)), spec.get("size", 10))
        m = NavMap.from_geometry(path, fl, wl, spec.get("size", 10))
        m.save()
        return m

    def run_mission(self, mission: dict, cache_dir=".", record: bool = True) -> dict:
        """Execute mission["steps"]; returns metrics. Steps: navigate {to:[x,z], radius}, interact {at:[x,z]},
        fight {radius, timeout}, press {key, n}, wait {secs}. Stops at the first failed step."""
        navmap = self.load_navmap(mission["map"], cache_dir) if mission.get("map") else None
        self.analog = mission.get("move") == "analog"
        self.attack_key = mission.get("attack_key", "a")
        self.talk_key = mission.get("interact_key")
        self.reach = mission.get("reach")
        assist = self._hold_hp() if mission.get("assist_hold_hp") or getattr(self, "assist_hold_hp", False) else None
        self._assist_release = assist
        self.combo, self.kite = mission.get("combo", 3), mission.get("kite", False)
        self.cam_reset = mission.get("camera_reset_key")         # e.g. PSO: L trigger re-centres the camera
        self.right_sign = mission.get("right_sign")              # +1/-1: "right" is clockwise/counter-clockwise in heading
        if mission.get("record"):
            self._session_op("record_start")
        t0, log, kills, ok = time.time(), [], 0, True
        hp0 = self.player().get("hp")
        self.trace = []
        for i, st in enumerate(mission["steps"]):
            ts, op = time.time(), st["op"]
            if op == "navigate":
                r = self.navigate(*st["to"], navmap, radius=st.get("radius", 12)) if navmap else                     self.goto(*st["to"], radius=st.get("radius", 12), timeout=st.get("timeout", 90))
            elif op == "interact":
                r = self.navigate(*st["at"], navmap, radius=st.get("radius", 20)) if navmap else                     self.goto(*st["at"], radius=st.get("radius", 20), timeout=st.get("timeout", 90))
                if not r["ok"] and not navmap and r.get("reason") == "stuck":     # something in the way (an NPC, a desk):
                    learn = NavMap(Path(cache_dir) / f"nav-{mission['name']}-{i}-{int(time.time())}.json", 10.0)   # fresh each run: stale blocks lie   # route around it, learning blocks
                    r = self.navigate(*st["at"], learn, radius=st.get("radius", 20))
                if r["ok"]:
                    self.press(st.get("key", mission.get("interact_key", "a")))
                    time.sleep(st.get("settle", 1.5))
            elif op == "explore":
                r = self.explore(kills_goal=st.get("kills", 6), timeout=st.get("timeout", 420), radius=st.get("radius", 220),
                                 cache_dir=cache_dir, heal_key=st.get("heal_key"), heals=st.get("heals", 0), navmap=navmap)
                kills += r.get("kills", 0)
            elif op == "fight":
                r = self.fight(radius=st.get("radius", 300), timeout=st.get("timeout", 120), wave_wait=st.get("wave_wait", 4.0),
                               heal_key=st.get("heal_key"), heal_below=st.get("heal_below", 0.5), heals=st.get("heals", 0))
                kills += r.get("kills", 0)
            elif op == "press":
                self.press(st["key"], st.get("n", 1))
                r = {"ok": True}
            elif op == "wait":
                time.sleep(st["secs"])
                r = {"ok": True}
            else:
                r = {"ok": False, "reason": f"unknown op {op}"}
            log.append({"i": i, "op": op, "args": {k: v for k, v in st.items() if k != "op"}, "result": r,
                        "secs": round(time.time() - ts, 1)})
            self.log(f"step {i} {op}: {r}")
            if not r.get("ok") and not st.get("optional"):
                ok = False
                break
        p = self.player()
        metrics = {"success": 1.0 if ok else 0.0, "secs": round(time.time() - t0, 1), "steps_done": float(len(log)),
                   "kills": float(kills), "damage_taken": float((hp0 or 0) - p.get("hp", 0)), "hp_end": float(p.get("hp", 0))}
        out = {"ok": ok, "metrics": metrics, "steps": log}
        video = self._session_op("record_stop").get("artifact") if mission.get("record") else None
        if video:
            out["video"] = video
        if record:
            trace = json.dumps({"mission": mission, "steps": log, "trace": self.trace}).encode()
            ref = self.api.post("/api/artifacts", content=trace, params={
                "name": f"run-{mission.get('name', 'mission')}.json", "media_type": "application/json",
                "provenance": json.dumps({"session": self.sid, "mission": mission.get("name")})}).json()
            run = self.api.post("/api/runs", json={
                "game_id": mission.get("game_id", "unknown"), "objective": mission.get("objective", mission.get("name", "")),
                "initial_state": mission.get("initial_state"), "policy_version": mission.get("policy", "autoplay-v1"),
                "proposer": "autoplay", "outcome": "success" if ok else f"failed at step {len(log) - 1}",
                "metrics": metrics, "artifacts": [ref["sha256"]] + ([video] if video else []), "cost_s": metrics["secs"]}).json()
            out["run_id"], out["trace_artifact"] = run.get("id"), ref["sha256"]
        if assist:
            assist()
            self._assist_release = None
        return out

    def follow(self, waypoints: list[tuple[float, float]], radius=12.0) -> dict:
        for i, (x, z) in enumerate(waypoints):
            r = self.goto(x, z, radius)
            self.log(f"waypoint {i} ({x:.0f},{z:.0f}): {r}")
            if not r["ok"]:
                return r | {"waypoint": i}
        return {"ok": True, "waypoints": len(waypoints)}


class NavMap:
    """Learned walkability grid for one floor of one game (plan: room graph / navigation knowledge).
    Saved as JSON so later runs (and other sessions) reuse what earlier runs discovered."""
    def __init__(self, path, size: float = 10.0):
        from pathlib import Path
        self.path, self.size = Path(path), size
        self.walk: set = set()
        self.blocked: set = set()
        self.closed = False                # True when walkability comes from real level geometry (only walk known floor)
        if self.path.exists():
            d = json.loads(self.path.read_text())
            self.size = d["size"]
            self.walk = {tuple(c) for c in d["walk"]}
            self.blocked = {(tuple(a), tuple(b)) for a, b in d["blocked"]}
            self.closed = d.get("closed", False)

    @classmethod
    def from_geometry(cls, path, floor_cells: set, wall_cells: set, size: float):
        """Navigation grid from collision geometry: floor minus walls (plus a one-cell margin off walls)."""
        m = cls(path, size)
        m.walk = {c for c in floor_cells if c not in wall_cells} or set(floor_cells)
        m.closed = True
        return m

    def cell(self, x, z):
        return (int(math.floor(x / self.size)), int(math.floor(z / self.size)))

    def center(self, c):
        return ((c[0] + 0.5) * self.size, (c[1] + 0.5) * self.size)

    def walked(self, a, b):
        """Every cell on a segment the player actually walked is walkable, and its edges are open."""
        n = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) / (self.size / 2)))
        prev = None
        for i in range(n + 1):
            c = self.cell(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n)
            self.walk.add(c)
            if prev and prev != c:
                self.blocked.discard((prev, c))
                self.blocked.discard((c, prev))
            prev = c

    def block(self, a, b):
        self.blocked.add((a, b))
        self.blocked.add((b, a))

    def astar(self, start, goal, limit: int = 60000):
        import heapq
        h = lambda c: math.hypot(c[0] - goal[0], c[1] - goal[1])
        openq, came, g = [(h(start), start)], {start: None}, {start: 0.0}
        while openq and len(came) < limit:
            _, c = heapq.heappop(openq)
            if c == goal:
                path = [c]
                while came[path[-1]] is not None:
                    path.append(came[path[-1]])
                return path[::-1]
            for dx in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    if dx == dz == 0:
                        continue
                    n = (c[0] + dx, c[1] + dz)
                    if self.closed and n not in self.walk and n != goal:
                        continue
                    if (c, n) in self.blocked or (dx and dz and ((c, (c[0] + dx, c[1])) in self.blocked and (c, (c[0], c[1] + dz)) in self.blocked)):
                        continue
                    cost = g[c] + math.hypot(dx, dz) * (1.0 if n in self.walk else 1.6)   # prefer known ground
                    if cost < g.get(n, 1e18):
                        g[n], came[n] = cost, c
                        heapq.heappush(openq, (cost + h(n), n))
        return None

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # geometry-backed maps keep only geometry: blocked edges there are transient (closed doors, enemies), per run
        blocked = [] if self.closed else sorted([list(a), list(b)] for a, b in self.blocked)
        self.path.write_text(json.dumps({"size": self.size, "closed": self.closed, "walk": sorted(self.walk), "blocked": blocked}))


def _selftest():
    assert angdiff(10, 350) == 20 and angdiff(350, 10) == -20 and abs(angdiff(180, 0)) == 180
    # simulated player: camera at 30 deg, "right" clockwise; goto must converge
    class Sim(Driver):
        def __init__(self):
            self.cam = self.sign = None
            self.trace, self.log = [], (lambda *a: None)
            self.pos, self.true_cam = [0.0, 0.0], 30.0
        def player(self):
            return {"x": self.pos[0], "z": self.pos[1]}
        def hold(self, keys, secs):
            k = DIRS.index(tuple(keys))
            h = math.radians(self.true_cam + 45 * k)
            self.pos[0] += math.sin(h) * 40 * secs
            self.pos[1] += math.cos(h) * 40 * secs
            self.true_cam += 3                                  # camera drifts while walking
    s = Sim()
    s.hold = s.hold
    time.sleep = lambda *_: None
    r = s.goto(150, -80, radius=10)
    assert r["ok"], r
    print("autoplay selftest ok", r)
    import tempfile, os
    m = NavMap(os.path.join(tempfile.mkdtemp(), "nav.json"))
    for z in range(-3, 4):                                       # wall at x=5 except a gap at z=6
        m.block((4, z), (5, z))
        for dz in (-1, 1):
            m.block((4, z), (5, z + dz))
    path = m.astar((0, 0), (9, 0))
    assert path and all(abs(c[1]) > 3 for c in path if c[0] in (4, 5)), path
    m.save(); assert NavMap(m.path).blocked == m.blocked
    print("navmap selftest ok", len(path), "cells")


if __name__ == "__main__":
    _selftest()
