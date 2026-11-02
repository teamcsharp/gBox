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
from .pso_coop_menu import MenuProgress, known_menu_command
from .pso_coop_progress import Checkpoint, card_binding
from .pso_coop_recovery import TransientRecovery, continuous_requested
from . import pso_coop_mapping as mapping_continuity
from .pso_coop_combat import WeaponRanges, Engagements, EquipmentRecovery, FALLBACK, geometry as attack_geometry
from .pso_gc_live import PLAYER, VT_UPDATE
from .registry import Unsupported

CAMPAIGN = "pso-coop-episodes-1-2"
# Controller tokens are constrained at generation and independently checked before input.
PLAN_SCHEMA = {'type': 'object', 'additionalProperties': False, 'properties': {'thought': {'type': 'string', 'maxLength': 800}, 'screen': {'type': 'string', 'enum': ['gameplay', 'menu', 'loading', 'credits', 'death', 'unknown']}, 'needs_operator': {'type': 'boolean'}, 'difficulty_locked': {'type': 'boolean'}, 'menu_title': {'type': 'string'}, 'selected_option': {'type': 'string'}, 'intended_option': {'type': 'string'}, 'selection_evidence': {'type': 'string'}, 'actions': {'type': 'array', 'maxItems': 4, 'items': {'type': 'object', 'additionalProperties': False, 'properties': {'player': {'type': 'integer', 'enum': [1, 2]}, 'keys': {'type': 'array', 'maxItems': 3, 'items': {'type': 'string', 'enum': ['a', 'b', 'x', 'y', 'l', 'r', 'start', 'dup', 'ddown', 'dleft', 'dright', 'lup', 'ldown', 'lleft', 'lright']}}, 'secs': {'type': 'number', 'minimum': 0, 'maximum': 0.6}}, 'required': ['player', 'keys', 'secs']}}, 'goals': {'type': 'array', 'maxItems': 2, 'items': {'type': 'object', 'additionalProperties': False, 'properties': {'player': {'type': 'integer', 'enum': [1, 2]}, 'x': {'type': 'number'}, 'z': {'type': 'number'}, 'room': {'type': 'integer'}, 'reason': {'type': 'string'}}, 'required': ['player', 'x', 'z', 'room', 'reason']}}}, 'required': ['thought', 'screen', 'needs_operator', 'actions', 'goals']}
DIFFICULTIES = ("Normal", "Hard", "Very Hard", "Ultimate")
CLASSES = ("HUmar", "HUnewearl", "HUcast", "HUcaseal", "RAmar", "RAmarl", "RAcast", "RAcaseal", "FOmar", "FOmarl", "FOnewm", "FOnewearl")
PROMPT = """Control two buddies in OFFLINE MULTI MODE in GameCube PSO Episode I & II Plus.
Use controllers player=1 and player=2; never merge their inputs. The context gives
the saved buddy identities. When existing_buddies is true, these buddies have
already joined: continue their current game and select those same saved characters
on later menus. Never return to the creator or replace them. Create characters
only on the dedicated isolated new card when the context explicitly authorizes it.
Initialize ONLY that new card when the context
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
and actions [{player:1|2, keys:[a|b|x|y|l|r|start|dup|ddown|dleft|dright|lup|ldown|lleft|lright], secs:0..0.6}].
Use lup/ldown/lleft/lright for character movement and dup/ddown/dleft/dright for menus;
the main stick can move the character behind an open in-game menu.
At most four short actions. Player-specific waypoints may be returned as goals
[{player:1|2,x:number,z:number,room:integer,reason:string}] ONLY from native entities
in context or clearly supported nearby movement; do not invent a distant route.
Credits means visible genuine ending credits, never an empty arena or loading.
"""
PROMPT += solo.RECORDING_PROMPT

GAMEPLAY_PROMPT = """Control the two EXISTING buddies in the CURRENT GameCube PSO offline multiplayer game.
The top view is Player 1; the bottom view is Player 2. Native memory verifies both
players already joined. Their saved names/classes and current positions are in
context. Continue the current objective; do not revisit title/offline setup or
character creation. Do not press Start or quit merely because this is a new plan.

Prioritize the current native objective and observed landmarks over uncertain
image geometry. On Episode I floor 0 (Pioneer 2), reach the field departure area
together and inspect the route to Forest. Native class TObjCityDoor_Warp identifies
an observed TOWN EXIT CANDIDATE, not a proven usable portal or completed transport.
Approach that actual object using a goal for each player within 300 units in its
room. The purple glowing device near the buddies may be a different town telepipe;
color alone does not establish the field exit. Never invent coordinates.
For other areas, inspect actual nearby exits/switches and objective progress;
an object's class and coordinates alone do not prove the full route or room clear.

Return goals using ONLY the exact x,z,room of an observed nearby native landmark
when its role is supported. Native movement handles steering and remembered
obstacles. Combat uses fresh enemy RAM; do not interrupt it with an old plan.
The main transporter destination list appears at its center. Both players must
be aboard before offline transport activates. Require a fresh visible destination
list and selected option before proposing A; do not claim Forest was entered
until the native area changes. Do not claim completion, transport or door opening.

Use lup/ldown/lleft/lright for short character movement, dup/ddown/dleft/dright for
menu selection. Main-stick movement can move a character behind an open menu.
If a menu is actually visible, report screen=menu, menu_title, selected_option,
intended_option and selection_evidence; the independent menu guard must approve
it. Never combine navigation and confirmation. If uncertain return no action.
Return only JSON with thought, screen (gameplay|menu|loading|death|unknown),
needs_operator, difficulty_locked, menu_title, selected_option, intended_option,
selection_evidence, actions [{player:1|2,keys:[a|b|x|y|l|r|start|dup|ddown|dleft|dright|lup|ldown|lleft|lright],secs:0..0.4}],
and goals [{player:1|2,x:number,z:number,room:integer,reason:string}]. Prefer goals
over raw movement for observed landmarks. At most one goal and one action per
player. When goals suffice return actions:[]; the controller will move both buddies.
"""
GAMEPLAY_PROMPT += solo.RECORDING_PROMPT


FIELD_PROMPT = """Control the two EXISTING buddies in the CURRENT verified field area.
Native episode, floor and each player's room/position below are the current truth.
The top view is Player 1; the bottom view is Player 2. Continue forward together
through the current field rooms toward observed exits, switches and enemies.
Do not revisit the spawn/return portal without an explicit current objective.
An empty nearby enemy list does not mean this room or area is complete.

Keep each native entity's exact class and entity_id paired. Never rename a supply
container as a portal or infer an exit from its identifier. Class and coordinates
alone do not establish a traversable route, open door or switch state. When no
actual exit is observed, inspect the visible forward path with short movement,
then reobserve; do not repeatedly approach the same nearby supply box.
Native combat handles fresh enemies. For an observed useful landmark, return its
exact x,z,room as a goal only in that player's current room and within 300 units.
Native steering handles remembered obstacles. Do not invent distant coordinates.

Use lup/ldown/lleft/lright for short character movement and dup/ddown/dleft/dright
for menus. Never place move_to, entity IDs, coordinates or prose in keys.
Every action requires player, keys and secs. Both existing saved buddies remain
in the current run; do not open setup, quit or claim completion from an empty room.
If a menu is actually visible, report screen=menu with menu_title, selected_option,
intended_option and selection_evidence. Its independent guard must approve input.
Never combine menu navigation and confirmation. If uncertain return no action.
Return only JSON with thought, screen (gameplay|menu|loading|death|unknown),
needs_operator, actions [{player:1|2,keys:[a|b|x|y|l|r|start|dup|ddown|dleft|dright|lup|ldown|lleft|lright],secs:0..0.4}],
and goals [{player:1|2,x:number,z:number,room:integer,reason:string}]. At most one
goal and one action per player; return actions:[] when native goals suffice.
"""
FIELD_PROMPT += solo.RECORDING_PROMPT


def _planner_native_observation(state):
    """Unknown/loading observations never carry the full collision raster to a model."""
    scalars = ("verified", "cooperative", "travelling", "phase", "episode", "floor", "difficulty",
               "difficulty_verified", "geometry_verified", "geometry_identity", "geometry_diagnostic", "diagnostic")
    fields = ("ptr", "class", "kind", "entity_id", "room", "x", "y", "z", "heading_deg", "hp", "hp_max", "tp", "tp_max")
    def row(entity):
        return {key: (value[:240] if isinstance(value, str) else value)
                for key in fields if (value := entity.get(key)) is not None and
                (isinstance(value, (str, bool)) or type(value) in (int, float) and math.isfinite(value))}
    result = {key: (value[:400] if isinstance(value, str) else value)
              for key in scalars if (value := state.get(key)) is not None and
              (isinstance(value, (str, bool)) or type(value) in (int, float) and math.isfinite(value))}
    result['players'] = {slot: row(actor) for slot, actor in (state.get('players') or {}).items()
                         if slot in (1, 2) and isinstance(actor, dict)}
    entities = state.get('entities') or []
    result['entities'] = [row(entity) for entity in entities[:64] if isinstance(entity, dict)]
    result['entities_omitted'] = max(0, len(entities) - 64)
    result['geometry_payload_omitted'] = any(key in state for key in ('geometry_players', 'collision_grid'))
    return result


