"""Two real controllers for offline PSO Plus, with native observation on each step.

Character creation and story puzzles use the visual planner. Combat and movement
use two independently validated TObjPlayer slots. Completion is evidence gated;
this module does not synthesize characters, change quest flags, or warp players.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import inspect
import json
import math
from pathlib import Path
import random
import re
import struct
import time

import httpx

from . import pso_campaign as solo
from .pso_coop_nav import Maps, room_key
from .pso_coop_native import context as native_context, SpeedSampler
from .pso_coop_menu import MenuProgress
from .pso_gc_live import PLAYER, VT_UPDATE
from .registry import Unsupported

CAMPAIGN = "pso-coop-episodes-1-2"
DIFFICULTIES = ("Normal", "Hard", "Very Hard", "Ultimate")
CLASSES = ("HUmar", "HUnewearl", "HUcast", "HUcaseal", "RAmar", "RAmarl", "RAcast", "RAcaseal", "FOmar", "FOmarl", "FOnewm", "FOnewearl")
PROMPT = """Control two buddies in OFFLINE MULTI MODE in GameCube PSO Episode I & II Plus.
Use controllers player=1 and player=2; never merge their inputs. The context gives
random NEW character preferences: create those characters through the real creator
on the dedicated isolated new card. Initialize ONLY that new card when the context
explicitly authorizes it. Never delete/overwrite an existing character, use an
existing personal card, enter online play, or change emulator settings. If the
isolated-new-card authorization is false, only select existing campaign characters;
card initialization/new character replacement requires needs_operator=true.
Read the actual screen, move a visible selection one step at a time, then reassess.
Before a menu confirmation, name menu_title, selected_option, intended_option,
and selection_evidence describing the visible cursor/highlight. The highlighted
option is not necessarily the desired option. On the software license screen,
Agree and Disagree are separate choices: if Disagree is highlighted, move to
Agree and reobserve; do not press A on Disagree. Never combine navigation and
confirmation in one action. If the highlight is unclear, return no action and
explain the uncertainty. Use previous_menu_attempt to notice an unchanged menu;
do not keep repeating a confirmation that has not advanced it.
Select offline multi mode, join both controllers, and choose the requested episode
and difficulty when naturally unlocked. If a difficulty is locked, report locked
and continue leveling the same buddies at their highest available difficulty.
Clear rooms together, activate switches and portals, defeat every boss, use the
normal save path, and continue the requested next episode/difficulty. Never declare
a room clear solely because it currently has no visible enemies. Native combat
handles nearby enemies; plan actual exits, switches, healing and menus. The game
requires both buddies aboard a transporter before it departs. After a native
final-boss defeat, return both buddies to Pioneer 2, then use the normal Quit Game
save confirmation and Change Game Mode for the next run. Do not wait for solo
credits in multiplayer or seek single-player quests. The game
has no dodge roll: evade by moving out of attacks. Do not assume an action palette
button is healing; read it. Return only JSON with thought, screen
(gameplay|menu|loading|credits|death|unknown), needs_operator, difficulty_locked,
menu_title, selected_option, intended_option, selection_evidence,
and actions [{player:1|2, keys:[a|b|x|y|l|r|start|up|down|left|right|lup|ldown|lleft|lright], secs:0..0.6}].
At most four short actions. Player-specific waypoints may be returned as goals
[{player:1|2,x:number,z:number,room:integer,reason:string}] ONLY from native entities
in context or clearly supported nearby movement; do not invent a distant route.
Credits means visible genuine ending credits, never an empty arena or loading.
"""
PROMPT += solo.RECORDING_PROMPT


def character_preferences(seed=None):
    rng = random.Random(seed)
    return [{"player": slot, "name": "GB" + "".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(6)),
             "class": rng.choice(CLASSES), "costume": rng.randrange(9), "hair": rng.randrange(9),
             "height_fraction": round(rng.uniform(.25, .75), 2), "width_fraction": round(rng.uniform(.25, .75), 2)}
            for slot in (1, 2)]


def saved_preferences(path):
    """A worker restart keeps the buddies' names instead of creating new slots."""
    path = Path(path)
    if path.is_file():
        values = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(values, list) or len(values) != 2 or
                any(not isinstance(row, dict) or row.get("player") != i or row.get("class") not in CLASSES
                    or not re.fullmatch(r"[A-Z]{2,8}", str(row.get("name", "")))
                    for i, row in enumerate(values, 1))):
            raise Unsupported("Saved buddy identities are invalid; preserve the campaign card and inspect its characters")
        return values
    values = character_preferences()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as output:
            json.dump(values, output)
    except FileExistsError:
        return saved_preferences(path)
    return values


