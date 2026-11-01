"""Play PSO GameCube Episode I then II repeatedly, retaining evidence of each finish.

The controller combines the existing semantic combat driver with a vision planner
for menus, healing and routes that have no recorded mission. It is an experimental
completion attempt, not a verified walkthrough. Only 3OE2 has a native reader.
No warp, save-state restore, progress flag, HP freeze or memory write is used.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .autoplay import Driver
from .pso_gc_live import GC, PHASE, FLOOR, PLAYER
from .registry import Unsupported
from .pso_coop_menu import MenuProgress

CAMPAIGN = "pso-episodes-1-2"
COOP_CAMPAIGN = "pso-coop-episodes-1-2"
EPISODE = 0x805D6060
TRAVELLING = 0x805D49B8
FINAL_FLOORS = {1: 14, 2: 13}
# newserv StaticGameData.cc floor_infos (EP1 01..0E, EP2 01..0F):
# https://github.com/fuzziqersoftware/newserv/blob/master/src/StaticGameData.cc
# EP2 0x10 (Seaside Night) and 0x11 (Control Tower) are not free-play completion.
REQUIRED_FLOORS = {1: set(range(1, 15)), 2: set(range(1, 16))}
GAME_IDS = {"436e0bb84d5337d1", "7a3692dc0cbc9b82", "6b55435e3c565370"}
BUTTONS = {"a", "b", "x", "y", "l", "r", "start", "up", "down", "left", "right",
           "lup", "ldown", "lleft", "lright"}
PROMPT = """You control Phantasy Star Online Episode I & II Plus on GameCube.
Complete offline Episode I and Episode II on Normal, then repeat using the same
existing character. The requested episode and observed native state are below.
Use the existing character and memory card. Never delete or overwrite a character,
format a card, enter online play, change emulator settings, or choose Quit without
saving. On a genuine save/quit menu use the game's normal save path. An empty card,
card format, overwrite or delete prompt requires no input and needs_operator=true.
Walk the whole episode: defeat enemies, open doors, use switches/transporters,
talk to the Principal or Lab when progression requires it, and defeat all bosses.
Heal with inventory items or techniques when HP is low. Do not assume B is heal:
read the palette. Equip useful acquired equipment. Return from death normally.
Menus/door puzzles are your job; native combat handles nearby ordinary enemies.
Choose at most 4 short input actions then reassess. Use lup/ldown/lleft/lright for
the analog stick, up/down/left/right for menus, a/b/x/y/l/r/start for buttons.
Label credits ONLY if ending credits or an unmistakable episode ending are visible;
an empty room, a dead regular enemy, a loading screen or boss form change is not
completion. The controller independently requires native boss and route evidence.
Return JSON only: {"thought":"short plan", "screen":"gameplay|menu|loading|credits|death|unknown",
"needs_operator":false, "actions":[{"keys":["lup"],"secs":0.5}]}.
"""

RECORDING_PROMPT = """Historical recorded_input_evidence is only button-pattern frequency and example timing.
Use it as a weak preference for familiar controls ONLY when the current visible palette agrees.
It has no objective, route, door, switch, kill or completion labels; never infer those from input counts.
Do not replay recorded bursts or override native combat, navigation, short-action or save/card guards.
Historical build equivalence and per-event human ownership are not verified. Live observations take priority.
"""
PROMPT += RECORDING_PROMPT


def recording_context(style, game):
    """Bounded evidence for the planner, never executable learned input or route supervision."""
    game_id = (game or {}).get("game_id")
    result = {"state": "unavailable", "game_id": game_id,
              "scope": "historical input patterns only; no route, objective or completion supervision"}
    model = getattr(style, "m", None)
    provenance = model.get("provenance") if isinstance(model, dict) else None
    if (not isinstance(provenance, dict) or game_id not in GAME_IDS or
            provenance.get("game_id") != game_id or provenance.get("adapter") != "dolphin"):
        return result
    run_ids = provenance.get("run_ids")
    if not isinstance(run_ids, list) or not run_ids or len(run_ids) > 50 or any(
            not isinstance(sid, str) or not 1 <= len(sid) <= 120 or
            any(not (c.isascii() and (c.isalnum() or c in "-_")) for c in sid) for sid in run_ids):
        return result
    bursts = model.get("bursts")
    if not isinstance(bursts, list):
        return result
    # The existing style model uses Dolphin keyboard names. Convert to the
    # campaign's controller names; unsupported chords are omitted in full.
    names = {k: k for k in ("a", "b", "x", "y", "l", "r")}
    names.update(up="lup", down="ldown", left="lleft", right="lright",
                 t="up", g="down", f="left", h="right")
    patterns = []
    for burst in bursts[:2000]:
        if not isinstance(burst, dict) or type(burst.get("n")) is not int or not 1 <= burst["n"] <= 2147483647:
            continue
        steps = burst.get("steps")
        if not isinstance(steps, list) or not 1 <= len(steps) <= 128:
            continue
        keys, previous, valid = set(), -1., True
        for step in steps:
            if not isinstance(step, (list, tuple)) or len(step) != 2:
                valid = False
                break
            dt, held = step
            if (type(dt) not in (int, float) or not 0 <= dt <= 2.5 or dt < previous or
                    not isinstance(held, (list, tuple)) or len(held) > 16 or
                    any(not isinstance(key, str) or key not in names for key in held)):
                valid = False
                break
            keys.update(names[key] for key in held)
            previous = dt
        if valid and keys:
            patterns.append({"keys_seen": sorted(keys), "occurrences": burst["n"],
                             "example_burst_s": round(previous, 3)})
    if not patterns:
        return result
    patterns.sort(key=lambda row: (-row["occurrences"], row["keys_seen"], row["example_burst_s"]))
    return result | {"state": "available", "source": "gameplay_memory pad events via imitate.learn",
                     "source_run_ids": list(run_ids), "selected_game_id_only": True,
                     "historical_build_equivalence_verified": False, "per_event_human_ownership_verified": False,
                     "timing": "server receipt time; one example duration per pattern, not core frames",
                     "patterns_examined": min(len(bursts), 2000), "patterns_truncated": len(bursts) > 2000,
                     "patterns": patterns[:6]}


def matches(ad, game):
    return game.get("platform") == "gamecube" and (game.get("game_id") in GAME_IDS or
            "phantasy star online episode i" in str(game.get("title", "")).lower())


def setup(ad):
    # Runtime fingerprints are checked before every native observation, including
    # after a state load. Boot/menu input is allowed only for this disc revision.
    if ad.read_memory(0x80000000, 8) != b"GPOE8P\0\x02":
        raise Unsupported("PSO campaign native support requires GPOE8P disc 0 revision 2 (Episode I & II Plus)")
    return []


class Reader:
    def __init__(self, ad):
        from .semantic import Extractor, load_profiles
        self.ad, self.gc = ad, GC(ad)
        profile = next(p for p in load_profiles() if p["id"] == "pso-gc-plus-us")
        self.extractor = Extractor(profile, ad.read_memory)

    def snapshot(self):
        if getattr(self.ad, "paused", False):
            raise OSError("PSO session is paused")
        setup(self.ad)
        phase = self.gc.u32(PHASE)
        if phase == 15:
            raise Unsupported("PSO completion controller is for offline play; online input is disabled")
        if phase != 14:
            return {"verified": False, "phase": phase, "entities": [], "player": None}
        if self.gc.u32(TRAVELLING) or self.gc.u32(PLAYER) == 0:
            # The area loader temporarily destroys/recreates the player object.
            # Keep code/revision guards, but do not dereference that absent player.
            self.gc.check(player=False)
            return {"verified": False, "phase": phase, "travelling": True, "entities": [], "player": None}
        self.gc.check()
        st = self.extractor.state()
        episode, floor = self.gc.u32(EPISODE) + 1, self.gc.u32(FLOOR)
        if episode not in FINAL_FLOORS or not 0 <= floor <= 17:
            raise Unsupported("PSO campaign episode/floor values are outside the supported build")
        return st | {"episode": episode, "floor": floor, "phase": phase,
                     "travelling": bool(self.gc.u32(TRAVELLING))}


class Progress:
    """Conservative episode ledger; a loading screen or despawn never wins a run."""
    def __init__(self):
        self.target = 1
        self.cycles = 0
        self.episodes = 0
        self.visited = set()
        self.started_at_entry = False
        self.awaiting_entry = False
        self.boss_alive = set()
        self.boss_zero = False
        self.credit_samples = []
        self.receipts = []
        self.state = "attempting_episode"
        self.left_free_play = False

    def observe(self, st):
        if st.get("phase") is not None and st.get("phase") != 14:
            self.left_free_play = True
        if not st.get("verified") or st.get("travelling") or st.get("episode") != self.target:
            return
        floor = st.get("floor")
        if self.left_free_play:
            # Quitting/reloading an unfinished episode cannot combine two partial
            # routes into one complete run. Town trips within free play keep it.
            self.visited.clear()
            self.started_at_entry = False
            self.boss_alive.clear()
            self.boss_zero = False
            self.credit_samples = []
            self.left_free_play = False
        if self.awaiting_entry:
            if floor not in (0, 1):
                return
            self.awaiting_entry = False
            self.state = "attempting_episode"
        if floor == 1 and not self.visited:
            self.started_at_entry = True
        if floor in REQUIRED_FLOORS[self.target]:
            self.visited.add(floor)
        if floor != FINAL_FLOORS[self.target]:
            return
        live, zero = set(), set()
        for entity in st.get("entities", []):
            if not str(entity.get("class", "")).startswith(("TBoss", "TObjBoss")):
                continue
            hp, maximum = entity.get("hp"), entity.get("hp_max")
            if not isinstance(hp, int) or not isinstance(maximum, int) or not 0 <= hp <= maximum or maximum <= 0:
                continue
            identity = (entity.get("ptr"), entity.get("class"))
            if hp > 0:
                live.add(identity)
            elif identity in self.boss_alive:
                zero.add(identity)
        self.boss_alive.update(live)
        if live:
            # A second phase or living boss part revokes a premature zero.
            self.boss_zero = False
            self.credit_samples = []
        elif zero:
            self.boss_zero = True

    def ending(self, screen, frame_sha, now):
        if screen != "credits":
            self.credit_samples = []
            return None
        if self.awaiting_entry or not self.boss_zero:
            return None
        if any(s["sha256"] == frame_sha for s in self.credit_samples):
            return None
        self.credit_samples.append({"sha256": frame_sha, "at": now})
        if len(self.credit_samples) < 2 or now - self.credit_samples[0]["at"] < 2:
            return None
        missing = sorted(REQUIRED_FLOORS[self.target] - self.visited)
        complete = self.started_at_entry and not missing
        receipt = {"episode": self.target, "cycle": self.cycles + 1,
                   "outcome": "episode_complete" if complete else "partial_episode_finish",
                   "evidence": "native_final_boss_hp_transition_and_two_ending_frames",
                   "visited_floors": sorted(self.visited), "missing_floors": missing,
                   "started_at_entry": self.started_at_entry,
                   "frames": list(self.credit_samples), "at": now}
        self.receipts.append(receipt)
        self.receipts = self.receipts[-32:]
        if complete:
            self.episodes += 1
            if self.target == 2:
                self.cycles += 1
            self.target = 2 if self.target == 1 else 1
        self.visited.clear()
        self.started_at_entry = False
        self.awaiting_entry = True
        self.boss_alive.clear()
        self.boss_zero = False
        self.credit_samples = []
        self.state = "select_episode"
        self.left_free_play = False
        return receipt

    def status(self):
        return {"campaign": CAMPAIGN, "campaign_state": self.state,
                "target_episode": self.target, "completed_episodes": self.episodes,
                "completed_cycles": self.cycles, "visited_floors": sorted(self.visited),
                "missing_floors": sorted(REQUIRED_FLOORS[self.target] - self.visited),
                "final_boss_zero_observed": self.boss_zero,
                "completion_verified": bool(self.cycles), "receipts": self.receipts[-4:]}


def actions(plan):
    """Validate the complete model response before sending any button."""
    if not isinstance(plan, dict) or not isinstance(plan.get("actions", []), list):
        raise ValueError("PSO planner response has no action list")
    if plan.get("needs_operator"):
        return []
    out = []
    for action in plan.get("actions", [])[:4]:
        if not isinstance(action, dict):
            raise ValueError("PSO planner action is not an object")
        keys, secs = action.get("keys"), action.get("secs")
        if not isinstance(keys, list) or len(keys) > 3 or any(not isinstance(k, str) or k not in BUTTONS for k in keys):
            raise ValueError("PSO planner chose unsupported controller buttons")
        if isinstance(secs, bool) or not isinstance(secs, (int, float)) or not math.isfinite(secs) or not 0 <= secs <= 1.5:
            raise ValueError("PSO planner hold must be between zero and 1.5 seconds")
        out.append((keys, secs))
    return out


def wait(secs, stopped):
    end = time.monotonic() + secs
    while not stopped() and time.monotonic() < end:
        time.sleep(min(0.05, max(0, end - time.monotonic())))


class LocalDriver(Driver):
    """Use the existing closed-loop fighter without the control-plane RPC hop."""
    def __init__(self, reader, send, stopped, progress):
        self.reader, self.send, self.stop_requested, self.progress = reader, send, stopped, progress
        self.trace, self.cam, self.sign = [], None, None
        self.log = lambda *args: None
        self.analog, self.attack_key, self.combo, self.reach = True, "a", 3, 25
        self.cam_reset, self.right_sign = "l", None
        self.talk_key, self.kite = None, False  # the visual planner handles dialogue explicitly

    @property
    def stopped(self):
        return self.stop_requested()

    def state(self):
        if self.stop_requested():
            raise InterruptedError("PSO autoplay stopped")
        st = self.reader.snapshot()
        self.progress.observe(st)
        if not st.get("verified") or st.get("travelling"):
            raise InterruptedError("PSO changed area/menu during combat")
        return st

    def player(self):
        return self.state()["player"]

    def hold(self, keys, secs):
        if self.stop_requested():
            raise InterruptedError("PSO autoplay stopped")
        try:
            self.send([{"key": k, "down": True} for k in keys])
            wait(secs, self.stop_requested)
        finally:
            self.send([{"key": k, "down": False} for k in keys])


def vision_settings(driver, config):
    """Use the configured vision endpoint; resolve the default on a remote worker."""
    agent = getattr(config, "agent", {}) or {}
    model = getattr(driver, 'pso_vision_model', '') or agent.get("vision_model") or "qwen2.5vl:7b"
    configured = agent.get("vision_url") or agent.get("llm_url")
    if configured and (agent.get("vision_url") or urlparse(configured).hostname not in ("localhost", "127.0.0.1", "::1")):
        return configured.rstrip("/"), model
    # Workers often share the server's default localhost agent settings. Prefer
    # their explicit remote endpoint instead of assuming a model runs locally.
    for endpoint in getattr(config, "llm_endpoints", []) or []:
        url = endpoint.get("url") if isinstance(endpoint, dict) else endpoint.url
        if urlparse(url).hostname not in ("localhost", "127.0.0.1", "::1"):
            return url.rstrip("/"), model
    host = urlparse(str(driver.api.base_url)).hostname
    authority = "127.0.0.1" if host in (None, "localhost", "127.0.0.1") else host
    if ":" in authority:
        authority = "[" + authority + "]"
    return f"http://{authority}:11434/v1", model


class Planner:
    def __init__(self, driver, config=None):
        endpoint, self.model = vision_settings(driver, config)
        self.api = httpx.Client(base_url=endpoint, timeout=httpx.Timeout(35, connect=5))
        self.native_url = endpoint[:-3] if endpoint.endswith('/v1') else endpoint
        self.ollama = None

    @staticmethod
    def timeout(deadline, maximum):
        available = min(maximum, deadline - time.monotonic())
        if available <= 0:
            raise TimeoutError('PSO planner elapsed-time budget exhausted')
        return available

    def provider(self, deadline):
        if getattr(self, 'ollama', None) is None:
            endpoint = str(self.api.base_url).rstrip('/')
            self.native_url = endpoint[:-3] if endpoint.endswith('/v1') else endpoint
            try:
                response = self.api.get(self.native_url + '/api/version', timeout=self.timeout(deadline, 4))
                data = response.json()
                self.ollama = response.status_code == 200 and isinstance(data, dict) and isinstance(data.get('version'), str)
            except (httpx.HTTPError, ValueError, AttributeError):
                self.ollama = False
        return self.ollama

    def native_settings(self, deadline):
        # Metadata only: no alternate model, inferred context or forced reload.
        response = self.api.post(self.native_url + '/api/show', json={'model': self.model},
                                 timeout=self.timeout(deadline, 4))
        if response.status_code == 404:
            raise Unsupported(f'PSO route planner model {self.model!r} is not available')
        response.raise_for_status()
        data = response.json()
        capabilities = data.get('capabilities') if isinstance(data, dict) else None
        if not isinstance(capabilities, list) or 'vision' not in capabilities:
            raise Unsupported(f'PSO route planner model {self.model!r} does not advertise vision capability')
        settings, options, resident = {}, {}, False
        thinking = data.get('thinking')
        values = thinking.get('values') if isinstance(thinking, dict) else None
        if isinstance(values, list) and any(value is False for value in values):
            settings['think'] = False
        try:
            response = self.api.get(self.native_url + '/api/ps', timeout=self.timeout(deadline, 4))
            response.raise_for_status()
            data = response.json()
            models = data.get('models') if isinstance(data, dict) else None
            matches = [row for row in models if isinstance(row, dict) and
                       self.model in (row.get('name'), row.get('model'))] if isinstance(models, list) else []
            if len(matches) == 1:
                resident = True
                context = matches[0].get('context_length')
                if type(context) is int and 512 <= context <= 1_048_576:
                    options['num_ctx'] = context
        except (httpx.HTTPError, ValueError):
            pass  # Optional running-model metadata may be unavailable.
        return settings, options, resident

    def preflight(self):
        deadline = time.monotonic() + 12
        if self.provider(deadline):
            settings, options, resident = self.native_settings(deadline)
            return {'model': self.model, 'endpoint': self.native_url, 'protocol': 'ollama',
                    'vision_capability_verified': True, 'resident': resident,
                    'context_length': options.get('num_ctx'), 'think': settings.get('think')}
        res = self.api.get("/models", timeout=self.timeout(deadline, 8))
        res.raise_for_status()
        available = {str(row.get("id")) for row in res.json().get("data", [])}
        if self.model not in available:
            raise Unsupported(f"PSO route planner model {self.model!r} is not available at {self.api.base_url}; configure agent.vision_url/vision_model before starting")
        return {"model": self.model, "endpoint": str(self.api.base_url)}

    def __call__(self, frame, context):
        deadline = time.monotonic() + 35
        prompt = getattr(self, 'prompt', PROMPT) + '\n' + json.dumps(context)
        encoded = base64.b64encode(frame).decode()
        if self.provider(deadline):
            settings, options, _ = self.native_settings(deadline)
            res = self.api.post(self.native_url + '/api/chat', timeout=self.timeout(deadline, 35), json={
                'model': self.model, 'messages': [{'role': 'user', 'content': prompt, 'images': [encoded]}],
                'stream': False, 'format': 'json', **settings,
                'options': {'temperature': 0.1, 'num_predict': 1800, **options}})
            res.raise_for_status()
            raw = res.json()['message']['content']
        else:
            res = self.api.post("/chat/completions", timeout=self.timeout(deadline, 35), json={"model": self.model, "temperature": 0.1,
                "messages": [{"role": "user", "content": [{"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64," + encoded}}]}]})
            res.raise_for_status()
            raw = res.json()["choices"][0]["message"]["content"]
        self.timeout(deadline, 1)  # A late response cannot authorize an input.
        return json.loads(raw[raw.index("{"):raw.rindex("}") + 1])

    def close(self):
        self.api.close()


def preflight(ad, driver):
    setup(ad)
    planner = Planner(driver, ad.config)
    try:
        return planner.preflight()
    finally:
        planner.close()


def play(ad, send, stopped, *, stats=None, driver=None, game=None, session_id="", upload=None, players=1, style=None):
    """Run until stopped; retained telemetry distinguishes attempts from proven finishes."""
    if players == 2:
        from .pso_coop import play as coop_play
        return coop_play(ad, send, stopped, stats=stats, driver=driver, game=game, session_id=session_id, upload=upload, style=style)
    if players != 1:
        raise ValueError("PSO campaign supports one or two controllers")
    stats = stats if stats is not None else {}
    if driver is None:
        raise ValueError("The PSO campaign needs its autoplay driver for the local vision endpoint")
    reader = Reader(ad)
    ledger = getattr(ad, "_pso_campaign_progress", None) or Progress()
    ad._pso_campaign_progress = ledger
    fighter = LocalDriver(reader, send, stopped, ledger)
    planner = Planner(driver, ad.config)
    recorded = recording_context(style, game)
    stats["recorded_input_evidence"] = recorded
    safe_sid = "".join(c for c in session_id if c.isalnum() or c in "-_") or "session"
    evidence = Path(ad.config.runtime) / "autoplay" / "pso-campaign" / safe_sid
    evidence.mkdir(parents=True, exist_ok=True)
    errors, last_plan, last_plan_at, last_progress, last_signature = 0, [], 0.0, time.monotonic(), None
    gate_attempts = {}
    menu = MenuProgress()
    stats.update(ledger.status(), note="Experimental campaign attempt; no full completion is claimed without receipts.")
    try:
        while not stopped():
            if getattr(ad, "paused", False):
                wait(0.25, stopped)
                continue
            try:
                st = reader.snapshot()
                ledger.observe(st)
                stats.update(ledger.status(), episode=st.get("episode"), floor=st.get("floor"), hp=(st.get("player") or {}).get("hp"))
                if st.get("travelling"):
                    stats["action"] = "waiting_for_area_loader"
                    wait(0.25, stopped)
                    continue
                signature = (st.get("episode"), st.get("floor"), tuple((e.get("ptr"), e.get("hp")) for e in st.get("entities", []) if e.get("kind") == "enemy"))
                if signature != last_signature:
                    last_progress, last_signature = time.monotonic(), signature
                stats["progress_age_s"] = round(time.monotonic() - last_progress, 1)
                player = st.get("player") or {}
                nearby = [e for e in st.get("entities", []) if e.get("kind") == "enemy" and e.get("hp", 0) > 0 and
                          math.hypot(e.get("x", 0) - player.get("x", 0), e.get("z", 0) - player.get("z", 0)) < 300]
                gates = sorted((e for e in st.get("entities", []) if e.get("kind") == "gate"),
                               key=lambda e: math.hypot(e["x"] - player.get("x", 0), e["z"] - player.get("z", 0)))
                # Periodically consult the picture even during combat: multi-part
                # bosses, healing and unusual action palettes need visual context.
                if st.get("verified") and not st.get("travelling") and nearby and player.get("hp", 0) > 0.4 * player.get("hp_max", 1) and time.monotonic() - last_plan_at < 20:
                    stats["action"] = "native_combat"
                    try:
                        stats["combat"] = fighter.fight(timeout=6, radius=300, wave_wait=0, min_hp_frac=0.4)
                    except InterruptedError:
                        pass
                    fighter.trace = fighter.trace[-100:]
                    continue
                if st.get("verified") and st.get("floor", 0) > 0 and not st.get("travelling") and not nearby and \
                   player.get("hp", 0) > 0.4 * player.get("hp_max", 1) and time.monotonic() - last_plan_at < 20:
                    gate = next((g for g in gates if gate_attempts.get((st["episode"], st["floor"], g["ptr"]), 0) < 2), None)
                    if gate:
                        key = (st["episode"], st["floor"], gate["ptr"])
                        gate_attempts[key] = gate_attempts.get(key, 0) + 1
                        dx, dz = gate["x"] - player["x"], gate["z"] - player["z"]
                        distance = max(1, math.hypot(dx, dz))
                        stats["action"] = "native_door_approach"
                        try:
                            stats["navigation"] = fighter.goto(gate["x"] + dx / distance * 35,
                                                               gate["z"] + dz / distance * 35,
                                                               radius=12, timeout=3, stuck_limit=2)
                        except InterruptedError:
                            pass
                        continue
                frame = ad.get_frame()
                context = {"target_episode": ledger.target, "loop": ledger.cycles + 1,
                           "state": ledger.state, "observed_episode": st.get("episode"), "floor": st.get("floor"),
                           "player": player, "nearby_enemies": nearby[:6], "nearby_doors": gates[:6],
                           "missing_floors": stats["missing_floors"],
                           "progress_age_s": stats["progress_age_s"], "recent_plans": last_plan,
                           "recorded_input_evidence": recorded,
                           "previous_menu_attempt": menu.previous,
                           "next": "Save normally and select the requested episode with this character" if ledger.awaiting_entry else "Complete the requested episode, visiting its areas and bosses"}
                stats["action"] = "planning_route_or_menu"
                plan = planner(frame, context)
                last_plan_at = time.monotonic()
                selected = actions(plan)
                if stopped():
                    break
                stats.update(thought=str(plan.get("thought", ""))[:400], screen=plan.get("screen", "unknown"))
                if plan.get("needs_operator"):
                    stats.update(campaign_state="needs_operator", stopped_reason=stats["thought"], ok=False)
                    break
                # Re-read after model latency. Never execute a stale combat/menu
                # action following an area transition or the player dying.
                fresh = reader.snapshot()
                ledger.observe(fresh)
                if (fresh.get("episode"), fresh.get("floor"), fresh.get("phase"), bool((fresh.get("player") or {}).get("hp", 0))) != \
                   (st.get("episode"), st.get("floor"), st.get("phase"), bool(player.get("hp", 0))):
                    stats["action"] = "discarded_stale_plan"
                    continue
                digest = hashlib.sha256(frame).hexdigest()
                if plan.get("screen") == "credits" and ledger.boss_zero:
                    image_path = evidence / (digest + ".png")
                    image_path.write_bytes(frame)
                    if upload:
                        upload(image_path.name, frame, "image/png", campaign=CAMPAIGN, episode=ledger.target)
                receipt = ledger.ending(plan.get("screen"), digest, time.time())
                if receipt:
                    with (evidence / "finishes.jsonl").open("a", encoding="utf-8") as output:
                        output.write(json.dumps(receipt) + "\n")
                    stats.update(ledger.status(), last_receipt=receipt, evidence_dir=str(evidence))
                    # A newly selected episode invalidates this plan's old goal.
                    continue
                # Hold ending evidence on screen until a second observation.
                if plan.get("screen") == "credits" and ledger.boss_zero:
                    wait(2.1, stopped)
                    continue
                reviewed, reason = menu.review(plan, [(1, keys, secs) for keys, secs in selected],
                    (fresh.get('episode'), fresh.get('floor'), fresh.get('phase')),
                    frame=frame, fresh_frame=ad.get_frame(),
                    native_gameplay=bool(fresh.get('verified') and fresh.get('phase') == 14))
                stats.update(menu_repeated_attempts=menu.repeats, menu_input_withheld=reason,
                             menu_independent_selection=menu.previous.get('independent_selection'))
                if menu.stalled:
                    stats.update(ok=False, campaign_state='needs_operator', stopped_reason=reason)
                    break
                for _, keys, secs in reviewed:
                    if stopped():
                        break
                    fighter.hold(keys, secs)
                    if menu.previous:
                        menu.previous["input_delivery_verified"] = True
                    wait(0.15, stopped)
                last_plan = (last_plan + [stats["thought"]])[-5:]
                errors = 0
                wait(0.25, stopped)
            except Unsupported:
                raise
            except InterruptedError:
                if stopped():
                    break
            except (OSError, ValueError, KeyError, httpx.HTTPError) as exc:
                errors += 1
                stats.update(last_error=str(exc), consecutive_errors=errors, action="waiting_for_observation")
                if errors >= 5:
                    stats.update(ok=False, stopped_reason="Five consecutive native/vision observations failed; no inputs sent blindly")
                    break
                wait(min(5, errors), stopped)
    finally:
        planner.close()
        send([{"key": key, "down": False} for key in sorted(BUTTONS)])
    stats.setdefault("ok", True)
    stats["stopped"] = bool(stopped())
    return stats