def planner_input(context):
    """Keep verified gameplay separate from boot instructions and irrelevant RAM rows."""
    state = context.get('native_state') or {}
    players = state.get('players') or {}
    if not (context.get('existing_buddies') is True and state.get('verified') is True and
            state.get('phase') == 14 and set(players) == {1, 2} and not context.get('awaiting_entry')):
        return PROMPT, {**context, 'native_state': _planner_native_observation(state)}
    fields = ('class', 'kind', 'entity_id', 'room', 'x', 'y', 'z', 'heading_deg', 'hp', 'hp_max')
    def summary(entity):
        return {key: entity[key] for key in fields if key in entity}
    landmarks = []
    for entity in state.get('entities', []):
        if entity.get('kind') not in ('object', 'gate') or not all(type(entity.get(key)) in (int, float) and
                math.isfinite(entity[key]) for key in ('x', 'y', 'z')):
            continue
        nearby = any(entity.get('room') == player.get('room') and
                     abs(entity['y'] - player.get('y', 0)) <= 15 and
                     math.hypot(entity['x'] - player['x'], entity['z'] - player['z']) <= 300
                     for player in players.values())
        if nearby:
            landmarks.append(summary(entity))
    field = type(state.get('floor')) is int and state['floor'] > 0
    if field:
        landmarks.sort(key=lambda e: e.get('entity_id', 0))
    else:
        landmarks.sort(key=lambda e: (e.get('class') != 'TObjCityDoor_Warp', e.get('entity_id', 0)))
    enemies = [summary(e) for e in state.get('entities', []) if e.get('kind') == 'enemy' and e.get('hp', 0) > 0]
    compact = {key: context[key] for key in ('characters', 'existing_buddies', 'next', 'target_episode',
               'target_difficulty', 'campaign_state', 'visited_floors', 'missing_floors', 'current_goals',
               'controller_mapping_verified', 'recorded_input_evidence', 'previous_menu_attempt') if key in context}
    compact.update(episode=state.get('episode'), floor=state.get('floor'), difficulty=state.get('difficulty'),
                   native_players={player: summary(entity) for player, entity in players.items()},
                   nearby_native_landmarks=landmarks[:32], native_enemies_alive=len(enemies),
                   nearby_native_enemies=enemies[:24], initialization_authorized=False)
    if field:
        location = {'episode': compact['episode'], 'floor': compact['floor'],
                    'players': compact['native_players']}
        return ('CURRENT VERIFIED FIELD: ' + json.dumps(location) + '\n' + FIELD_PROMPT), compact
    return GAMEPLAY_PROMPT, compact


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
                    or not re.fullmatch(r"[A-Za-z0-9]{2,8}", str(row.get("name", "")))
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


def buddy_context(characters, state, authorization, session_id, *, seen=False, awaiting_entry=False):
    """Native presence proves joined buddies, not their names or save completion."""
    existing = bool(seen or (state.get("verified") is True and state.get("phase") == 14
                            and set(state.get("players", {})) == {1, 2}))
    initialize = (not existing and authorization.get("isolated") is True and authorization.get("created") is True
                  and authorization.get("session_id") == session_id and bool(authorization.get("path")))
    if awaiting_entry:
        task = "Use the normal save/quit path, Change Game Mode, and select the same saved buddies for the next requested episode and available difficulty"
    elif existing:
        task = "Continue from the current two-player game with the same buddies; clear the requested episode together. Do not create or replace characters"
    elif initialize:
        task = "Create and join the two new buddies on the authorized new card; then clear the requested episode together"
    else:
        task = "Select and join the same saved buddy identities from the existing campaign card; never create, replace or initialize characters"
    return {"characters": characters, "existing_buddies": existing,
            "isolated_new_card_initialization_authorized": initialize,
            "awaiting_entry": bool(awaiting_entry), "next": task}


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
    def snapshot(self, _geometry_refreshed=False):
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
        from .pso_coop_geometry import Provider
        if not hasattr(self, "geometry"):
            self.geometry = Provider(self.ad)
        state.update(self.geometry.snapshot(state))
        if state.get("geometry_refreshed"):
            # Building a new raster can take a moment; movement uses a fresh RAM
            # observation after that work, never the pre-build player positions.
            if _geometry_refreshed:
                return dict(state, verified=False, diagnostic="Collision changed again; reobserve")
            return self.snapshot(_geometry_refreshed=True)
        context_reader = getattr(self.ad, "pso_campaign_context", None)
        if context_reader:
            context = context_reader()
            if context.get("geometry_verified") and isinstance(context.get("geometry_identity"), str):
                state.update(geometry_identity=context["geometry_identity"], collision_grid=context.get("collision_grid"))
                layer = context.get("geometry_layer")
                if type(layer) in (str, int) and (not isinstance(layer, str) or layer):
                    state["geometry_layer"] = layer
        from .pso_coop_gates import observe as observe_gates
        return observe_gates(self.ad, state)


class Progress(solo.Progress):
    def __init__(self, *, allow_training=True):
        super().__init__()
        self.difficulty, self.difficulty_cycles = 0, 0
        self.difficulty_verified = False
        self.route_episodes, self.route_cycles, self.route_difficulty_cycles = 0, 0, 0
        self.defeat_since, self.town_since, self.defeat_proof = None, None, None
        self.pending_receipts = []
        self._allow_training = allow_training
        self._training_progress = None
        self._training_difficulty = None
        self.selected_difficulty = None
        self.selected_difficulty_verified = False
        self.training_episodes = 0
        self.training_native_episode_routes = 0

    def _reset_attempt(self):
        """A difficulty change cannot join two different runs into one receipt."""
        self.visited.clear()
        self.started_at_entry = self.awaiting_entry = self.boss_zero = self.left_free_play = False
        self.boss_alive.clear()
        self.credit_samples = []
        self.defeat_since = self.town_since = self.defeat_proof = None
        self.state = "attempting_episode"

    def _training_receipt(self, receipt):
        original = receipt["outcome"]
        result = dict(receipt, outcome="training_" + original,
                      requested_episode=self.target, requested_difficulty=self.difficulty,
                      requested_difficulty_name=DIFFICULTIES[self.difficulty],
                      requested_campaign_progress=False, completion_verified=False,
                      full_campaign_verified=False, highest_unlocked_verified=False,
                      fallback_evidence="native_verified_selected_lower_difficulty")
        self.training_episodes += int(original == "episode_complete")
        self.training_native_episode_routes += int(original == "episode_route_complete")
        self.receipts.append(result)
        self.receipts = self.receipts[-32:]
        return result

    def _sync_training(self):
        training = self._training_progress
        self.awaiting_entry, self.boss_zero = training.awaiting_entry, training.boss_zero
        # These are control/menu hints only. The requested run's completion
        # counters, episode and difficulty remain on this parent ledger.
        self.state = "training_lower_difficulty"
        self.difficulty_verified = False
        while training.pending_receipts:
            self.pending_receipts.append(self._training_receipt(training.pending_receipts.pop(0)))

    def observe(self, state, now=None):
        now = time.monotonic() if now is None else now
        if not state.get("verified"):
            self.selected_difficulty_verified = False
            if self._training_progress is not None:
                self._training_progress.observe(state, now)
                self._sync_training()
            return super().observe(state)
        actual = state.get("difficulty")
        self.selected_difficulty_verified = bool(state.get("phase") == 14 and
            state.get("difficulty_verified") is True and type(actual) is int and 0 <= actual < 4 and
            set(state.get("players", {})) == {1, 2} and state.get("episode") in (1, 2))
        self.selected_difficulty = actual if self.selected_difficulty_verified else None
        if (self._allow_training and self.selected_difficulty_verified and actual < self.difficulty):
            if self._training_progress is None and self.awaiting_entry and not self.left_free_play:
                # The old game's town still reports its previous difficulty
                # immediately after completion. It is not a new fallback choice.
                self.difficulty_verified = False
                return
            if self._training_progress is None or self._training_difficulty != actual:
                self._reset_attempt()
                self._training_progress = Progress(allow_training=False)
                self._training_progress.target = state.get("episode", self.target)
                self._training_difficulty = actual
            training = self._training_progress
            # Repeating a lower difficulty never advances the pending requested
            # difficulty. Only the game's guarded current selection admits it.
            training.difficulty = actual
            training.observe(state, now)
            self._sync_training()
            return
        if self._training_progress is not None:
            if not self.selected_difficulty_verified:
                self.difficulty_verified = False
                return
            self._training_progress = self._training_difficulty = None
            self._reset_attempt()
        self.difficulty_verified = bool(self.selected_difficulty_verified and actual == self.difficulty)
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
        if self._training_progress is not None:
            receipt = self._training_progress.ending(screen, frame_sha, now)
            self._sync_training()
            return self._training_receipt(receipt) if receipt else None
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
        result = super().status() | {"campaign": CAMPAIGN, "players": 2,
            "target_difficulty": DIFFICULTIES[self.difficulty], "difficulty_verified": self.difficulty_verified,
            "completed_all_difficulty_cycles": self.difficulty_cycles,
            "completed_native_episode_routes": self.route_episodes,
            "completed_native_episode_pairs": self.route_cycles,
            "completed_native_all_difficulty_route_cycles": self.route_difficulty_cycles,
            "completion_verified": bool(self.difficulty_cycles)}
        result.update(selected_difficulty=self.selected_difficulty,
                      selected_difficulty_verified=self.selected_difficulty_verified,
                      requested_episode=self.target, requested_difficulty=DIFFICULTIES[self.difficulty],
                      training_lower_difficulty=self._training_progress is not None,
                      completed_training_episodes=self.training_episodes,
                      completed_training_native_episode_routes=self.training_native_episode_routes,
                      highest_unlocked_verified=False)
        if self._training_progress is not None:
            active = self._training_progress.status()
            result.update({key: active[key] for key in ("target_episode", "visited_floors", "missing_floors",
                                                       "final_boss_zero_observed")})
            result.update(target_difficulty=DIFFICULTIES[self._training_difficulty],
                          campaign_state="training_lower_difficulty",
                          fallback_evidence="native_verified_selected_lower_difficulty",
                          next_difficulty_goal="Retry the requested difficulty only after independently observing its availability; otherwise keep these saved buddies at their verified selected difficulty")
        return result


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
        self._last_hold_timing_ok = True
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
        if not self._last_hold_timing_ok:
            return False
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
        sent, deadlines, timing = [], {}, {}
        self._last_hold_timing_ok = False
        try:
            for player, keys, secs in commands:
                if self.stopped():
                    raise InterruptedError("PSO co-op stopped before the next controller press")
                check_timing()
                sent.append((player, keys, secs))
                delivery_started = time.monotonic()
                self.send([{"key": k, "down": True} for k in keys], player)
                acknowledged = time.monotonic()
                deadlines[player] = acknowledged + secs
                timing[player] = dict(requested_wall_ms=round(secs*1000,3),
                    delivery_ms=round((acknowledged-delivery_started)*1000,3),
                    acknowledged_at=acknowledged)
                if self.stopped():
                    raise InterruptedError("PSO stopped during controller delivery")
                check_timing()
            for player, keys, secs in sorted(sent, key=lambda command: deadlines[command[0]]):
                solo.wait(max(0, deadlines[player] - time.monotonic()), lambda: self.stopped() or
                          getattr(self.ad, "_autoplay_speed_changing", False) or
                          getattr(self.ad, "_pso_timing_paused", False) or
                          getattr(self.ad, "_pso_timing_epoch", 0) != timing_epoch or
                          getattr(self.ad, "_autoplay_speed_known", True) is False)
                check_timing()
                if self.stopped():
                    raise InterruptedError("PSO stopped during controller hold")
                if self.speed() != requested:
                    raise SpeedChanging("Autoplay speed changed during controller input; reobserve before moving")
                release_started = time.monotonic()
                self.send([{"key": k, "down": False} for k in keys], player)
                timing[player].update(held_ms=round((release_started-timing[player]['acknowledged_at'])*1000,3),
                    release_delivery_ms=round((time.monotonic()-release_started)*1000,3))
            # Slow delivery can lengthen another pad's hold. It is valid input,
            # but cannot establish a wall from the nominal pulse duration.
            self._last_hold_timing_ok = all(row['delivery_ms'] <= row['requested_wall_ms'] and
                row['release_delivery_ms'] <= row['requested_wall_ms'] and
                row['held_ms'] <= row['requested_wall_ms']+20 for row in timing.values())
        finally:
            for player,row in timing.items():
                for key in ('requested_wall_ms','delivery_ms','held_ms','release_delivery_ms'):
                    self.stats[f'input_p{player}_{key}'] = row.get(key)
            self.stats['input_hold_timing_verified'] = self._last_hold_timing_ok
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