def actions(plan):
    if not isinstance(plan, dict) or not isinstance(plan.get("actions", []), list):
        raise ValueError("Co-op planner response needs an action list")
    if plan.get("needs_operator"):
        return []
    out = []
    for action in plan.get("actions", [])[:4]:
        if not isinstance(action, dict) or type(action.get("player")) is not int or action["player"] not in (1, 2):
            raise ValueError("Every PSO action needs controller 1 or 2")
        selected = solo.actions({"actions": [action]})
        if selected[0][1] > .6:
            raise ValueError("Co-op plan holds must not exceed 0.6 game seconds")
        out.append((action["player"], *selected[0]))
    return out


class Reader(solo.Reader):
    def snapshot(self):
        state = super().snapshot()
        state["players"] = {}
        if not state.get("verified") or state.get("travelling"):
            return state
        pointers = struct.unpack(">2I", self.ad.read_memory(PLAYER, 8))
        if not all(pointers) or pointers[0] == pointers[1]:
            state.update(verified=False, cooperative=False, diagnostic="Two distinct native local player slots are required")
            return state
        players = {}
        by_pointer = {e["ptr"]: e for e in state["entities"] if e.get("kind") == "player"}
        for slot, pointer in enumerate(pointers):
            self.gc.ptr(pointer, 0x340)
            entity = by_pointer.get(f"{pointer:08X}")
            if (not entity or entity.get("class") != "TObjPlayer" or entity.get("entity_id") != slot
                    or self.gc.u32(pointer + 0x18) != VT_UPDATE - 12):
                raise Unsupported(f"PSO controller {slot + 1} does not have a verified local player object")
            players[slot + 1] = dict(entity, controller=slot + 1)
        # Guard against an area swap in the middle of gathering the two players.
        if self.ad.read_memory(PLAYER, 8) != struct.pack(">2I", *pointers):
            return dict(state, verified=False, travelling=True)
        state.update(players=players, player=players[1], cooperative=True)
        state.update(native_context(self.ad))
        context_reader = getattr(self.ad, "pso_campaign_context", None)
        if context_reader:
            context = context_reader()
            if context.get("geometry_verified") and isinstance(context.get("geometry_identity"), str):
                state.update(geometry_identity=context["geometry_identity"], collision_grid=context.get("collision_grid"))
        return state


class Progress(solo.Progress):
    def __init__(self):
        super().__init__()
        self.difficulty, self.difficulty_cycles = 0, 0
        self.difficulty_verified = False
        self.route_episodes, self.route_cycles, self.route_difficulty_cycles = 0, 0, 0
        self.defeat_since, self.town_since, self.defeat_proof = None, None, None
        self.pending_receipts = []

    def observe(self, state, now=None):
        now = time.monotonic() if now is None else now
        if not state.get("verified"):
            return super().observe(state)
        self.difficulty_verified = bool(state.get("difficulty_verified") and state.get("difficulty") == self.difficulty)
        if not self.difficulty_verified or state.get("difficulty") != self.difficulty or len(state.get("players", {})) != 2:
            return
        super().observe(state)
        if state.get("floor") == solo.FINAL_FLOORS[self.target]:
            if self.boss_zero:
                if self.defeat_since is None:
                    self.defeat_since = now
                elif now - self.defeat_since >= 2:
                    self.defeat_proof = {"boss_objects": sorted(self.boss_alive), "final_floor": state["floor"],
                                         "difficulty": self.difficulty, "episode": self.target}
            else:
                self.defeat_since, self.defeat_proof, self.town_since = None, None, None
        if (self.defeat_proof and state.get("floor") == 0 and not state.get("travelling")
                and all(p.get("hp", 0) > 0 for p in state["players"].values())):
            if self.town_since is None:
                self.town_since = now
            elif now - self.town_since >= 1:
                self._finish_route(now)
        else:
            self.town_since = None

    def _finish_route(self, now):
        missing = sorted(solo.REQUIRED_FLOORS[self.target] - self.visited)
        complete = self.started_at_entry and not missing
        receipt = {"episode": self.target, "difficulty": self.difficulty,
                   "difficulty_name": DIFFICULTIES[self.difficulty], "players": 2,
                   "outcome": "episode_route_complete" if complete else "partial_episode_route",
                   "evidence": "native_final_boss_hp_transition_stable_zero_and_two_player_return_to_town",
                   "native_boss": self.defeat_proof, "visited_floors": sorted(self.visited),
                   "missing_floors": missing, "all_rooms_verified": False, "full_campaign_verified": False,
                   "at": time.time(), "observation_monotonic": now}
        self.receipts.append(receipt)
        self.receipts = self.receipts[-32:]
        self.pending_receipts.append(receipt)
        if complete:
            self.route_episodes += 1
            if self.target == 2:
                self.route_cycles += 1
                self.difficulty = (self.difficulty + 1) % 4
                self.route_difficulty_cycles += int(self.difficulty == 0)
                self.difficulty_verified = False
            self.target = 2 if self.target == 1 else 1
        self.visited.clear()
        self.started_at_entry = False
        self.awaiting_entry = True
        self.boss_alive.clear()
        self.boss_zero = False
        self.credit_samples = []
        self.state = "select_episode"
        self.left_free_play = False
        self.defeat_since, self.town_since, self.defeat_proof = None, None, None

    def ending(self, screen, frame_sha, now):
        if not self.difficulty_verified:
            return None
        completed = self.episodes
        receipt = super().ending(screen, frame_sha, now)
        if receipt:
            receipt.update(difficulty=self.difficulty, difficulty_name=DIFFICULTIES[self.difficulty], players=2)
        if self.episodes > completed and self.target == 1:
            self.difficulty = (self.difficulty + 1) % 4
            if self.difficulty == 0:
                self.difficulty_cycles += 1
            self.difficulty_verified = False
        return receipt

    def status(self):
        return super().status() | {"campaign": CAMPAIGN, "players": 2,
            "target_difficulty": DIFFICULTIES[self.difficulty], "difficulty_verified": self.difficulty_verified,
            "completed_all_difficulty_cycles": self.difficulty_cycles,
            "completed_native_episode_routes": self.route_episodes,
            "completed_native_episode_pairs": self.route_cycles,
            "completed_native_all_difficulty_route_cycles": self.route_difficulty_cycles,
            "completion_verified": bool(self.difficulty_cycles)}