class MappingPending(Unsupported):
    """An otherwise valid town pad probe saw no movement yet."""


def _probe_town_ready(state):
    """Loading actors cannot provide evidence about controller ownership."""
    if not state.get("verified") or set(state.get("players", {})) != {1, 2}:
        raise Unsupported("Both PSO players must remain present during pad verification")
    if state.get("floor") != 0 or any(e.get("kind") == "enemy" and e.get("hp", 0) > 0
                                      for e in state.get("entities", [])):
        raise Unsupported("Verify both controllers in Pioneer 2 before autonomous co-op combat")
    if state.get("phase") != 14 or state.get("travelling"):
        raise MappingPending("PSO town actors are still loading")
    for actor in state["players"].values():
        room = actor.get("room")
        coords = (actor.get("x"), actor.get("y", 0.), actor.get("z"))
        if (type(room) is not int or not 0 <= room < 65535 or actor.get("hp", 0) <= 0 or
                any(type(value) not in (int, float) or not math.isfinite(value) for value in coords)):
            raise MappingPending("PSO town actor position has not settled")


def _probe_settled(reader, inputs):
    """Observe both untouched actors before each short mapping pulse."""
    before = reader.snapshot()
    _probe_town_ready(before)
    solo.wait(.12 / inputs.speed(), inputs.stopped)
    if inputs.stopped():
        raise InterruptedError("PSO stopped while waiting for town actors")
    after = reader.snapshot()
    _probe_town_ready(after)
    if ((before.get("episode"), before.get("floor")) != (after.get("episode"), after.get("floor")) or
            any(after["players"][slot].get("ptr") != before["players"][slot].get("ptr") for slot in (1, 2))):
        raise Unsupported("PSO player or area identity changed before controller verification")
    for slot in (1, 2):
        first, last = before["players"][slot], after["players"][slot]
        if (first["room"] != last["room"] or
                math.hypot(last["x"] - first["x"], last["z"] - first["z"]) > .25 or
                abs(last.get("y", 0.) - first.get("y", 0.)) > .25):
            raise MappingPending("PSO town actors moved before the controller probe; wait for spawn to settle")
    return after


def mapping_probe(reader, inputs, state):
    """A short, isolated movement proves each pad owns only its intended actor."""
    _probe_town_ready(state)
    receipts = []
    for player in (1, 2):
        matched = False
        for key in ("lup", "lleft", "ldown"):
            before = _probe_settled(reader, inputs)
            inputs.hold([(player, [key], .45)])
            solo.wait(.12 / inputs.speed(), inputs.stopped)
            after = reader.snapshot()
            if (not after.get("verified") or (before.get("episode"), before.get("floor")) !=
                    (after.get("episode"), after.get("floor"))):
                raise Unsupported("PSO changed areas during controller verification")
            if (set(after.get("players", {})) != {1, 2} or
                    any(after["players"][slot].get("ptr") != before["players"][slot].get("ptr") for slot in (1, 2))):
                raise Unsupported("PSO player identities changed during controller verification")
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
            raise MappingPending(f"PSO controller {player} produced no measurable movement")
    return receipts


def delta(bearing, heading):
    return (bearing - heading + 180) % 360 - 180


def movement_keys(player, destination):
    desired = math.degrees(math.atan2(destination[0] - player["x"], destination[1] - player["z"]))
    turn = round(delta(desired, player["heading_deg"]) / 45)
    return {0: ["lup"], 1: ["lup", "lleft"], 2: ["lleft"], 3: ["ldown", "lleft"],
            4: ["ldown"], -4: ["ldown"], -1: ["lup", "lright"], -2: ["lright"], -3: ["ldown", "lright"]}[turn]


RECENTER_S = 2.0            # a pad's L reset is at most this frequent while its actor walks straight
RECENTER_TURN_DEG = 45      # an actor turning this far since its last reset gets one immediately
# Operator 2026-11-02: buddies play at 2x by default so a run reaches each teleporter in
# reasonable time. Defined here, in a hot-reloadable bot module, so apply_default_speed()
# never binds a name across the non-reloadable pso_coop_setup boundary.
DEFAULT_AUTOPLAY_SPEED = 2

# Geometry-free forward progress (operator 2026-11-02: buddies must MOVE toward the
# exit, never idle, even before the verified collision grid proves geometry_verified).
# A switch is stood on first, then the door/barrier it gates. These live in this
# hot-reloadable module so no name crosses the non-reloadable setup boundary.
FORWARD_SWITCH_CLASSES = frozenset({'TLazerFenceSw', 'TObjDoorKey'})
FORWARD_GATE_CLASSES = frozenset({'TObjDoor', 'TOBarrierEnergy01', 'TObjLazerFenceNorm'})
FORWARD_FALLBACK_CLASSES = FORWARD_SWITCH_CLASSES | FORWARD_GATE_CLASSES
FALLBACK_STALL_S = 6.0        # abandon a forward affordance that stops getting closer
FALLBACK_REACH = 9.0          # a switch/door counts as reached within this many units
FALLBACK_STUCK_S = 120.0      # operator fail-safe threshold: a room with no forward progress
COMBAT_NEARBY_RADIUS = 60.0   # engage an enemy this close even when its room id does not match