class InputDeferred(OSError):
    """The adapter withheld or only partly delivered an input; do not infer motion."""


class SpeedChanging(InputDeferred):
    """Input timing is unsettled while Dolphin consumes the speed hotkeys."""


class SpeedUnknown(Unsupported):
    """An interrupted speed change requires a fresh, known emulator baseline."""


class EmulationPaused(InputDeferred):
    """Keep both pads released until the emulator resumes."""


class Inputs:
    def __init__(self, ad, stopped, *, send_primary=None, polite=False, stats=None):
        if not callable(getattr(ad, "send_input_player", None)):
            raise Unsupported("This Dolphin adapter has no independent second controller")
        self.ad, self.stopped = ad, stopped
        self.send_primary, self.polite = send_primary, polite
        self.stats = stats if stats is not None else {}
        try:
            self.has_polite = "polite" in inspect.signature(ad.send_input_player).parameters
        except (TypeError, ValueError):
            self.has_polite = False

    def send(self, events, player, *, check=True):
        if player == 1 and self.send_primary is not None:
            result = self.send_primary(events)
        elif self.has_polite:
            result = self.ad.send_input_player(events, player=player, polite=self.polite)
        else:
            result = self.ad.send_input_player(events, player=player)
        self.stats.update(last_input_player=player, last_input_keys=','.join(e['key'] for e in events),
                          last_input_requested=len(events),
                          last_input_sent=result.get('sent', 0) if isinstance(result, dict) else 0,
                          last_input_held=str(result.get('held') or result.get('stopped') or '')[:200] if isinstance(result, dict) else '')
        if check and (not isinstance(result, dict) or result.get("sent") != len(events)
                      or result.get("held") or result.get("stopped")):
            reason = (result.get("held") or result.get("stopped")) if isinstance(result, dict) else None
            raise InputDeferred(reason or "PSO controller did not acknowledge every input event")
        if check:
            self.stats['input_batches_acknowledged'] = self.stats.get('input_batches_acknowledged', 0) + 1
            self.stats['input_down_events_acknowledged'] = self.stats.get('input_down_events_acknowledged', 0) + sum(bool(e.get('down', True)) for e in events)
        return result

    def speed(self):
        speed = getattr(self.ad, "autoplay_speed", 1)
        return float(speed) if speed in (1, 2, 4, 8, 10) else 1.0

    def check_speed(self):
        if getattr(self.ad, "_autoplay_speed_known", True) is False:
            raise SpeedUnknown("PSO autoplay speed is unknown after an interrupted change; relaunch the buddy session")
        if getattr(self.ad, "_autoplay_speed_changing", False):
            raise SpeedChanging("Waiting for Dolphin to finish changing autoplay speed")
        if getattr(self.ad, "_pso_timing_paused", False):
            raise EmulationPaused("Waiting for Dolphin to resume")

    def wall_learning_safe(self):
        if (getattr(self.ad, "_autoplay_speed_known", True) is False or
                getattr(self.ad, "_autoplay_speed_changing", False) or
                getattr(self.ad, "_pso_timing_paused", False)):
            return False
        requested = self.speed()
        if requested == 1:
            return True
        # A hotkey receipt proves delivery, not emulated time. A slow host can
        # run a requested 10x rate at 1x, making a short pulse look like a wall.
        observation = getattr(self.ad, "_autoplay_speed_observed", None)
        if not isinstance(observation, dict) or observation.get("verified") is not True:
            return False
        actual, at = observation.get("actual"), observation.get("monotonic")
        return (observation.get("requested") == requested and type(actual) in (int, float) and
                math.isfinite(actual) and abs(actual - requested) <= requested * .05 and
                observation.get("timing_epoch", 0) == getattr(self.ad, "_pso_timing_epoch", 0) and
                observation.get("lower", actual) >= requested * .95 and
                observation.get("upper", actual) <= requested * 1.05 and
                type(at) in (int, float) and 0 <= time.monotonic() - at <= 2)

    def hold(self, commands):
        """Press both pads together; release every pad even when stopped or failed."""
        if self.stopped():
            raise InterruptedError("PSO co-op stopped")
        self.check_speed()
        requested = self.speed()
        timing_epoch = getattr(self.ad, "_pso_timing_epoch", 0)
        def check_timing():
            self.check_speed()
            if getattr(self.ad, "_pso_timing_epoch", 0) != timing_epoch:
                raise EmulationPaused("Dolphin paused, resumed or restored during input; reobserve before moving")
        commands = [(player, list(keys), max(.02, secs / requested)) for player, keys, secs in commands]
        started, sent = time.monotonic(), []
        try:
            for player, keys, secs in commands:
                if self.stopped():
                    raise InterruptedError("PSO co-op stopped before the next controller press")
                check_timing()
                sent.append((player, keys, secs))
                self.send([{"key": k, "down": True} for k in keys], player)
            for player, keys, secs in sorted(sent, key=lambda command: command[2]):
                solo.wait(max(0, started + secs - time.monotonic()), lambda: self.stopped() or
                          getattr(self.ad, "_autoplay_speed_changing", False) or
                          getattr(self.ad, "_pso_timing_paused", False) or
                          getattr(self.ad, "_pso_timing_epoch", 0) != timing_epoch or
                          getattr(self.ad, "_autoplay_speed_known", True) is False)
                check_timing()
                if self.speed() != requested:
                    raise SpeedChanging("Autoplay speed changed during controller input; reobserve before moving")
                self.send([{"key": k, "down": False} for k in keys], player)
        finally:
            release_error = None
            for player, keys, _ in sent:
                try:
                    self.send([{"key": k, "down": False} for k in keys], player, check=False)
                except Exception as exc:
                    release_error = exc
            if release_error:
                raise release_error

    def release(self):
        error = None
        for player in (1, 2):
            try:
                self.send([{"key": k, "down": False} for k in sorted(solo.BUTTONS)], player, check=False)
            except Exception as exc:
                error = exc
        if error:
            raise error


def mapping_probe(reader, inputs, state):
    """A short, isolated movement proves each pad owns only its intended actor."""
    if state.get("floor") != 0 or any(e.get("kind") == "enemy" and e.get("hp", 0) > 0 for e in state.get("entities", [])):
        raise Unsupported("Verify both controllers in Pioneer 2 before autonomous co-op combat")
    receipts = []
    for player in (1, 2):
        matched = False
        for key in ("lup", "lleft", "ldown"):
            before = reader.snapshot()
            if not before.get("verified") or len(before.get("players", {})) != 2:
                raise Unsupported("Both PSO players must remain present during pad verification")
            inputs.hold([(player, [key], .45)])
            solo.wait(.12 / inputs.speed(), inputs.stopped)
            after = reader.snapshot()
            if (not after.get("verified") or (before.get("episode"), before.get("floor")) !=
                    (after.get("episode"), after.get("floor"))):
                raise Unsupported("PSO changed areas during controller verification")
            distances = {slot: math.hypot(after["players"][slot]["x"] - before["players"][slot]["x"],
                                         after["players"][slot]["z"] - before["players"][slot]["z"]) for slot in (1, 2)}
            if distances[3 - player] > 1.5:
                raise Unsupported("A PSO controller moved the wrong buddy; stop before issuing combat inputs")
            if distances[player] >= 2:
                receipts.append({"controller": player, "native_slot": player - 1, "pointer": after["players"][player]["ptr"],
                                 "moved": round(distances[player], 2), "other_moved": round(distances[3 - player], 2)})
                matched = True
                break
        if not matched:
            raise Unsupported(f"PSO controller {player} produced no measurable movement")
    return receipts