class Controller:
    def __init__(self, reader, inputs, maps):
        self.reader, self.inputs, self.maps = reader, inputs, maps
        self.goals, self.last_attack, self.enemy_hp = {}, {}, {}
        self.damage, self.kills, self.attacks, self.blocked = 0, 0, 0, 0
        self.cooldown = {}
        self.recentered = {}
        self.approaches = {}
        self.weapon_ranges = WeaponRanges(getattr(reader, 'ad', None))
        self.engagements = Engagements()
        self.combat_status = {}
        from .pso_coop_town import TownRoute
        self.town = TownRoute(getattr(reader, "ad", None))
        self.town_enabled = False
        from .pso_coop_frontier import FieldObjectives
        self.field = FieldObjectives()
        self.margin_attempts = {}
        self.fallback = {}      # (episode,floor,geometry) -> geometry-free forward approach book
        self.room_dwell = {}    # P1 dwell tracking for the stuck-room fail-safe telemetry

    def _steering_publish(self):
        """Diagnostics only: bounded scalar JSON uses the existing telemetry path."""
        try:
            stats = getattr(self.inputs, 'stats', None)
            if not isinstance(stats, dict):
                return
            rows = getattr(self, '_steering_events', [])[-4:]
            while rows:
                raw = json.dumps({'schema': 'gbox.pso.steering/1', 'events': rows},
                                 allow_nan=False, separators=(',', ':'))
                if len(raw.encode()) <= 6000:
                    self._steering_events = rows
                    stats['steering_evidence_json'] = raw
                    return
                rows.pop(0)
        except Exception:
            pass

    def _steering_begin(self, state, selected, commands):
        try:
            if not selected or not isinstance(getattr(self.inputs, 'stats', None), dict):
                return None
            pose = lambda p: {k: p.get(k) for k in ('ptr', 'room', 'x', 'y', 'z', 'heading_deg', 'hp')}
            self._steering_sequence = getattr(self, '_steering_sequence', 0) + 1
            row = {'sequence': self._steering_sequence, 'state': 'delivery_pending',
                   'episode': state.get('episode'), 'floor': state.get('floor'),
                   'geometry_identity': state.get('geometry_identity'),
                   'hold_call_started_monotonic': time.monotonic(),
                   'hold_call_started_wall_time': time.time(),
                   'pre_pose_exact_sample_time_known': False, 'players': {}}
            for slot, keys, seconds in commands:
                if slot not in selected:
                    continue
                player, waypoint, source = selected[slot]
                bearing = math.degrees(math.atan2(waypoint[0]-player['x'], waypoint[1]-player['z']))
                row['players'][str(slot)] = {'before': pose(player), 'waypoint': list(waypoint),
                    'source': source, 'bearing_deg': bearing,
                    'relative_bearing_deg': delta(bearing, player['heading_deg']),
                    'keys': list(keys), 'requested_game_seconds': seconds,
                    'requested_speed': self.inputs.speed()}
                view = ((state.get('geometry_players') or {}).get(slot) or
                        (state.get('geometry_recovery_players') or {}).get(slot) or {})
                row['players'][str(slot)]['geometry_layer'] = view.get('geometry_layer')
            json.dumps(row, allow_nan=False)
            self._steering_events = [*getattr(self, '_steering_events', []), row][-4:]
            self._steering_publish()
            return row
        except Exception:
            return None

    def _steering_delivered(self, row):
        try:
            if row is None:
                return
            row['state'] = 'delivery_returned'
            row['hold_call_returned_monotonic'] = time.monotonic()
            for slot, player in row['players'].items():
                player['ack_timing'] = {key: self.inputs.stats.get(f'input_p{slot}_{key}')
                    for key in ('requested_wall_ms', 'delivery_ms', 'held_ms', 'release_delivery_ms')}
            row['post_observation_interval_started_monotonic'] = time.monotonic()
            self._steering_publish()
        except Exception:
            pass

    def _steering_finish(self, row, after, outcome):
        try:
            if row is None:
                return
            row['state'] = outcome
            row['finished_monotonic'] = time.monotonic()
            if isinstance(after, dict):
                row['post_observation_returned_monotonic'] = row['finished_monotonic']
                row['after_verified'] = after.get('verified') is True
                row['same_area'] = (after.get('episode'), after.get('floor')) == (row['episode'], row['floor'])
                row['after_geometry_identity'] = after.get('geometry_identity')
                for slot, player in row['players'].items():
                    p = (after.get('players') or {}).get(int(slot))
                    if p:
                        player['after'] = {k: p.get(k) for k in ('ptr', 'room', 'x', 'y', 'z', 'heading_deg', 'hp')}
                        player['same_actor'] = p.get('ptr') == player['before']['ptr']
            self._steering_publish()
        except Exception:
            pass

    def margin_waypoint(self, state, slot, player):
        """Consume only the current player's exact, bounded base-floor connector."""
        proof = state.get('geometry_recovery_players', {}).get(slot) or {}
        row = self.field.status['players'].setdefault(str(slot), {})
        row.update(goal=None, exit=None, predicate='unknown', dependency='own_geometry_unavailable', outcome='held')
        if (state.get('verified') is not True or state.get('geometry_verified') is not True or
                state.get('phase') != 14 or state.get('floor', 0) <= 0 or state.get('travelling') or
                player.get('hp', 0) <= 0 or proof.get('source') != 'verified_native_collision_base' or
                proof.get('geometry_identity') != state.get('geometry_identity') or
                not proof.get('geometry_layer') or proof.get('player_ptr') != player.get('ptr')):
            return None
        start, point = proof.get('start') or {}, proof.get('waypoint') or {}
        path, heights = proof.get('path') or [], proof.get('path_heights') or []
        finite = lambda value: type(value) in (int,float) and math.isfinite(value)
        if (any(not finite(start.get(k)) or abs(start[k]-player[k]) > .001 for k in ('x','y','z')) or
                any(not finite(point.get(k)) for k in ('x','z')) or not 2 <= len(path) <= 16 or
                len(heights) != len(path) or any(not finite(h) for h in heights) or
                any(not isinstance(p,(list,tuple)) or len(p)!=2 or any(not finite(v) for v in p) for p in path)):
            return None
        actual_start = player['x'],player['z']
        length = sum(math.dist(a,b) for a,b in zip(path,path[1:]))
        destination = point['x'],point['z']
        if (math.dist(path[0],actual_start) > .001 or not 0 < length <= 12.001 or
                not 0 < math.dist(actual_start,destination) <= 6.001 or
                not finite(proof.get('path_length')) or abs(length-proof['path_length']) > .01 or
                tuple(path[1]) != destination):
            return None
        identity = (state.get('episode'),state.get('floor'),state.get('geometry_identity'),
                    proof['geometry_layer'],player['ptr'])
        current = self.margin_attempts.get(slot)
        if current is None or current['identity'] != identity:
            current = self.margin_attempts[slot] = dict(identity=identity,attempts=0)
        if current['attempts'] >= 8:
            row.update(dependency='margin_recovery_limit')
            return None
        row.update(goal={'x':destination[0],'z':destination[1]},dependency='margin_recovery',outcome='active',
                   clearance_verified=False,dynamic_passability_verified=False,attempts=current['attempts'])
        return destination

    def recenter(self, state, now):
        """L-reset a pad's camera only when pad-space may have drifted from its actor's heading.

        PSO's L reset makes pad-relative forward match the actor's native heading, and the
        trailing camera keeps that true while the actor walks. Resetting both pads every tick
        showed as constant reframing and froze movement .20 s per tick (operator 2026-11-02):
        reset a pad only when its last reset is stale or its actor has turned since. Returns
        True when any pad was reset, so the caller re-reads the moved-on world."""
        due = []
        for slot, player in state.get("players", {}).items():
            heading = player.get("heading_deg")
            last = self.recentered.get(slot)
            if (last is None or now - last[0] >= RECENTER_S or heading is None
                    or abs(delta(heading, last[1])) >= RECENTER_TURN_DEG):
                due.append(slot)
                self.recentered[slot] = (now, heading if heading is not None else 0.0)
        if due:
            self.inputs.hold([(slot, ["l"], .08) for slot in due])
            solo.wait(.20 / self.inputs.speed(), self.inputs.stopped)
        return bool(due)

    def tick_town(self, state):
        identity = self.town.bind(state)
        if identity is None:
            return False
        # A held route must release all inputs, including camera recentering.
        if not self.town.plan(state, time.monotonic()):
            return False
        if self.recenter(state, time.monotonic()):
            fresh = self.reader.snapshot()
            if self.town.bind(fresh) != identity:
                return False
        else:
            fresh = state
        waypoints = self.town.plan(fresh, time.monotonic())
        commands = [(slot, movement_keys(fresh["players"][slot], point), self.town.pulse_seconds(slot))
                    for slot, point in waypoints.items()]
        if not commands:
            return False
        for slot, point in waypoints.items():
            self.town.target(slot, point)
        self.inputs.hold(commands)
        for slot in waypoints:
            self.town.moved(slot)
        # Re-read on the next tick; no persistent room-wall learning is made
        # from these door approaches or from a cross-room transition.
        return True

    def forward_fallback(self, state, slot, player, now):
        """Geometry-free forward progress toward the room's exit affordance.

        When the verified field grid is not yet proven (geometry_verified is not
        True) the whole FieldObjectives path is dead and the planner rarely yields
        a goal, so the buddies would stand still. Instead advance them toward the
        nearest forward affordance in their room - a floor switch to stand on,
        else the door/barrier it gates. P1 leads to the nearest switch/door; P2
        follows P1's committed choice or closes the gap. A per-slot approach is
        abandoned (cooled down) once it stops getting closer, rotating to the next
        candidate rather than pushing a wall forever. Movement itself still routes
        through nav.route, which is permissive when no collision grid exists."""
        finite = lambda row: all(type(row.get(k)) in (int, float) and math.isfinite(row[k])
                                 for k in ('x', 'z'))
        if not finite(player):
            return None
        room = player.get('room')
        px, pz = player['x'], player['z']
        identity = (state.get('episode'), state.get('floor'), state.get('geometry_identity'))
        book = self.fallback.get(identity)
        if book is None or book.get('_room') != room:
            book = self.fallback[identity] = {'_room': room, 'cooldown': {}, 'slots': {}}
            if len(self.fallback) > 16:
                self.fallback.pop(next(iter(self.fallback)))
        cooldown = book['cooldown']

        def candidates(same_room):
            rows = []
            for e in state.get('entities', ())[:512]:
                if e.get('class') not in FORWARD_FALLBACK_CLASSES or not finite(e):
                    continue
                if same_room and e.get('room') != room:
                    continue
                gkey = (str(e.get('class')), round(e['x'], 1), round(e['z'], 1))
                if cooldown.get(gkey, 0) > now:
                    continue
                is_switch = 0 if e.get('class') in FORWARD_SWITCH_CLASSES else 1
                rows.append((is_switch, math.hypot(e['x'] - px, e['z'] - pz), gkey, e))
            rows.sort(key=lambda r: (r[0], r[1]))
            return rows

        if slot == 2:
            leader = book['slots'].get(1)
            buddy = state['players'][1]
            if leader and leader.get('room') == room:
                return leader['x'], leader['z']
            if finite(buddy) and buddy.get('room') == room and math.hypot(buddy['x'] - px, buddy['z'] - pz) > 40:
                return buddy['x'], buddy['z']

        for _ in range(8):
            rows = candidates(True) or candidates(False)
            if not rows:
                book['slots'].pop(slot, None)
                return None
            _, dist, gkey, entity = rows[0]
            track = book['slots'].get(slot)
            if track is None or track.get('gkey') != gkey:
                track = book['slots'][slot] = {'gkey': gkey, 'best': dist, 'since': now}
            elif dist < track['best'] - 2:
                track.update(best=dist, since=now)
            elif now - track['since'] > FALLBACK_STALL_S and dist > FALLBACK_REACH:
                cooldown[gkey] = now + 30
                book['slots'].pop(slot, None)
                continue
            track.update(room=room, x=entity['x'], z=entity['z'], cls=str(entity.get('class')))
            if slot == 1:
                stats = getattr(self.inputs, 'stats', None)
                if isinstance(stats, dict):
                    stats['forward_fallback_target'] = str(entity.get('class'))
                    stats['forward_fallback_dist'] = round(dist, 1)
            return entity['x'], entity['z']
        book['slots'].pop(slot, None)
        return None

    def _forward_dwell_telemetry(self, state, now, engaged):
        """Scalar fail-safe telemetry: how long P1 has held one room with no forward
        translation. The telemetry endpoint drops nested dicts, so these stay flat.
        forward_stuck crossing FALLBACK_STUCK_S is the operator's cue that the
        physical switch/door path has not progressed (see report: a RAM door-unlock
        fail-safe needs the TObjDoor open-flag offset reverse-engineered first)."""
        stats = getattr(self.inputs, 'stats', None)
        if not isinstance(stats, dict):
            return
        p1 = state.get('players', {}).get(1) or {}
        room = p1.get('room')
        key = (state.get('episode'), state.get('floor'), room)
        here = (p1.get('x'), p1.get('z'))
        moved = lambda a, b: (all(type(v) in (int, float) and math.isfinite(v) for v in (*a, *b))
                              and math.hypot(a[0] - b[0], a[1] - b[1]) > 6)
        rec = self.room_dwell.get('_cur')
        if rec is None or rec['key'] != key:
            rec = self.room_dwell['_cur'] = {'key': key, 'since': now, 'anchor': here}
        elif moved(here, rec['anchor']):
            rec.update(since=now, anchor=here)
        dwell = now - rec['since']
        stats['forward_room'] = room
        stats['forward_time_in_room_s'] = round(dwell, 1)
        stats['forward_stuck'] = dwell >= FALLBACK_STUCK_S
        stats['forward_fallback_engaged'] = bool(engaged)

    def tick(self, state):
        if not state.get("verified") or len(state.get("players", {})) != 2:
            return False
        if (self.town_enabled and state.get("phase") == 14 and state.get("episode") == 1
                and state.get("floor") == 0):
            return self.tick_town(state)
        from .pso_coop_frontier import same_room_threats
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
        commands, moves, attack_rows, margin_slots = [], {}, {}, []
        steering, fallback_slots = {}, []
        dbg = {}
        envelopes = {slot: self.weapon_ranges.for_player(state, slot) if enemies else FALLBACK for slot in (1, 2)}
        # Recenter only on drift (see recenter()); after a reset the world moved
        # on during the hold, so choose input from a fresh read.
        if self.recenter(state, now):
            fresh = self.reader.snapshot()
            if (not fresh.get("verified") or (fresh.get("episode"), fresh.get("floor")) !=
                    (state.get("episode"), state.get("floor"))):
                return False
            state = fresh
            enemies = [e for e in state["entities"] if e.get("kind") == "enemy" and e.get("hp", 0) > 0]
        field_revision = self.field.revision
        for slot, player in state["players"].items():
            self.combat_status.pop(slot,None)
            if player["hp"] <= 0:
                continue
            envelope = envelopes[slot]
            if envelope.get('verified') and envelope.get('player_ptr') != player['ptr']:
                envelope = FALLBACK
            self.combat_status[slot] = dict(range=envelope,target=None,room=player.get('room'),
                                           player_ptr=player.get('ptr'))
            nearby = sorted((e for e in enemies if e.get("room") == player.get("room")),
                            key=lambda e: math.hypot(e["x"] - player["x"], e["z"] - player["z"]))
            if not nearby and enemies:
                # Room ids can lag the live actor; still engage an enemy that is
                # physically within reach. The weapon envelope still gates the shot.
                nearby = sorted((e for e in enemies
                                 if math.hypot(e["x"] - player["x"], e["z"] - player["z"]) <= COMBAT_NEARBY_RADIUS),
                                key=lambda e: math.hypot(e["x"] - player["x"], e["z"] - player["z"]))
            target = next((e for e in nearby if self.cooldown.get((slot, e["ptr"]), 0) <= now), None)
            nav = self.maps.get(state, player)
            field_owned = bool(state.get("floor", 0) > 0 and state.get("geometry_verified"))
            dbg[f'{slot}_tgt'] = bool(target); dbg[f'{slot}_fo'] = field_owned
            dbg[f'{slot}_navfloor'] = nav.floor is not None
            dbg[f'{slot}_gates'] = sum(1 for e in state.get('entities', ())
                                       if e.get('class') in FORWARD_FALLBACK_CLASSES and e.get('room') == player.get('room'))
            field_destination = self.field.destination(state, slot, nav, now) if field_owned else None
            if nav.floor is not None:
                self.margin_attempts.pop(slot,None)
            if field_owned and nav.floor is None and target is None:
                waypoint = self.margin_waypoint(state,slot,player)
                if waypoint is not None:
                    commands.append((slot,movement_keys(player,waypoint),.04))
                    margin_slots.append(slot)
                    steering[slot] = (player, waypoint, 'margin_recovery')
                else:
                    # No own verified collision grid and margin recovery is
                    # unavailable: a buddy whose collision layer never resolves
                    # would idle here and deadlock the pair (P1 then waits on it
                    # forever). Still advance, bounded and geometry-free, toward
                    # the room's forward switch/door / the leader. nav.route is
                    # permissive when floor is None; movement stays short-pulsed.
                    dest = self.forward_fallback(state, slot, player, now)
                    dbg[f'{slot}_nogrid_fb'] = dest is not None
                    if dest is not None:
                        route = nav.route((player["x"], player["z"]), dest)
                        wp = route[1] if route and len(route) > 1 else dest
                        commands.append((slot, movement_keys(player, wp), .40))
                        moves[slot] = (player, wp, nav, True)
                        steering[slot] = (player, wp, 'forward_fallback_nogrid')
                        fallback_slots.append(slot)
                continue
            destination = None
            if target:
                dist, angle, vertical_ok = attack_geometry(player, target, envelope)
                row = self.engagements.observe(state, slot, target, envelope, now)
                recovery, recovery_goal = self.engagements.recovery(row, player, target, envelope, now)
                self.combat_status[slot] = dict(range=envelope, target=target['class'],
                    distance=round(dist, 2), heading_error=round(angle, 2), vertical_ok=vertical_ok,
                    unchanged_hp_attempts=row['attempts'], recovery=recovery,
                    damage_attribution='shared_target_hp_only')
                if recovery == 'defer' or (not vertical_ok and dist < 4):
                    self.cooldown[(slot, target['ptr'])] = now + 8
                    self.engagements.rows.pop(slot, None)
                    continue
                elif recovery_goal is not None:
                    destination = recovery_goal
                elif dist <= envelope['horizontal'] and vertical_ok and abs(angle) <= envelope['horizontal_half_angle']:
                    if now - self.last_attack.get(slot, 0) >= .52 / self.inputs.speed():
                        commands.append((slot, ["a"], .12))
                        attack_rows[slot] = row
                    continue
                elif dist <= envelope['horizontal'] and vertical_ok:
                    if row['aim_angle'] is None or abs(angle) < row['aim_angle'] - 2:
                        row['aim_angle'], row['aim_at'] = abs(angle), now
                    elif now - row['aim_at'] > 4:
                        self.cooldown[(slot, target['ptr'])] = now + 8
                        self.engagements.rows.pop(slot, None)
                        continue
                    # Reobserve after a small steering pulse. Rounding a small
                    # error into the forward octant cannot align a narrow gun cone.
                    commands.append((slot, ['lleft' if angle > 0 else 'lright'],
                                     .02 if field_owned and nav.floor is None else max(.02, min(.12, abs(angle) / 450))))
                    moves[slot] = (player, (target['x'], target['z']), self.maps.get(state, player), False)
                    steering[slot] = (player, (target['x'], target['z']), 'local_aim')
                    continue
                else:
                    if field_owned and nav.floor is None:
                        waypoint = self.margin_waypoint(state,slot,player)
                        if waypoint is not None:
                            commands.append((slot,movement_keys(player,waypoint),.04))
                            margin_slots.append(slot)
                            steering[slot] = (player, waypoint, 'margin_recovery')
                        continue
                    destination = (self.field.combat_goal(nav,player,target,envelope) if field_owned else
                                   (target["x"],target["z"]))
                    if field_owned and destination is None:
                        self.field.status['players'].setdefault(str(slot),{}).update(
                            goal=None,dependency='no_reachable_attack_position',outcome='held')
                        self.combat_status[slot]['approach'] = 'no_reachable_attack_position'
                        self.cooldown[(slot,target['ptr'])] = now+8
                        continue
                    if field_owned:
                        self.combat_status[slot]['approach'] = 'verified_layer_attack_position'
                        self.field.status['players'].setdefault(str(slot),{}).update(
                            goal={'x':destination[0],'z':destination[1]},
                            dependency='combat_approach',outcome='active')
            else:
                self.engagements.rows.pop(slot, None)
                goal = None if field_owned else self.goals.get(slot)
                if field_owned:
                    destination = field_destination
                if goal and goal["identity"] == room_key(state, player)[0]:
                    destination = goal["x"], goal["z"]
                    if math.hypot(destination[0] - player["x"], destination[1] - player["z"]) < 9:
                        self.goals.pop(slot, None)
                        destination = None
                # Buddy 2 closes separation when there is no independently read
                # puzzle goal; it never blindly teleports to the leader's room.
                buddy = state["players"][3 - slot]
                if not field_owned and destination is None and slot == 2 and buddy.get("room") == player.get("room") and math.hypot(buddy["x"] - player["x"], buddy["z"] - player["z"]) > 65:
                    destination = buddy["x"], buddy["z"]
                # Last resort: without a verified grid, still advance toward the
                # room's forward switch/door instead of standing still.
                dbg[f'{slot}_goal'] = bool(goal); dbg[f'{slot}_destpre'] = destination is not None
                # Advance toward the room's forward switch/door instead of idling
                # when nothing else produced a destination: either geometry is
                # unverified (not field_owned), or the field objective is None
                # while both buddies share the room (e.g. P1 pinned on
                # waiting_for_buddy because P2's collision layer never resolves).
                if destination is None and target is None and (not field_owned
                        or state["players"][3 - slot].get("room") == player.get("room")):
                    destination = self.forward_fallback(state, slot, player, now)
                    dbg[f'{slot}_fbret'] = destination is not None
                    if destination is not None:
                        fallback_slots.append(slot)
            if destination is None:
                dbg[f'{slot}_end'] = 'dest_none'
                continue
            if field_owned and nav.floor is None:
                # Local observed defense above may attack/aim in range. Never
                # convert a missing player projection into unbounded pursuit,
                # retreat, or the generic .40-second movement fallback.
                waypoint = self.margin_waypoint(state,slot,player)
                if waypoint is not None:
                    commands.append((slot,movement_keys(player,waypoint),.04))
                    margin_slots.append(slot)
                    steering[slot] = (player, waypoint, 'margin_recovery')
                continue
            identity = (slot, state.get("episode"), state.get("floor"), player.get("room"),
                        (target["ptr"], row['recoveries'] if recovery_goal is not None else 0)
                        if target else (round(destination[0]), round(destination[1])))
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
                dbg[f'{slot}_end'] = 'approach_stall'
                self.goals.pop(slot, None)
                self.approaches.pop(identity, None)
                continue
            if len(self.approaches) > 128:
                self.approaches.pop(next(iter(self.approaches)))
            nav = self.maps.get(state, player)
            route = (self.field.route(nav,(player["x"],player["z"]),destination)
                     if field_owned and slot not in fallback_slots else
                     nav.route((player["x"], player["z"]), destination))
            if not route:
                dbg[f'{slot}_end'] = 'route_fail'; dbg[f'{slot}_blocked'] = len(getattr(nav, 'blocked', ()))
                self.goals.pop(slot, None)
                continue
            dbg[f'{slot}_end'] = 'moved'
            waypoint = route[1] if len(route) > 1 else destination
            # Five-unit collision cells need short observed pulses; a long
            # hold can cross a corner beyond the verified adjacent edge.
            duration = .08 if nav.floor is not None else .40
            commands.append((slot, movement_keys(player, waypoint), duration))
            moves[slot] = (player, waypoint, nav, not nearby)
            steering[slot] = (player, waypoint, 'native_route')
        _stats = getattr(self.inputs, 'stats', None)
        if isinstance(_stats, dict):
            for _k, _v in dbg.items():
                _stats['dbg_' + _k] = _v
        self._forward_dwell_telemetry(state, now, bool(fallback_slots))
        if self.field.revision != field_revision:
            # First route selection can perform several bounded searches.
            # Cache the objective, then reobserve before movement or attack.
            return False
        if not commands:
            return False
        movement_speed = self.inputs.speed()
        movement_epoch = getattr(getattr(self.inputs, "ad", None), "_pso_timing_epoch", 0)
        learning_safe = getattr(self.inputs, "wall_learning_safe", lambda: self.inputs.speed() == 1)
        movement_timing_safe = learning_safe()
        steering_row = self._steering_begin(state, steering, commands)
        try:
            self.inputs.hold(commands)
        except BaseException:
            self._steering_finish(steering_row, None, 'delivery_interrupted')
            raise
        self._steering_delivered(steering_row)
        for slot in margin_slots:
            self.margin_attempts[slot]['attempts'] += 1
        for slot, keys, _ in commands:
            if keys == ["a"]:
                self.last_attack[slot] = now
                self.attacks += 1
                attack_rows[slot]['attempts'] += 1
        solo.wait(.08 / self.inputs.speed(), self.inputs.stopped)
        try:
            after = self.reader.snapshot()
        except BaseException:
            self._steering_finish(steering_row, None, 'post_observation_failed')
            raise
        self._steering_finish(steering_row, after, 'observed')
        for slot, (before, intended, nav, quiet) in moves.items():
            p = after.get("players", {}).get(slot)
            if not p:
                continue
            reliable = (movement_timing_safe and learning_safe() and self.inputs.speed() == movement_speed and
                        getattr(getattr(self.inputs, "ad", None), "_pso_timing_epoch", 0) == movement_epoch and
                        after.get("verified") and not after.get("travelling") and quiet and
                        p["hp"] == before["hp"] and p.get("room") == before.get("room") and
                        p.get("ptr") == before.get("ptr") and room_key(after, p)[0] == room_key(state, before)[0] and
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


def observe_menu_controls(menu, frame, state, controller, inputs, stats):
    """A visible menu can coexist with phase 14; stop movement before either pad path."""
    paused = menu.observe_frame(frame, native_gameplay=bool(state.get("verified") and state.get("phase") == 14),
                                identity=state_identity(state))
    stats["menu_controls_paused"] = paused
    stats["menu_observation"] = menu.observation
    if paused:
        controller.goals.clear()
        controller.approaches.clear()
        if hasattr(controller, 'engagements'):
            controller.engagements.rows.clear()
        inputs.release()
        stats["action"] = "waiting_for_observed_menu"
    return paused


def apply_default_speed(ad, stats):
    """Step the emulator to the default run speed once per launch, after the pads verify.

    Operator 2026-11-02: the buddies play at 2x so a run reaches each teleporter in
    reasonable time. One-shot (``_pso_coop_speed_defaulted``), so the operator's own
    later speed choice is never overridden; a failed step is recorded, never raised."""
    if (getattr(ad, "_pso_coop_speed_defaulted", False)
            or getattr(ad, "autoplay_speed", 1) >= DEFAULT_AUTOPLAY_SPEED
            or not callable(getattr(ad, "set_autoplay_speed", None))):
        return
    ad._pso_coop_speed_defaulted = True
    try:
        stats["default_speed"] = ad.set_autoplay_speed(DEFAULT_AUTOPLAY_SPEED)
    except Exception as exc:                       # noqa: BLE001 - speed is best-effort, never blocks play
        stats["default_speed_error"] = str(exc)[:200]


def play(ad, send, stopped, *, stats=None, driver=None, game=None, session_id="", upload=None, style=None):
    if driver is None:
        raise ValueError("PSO co-op requires an autoplay driver")
    stats = stats if stats is not None else {}
    reader, inputs = Reader(ad), Inputs(ad, stopped, send_primary=send,
        polite=bool((getattr(driver, "demo", False) or getattr(driver, "screensaver", None))
                    and not getattr(driver, "owns_keyboard", False)), stats=stats)
    authorization = getattr(ad, "_pso_coop_new_card", {}) or {}
    card_identity = hashlib.sha256(str(authorization.get("path", session_id)).encode()).hexdigest()[:20]
    root = Path(ad.config.runtime) / "autoplay" / "pso-coop" / card_identity
    root.mkdir(parents=True, exist_ok=True)
    characters = getattr(ad, "_pso_coop_characters", None) or saved_preferences(root / "character-preferences.json")
    ad._pso_coop_characters = characters
    binding = card_binding(authorization, getattr(ad, "memory_card_context", {}) or {})
    checkpoint = Checkpoint(root / "progress.json", card_identity, characters, card_path=binding)
    # A new controller reobserves routes, bosses and menus even on the same adapter.
    ledger = Progress()
    restored = checkpoint.restore(ledger)
    ad._pso_coop_progress = ledger
    stats["progress_restored"] = restored
    maps = Maps(root / "room-memory")
    controller = Controller(reader, inputs, maps)
    equipment = EquipmentRecovery(ad, session_id, driver, stopped)
    controller.weapon_ranges.recovery = equipment
    review_sampler = None
    try:
        from .pso_run_review import Sampler
        review_sampler = Sampler(session_id, (game or {}).get("game_id", ""))
    except Exception as exc:
        stats["pso_review_error"] = str(exc)[:240]
    speed_sampler = SpeedSampler(ad, session_id, stopped)
    planner = solo.Planner(driver, ad.config)
    planner.prompt = PROMPT
    planner.response_schema = PLAN_SCHEMA
    recorded = solo.recording_context(style, game)
    stats["recorded_input_evidence"] = recorded
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pso-coop-planner")
    pending, planned_identity, planned_frame, last_plan_at, errors = None, None, None, 0., 0
    menu, planner_errors = MenuProgress(players=2), 0
    planner_retry_at = 0.
    native_retry_identity = None
    mapping_attempts = 0
    def invalidate_plan():
        nonlocal pending, planned_identity, planned_frame, last_plan_at, planner_retry_at, native_retry_identity
        speed_sampler.invalidate()
        controller.goals.clear()
        controller.approaches.clear()
        planned_identity = planned_frame = None
        last_plan_at = 0.
        planner_retry_at = 0.
        native_retry_identity = None
        stats["native_control_during_recovery"] = False
        if pending is not None and pending.cancel():
            pending = None
        # Keep any running future until it finishes so its HTTP client is not
        # closed underneath it. Its result cannot authorize a later input.
        # MenuProgress retains unknown-menu bounds and its paused-controls guard.
    recovery = TransientRecovery(enabled=lambda: continuous_requested(driver, session_id),
        stopped=stopped, release=inputs.release, invalidate=invalidate_plan, wait=solo.wait, stats=stats)
    from .pso_coop_access import AccessPolicy
    access_policy = AccessPolicy(ad, reader, inputs, session_id, game or {}, stopped, invalidate_plan, stats)
    mapped = False
    ad._pso_verified_player_slots = set()
    seen_buddies = bool(getattr(ad, "_pso_coop_buddies_observed", False))
    stats.update(ledger.status(), characters=characters, controller_mapping_verified=False,
                 note="Two-controller campaign attempt; native receipts are required for completion.")
    try:
        while not stopped():
            try:
                stats["native_control_during_recovery"] = False
                inputs.check_speed()
                if getattr(ad, "paused", False):
                    solo.wait(.2, stopped)
                    continue
                state = reader.snapshot()
                equipment.observe(state)
                stats["equipment_recovery"] = equipment.status
                identity_context = buddy_context(characters, state, authorization, session_id,
                    seen=seen_buddies, awaiting_entry=ledger.awaiting_entry)
                seen_buddies = identity_context["existing_buddies"]
                ad._pso_coop_buddies_observed = seen_buddies
                ledger.observe(state)
                checkpoint.save(ledger)
                controller.town_enabled = ledger.target == 1 and not ledger.awaiting_entry
                while ledger.pending_receipts:
                    receipt = ledger.pending_receipts.pop(0)
                    with (root / "finishes.jsonl").open("a", encoding="utf-8") as output:
                        output.write(json.dumps(receipt) + "\n")
                    stats["last_receipt"] = receipt
                    controller.goals.clear()
                stats.update(ledger.status(), episode=state.get("episode"), floor=state.get("floor"),
                             native_players=state.get("players", {}), requested_speed=inputs.speed(),
                             observed_enemy_damage=controller.damage, observed_kills=controller.kills,
                             attack_inputs=controller.attacks, remembered_blocked_edges=controller.blocked,
                             combat=controller.combat_status, town_navigation=controller.town.status,
                             field_navigation=getattr(getattr(controller, "field", None), "status", {}),
                             no_damage_repositions=controller.engagements.recoveries,
                             no_damage_deferrals=controller.engagements.deferred)
                stats["door_requirements"] = state.get("door_requirements", {})
                try:
                    if review_sampler is not None:
                        review_sampler.offer(state, controller, stats)
                except Exception as exc:
                    stats["pso_review_error"] = str(exc)[:240]
                if state.get("travelling"):
                    speed_sampler.invalidate()
                    stats["action"] = "waiting_for_area_loader"
                    solo.wait(.15, stopped)
                    continue
                menu_frame = ad.get_frame()
                menu_paused = observe_menu_controls(menu, menu_frame, state, controller, inputs, stats)
                proposed = known_menu_command(menu.observation, finish_save=ledger.awaiting_entry is True)
                if menu_paused and proposed is not None and not recovery.waiting:
                    # These exact observed menus need no model guess or network
                    # round trip. The existing guard remains the sole authority.
                    selected, reason = menu.review({'screen': 'menu'}, [proposed], state_identity(state),
                        frame=menu_frame, fresh_frame=ad.get_frame(),
                        native_gameplay=bool(state.get('verified') and state.get('phase') == 14),
                        finish_save=ledger.awaiting_entry is True,
                        target_episode=ledger.target, target_difficulty=ledger.difficulty)
                    invalidate_plan()
                    stats.update(menu_repeated_attempts=menu.repeats, menu_input_withheld=reason,
                        menu_independent_selection=menu.previous.get('independent_selection'),
                        planned_input_player=selected[0][0] if selected else 0,
                        planned_input_keys=','.join(selected[0][1]) if selected else '',
                        action='observed_menu_step' if selected else 'waiting_for_observed_menu')
                    if menu.stalled:
                        stats.update(ok=False, campaign_state='needs_operator', stopped_reason=reason)
                        break
                    for command in selected[:1]:
                        inputs.hold([command])
                        menu.previous['input_delivery_verified'] = True
                    # Let selection/transition animation settle, with Stop and
                    # takeover interruptible. Reobserve before every next input.
                    solo.wait(.6 if selected else .2, stopped)
                    continue
                if state.get("verified") and not mapped and not menu_paused and not recovery.waiting:
                    retained = mapping_continuity.restore(ad, reader, session_id, game or {}, stopped)
                    stats.update(mapping_continuity.diagnostics(ad))
                    if retained is not None:
                        stats["controller_mapping"] = retained['probe']
                        state = retained['state']
                        stats['controller_mapping_source'] = 'same_live_adapter_revalidated'
                    else:
                        try:
                            stats["controller_mapping"] = mapping_continuity.prove(
                                ad, reader, inputs, state, session_id, game or {}, stopped, mapping_probe)
                        except MappingPending as exc:
                            if not continuous_requested(driver, session_id):
                                raise
                            invalidate_plan()
                            inputs.release()
                            ad._pso_verified_player_slots = set()
                            mapping_attempts += 1
                            delay = min(5, 2 ** min(mapping_attempts - 1, 3))
                            stats.update(controller_mapping_verified=False, mapping_attempts=mapping_attempts,
                                mapping_retry_backoff_s=delay, mapping_last_error=str(exc),
                                action="waiting_for_spawn_ready")
                            solo.wait(delay, lambda: stopped() or not continuous_requested(driver, session_id))
                            if stopped() or not continuous_requested(driver, session_id):
                                break
                            continue
                        finally:
                            stats.update(mapping_continuity.diagnostics(ad))
                        stats['controller_mapping_source'] = 'two_pad_movement_probe'
                    if stopped():
                        raise InterruptedError('PSO stopped before activating controller mapping')
                    mapped = True
                    ad._pso_verified_player_slots = {0, 1}
                    mapping_attempts = 0
                    stats.update(controller_mapping_verified=True, mapping_retry_backoff_s=0, mapping_last_error="")
                    apply_default_speed(ad, stats)
                    state = reader.snapshot()
                if access_policy.step(state, mapped=mapped, menu_paused=menu_paused, waiting=recovery.waiting):
                    # Reobserve flags, actors and menu after any native access work.
                    solo.wait(.05, stopped)
                    continue
                if state.get("phase") != 14:
                    mapped = False
                    mapping_continuity.invalidate(ad, 'native_phase_' + str(state.get('phase')))
                    stats.update(mapping_continuity.diagnostics(ad))
                elif mapped:
                    mapping_continuity.observe(ad, state, session_id, game or {}, stopped)
                if (recovery.waiting and mapped and not menu_paused and
                        continuous_requested(driver, session_id)):
                    identity = state_identity(state)
                    if native_retry_identity != identity:
                        # Fresh RAM alone cannot restore input authority. Recheck
                        # the sealed proof against this exact live process/card/
                        # pad configuration, without another movement probe.
                        native_retry_identity = None
                        retained = mapping_continuity.restore(ad, reader, session_id, game or {}, stopped)
                        if retained is not None and state_identity(retained['state']) == identity:
                            state = retained['state']
                            native_retry_identity = identity
                stats["achieved_speed_observation"] = speed_sampler.observe(state)
                if speed_sampler.failure:
                    stats["speed_sampling_error"] = speed_sampler.failure
                if pending is not None and pending.done():
                    completed, pending = pending, None  # a failed future must not be read again forever
                    if planned_identity is None:
                        stats["action"] = "discarded_stale_plan"
                        last_plan_at = 0.
                        continue
                    stats['planner_latency_s'] = round(time.monotonic() - last_plan_at, 3)
                    plan = None
                    try:
                        plan = completed.result()
                        selected = actions(plan)
                    except (OSError, ValueError, KeyError, httpx.HTTPError) as exc:
                        planner_errors += 1
                        stats.update(planner_consecutive_errors=planner_errors,
                                     planner_state='failed_observation',
                                     planner_last_error=f'{type(exc).__name__}: {exc}'[:400],
                                     planner_failures=stats.get('planner_failures', 0) + 1)
                        if isinstance(exc, ValueError) and continuous_requested(driver, session_id):
                            # Invalid model output has no input authority. Keep
                            # independently verified native control available;
                            # clear old goals and ask again at a bounded rate.
                            invalidate_plan()
                            inputs.release()
                            delay = min(30, 8 * 2 ** min(planner_errors - 1, 2))
                            planner_retry_at = time.monotonic() + delay
                            stats.update(planner_state="discarded_invalid_plan",
                                planner_invalid_responses=stats.get("planner_invalid_responses", 0) + 1,
                                planner_invalid_sample=repr(plan.get("actions") if isinstance(plan, dict) else plan)[:800],
                                planner_retry_backoff_s=delay, action="discarded_invalid_plan")
                            solo.wait(.05, stopped)
                            continue
                        if recovery.pause(exc, "planner"):
                            continue
                        if planner_errors >= 5:
                            stats.update(ok=False, campaign_state='needs_operator',
                                         stopped_reason='Five planner observations failed; inputs released')
                            break
                        solo.wait(min(planner_errors, 3), stopped)
                        continue
                    planner_errors = 0
                    stats.update(planner_consecutive_errors=0, planner_last_error='', planner_retry_backoff_s=0, planner_state='observed',
                                 planner_actions=len(selected), planner_responses=stats.get('planner_responses', 0) + 1)
                    stats.update(thought=str(plan.get("thought", ""))[:400], screen=plan.get("screen", "unknown"),
                                 difficulty_locked=bool(plan.get("difficulty_locked")))
                    if plan.get("needs_operator"):
                        stats.update(ok=False, campaign_state="needs_operator", stopped_reason=stats["thought"])
                        break
                    if state_identity(state) == planned_identity:
                        recovery.observed()
                        stats["native_control_during_recovery"] = False
                        digest = hashlib.sha256(planned_frame).hexdigest()
                        if plan.get("screen") == "credits" and ledger.boss_zero:
                            (root / (digest + ".png")).write_bytes(planned_frame)
                        receipt = ledger.ending(plan.get("screen"), digest, time.time())
                        checkpoint.save(ledger)
                        if receipt:
                            with (root / "finishes.jsonl").open("a", encoding="utf-8") as output:
                                output.write(json.dumps(receipt) + "\n")
                            stats["last_receipt"] = receipt
                            controller.goals.clear()
                        elif not (plan.get("screen") == "credits" and ledger.boss_zero):
                            if not menu_paused and plan.get("screen") == "gameplay":
                                controller.accept_goals(plan, state)
                            # Combat is always chosen from current RAM; a slow model
                            # cannot inject stale movement into a currently busy fight.
                            from .pso_coop_frontier import same_room_threats, field_actions
                            combat = state.get("verified") and any(same_room_threats(state, p) for p in state.get("players", {}).values())
                            selected = field_actions(selected, state)
                            if menu_paused or not combat or any(p.get("hp", 0) < p.get("hp_max", 1) * .35 for p in state.get("players", {}).values()):
                                # The grounded town route owns movement in this one scene.
                                # A model may still operate independently observed menus.
                                if (controller.town_enabled and not menu_paused and
                                        state.get("phase") == 14 and state.get("episode") == 1 and
                                        state.get("floor") == 0 and plan.get("screen") == "gameplay"):
                                    selected = []
                                if (not menu_paused and state.get("floor", 0) > 0 and
                                        state.get("geometry_verified") and plan.get("screen") == "gameplay"):
                                    selected = []
                                selected, reason = menu.review(plan, selected, state_identity(state),
                                    frame=planned_frame, fresh_frame=ad.get_frame(),
                                    native_gameplay=bool(state.get('verified') and state.get('phase') == 14),
                                    finish_save=ledger.awaiting_entry is True,
                                    target_episode=ledger.target, target_difficulty=ledger.difficulty)
                                stats.update(menu_repeated_attempts=menu.repeats, menu_input_withheld=reason,
                                             menu_independent_selection=menu.previous.get('independent_selection'),
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
                if (pending is None and time.monotonic() >= planner_retry_at and
                        time.monotonic() - last_plan_at > (2.1 if ledger.boss_zero else 8)):
                    context = {**ledger.status(), **buddy_context(characters, state, authorization, session_id,
                                   seen=seen_buddies, awaiting_entry=ledger.awaiting_entry),
                               "native_state": state, "controller_mapping_verified": mapped,
                               "menu_controls_paused": menu_paused,
                               "current_goals": controller.goals,
                               "previous_menu_attempt": menu.previous,
                               "recorded_input_evidence": recorded}
                    planned_frame, planned_identity = ad.get_frame(), state_identity(state)
                    planner.prompt, planning_context = planner_input(context)
                    pending = executor.submit(planner, planned_frame, planning_context)
                    last_plan_at = time.monotonic()
                    stats.update(planner_requests=stats.get('planner_requests', 0) + 1,
                                 planner_state='waiting', input_polite=inputs.polite,
                                 second_pad_polite_supported=inputs.has_polite)
                native_retry_ready = (native_retry_identity == state_identity(state) and
                                      continuous_requested(driver, session_id))
                if mapped and state.get("verified") and (not recovery.waiting or native_retry_ready):
                    # Reobserve after any planner input; Start/menu overlays leave
                    # native phase 14 unchanged and must never receive steering/L.
                    menu_paused = observe_menu_controls(menu, ad.get_frame(), state, controller, inputs, stats)
                    if not menu_paused:
                        if recovery.waiting:
                            stats.update(recovery_state="native_control_available_planner_retrying",
                                         native_control_during_recovery=True)
                        if equipment.tick(state, menu_allowed=True):
                            # Existing native equipment work may have changed the
                            # active item. Discard all pre-call plans and reobserve
                            # actors/menu before any controller command.
                            invalidate_plan()
                            controller.weapon_ranges.cache.clear()
                            controller.weapon_ranges.attempted.clear()
                            controller.engagements.rows.clear()
                            inputs.release()
                            stats["action"] = "reobserving_after_equipment_recovery"
                            continue
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
                if recovery.pause(exc, "observation"):
                    continue
                if errors >= 5:
                    stats.update(ok=False, stopped_reason="Five consecutive observations failed; controller inputs released")
                    break
                solo.wait(min(errors, 3), stopped)
    finally:
        equipment.clear("bot_stopped")
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