def delta(bearing, heading):
    return (bearing - heading + 180) % 360 - 180


def movement_keys(player, destination):
    desired = math.degrees(math.atan2(destination[0] - player["x"], destination[1] - player["z"]))
    turn = round(delta(desired, player["heading_deg"]) / 45)
    return {0: ["lup"], 1: ["lup", "lleft"], 2: ["lleft"], 3: ["ldown", "lleft"],
            4: ["ldown"], -4: ["ldown"], -1: ["lup", "lright"], -2: ["lright"], -3: ["ldown", "lright"]}[turn]


class Controller:
    def __init__(self, reader, inputs, maps):
        self.reader, self.inputs, self.maps = reader, inputs, maps
        self.goals, self.last_attack, self.enemy_hp = {}, {}, {}
        self.damage, self.kills, self.attacks, self.blocked = 0, 0, 0, 0
        self.cooldown = {}
        self.approaches = {}

    def tick(self, state):
        if not state.get("verified") or len(state.get("players", {})) != 2:
            return False
        now = time.monotonic()
        enemies = [e for e in state["entities"] if e.get("kind") == "enemy" and e.get("hp", 0) > 0]
        for e in state["entities"]:
            if e.get("kind") != "enemy" or not isinstance(e.get("hp"), int):
                continue
            key = state.get("episode"), state.get("floor"), e["ptr"], e.get("class")
            previous = self.enemy_hp.get(key)
            if previous is not None and previous > e["hp"]:
                self.damage += previous - e["hp"]
                self.kills += int(e["hp"] == 0)
            self.enemy_hp[key] = e["hp"]
        commands, moves = [], {}
        # Recenter independently. PSO's L camera reset makes pad-relative forward
        # correspond to the actor's native heading. Re-read before choosing input.
        self.inputs.hold([(slot, ["l"], .08) for slot in (1, 2)])
        solo.wait(.20 / self.inputs.speed(), self.inputs.stopped)
        fresh = self.reader.snapshot()
        if (not fresh.get("verified") or (fresh.get("episode"), fresh.get("floor")) !=
                (state.get("episode"), state.get("floor"))):
            return False
        state = fresh
        enemies = [e for e in state["entities"] if e.get("kind") == "enemy" and e.get("hp", 0) > 0]
        for slot, player in state["players"].items():
            if player["hp"] <= 0:
                continue
            nearby = sorted((e for e in enemies if e.get("room") == player.get("room")),
                            key=lambda e: math.hypot(e["x"] - player["x"], e["z"] - player["z"]))
            target = next((e for e in nearby if self.cooldown.get((slot, e["ptr"]), 0) <= now), None)
            destination = None
            if target:
                dist = math.hypot(target["x"] - player["x"], target["z"] - player["z"])
                heading = math.degrees(math.atan2(target["x"] - player["x"], target["z"] - player["z"]))
                if player["hp"] < player["hp_max"] * .35:
                    destination = player["x"] + (player["x"] - target["x"]), player["z"] + (player["z"] - target["z"])
                elif dist <= 27 and abs(delta(heading, player["heading_deg"])) <= 20:
                    if now - self.last_attack.get(slot, 0) >= .52 / self.inputs.speed():
                        commands.append((slot, ["a"], .12))
                    continue
                elif dist <= 27:
                    commands.append((slot, movement_keys(player, (target["x"], target["z"])), .12))
                    continue
                else:
                    destination = target["x"], target["z"]
            else:
                goal = self.goals.get(slot)
                if goal and goal["identity"] == room_key(state, player)[0]:
                    destination = goal["x"], goal["z"]
                    if math.hypot(destination[0] - player["x"], destination[1] - player["z"]) < 9:
                        self.goals.pop(slot, None)
                        destination = None
                # Buddy 2 closes separation when there is no independently read
                # puzzle goal; it never blindly teleports to the leader's room.
                buddy = state["players"][3 - slot]
                if destination is None and slot == 2 and buddy.get("room") == player.get("room") and math.hypot(buddy["x"] - player["x"], buddy["z"] - player["z"]) > 65:
                    destination = buddy["x"], buddy["z"]
            if destination is None:
                continue
            identity = (slot, state.get("episode"), state.get("floor"), player.get("room"),
                        target["ptr"] if target else (round(destination[0]), round(destination[1])))
            distance = math.hypot(destination[0] - player["x"], destination[1] - player["z"])
            approach = self.approaches.get(identity)
            if approach is None or distance < approach[0] - 3:
                self.approaches[identity] = (distance, now)
            elif now - approach[1] > 6:
                # Do not repeat the same unreachable approach indefinitely. A
                # target behind a closed door is deferred while the planner finds
                # a switch/route; this does not turn combat stagger into a wall.
                if target:
                    self.cooldown[(slot, target["ptr"])] = now + 8
                self.goals.pop(slot, None)
                self.approaches.pop(identity, None)
                continue
            if len(self.approaches) > 128:
                self.approaches.pop(next(iter(self.approaches)))
            nav = self.maps.get(state, player)
            route = nav.route((player["x"], player["z"]), destination)
            if not route:
                self.goals.pop(slot, None)
                continue
            waypoint = route[1] if len(route) > 1 else destination
            commands.append((slot, movement_keys(player, waypoint), .40))
            moves[slot] = (player, waypoint, nav, not nearby)
        if not commands:
            return False
        movement_speed = self.inputs.speed()
        movement_epoch = getattr(getattr(self.inputs, "ad", None), "_pso_timing_epoch", 0)
        learning_safe = getattr(self.inputs, "wall_learning_safe", lambda: self.inputs.speed() == 1)
        movement_timing_safe = learning_safe()
        self.inputs.hold(commands)
        for slot, keys, _ in commands:
            if keys == ["a"]:
                self.last_attack[slot] = now
                self.attacks += 1
        solo.wait(.08 / self.inputs.speed(), self.inputs.stopped)
        after = self.reader.snapshot()
        for slot, (before, intended, nav, quiet) in moves.items():
            p = after.get("players", {}).get(slot)
            if not p:
                continue
            reliable = (movement_timing_safe and learning_safe() and self.inputs.speed() == movement_speed and
                        getattr(getattr(self.inputs, "ad", None), "_pso_timing_epoch", 0) == movement_epoch and
                        after.get("verified") and not after.get("travelling") and quiet and
                        p["hp"] == before["hp"] and p.get("room") == before.get("room") and
                        (state.get("episode"), state.get("floor")) == (after.get("episode"), after.get("floor")))
            if nav.observe((before["x"], before["z"]), (p["x"], p["z"]), intended, reliable=reliable):
                self.blocked += 1
        return True

    def accept_goals(self, plan, state):
        for goal in plan.get("goals", [])[:2]:
            if not isinstance(goal, dict) or type(goal.get("player")) is not int:
                continue
            player = state.get("players", {}).get(goal["player"])
            if not player or goal.get("room") != player.get("room"):
                continue
            if not all(isinstance(goal.get(k), (int, float)) and not isinstance(goal[k], bool) and math.isfinite(goal[k]) for k in ("x", "z")):
                continue
            if math.hypot(goal["x"] - player["x"], goal["z"] - player["z"]) > 300:
                continue
            self.goals[goal["player"]] = dict(goal, identity=room_key(state, player)[0])


def state_identity(state):
    return (state.get("phase"), state.get("episode"), state.get("floor"),
            tuple((k, p["ptr"], p.get("room"), bool(p.get("hp"))) for k, p in sorted(state.get("players", {}).items())))


def play(ad, send, stopped, *, stats=None, driver=None, game=None, session_id="", upload=None, style=None):
    if driver is None:
        raise ValueError("PSO co-op requires an autoplay driver")
    stats = stats if stats is not None else {}
    reader, inputs = Reader(ad), Inputs(ad, stopped, send_primary=send,
        polite=bool((getattr(driver, "demo", False) or getattr(driver, "screensaver", None))
                    and not getattr(driver, "owns_keyboard", False)), stats=stats)
    ledger = getattr(ad, "_pso_coop_progress", None) or Progress()
    ad._pso_coop_progress = ledger
    authorization = getattr(ad, "_pso_coop_new_card", {}) or {}
    card_identity = hashlib.sha256(str(authorization.get("path", session_id)).encode()).hexdigest()[:20]
    root = Path(ad.config.runtime) / "autoplay" / "pso-coop" / card_identity
    root.mkdir(parents=True, exist_ok=True)
    characters = getattr(ad, "_pso_coop_characters", None) or saved_preferences(root / "character-preferences.json")
    ad._pso_coop_characters = characters
    maps = Maps(root / "room-memory")
    controller = Controller(reader, inputs, maps)
    speed_sampler = SpeedSampler(ad, session_id, stopped)
    planner = solo.Planner(driver, ad.config)
    planner.prompt = PROMPT
    recorded = solo.recording_context(style, game)
    stats["recorded_input_evidence"] = recorded
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pso-coop-planner")
    pending, planned_identity, planned_frame, last_plan_at, errors = None, None, None, 0., 0
    menu, planner_errors = MenuProgress(), 0
    mapped = False
    ad._pso_verified_player_slots = set()
    initialize = (authorization.get("isolated") is True and authorization.get("session_id") == session_id
                  and bool(authorization.get("path")))
    stats.update(ledger.status(), characters=characters, controller_mapping_verified=False,
                 note="Two-controller campaign attempt; native receipts are required for completion.")
    try:
        while not stopped():
            try:
                inputs.check_speed()
                if getattr(ad, "paused", False):
                    solo.wait(.2, stopped)
                    continue
                state = reader.snapshot()
                ledger.observe(state)
                while ledger.pending_receipts:
                    receipt = ledger.pending_receipts.pop(0)
                    with (root / "finishes.jsonl").open("a", encoding="utf-8") as output:
                        output.write(json.dumps(receipt) + "\n")
                    stats["last_receipt"] = receipt
                    controller.goals.clear()
                stats.update(ledger.status(), episode=state.get("episode"), floor=state.get("floor"),
                             native_players=state.get("players", {}), requested_speed=inputs.speed(),
                             observed_enemy_damage=controller.damage, observed_kills=controller.kills,
                             attack_inputs=controller.attacks, remembered_blocked_edges=controller.blocked)
                if state.get("travelling"):
                    speed_sampler.invalidate()
                    stats["action"] = "waiting_for_area_loader"
                    solo.wait(.15, stopped)
                    continue
                if state.get("verified") and not mapped:
                    stats["controller_mapping"] = mapping_probe(reader, inputs, state)
                    mapped = True
                    ad._pso_verified_player_slots = {0, 1}
                    stats["controller_mapping_verified"] = True
                    state = reader.snapshot()
                if state.get("phase") != 14:
                    mapped = False
                    ad._pso_verified_player_slots = set()
                stats["achieved_speed_observation"] = speed_sampler.observe(state)
                if speed_sampler.failure:
                    stats["speed_sampling_error"] = speed_sampler.failure
                if pending is not None and pending.done():
                    completed, pending = pending, None  # a failed future must not be read again forever
                    stats['planner_latency_s'] = round(time.monotonic() - last_plan_at, 3)
                    try:
                        plan = completed.result()
                        selected = actions(plan)
                    except (OSError, ValueError, KeyError, httpx.HTTPError) as exc:
                        planner_errors += 1
                        stats.update(planner_consecutive_errors=planner_errors,
                                     planner_state='failed_observation',
                                     planner_last_error=f'{type(exc).__name__}: {exc}'[:400],
                                     planner_failures=stats.get('planner_failures', 0) + 1)
                        if planner_errors >= 5:
                            stats.update(ok=False, campaign_state='needs_operator',
                                         stopped_reason='Five planner observations failed; inputs released')
                            break
                        solo.wait(min(planner_errors, 3), stopped)
                        continue
                    planner_errors = 0
                    stats.update(planner_consecutive_errors=0, planner_last_error='', planner_state='observed',
                                 planner_actions=len(selected), planner_responses=stats.get('planner_responses', 0) + 1)
                    stats.update(thought=str(plan.get("thought", ""))[:400], screen=plan.get("screen", "unknown"),
                                 difficulty_locked=bool(plan.get("difficulty_locked")))
                    if plan.get("needs_operator"):
                        stats.update(ok=False, campaign_state="needs_operator", stopped_reason=stats["thought"])
                        break
                    if state_identity(state) == planned_identity:
                        digest = hashlib.sha256(planned_frame).hexdigest()
                        if plan.get("screen") == "credits" and ledger.boss_zero:
                            (root / (digest + ".png")).write_bytes(planned_frame)
                        receipt = ledger.ending(plan.get("screen"), digest, time.time())
                        if receipt:
                            with (root / "finishes.jsonl").open("a", encoding="utf-8") as output:
                                output.write(json.dumps(receipt) + "\n")
                            stats["last_receipt"] = receipt
                            controller.goals.clear()
                        elif not (plan.get("screen") == "credits" and ledger.boss_zero):
                            controller.accept_goals(plan, state)
                            # Combat is always chosen from current RAM; a slow model
                            # cannot inject stale movement into a currently busy fight.
                            combat = state.get("verified") and any(e.get("kind") == "enemy" and e.get("hp", 0) > 0 for e in state.get("entities", []))
                            if not combat or any(p.get("hp", 0) < p.get("hp_max", 1) * .35 for p in state.get("players", {}).values()):
                                selected, reason = menu.review(plan, selected, state_identity(state))
                                stats.update(menu_repeated_attempts=menu.repeats, menu_input_withheld=reason,
                                             menu_selected_option=menu.previous.get('selected_option', ''),
                                             menu_intended_option=menu.previous.get('intended_option', ''),
                                             planned_input_player=selected[0][0] if selected else 0,
                                             planned_input_keys=','.join(selected[0][1]) if selected else '')
                                if menu.stalled:
                                    stats.update(ok=False, campaign_state='needs_operator', stopped_reason=reason)
                                    break
                                # Menus are observed after every individual input.
                                # A confirm must never cascade into an unseen dialog.
                                for command in selected[:1]:
                                    inputs.hold([command])
                                    if menu.previous:
                                        menu.previous['input_delivery_verified'] = True
                    else:
                        stats["action"] = "discarded_stale_plan"
                if pending is None and time.monotonic() - last_plan_at > (2.1 if ledger.boss_zero else 8):
                    context = {**ledger.status(), "characters": characters,
                               "isolated_new_card_initialization_authorized": initialize,
                               "native_state": state, "controller_mapping_verified": mapped,
                               "current_goals": controller.goals,
                               "previous_menu_attempt": menu.previous,
                               "recorded_input_evidence": recorded,
                               "next": ("Use the normal save/quit path, Change Game Mode, and choose the next requested episode and available difficulty"
                                        if ledger.awaiting_entry else
                                        "Create and join the two new buddies; then clear the requested episode together")}
                    planned_frame, planned_identity = ad.get_frame(), state_identity(state)
                    pending = executor.submit(planner, planned_frame, context)
                    last_plan_at = time.monotonic()
                    stats.update(planner_requests=stats.get('planner_requests', 0) + 1,
                                 planner_state='waiting', input_polite=inputs.polite,
                                 second_pad_polite_supported=inputs.has_polite)
                if mapped and state.get("verified"):
                    stats["action"] = "coordinated_native_combat_or_navigation"
                    controller.tick(state)
                errors = 0
                solo.wait(.05, stopped)
            except SpeedUnknown as exc:
                speed_sampler.invalidate()
                stats.update(ok=False, campaign_state="needs_relaunch", stopped_reason=str(exc))
                break
            except (SpeedChanging, EmulationPaused) as exc:
                speed_sampler.invalidate()
                inputs.release()
                controller.approaches.clear()
                planned_identity = None  # Do not resume a pre-change frame's menu/movement plan.
                stats.update(action="waiting_for_emulator_resume" if isinstance(exc, EmulationPaused)
                             else "waiting_for_speed_change", input_deferred=str(exc))
                solo.wait(.1, stopped)
            except Unsupported:
                raise
            except InputDeferred as exc:
                stats.update(action="waiting_for_controller_focus", input_deferred=str(exc))
                solo.wait(.25, stopped)
            except InterruptedError:
                if stopped():
                    break
            except (OSError, ValueError, KeyError, httpx.HTTPError) as exc:
                speed_sampler.invalidate()
                errors += 1
                stats.update(last_error=str(exc), consecutive_errors=errors)
                if errors >= 5:
                    stats.update(ok=False, stopped_reason="Five consecutive observations failed; controller inputs released")
                    break
                solo.wait(min(errors, 3), stopped)
    finally:
        speed_sampler.invalidate()
        ad._pso_verified_player_slots = set()
        try:
            inputs.release()
        finally:
            maps.save()
            if pending:
                pending.cancel()
            executor.shutdown(wait=False, cancel_futures=True)
            # Active HTTP calls retain their own client until they finish; closing
            # it from the input thread would race an in-flight request.
            if pending and not pending.done():
                pending.add_done_callback(lambda _: planner.close())
            else:
                planner.close()
    stats.setdefault("ok", True)
    stats["stopped"] = bool(stopped())
    return stats
