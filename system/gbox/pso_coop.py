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
from .pso_coop_nav import Maps, room_key, geometry_view
from .pso_coop_native import context as native_context, SpeedSampler
from .pso_coop_menu import MenuProgress, known_menu_command
from .pso_coop_progress import Checkpoint, card_binding
from .pso_coop_recovery import TransientRecovery, continuous_requested
from . import pso_coop_mapping as mapping_continuity
from .pso_coop_combat import WeaponRanges, Engagements, EquipmentRecovery, FALLBACK, geometry as attack_geometry
from .pso_gc_live import PLAYER, VT_UPDATE
from .registry import Unsupported
from .debug import Unavailable as StubUnavailable      # a transient GDB-stub read refusal ("stub refused read")

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

    def send(self, events, player, *, check=True, held_ok=False):
        if player == 1 and self.send_primary is not None:
            result = self.send_primary(events)
        else:
            try:
                if self.has_polite:
                    result = self.ad.send_input_player(events, player=player, polite=self.polite)
                else:
                    result = self.ad.send_input_player(events, player=player)
            except RuntimeError as _exc:
                # STOPGAP (vpad-P2): the keyboard pad (player 2 on this adapter) needs the game window
                # focused; a docked/background Dolphin raises. Never let that kill play() (which rolls
                # back the hot-reload). Player 1 keeps driving on its virtual pad; player 2 is a no-op
                # until it gets its own virtual pad.
                self.stats['second_pad_input_error'] = str(_exc)[:200]
                self.stats.update(last_input_player=player,
                                  last_input_keys=','.join(e['key'] for e in events))
                return {"sent": 0, "held": "second pad needs window focus"}
        self.stats.update(last_input_player=player, last_input_keys=','.join(e['key'] for e in events),
                          last_input_requested=len(events),
                          last_input_sent=result.get('sent', 0) if isinstance(result, dict) else 0,
                          last_input_held=str(result.get('held') or result.get('stopped') or '')[:200] if isinstance(result, dict) else '')
        # held_ok: a HOLD's own down-press intentionally leaves its keys held - the focus-independent virtual pad
        # (gbox/vpad_linux.py, vpad_win.py) truthfully reports those keys in "held", which is NOT a delivery failure.
        # Without this, hold()'s down raised InputDeferred on the vpad before its release ran, collapsing every menu
        # hold into a sub-frame tap the game never polled - PSO sat on the recognised PRESS START title forever
        # (2026-11-04, watched live). Partial delivery (sent != len) and an explicit "stopped" still fail.
        if check and (not isinstance(result, dict) or result.get("sent") != len(events)
                      or (result.get("held") and not held_ok) or result.get("stopped")):
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
                self.send([{"key": k, "down": True} for k in keys], player, held_ok=True)
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
SWITCH_PRESS_S = 1.5          # dwell/press a panel this long, then rotate to the door it gates
SWITCH_FINE_DIST = 30.0       # within this of a switch, approach in short pulses so we land to press it
WEDGE_STALL_S = 4.0           # a buddy that barely translates toward its goal this long is wall-wedged
WEDGE_ESCAPE_S = 1.0          # hold the back-off/strafe escape heading this long before re-committing
WEDGE_MOVE = 6.0              # progress threshold: translating more than this clears the wedge
WEDGE_ESCAPE_REACH = 45.0     # first strafe/back-off detour (18 was too small to clear a wall to a far door)
WEDGE_ESCAPE_GROW = 35.0      # each successive wedged phase widens the detour by this
WEDGE_ESCAPE_MAX = 180.0      # cap the detour so an escape never flings a buddy across the whole area
FALLBACK_STUCK_S = 15.0       # operator fail-safe threshold: a room with no forward progress
FORCE_DOOR_DIST = 60.0        # P1 this close to the forward door it can't cross -> force-open that door
FORCE_DOOR_RETRY_S = 20.0     # re-arm a specific door's force-open this often (in case a flag was contested)
COORD_DRIVE_AFTER_S = 3.0     # (B) after this long unable to A* past a forward door in a cleared room, drive straight at it
COORD_FORCE_DIST = 110.0      # (B) looser force-open range while coordinate-driving the committed door
COORD_DRIVE_MAX_S = 40.0      # (B) abandon a single coordinate-drive commit after this (re-pick a forward door)
CROSS_DIST = 40.0            # (B) P1 this close to the committed door = ON it: plant and push straight through
CROSS_HOLD_S = 4.0           # (B) push straight through a door this long (no wedge away-sweep) before giving up on it
BLOCKED_GATE_S = 45.0        # (B) after a failed crossing, don't re-commit to that door for this long (explore elsewhere)
FENCE_PAIR_DIST = 95.0       # a TObjLazerFenceNorm + a TLazerFenceSw within this = a hold-switch pair (one holds, one passes)
FENCE_SWITCH_ON = 18.0       # P2 within this of the switch is standing ON it (holding the fence down)
FENCE_FINE_DIST = 36.0       # P2 this close to the plate -> TIGHT terminal approach (short precise pulses onto it)
FENCE_CROSS_OVERSHOOT = 45.0 # P1 aims this far PAST the fence so it commits across while P2 holds the switch
P2_PLACE_AFTER_S = 5.0       # P2 can't reach the hold-switch for this long -> RAM-write it onto the switch
FENCE_PAST_OVERSHOOT = 75.0  # how far PAST the fence to RAM-place P1 so it lands in the next room
P1_CROSS_PLACE_S = 5.0       # P1 at an open fence this long without crossing -> RAM-write it past the fence
FENCE_GIVEUP_S = 28.0        # ANTI-STALL: attempt a fence hold at most this long, then give up and keep MOVING
FENCE_RETRY_S = 45.0         # after giving up on a fence, explore/fight this long before re-attempting it
ADVANCE_STALL_S = 90.0       # FULL EXPLORATION (operator 11-03: explore + MAP every room before advancing; warp is
                             # LAST-RESORT anti-stuck, NOT normal progress). Normal progress = walking door-to-door,
                             # clearing each room; the timer RESETS on every NEW room, so a bot that keeps exploring
                             # never warps. Only when a CLEARED area yields NO new room for this long (reachable rooms
                             # exhausted) does it advance to the next floor. Never-stand (wander/idle-drift) keeps it
                             # MOVING through these windows - exploration IS constant movement. Boss floors exempt.
ADVANCE_WARP_GAP_S = 10.0    # minimum time between native floor warps (don't spam the loader)
STALL_HARDCAP_S = 120.0      # ABSOLUTE anti-freeze (non-boss) last resort: no new room for this long -> warp REGARDLESS
                             # of enemies/cleared state (a gate that genuinely can't be crossed must never permafreeze).
STUCK_MOVE_S = 3.0           # P1 hasn't physically TRANSLATED (>WEDGE_MOVE) for this long -> parked: wander to break it
BOSS_SAFETY_S = 600.0        # BOSS DEFEAT: absolute ceiling - hold a boss floor up to this (10 min) while winning; a
                             # boss we have DAMAGED is held to the kill within it, only a never-damaged boss escapes early
BOSS_FIRE_CADENCE_S = 0.12   # RAPID boss fire: press the attack as fast as the swing/shot animation allows (vs .34 normal)
                             # - 3x-speed only accelerates MELEE, so fast ranged fire at the mobile Dragon needs this cadence
BOSS_DEAD_GRACE_S = 10.0     # keep holding the boss floor this long after a boss last read alive (covers inter-phase hp==0)
BOSS_CHASE_CAP = 220.0       # approach a boss up to (real gun reach + this) before holding; beyond = relocating, don't chase
BOSS_FIRE_MARGIN = 0.95      # fire within this fraction of the EQUIPPED gun's real reach (build PMT: rifle 178.5u, shot 110.5,
                             # handgun 144.5, mechgun 72.25) - a shot from beyond the gun's reach falls short and never connects.
                             # Using the live weapon envelope auto-gives the mobile Dragon its full ~170u firing range (not a tight 60).
BOSS_FIRE_RANGE_FALLBACK = 70.0  # fire range when the weapon envelope is UNVERIFIED (mechgun-safe; close enough to connect for any gun)
BOSS_HOLD_TOL = 40.0         # "positioned" when within this of the stand point (orbit centre for a circling boss like the Dragon)
BOSS_WEDGE_S = 2.5           # boss approach not getting CLOSER for this long = wedged (arena mouth) -> straight force-through
BOSS_NOPROG_S = 75.0         # DAMAGE-PROGRESS escape: boss HP/parts not dropping for this long -> can't kill it yet,
                             # warp off and loop back (don't burn the full BOSS_SAFETY_S on an un-damageable boss)
PLAN_PUBLISH_S = 0.5         # throttle for the live-map room-graph PLAN publish (telemetry, map agent consumes it)
COMBAT_NEARBY_RADIUS = 60.0   # engage an enemy this close even when its room id does not match
# DODGE / combat positioning (operator 2026-11-02: "the bots should be learning to
# dodge - basically moving and positioning during battle"). During combat the party
# MOVES to avoid attacks instead of standing still tanking: when a threat is HOT
# (close, facing the bot, or a boss) and there is no clean shot to take THIS tick,
# the bot STRAFES perpendicular to the strongest threat's attack line (side-stepping
# out of it) and backs off when critically close, biased away from spots that have
# gotten the party killed before (see DeathMemory). When a shot IS lined up it fires,
# then dodges the next tick - so it fights WHILE moving. These bound the behaviour.
DODGE_DANGER_RADIUS = 58.0    # consider a regular enemy a threat to dodge within this
DODGE_BOSS_RADIUS = 130.0     # bosses telegraph big attacks - react from much farther out
DODGE_HOT_RADIUS = 54.0       # a regular enemy closer than this -> prioritise repositioning (operator 11-03: dodge FAR more readily)
DODGE_BOSS_HOT = 120.0        # a boss closer than this -> prioritise repositioning (bosses hit hard; evade almost always)
ATTACK_CADENCE_S = 0.34       # min time between attack presses at 1x (operator 11-03: attack FASTER/more often; was .52)
DODGE_CRITICAL = 20.0         # this close -> blend straight repulsion in (gain spacing, not just strafe)
DODGE_FACING_CONE = 55.0      # enemy heading within this of its bearing-to-player = aimed at the bot
DODGE_STEP = 30.0             # how far ahead the strafe waypoint is placed (telemetry/steering)
DEATH_BIAS_GAIN = 14.0        # weight of the learned fatal-spot avoidance in the strafe-side choice
MINE_AVOID_R = 36.0           # steer the dodge away from boss mine adds within this (operator: never stand on mines)
MINE_AVOID_GAIN = 3.0         # weight of mine avoidance in the strafe-side choice
# DEATH-DRIVEN LEARNING (operator: "keep track of each and every time they die and
# file a report for gBox to adjust the logic of their pathfinding and boss
# management"). The WRITE side (down-and-revive logging) lives in pso_master_build;
# DeathMemory below is the CONSUMER: it reads those records and turns each fatal
# position into a spatial repulsion field, so pathfinding and boss-fight positioning
# learn to avoid where the party died, improving run over run.
DEATH_GRID = 40.0             # fatal-spot bucket size in world units (coarse so nearby deaths pool)
DEATH_AVOID_RADIUS = 120.0    # a fatal bucket repels the bot within this range
DEATH_REFRESH_S = 4.0         # re-read the death log at most this often (cheap, failure-tolerant)
# Party model (operator 2026-11-02): P1 is the SOLE navigator - it leads, unlocks
# every door and completes the game, never waiting. P2 (and P3/P4) are dumb
# swarm-followers: orbit P1 and defend him, with NO independent navigation (that
# was the waiting_for_buddy deadlock root). These bound the follow/defend swarm.
SWARM_FOLLOW_RADIUS = 45.0    # a follower beyond this of the leader closes the gap (geometry-free)
SWARM_DEFEND_RADIUS = 90.0    # a follower engages any enemy within this of the leader (attack-dog)
SWARM_SPREAD = 14.0           # keep at least this off the leader so followers do not stack on him
BACKTRACK_RADIUS = 45.0       # P1 won't re-pick the door it just entered through when another exit exists
DOOR_RETRAVERSE_COOLDOWN_S = 30.0  # hold a just-crossed door shut so P1 explores the NEW room's forward
# door instead of re-crossing back; frontier (never-traversed) doors are exempt from cooling, so this only
# damps the backward connector P1 just came through, never genuine forward progress.
# A transient host focus/active-window condition (the adapter cannot send input
# because the game window is not in front) must NEVER end the run - PSO has to keep
# playing. The loop pauses this long, tries to raise the game window, then retries.
FOCUS_WAIT_BACKOFF_S = 0.5
FOCUS_WAIT_MARK = "must be active to send emulator input"


class DeathMemory:
    """DEATH-DRIVEN LEARNING consumer (my half of the loop; pso_master_build owns the
    WRITE half - the Scape-Doll/revive backstop that logs each down-and-revive event).

    A "death" is now a down-and-revive (the party is effectively unkillable), but it is
    still the strongest signal of a bad position / pattern. This class reads those
    records and buckets each fatal spot into a coarse per-area grid, exposing:
      - penalty(ep, floor, x, z): 0..~1, how deadly the bot's CURRENT spot has been,
      - avoid_vector(ep, floor, x, z): a unit-ish vector pointing AWAY from nearby
        fatal buckets (feeds the dodge strafe-side choice + boss positioning).
    So pathfinding and boss management bias away from where the party died, and that
    bias strengthens as deaths accumulate run over run.

    Reading is SCHEMA-ADAPTIVE and fail-soft (it must never break perpetual play): it
    tries, in order, (1) a live list the build side appends to the shared adapter
    (ad._pso_deaths), (2) pso_master_build.read_deaths(ad) if present, (3) a JSONL file
    under the campaign runtime root. Each record is normalised over common key spellings
    so it works whatever exact names the build side settles on."""

    def __init__(self, ad):
        self._ad = ad
        self._buckets = {}          # (ep, floor, bx, bz) -> count
        self._by_area = {}          # (ep, floor) -> list of (cx, cz, count)
        self._seen_ids = set()      # dedup keys for records already ingested
        self._count = 0
        self._refresh_at = 0.0
        self._file_mtime = None
        self._source = 'none'
        self._last_cause = ''
        self._last_floor = None
        self._revives_p1 = 0        # from pso_survival.death_stats (operator wants exact revive counts)
        self._revives_p2 = 0
        self._last_death_str = ''   # "<area>@<x>,<z>:<cause>" of the most recent down event

    @staticmethod
    def _num(v):
        return v if type(v) in (int, float) and math.isfinite(v) else None

    def _normalise(self, rec):
        if not isinstance(rec, dict):
            return None
        g = rec.get
        x = self._num(g('x', g('pos_x', g('px'))))
        z = self._num(g('z', g('pos_z', g('pz'))))
        if x is None or z is None:
            return None
        ep = g('episode', g('ep', g('target')))
        floor = g('floor', g('area', g('area_id')))
        cause = g('cause', g('reason', g('attacker', g('enemy', g('killer_class', '')))))
        ts = g('timestamp', g('ts', g('time', g('at'))))
        pid = g('id', g('death_id'))
        player = g('player', g('slot', g('player_index')))
        ident = pid if pid is not None else (player, ep, floor, round(float(x), 1), round(float(z), 1), ts)
        return {'ep': ep, 'floor': floor, 'x': float(x), 'z': float(z),
                'cause': str(cause)[:48], 'ident': ident}

    def _records(self):
        ad = self._ad
        # (1) AUTHORITATIVE: the build side's pso_survival reader (shipped f14f4bc3). It
        # returns recent down-and-revive events (newest last) and is fail-soft.
        try:
            from . import pso_survival
            fn = getattr(pso_survival, 'read_deaths', None)
            if callable(fn):
                recs = fn(ad, limit=400)
                if recs:
                    self._source = 'pso_survival.read_deaths'
                    return list(recs)
        except Exception:
            pass
        # (2) shared live list on the adapter, if the build side exposes one that way.
        live = getattr(ad, '_pso_deaths', None)
        if isinstance(live, (list, tuple)) and live:
            self._source = 'ad._pso_deaths'
            return list(live)
        # (3) a JSONL log under the campaign runtime root.
        root = getattr(ad, '_pso_map_root', None)
        for base in (root,):
            if not base:
                continue
            for name in ('deaths.jsonl', 'pso_deaths.jsonl'):
                try:
                    p = (base / name) if hasattr(base, '__truediv__') else None
                    if p is None or not p.exists():
                        continue
                    mt = p.stat().st_mtime
                    if self._source == 'file:%s' % name and mt == self._file_mtime:
                        return []                       # unchanged since last read
                    self._file_mtime = mt
                    self._source = 'file:%s' % name
                    out = []
                    for line in p.read_text(encoding='utf-8').splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            out.append(json.loads(line))
                        except ValueError:
                            continue
                    return out
                except OSError:
                    continue
        return []

    def refresh(self, now, root=None):
        if root is not None and self._ad is not None:
            try:
                self._ad._pso_map_root = root
            except Exception:
                pass
        if now - self._refresh_at < DEATH_REFRESH_S:
            return
        self._refresh_at = now
        # Exact revive counts + last-death summary (operator: "keep track of each and
        # every time they die"). From the build side's pso_survival.death_stats; fail-soft.
        try:
            from . import pso_survival
            fn = getattr(pso_survival, 'death_stats', None)
            ds = fn(self._ad) if callable(fn) else None
            if isinstance(ds, dict):
                if type(ds.get('revives_p1')) in (int, float):
                    self._revives_p1 = ds['revives_p1']
                if type(ds.get('revives_p2')) in (int, float):
                    self._revives_p2 = ds['revives_p2']
                last = ds.get('last_death')
                if isinstance(last, dict):
                    lx, lz = DeathMemory._num(last.get('x')), DeathMemory._num(last.get('z'))
                    self._last_death_str = '%s@%s,%s:%s' % (
                        last.get('area', last.get('floor', '?')),
                        ('%.0f' % lx) if lx is not None else '?',
                        ('%.0f' % lz) if lz is not None else '?',
                        str(last.get('cause', ''))[:24])
        except Exception:
            pass
        try:
            records = self._records()
        except Exception:
            records = []
        for raw in records[:4096]:
            rec = self._normalise(raw)
            if rec is None or rec['ident'] in self._seen_ids:
                continue
            self._seen_ids.add(rec['ident'])
            self._count += 1
            self._last_cause = rec['cause']
            self._last_floor = rec['floor']
            key = (rec['ep'], rec['floor'], round(rec['x'] / DEATH_GRID), round(rec['z'] / DEATH_GRID))
            self._buckets[key] = self._buckets.get(key, 0) + 1
            area = self._by_area.setdefault((rec['ep'], rec['floor']), [])
            cx, cz = round(rec['x'] / DEATH_GRID) * DEATH_GRID, round(rec['z'] / DEATH_GRID) * DEATH_GRID
            for i, (ex, ez, c) in enumerate(area):
                if ex == cx and ez == cz:
                    area[i] = (ex, ez, c + 1)
                    break
            else:
                area.append((cx, cz, 1))

    def penalty(self, episode, floor, x, z):
        area = self._by_area.get((episode, floor))
        if not area or type(x) not in (int, float) or type(z) not in (int, float):
            return 0.0
        worst = 0.0
        for cx, cz, c in area:
            d = math.hypot(cx - x, cz - z)
            if d <= DEATH_AVOID_RADIUS:
                worst = max(worst, (1.0 - d / DEATH_AVOID_RADIUS) * min(c, 4) / 4.0)
        return worst

    def avoid_vector(self, episode, floor, x, z):
        area = self._by_area.get((episode, floor))
        if not area or type(x) not in (int, float) or type(z) not in (int, float):
            return (0.0, 0.0)
        vx = vz = 0.0
        for cx, cz, c in area:
            dx, dz = x - cx, z - cz
            d = math.hypot(dx, dz)
            if 0 < d <= DEATH_AVOID_RADIUS:
                w = (1.0 - d / DEATH_AVOID_RADIUS) * min(c, 4)
                vx += dx / d * w
                vz += dz / d * w
        n = math.hypot(vx, vz)
        return (vx / n, vz / n) if n > 1e-6 else (0.0, 0.0)

    def stats(self, episode=None, floor=None, x=None, z=None):
        out = {'deaths_seen': self._count, 'death_buckets': len(self._buckets),
               'death_source': self._source, 'death_last_cause': self._last_cause,
               'death_last_floor': self._last_floor,
               'revives_p1': self._revives_p1, 'revives_p2': self._revives_p2,
               'last_death': self._last_death_str}
        if episode is not None:
            out['death_penalty_here'] = round(self.penalty(episode, floor, x, z), 3)
        return out


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
        self.death_memory = DeathMemory(getattr(reader, 'ad', None))  # death-driven learning consumer
        self._dodges = 0            # how many dodge (reposition-during-combat) pulses fired (flat telemetry)
        self._boss_adv = None       # per-tick boss weak-point advisor result (pso_boss_strategy)
        self._bosses_defeated = 0   # confirmed boss kills this run (flat telemetry: goal "defeat every boss")
        self._boss_present_now = False  # a boss entity is in the current state
        self._boss_alive_now = False    # a boss entity is alive (hp>0 or hp unreadable)
        self._boss_alive_at = 0.0       # last monotonic a boss read alive (inter-phase grace)
        self._boss_seen_alive = False   # saw a live boss on the current boss floor (kill-credit guard)
        self._boss_kill_key = None      # (episode, floor) already credited a kill for (no double-count)
        self._boss_floor_key = None     # (episode, floor) the per-visit boss trackers are anchored to
        self._boss_hp_best = None       # lowest boss hp_frac seen this visit (damage-progress signal)
        self._boss_damaged = False      # we have landed damage this visit (HP dropped / a part died) -> hold to the kill
        self._boss_nearest_row = None   # nearest live boss entity (weak-point fallback when the advisor is inactive)
        self._boss_wp_prev = None       # previous tick's distance to the weak point (boss_approach_delta)
        self._boss_wp_xz = None         # last weak-point position (to tell a MOVING boss - circling Dragon - from a STATIC one)
        self._boss_wp_moved_at = 0.0    # last monotonic the weak point moved > a step (recent => moving => centre-hold ok)
        self._boss_close_best = None    # closest the boss approach has gotten to its drive target (wedge detection)
        self._boss_close_at = 0.0       # last monotonic the boss approach got closer (stale -> wedged -> force-through)
        self._boss_parts_prev = None    # live boss-part count last tick (a drop = damage progress)
        self._boss_progress_at = 0.0    # last monotonic the boss took damage (hp dropped or a part died)
        self._boss_approach_best = None # closest P1 has gotten to the weak point this visit (closing-progress)
        self._boss_approach_at = 0.0    # last monotonic P1 got closer (stalls -> platform/wall: hold the line + fire)
        self._p1_xz = None              # P1's last position where it had translated (physical-stuck detector)
        self._p1_moved_at = 0.0         # last monotonic P1 translated > WEDGE_MOVE (parked if stale > STUCK_MOVE_S)
        self._stuck_phase = 0           # rotating wander heading index to break a physical park
        self._room_centroid = {}        # room -> [x,z] last-seen P1 position (spatial node placement for the live map)
        self._plan_pub_at = 0.0         # throttle for the room-graph plan publish
        self._area_rooms = set()        # the area's REAL room ids (distinct room fields of loaded entities)
        self._frontier = []             # area rooms P1 has NOT yet entered (explore these before advancing)
        from .pso_coop_town import TownRoute
        self.town = TownRoute(getattr(reader, "ad", None))
        self.town_enabled = False
        from .pso_coop_frontier import FieldObjectives
        self.field = FieldObjectives()
        self.margin_attempts = {}
        self.fallback = {}      # (episode,floor,geometry) -> geometry-free forward approach book
        self.forward_interact = {}  # slot -> standing on a switch/panel this tick (press A, don't move)
        self.forward_kind = {}      # slot -> 'press' | 'approach_switch' | 'walk_through'
        self.room_dwell = {}    # P1 dwell tracking for the stuck-room fail-safe telemetry
        self.forced_rooms = set()   # (episode,floor,room,geometry) already force-unlocked this run
        self._forced_doors = {}     # gkey -> until: a SPECIFIC forward door force-opened (per-door, not per-room)
        self._adj_fires = 0         # how many times force_adjacent_door engaged (flat telemetry)
        self._adj_last = {}         # last force_adjacent_door result {room, gkey, written, flags} (flat telemetry)
        self._adj_skip = ''         # last force_adjacent_door skip reason (flat telemetry: WHY it refused)
        self._coord_target = {}     # (B) committed coordinate-drive forward door {gkey, dest, room, since, at_door}
        self._coord_grace = {}      # (B) grace timer on a forward door before committing {gkey, since}
        self._blocked_gates = {}    # (B) gkey -> until: a door that would not open on a committed push (explore elsewhere)
        self._cross_failed = 0      # (B) how many committed crossings gave up (flat telemetry)
        self._fence_obj = None      # two-player hold-fence crossing objective {fence gkey/xz, switch xz/room}
        self._crossed_fences = set()  # fence gkeys P1 has crossed this run (don't re-target)
        self._fence_cooldown = {}   # ANTI-STALL: fence gkey -> until; gave up on it, explore/fight before retry
        self._fence_try_fence = None  # the fence gkey the current attempt is on
        self._fence_try_since = 0.0   # when the current fence attempt started
        self._fence_try_visited = 0   # visited-room count when the attempt started (to detect real progress)
        self._fence_giveups = 0       # how many fence attempts gave up (flat telemetry)
        self._now_ref = 0.0           # latest tick time, so select_fence_objective can honor cooldowns
        self._last_warp_at = 0.0      # last native floor-advance warp (throttle)
        self._floor_advances = 0      # how many floor-advance warps fired (flat telemetry)
        self._hardcap_warps = 0       # how many ABSOLUTE anti-freeze warps fired (ignored enemies) (flat telemetry)
        self._adv_floor = None        # floor the stall timer is anchored to (reset the window on a floor change)
        self._fence_arm = None      # {gkey, room}: P1 reached the fence; a later room change = crossed it
        self._p2_placed = False     # P2 was RAM-placed onto the hold-switch (flat telemetry)
        self._p2_sw_best = None     # P2's best (smallest) distance to the switch, for the stuck timer
        self._p2_sw_best_at = 0.0   # when P2 last got closer to the switch
        self._p1_placed = False     # P1 was RAM-placed PAST the fence (flat telemetry)
        self._p1_cross_at = 0.0     # when P1 first parked at the fence (gate open) this objective
        self._forced_fence_coll = set()   # fence actor addrs whose collision field was force-probed (one-shot)
        self._fence_coll_before = None    # the fence collision field's value before the probe write
        self._fence_coll_skip = ''        # why the collision probe didn't write (class_mismatch/bad_subptr) or 'wrote'
        self.knowledge = None       # persistent per-room-template gate/flag store (set in play())
        self.wedge = {}             # slot -> per-slot translation-stall (wall-wedge) recovery state
        self.door_cooldown = {}     # P1 cross-room: gkey -> until; brief anti-rebounce on a just-crossed door
        self._p1_room = None        # P1's last room, to detect a traversal
        self._p1_door = None        # the door gkey P1 was pursuing (links its two rooms once it crosses)
        self.door_links = {}        # learned gkey -> set(rooms it connects); feeds forward-only room choice
        self.p1_visited = set()     # rooms P1 has entered this run (prefer UNVISITED, never backtrack to spawn)
        self._backtrack = frozenset()  # door gkeys whose far side is already visited (deprioritized)
        self._area = None           # current area fingerprint (episode/floor/geometry) for the adjacency graph
        self._area_graph = {}       # recalled+live: {from_room -> {str(gkey) -> to_room}}, a room OWNS its doors
        self._p1_path = []          # ordered unique rooms P1 reached this run (the run's exploration/critical path)
        self._crit_path = []        # recalled critical path for this area (room sequence that advanced to exit)
        self._area_floor = None     # floor of the current area, to detect a floor advance (exit reached)
        self.map_root = None        # campaign runtime root for published surfaces (set in play())
        self.directive_path = None  # operator map directive file the viewer/API writes (set in play())
        self._directive = None      # the parsed, active operator directive (GOTO/PRESS/ATTACK)
        self._directive_mtime = 0.  # mtime of the directive file last read
        self._directive_done = None # id of a GOTO already reached (do not re-pursue)
        self._published = set()     # area fingerprints whose collision surface is already published

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

        Advance the pair toward the room's forward affordance - a floor switch /
        door panel to press, else the door/fence/barrier it gates (aimed just
        past, so they commit THROUGH it). A per-slot approach is abandoned (cooled
        down) once it stops getting closer, rotating to the next candidate rather
        than pushing a wall forever. Movement routes through nav.route, permissive
        when no grid exists; drive_forward steers straight if it yields none.

        Co-op split: when a room holds two or more panels (the Forest-1 'open two
        door panels' puzzle), P2 claims a DIFFERENT panel than P1 so both panels
        are held at once; with a single switch, or none, P2 follows P1's choice.
        Sets self.forward_kind[slot] so drive_forward presses a reached panel,
        approaches a far panel in fine pulses (land, do not orbit), and drives
        through a door with gusto."""
        finite = lambda row: all(type(row.get(k)) in (int, float) and math.isfinite(row[k])
                                 for k in ('x', 'z'))
        self.forward_interact[slot] = False
        self.forward_kind[slot] = None
        if not finite(player):
            return None
        room = player.get('room')
        px, pz = player['x'], player['z']
        identity = (state.get('episode'), state.get('floor'), state.get('geometry_identity'))
        book = self.fallback.get(identity)
        if book is None or book.get('_room') != room:
            # 'entry' is P1's position on entering this room - the door it came
            # through, used to avoid immediately backtracking out of a hub.
            book = self.fallback[identity] = {'_room': room, 'cooldown': {}, 'slots': {}, 'entry': (px, pz)}
            if len(self.fallback) > 16:
                self.fallback.pop(next(iter(self.fallback)))
        cooldown = book['cooldown']
        entry = book.get('entry')
        from . import pso_coop_gates as gates
        # Forward-only room choice (P1): learn which rooms each door connects as P1
        # crosses it, remember visited rooms, and prefer doors to UNVISITED rooms so
        # P1 advances along the critical path and never backtracks to the spawn hub.
        # A brief cooldown on the just-crossed door only damps an instant rebounce.
        if slot == 1:
            self._sync_area(state)
            self.p1_visited.add(room)
            if room not in self._p1_path:
                self._p1_path.append(room)
                # Persist the run's exploration order as the critical-path candidate
                # so a later run beelines it; _advance_floor() promotes it on exit.
                if self._area and self.knowledge is not None:
                    self.knowledge.record_path(self._area, self._p1_path)
            if self._p1_room != room:
                if self._p1_door is not None:
                    self.door_links.setdefault(self._p1_door, set()).update({self._p1_room, room})
                    self.door_cooldown[self._p1_door] = now + DOOR_RETRAVERSE_COOLDOWN_S
                    # Record the directed crossing in the crystal and the live graph:
                    # this room now OWNS this outbound door regardless of the room id
                    # the connector entity is tagged to, and later runs recall it.
                    dk = str(self._p1_door)
                    if type(self._p1_room) is int and type(room) is int:
                        self._area_graph.setdefault(self._p1_room, {})[dk] = room
                        if self._area and self.knowledge is not None:
                            self.knowledge.record_edge(self._area, self._p1_room, dk, room)
                self._p1_room = room
                self._p1_door = None
            self.door_cooldown = {k: v for k, v in self.door_cooldown.items() if v > now}
            for k, v in self.door_cooldown.items():
                cooldown[k] = max(cooldown.get(k, 0), v)
            # Doors whose far side (the room that is not the current one) is already
            # visited are backtracks - deprioritized below when a forward door exists.
            self._backtrack = frozenset(g for g, rooms in self.door_links.items()
                                        if (rooms - {room}) and (rooms - {room}) <= self.p1_visited)

        # P2 claims the OTHER panel in a two-panel room; else follows P1 (to P1's
        # panel, or to the door once both panels are done) or just closes the gap.
        exclude = ()
        # Once the room's gate flags are set (fail-safe fired, or a recalled
        # recipe), the panels are done - stop pressing them and WALK THROUGH the
        # now-open door. P2 then simply follows P1 to the exit.
        forced = (state.get('episode'), state.get('floor'), room, state.get('geometry_identity')) in self.forced_rooms
        if slot == 2 and not forced:
            leader = book['slots'].get(1)
            multi_panel = gates.count_switches(state.get('entities', ()), room) >= 2
            if leader and leader.get('cls') in gates.SWITCH_CLASSES and multi_panel:
                exclude = (leader['gkey'],)              # split: avoid P1's panel
            else:
                buddy = state['players'][1]
                if leader and leader.get('room') == room:
                    return leader['x'], leader['z']
                if finite(buddy) and buddy.get('room') == room and math.hypot(buddy['x'] - px, buddy['z'] - pz) > 40:
                    return buddy['x'], buddy['z']

        for _ in range(8):
            rows = gates.forward_candidates(state.get('entities', ()), room, px, pz,
                                            cooldown=cooldown, now=now, prefer_room=True,
                                            exclude=exclude, skip_switches=forced)
            # Anti-backtrack: P1 leads toward the boss, not back through the door it
            # just entered. Drop entry-adjacent DOORS when a forward option remains
            # (never drop a switch/panel, and never strand a single-exit room).
            if slot == 1 and len(rows) > 1:
                # Crystal-guided choice (a room OWNS its outbound doors via the learned
                # adjacency graph, so a connector tagged to one room id doesn't hide the
                # NEW room's forward door). One rank over ALL candidates - never drop a
                # row first, which previously let a recalled DEAD-END door (one whose
                # crystal destination is a visited room) survive a live-door_links filter
                # and get chosen over the real frontier. Order: switches/panels first
                # (press them to open new paths), then a FRONTIER door (never traversed,
                # or recalled to an UNVISITED room), then recalled BACKTRACKS to visited
                # rooms, and worst of all the door P1 just entered through (anti-rebounce).
                graph = self._area_graph.get(room, {})

                def _rank(r):
                    is_switch, _dist, gkey, ent, _kind = r
                    if is_switch == 0:
                        return 0                       # switches/panels first, always
                    reentered = bool(entry and math.hypot(ent['x'] - entry[0],
                                                          ent['z'] - entry[1]) <= BACKTRACK_RADIUS)
                    dest = graph.get(str(gkey))        # recalled destination room, or None
                    # A known backtrack: the crystal recalls its destination as a
                    # VISITED room, or this run's door_links already learned both its
                    # sides are visited (self._backtrack). Either way, deprioritize it.
                    if (dest is not None and dest in self.p1_visited) or gkey in self._backtrack:
                        return 5 if reentered else 4
                    if dest is not None:               # recalled door to an UNVISITED room
                        return 1
                    return 4 if reentered else 1       # never traversed = a frontier to explore
                rows = sorted(rows, key=lambda r: (_rank(r), r[1]))
            if not rows:
                book['slots'].pop(slot, None)
                # No gate/switch left: head for the area's exit warp/teleporter so
                # P1 keeps progressing out of the level toward the boss (idle->exit).
                warp = self._nearest_warp(state, room, px, pz)
                if warp is not None:
                    self.forward_kind[slot] = 'walk_through'
                    if slot == 1 and isinstance(getattr(self.inputs, 'stats', None), dict):
                        self.inputs.stats['forward_fallback_target'] = str(warp.get('class'))
                        self.inputs.stats['forward_fallback_action'] = 'exit_warp'
                    return gates.through_point(px, pz, warp['x'], warp['z'])
                return None
            is_switch, dist, gkey, entity, _kind = rows[0]
            cls = str(entity.get('class'))
            track = book['slots'].get(slot)
            if track is None or track.get('gkey') != gkey:
                track = book['slots'][slot] = {'gkey': gkey, 'best': dist, 'since': now}
            elif dist < track['best'] - 2:
                track.update(best=dist, since=now)
            elif now - track['since'] > FALLBACK_STALL_S and dist > FALLBACK_REACH:
                # A FRONTIER door (a door never traversed yet, so its far side is a
                # potentially NEW room) must not be abandoned just because it is
                # slow to reach - abandoning it lets P1 retreat through the known
                # backward connector and oscillate forever. Keep committing to it
                # (drive_forward's wedge recovery works the approach); only cool
                # switches and already-known (traversed) doors.
                frontier_door = is_switch == 1 and gkey not in self.door_links
                if not frontier_door:
                    cooldown[gkey] = now + 30
                    book['slots'].pop(slot, None)
                    continue
                track['since'] = now        # keep pursuing the frontier door
            track.update(room=room, x=entity['x'], z=entity['z'], cls=cls, gkey=gkey)
            # A panel/switch within reach is pressed (stand on it + the controller
            # taps A). After a short dwell treat it as pressed and rotate to the
            # door it gates, so both panels get opened before the door.
            on_switch = is_switch == 0 and dist <= FALLBACK_REACH
            if on_switch:
                track.setdefault('pressed_at', now)
                if now - track['pressed_at'] > SWITCH_PRESS_S:
                    cooldown[gkey] = now + 45
                    book['slots'].pop(slot, None)
                    continue
            self.forward_interact[slot] = on_switch
            kind = ('press' if on_switch else 'approach_switch' if is_switch == 0 else 'walk_through')
            self.forward_kind[slot] = kind
            if slot == 1 and isinstance(getattr(self.inputs, 'stats', None), dict):
                self.inputs.stats['forward_fallback_target'] = cls
                self.inputs.stats['forward_fallback_dist'] = round(dist, 1)
                self.inputs.stats['forward_fallback_action'] = kind
            if is_switch == 0:
                return entity['x'], entity['z']
            if slot == 1:
                self._p1_door = gkey          # cooled if crossing it changes P1's room
            # A door/fence/barrier: aim beyond it so the actor commits through. Once
            # the gate is force-unlocked, aim well past the threshold to carry the
            # buddy across into the next room rather than parking at the doorway.
            return gates.through_point(px, pz, entity['x'], entity['z'], overshoot=36.0 if forced else 16.0)
        book['slots'].pop(slot, None)
        return None

    def _sync_area(self, state):
        """Keep the live room-adjacency graph + critical path aligned to the area
        P1 is in. On entering a NEW area, recall its learned graph and critical
        path from the crystal so a later run starts from compounded knowledge. On
        ADVANCING to a deeper floor (the area exit was reached), promote the
        previous area's exploration into a trimmed critical path later runs beeline.

        Degrades to a no-op if a hot-reload brought a new pso_coop in next to a
        still-old pso_knowledge (the graph/path API not yet live): the loop keeps
        running on the frontier heuristic until a restart loads the full crystal."""
        try:
            from .pso_knowledge import area_fingerprint
        except ImportError:
            return
        fp = area_fingerprint(state.get('episode'), state.get('floor'), state.get('geometry_identity'))
        if fp == self._area:
            return
        prev_area, prev_path, prev_graph, prev_floor = (
            self._area, self._p1_path, self._area_graph, self._area_floor)
        floor = state.get('floor')
        if (prev_area and self.knowledge is not None and type(floor) is int
                and type(prev_floor) is int and floor > prev_floor and len(prev_path) >= 2):
            self.knowledge.record_path(prev_area, self._trim_path(prev_graph, prev_path))
        self._area, self._area_floor = fp, floor
        self._p1_path, self._area_graph, self._crit_path = [], {}, []
        if fp and self.knowledge is not None:
            self._area_graph = {r: dict(d) for r, d in self.knowledge.area_edges(fp).items()}
            self._crit_path = self.knowledge.critical_path(fp)

    def _path_next(self, room):
        """The room that followed `room` on the recalled critical path, or None -
        the target a later run beelines toward from `room`."""
        p = self._crit_path
        if room in p:
            i = p.index(room)
            if i + 1 < len(p):
                return p[i + 1]
        return None

    @staticmethod
    def _trim_path(graph, path):
        """Shortest spawn->deepest route through the learned adjacency graph, so the
        recorded critical path drops the run's dead-ends. Falls back to the raw
        visit order if the graph cannot connect the endpoints."""
        if len(path) < 2:
            return list(path)
        start, goal = path[0], path[-1]
        adj = {}
        for fr, doors in graph.items():
            for to in doors.values():
                adj.setdefault(fr, set()).add(to)
        from collections import deque
        prev, q = {start: None}, deque([start])
        while q:
            u = q.popleft()
            if u == goal:
                break
            for v in adj.get(u, ()):
                if v not in prev:
                    prev[v] = u
                    q.append(v)
        if goal not in prev:
            return list(path)
        out, u = [], goal
        while u is not None:
            out.append(u)
            u = prev[u]
        return list(reversed(out))

    def drive_forward(self, state, slot, player, now, commands, moves, steering, fallback_slots):
        """Decisive forward door/switch progression (operator 2026-11-02: gusto).

        Press each panel/switch, then walk THROUGH the door it gates; P1 leads,
        P2 follows. Movement is committed (a .40 s hold) and geometry-free: it
        routes on the verified grid when the gate is on it, else steers straight
        at the forward target so a small spawn grid can never pin the pair. No
        wall is learned from a forced push. Returns True when it issued input."""
        dest = self.forward_fallback(state, slot, player, now)
        if dest is None:
            return False
        fallback_slots.append(slot)
        nav = self.maps.get(state, player)
        if self.forward_interact.get(slot):
            # Standing on the panel/switch: tap A to activate it, do not walk off.
            commands.append((slot, ["a"], .12))
            steering[slot] = (player, (player["x"], player["z"]), 'forward_switch_press')
            return True
        # toward() ALWAYS heads at the target: exact path when reachable, else the path
        # to the nearest reachable cell on P1's OWN floor component. P1 cannot A* to a
        # point just past a closed door (it is a disconnected component / a door-in-wall
        # cell), so instead of straight-lining into the wall and wedging, it walks up to
        # the door (the committed walk-through + stage-flag force-unlock carry it across).
        route, route_exact = nav.toward((player["x"], player["z"]), dest)
        waypoint = route[1] if route and len(route) > 1 else (route[0] if route else dest)
        # Diagnostic (slot 1): route_cells>0 = A* produced a path (exact or best-effort
        # toward the target); route_exact=0 means the target itself was unreachable
        # (across a door / off P1's component) and P1 is approaching the nearest cell.
        if slot == 1 and isinstance(getattr(self.inputs, 'stats', None), dict):
            st = self.inputs.stats
            route_cells = len(route) if route else 0
            floor_n = (len(nav.floor) if nav.floor is not None else -1)
            target_dist = round(math.hypot(dest[0] - player["x"], dest[1] - player["z"]), 1)
            recov = bool(getattr(nav, 'recovery', False))
            st['nav_diag'] = {'route_cells': route_cells, 'exact': bool(route_exact),
                              'floor': (None if floor_n < 0 else floor_n),
                              'heights': len(nav.heights), 'walls': len(nav.walls), 'blocked': len(nav.blocked),
                              'target_dist': target_dist, 'recovery': recov}
            # FLAT scalar mirrors (the telemetry endpoint drops nested dicts): the
            # ground truth for the routing fix. nav_grid_floor=-1 means an open grid
            # (no floor set); nav_recovery_grid=1 means the relaxable recovery surface;
            # nav_route_exact=0 with route_cells>0 means best-effort approach to a door.
            st['nav_route_cells'] = route_cells
            st['nav_route_exact'] = int(bool(route_exact))
            st['nav_grid_floor'] = floor_n
            st['nav_grid_walls'] = len(nav.walls)
            st['nav_blocked'] = len(nav.blocked)
            st['nav_target_dist'] = target_dist
            st['nav_recovery_grid'] = int(recov)
        # (B) COORDINATE-DRIVE out of a stuck cleared room. A* repeatedly can't reach
        # the forward exit door (route_exact False - its far side is a disconnected
        # room) and P1 oscillates in the hub never closing to 60u. So: once P1 has a
        # forward door selected in a CLEARED room (no combat to do) and A* has failed
        # to path past it for COORD_DRIVE_AFTER_S, COMMIT to that door and drive STRAIGHT
        # at its coordinates (bypassing A*'s backward waypoint), force its OWN flag on a
        # loose approach, and let the committed walk-through + escalating wedge-escape
        # carry P1 across. Combat still preempts (drive_forward only runs with no target),
        # and we re-check the room is clear here. Commit is per-door and time-bounded.
        door = self._p1_door if (isinstance(self._p1_door, tuple) and len(self._p1_door) == 3) else None
        coord_drive = cross_push = False
        if slot == 1:
            room_clear = not any(e.get('kind') == 'enemy' and type(e.get('hp')) in (int, float)
                                 and e['hp'] > 0 and e.get('room') == player.get('room')
                                 for e in state.get('entities', ())[:512])
            room = player.get('room')
            self._blocked_gates = {g: t for g, t in self._blocked_gates.items() if t > now}
            lock = self._coord_target
            # Expire the commit when P1 leaves the room (crossed / moved on) or it times out.
            if lock and (lock.get('room') != room or (now - lock.get('since', now)) > COORD_DRIVE_MAX_S):
                lock = self._coord_target = {}
            ddist = -1.0
            if lock.get('gkey') and room_clear:
                # HOLD the committed door: drive STRAIGHT at its STORED coords every tick,
                # regardless of what forward_fallback re-picks this frame or route_exact.
                coord_drive = True
                cgkey, cdest = lock['gkey'], lock['dest']
                waypoint = cdest
                ddist = math.hypot(cgkey[1] - player["x"], cgkey[2] - player["z"])
                if ddist <= COORD_FORCE_DIST:
                    self.force_adjacent_door(state, player, cgkey, now)
                if ddist <= CROSS_DIST:
                    # P1 is ON the door: PLANT and push straight THROUGH (suppress the
                    # wedge away-sweep that was flinging P1 off the door). If still not
                    # crossed (room unchanged) after CROSS_HOLD_S, this gate won't open
                    # from the flags we can set (a switch/fence/quest gate) - cool it
                    # down and release so P1 explores other doors instead of parking.
                    lock.setdefault('at_door', now)
                    cross_push = True
                    if (now - lock['at_door']) >= CROSS_HOLD_S:
                        self._blocked_gates[cgkey] = now + BLOCKED_GATE_S
                        self._coord_target = {}
                        self._cross_failed += 1
                        coord_drive = cross_push = False
                else:
                    lock.pop('at_door', None)
            elif (door is not None and self.forward_kind.get(slot) == 'walk_through'
                  and room_clear and not route_exact and self._blocked_gates.get(door, 0.) <= now):
                # Not committed yet: run a grace timer on THIS door; commit after the grace.
                grace = self._coord_grace
                if grace.get('gkey') != door:
                    grace = self._coord_grace = {'gkey': door, 'since': now}
                ddist = math.hypot(door[1] - player["x"], door[2] - player["z"])
                if (now - grace['since']) >= COORD_DRIVE_AFTER_S:
                    self._coord_target = {'gkey': door, 'dest': dest, 'room': room, 'since': now}
                    coord_drive = True
                    waypoint = dest
                    if ddist <= COORD_FORCE_DIST:
                        self.force_adjacent_door(state, player, door, now)
                elif ddist <= FORCE_DOOR_DIST:
                    self.force_adjacent_door(state, player, door, now)   # already on it: open now
            elif door:
                ddist = math.hypot(door[1] - player["x"], door[2] - player["z"])
            if isinstance(getattr(self.inputs, 'stats', None), dict):
                self.inputs.stats['coord_drive'] = int(coord_drive)
                self.inputs.stats['coord_cross_push'] = int(cross_push)
                self.inputs.stats['coord_cross_failed'] = self._cross_failed
                self.inputs.stats['coord_drive_door_dist'] = round(ddist, 1)
        # Approach a near panel in SHORT pulses so the actor lands on it (and the
        # next tick presses it) instead of orbiting the small target; drive a door
        # through with a committed, gusto-length hold.
        approaching_switch = (not coord_drive and self.forward_kind.get(slot) == 'approach_switch'
                              and math.hypot(dest[0] - player["x"], dest[1] - player["z"]) <= SWITCH_FINE_DIST)
        if cross_push:
            keys, escaping = movement_keys(player, waypoint), False   # committed straight push THROUGH the door
        else:
            keys, escaping = self._unwedge(slot, player, waypoint, now)
        commands.append((slot, keys, .40 if escaping else (.10 if approaching_switch else .40)))
        moves[slot] = (player, waypoint, nav, False)
        steering[slot] = (player, waypoint, 'forward_cross_push' if cross_push else
                          'forward_unwedge' if escaping else
                          'forward_coord_drive' if coord_drive else
                          'forward_fine' if approaching_switch else 'forward_gusto')
        return True

    def _unwedge(self, slot, player, waypoint, now):
        """Per-slot translation-stall (wall-wedge) recovery, distinct from the
        room-change stuck timer: when a buddy HAS a movement goal but barely
        translates for WEDGE_STALL_S (pinned on geometry, not merely stopping
        short), back it off the wall and try a different approach octant, then
        re-commit. A buddy that is making progress toward its goal is untouched.
        Returns (keys, escaping)."""
        here = (player["x"], player["z"])
        gkey = (round(waypoint[0]), round(waypoint[1]))
        rec = self.wedge.get(slot)
        if rec is None or rec["goal"] != gkey:
            rec = self.wedge[slot] = {"goal": gkey, "anchor": here, "since": now, "phase": 0, "until": 0.}
        if math.hypot(here[0] - rec["anchor"][0], here[1] - rec["anchor"][1]) > WEDGE_MOVE:
            rec.update(anchor=here, since=now, until=0.)      # translating: progress, clear any escape
            return movement_keys(player, waypoint), False
        if now < rec["until"]:
            return rec["keys"], True                          # mid-escape: hold the back-off heading
        if now - rec["since"] >= WEDGE_STALL_S:
            # Wedged. STRAFE first (slip around the corner) and only then reverse,
            # so a doorway seam does not become a back-and-forth limit cycle across
            # the room boundary; cycle both strafes, a diagonal, then a short reverse.
            # The detour GROWS with each failed phase (and counts phases across the
            # cycle) so a small strafe that can't clear a wall escalates to a wide
            # sweep instead of limit-cycling in place - the operator's acute pain is
            # the bot SITTING, so a wedged buddy must keep covering real ground.
            rec["phase"] = (rec["phase"] + 1) % 4
            rec["tries"] = rec.get("tries", 0) + 1
            bearing = math.atan2(waypoint[0] - player["x"], waypoint[1] - player["z"])
            angle = bearing + (math.pi / 2, -math.pi / 2, math.pi * 0.75, math.pi)[rec["phase"] - 1]
            reach = min(WEDGE_ESCAPE_REACH + WEDGE_ESCAPE_GROW * (rec["tries"] - 1), WEDGE_ESCAPE_MAX)
            escape = (player["x"] + math.sin(angle) * reach, player["z"] + math.cos(angle) * reach)
            rec.update(keys=movement_keys(player, escape), until=now + WEDGE_ESCAPE_S, since=now, anchor=here)
            stats = getattr(self.inputs, "stats", None)
            if isinstance(stats, dict):
                stats["wedge_recovery"] = {"slot": slot, "phase": rec["phase"], "at": [round(here[0]), round(here[1])]}
            return rec["keys"], True
        return movement_keys(player, waypoint), False

    def _nearest_warp(self, state, room, px, pz):
        """The nearest area warp/teleporter (the level exit), same room first then
        anywhere on the floor. Warps are not gate objects, so they are the
        autonomous forward target once a room's gates are done."""
        finite = lambda e: all(type(e.get(k)) in (int, float) and math.isfinite(e[k]) for k in ('x', 'z'))
        warps = [e for e in state.get('entities', ())[:512]
                 if finite(e) and any(k in str(e.get('class', '')) for k in ('Warp', 'Teleport', 'GoalWarp'))]
        if not warps:
            return None
        same = [e for e in warps if e.get('room') == room]
        return min(same or warps, key=lambda e: math.hypot(e['x'] - px, e['z'] - pz))

    def swarm_follow(self, state, slot, player, now, enemies, envelope, commands, moves, steering, attack_rows):
        """A non-leader (P2..P4): orbit and defend P1 - never navigates on its own.

        The whole party's navigation intelligence lives in P1; followers are a
        simple attack-dog swarm. Dropping followers' independent routing / own
        geometry is what removes the waiting_for_buddy deadlock. Behaviour: if an
        enemy is within reach of the follower OR near the leader, engage it; else
        keep station on the leader (close the gap if far, step off if crowding),
        geometry-free. Generic over slot, so P3/P4 swarm the same way."""
        leader = state["players"].get(1)
        px, pz = player["x"], player["z"]
        self.combat_status[slot] = dict(range=envelope, target=None, room=player.get("room"),
                                        player_ptr=player.get("ptr"), role="swarm_follow")

        def relevant(e):
            if e.get("hp", 0) <= 0:
                return False
            if math.hypot(e["x"] - px, e["z"] - pz) <= COMBAT_NEARBY_RADIUS:
                return True
            return bool(leader) and math.hypot(e["x"] - leader["x"], e["z"] - leader["z"]) <= SWARM_DEFEND_RADIUS

        threats = sorted((e for e in enemies if relevant(e)),
                         key=lambda e: math.hypot(e["x"] - px, e["z"] - pz))
        target = next((e for e in threats if self.cooldown.get((slot, e["ptr"]), 0) <= now), None)
        # BOSS DEFEAT: followers run the SAME owned boss logic (fire in range / strike the
        # grounded window / converge / hold-don't-chase) so they also land damage instead of
        # strafing at the boss or keeping station on the leader.
        boss_row = self._boss_target_row(player)
        if boss_row is not None:
            self.boss_combat(state, slot, player, envelope, boss_row, now,
                             commands, moves, steering, enemies, attack_rows)
            return
        # DODGE (follower): a swarm bot also moves out of attacks instead of tanking.
        # When a threat is hot and no clean shot is lined up this tick, strafe out of the
        # attack line (biased away from learned fatal spots) rather than standing to aim.
        if enemies:
            dodge = self.combat_dodge(state, slot, player, enemies, envelope, target, now)
            if dodge is not None and dodge["act"]:
                commands.append((slot, dodge["keys"], dodge["dur"]))
                steering[slot] = (player, dodge["point"], "swarm_dodge")
                self.combat_status[slot].update(role="swarm_dodge", dodge_min_dist=dodge["min_dist"])
                self._dodge_telemetry(dodge)
                return
        if target is not None:
            dist, angle, vertical_ok = attack_geometry(player, target, envelope)
            self.combat_status[slot].update(target=target.get("class"), distance=round(dist, 2),
                                            heading_error=round(angle, 2), role="swarm_defend")
            if dist <= envelope["horizontal"] and vertical_ok and abs(angle) <= envelope["horizontal_half_angle"]:
                if now - self.last_attack.get(slot, 0) >= ATTACK_CADENCE_S / self.inputs.speed():
                    commands.append((slot, ["a"], .12))
                    attack_rows[slot] = {"attempts": 0}
                return
            if dist <= envelope["horizontal"] and vertical_ok:
                commands.append((slot, ["lleft" if angle > 0 else "lright"], max(.02, min(.12, abs(angle) / 450))))
                steering[slot] = (player, (target["x"], target["z"]), "swarm_aim")
                return
            commands.append((slot, movement_keys(player, (target["x"], target["z"])), .20))
            steering[slot] = (player, (target["x"], target["z"]), "swarm_approach")
            return
        # No threat: keep station on the leader. Geometry-free - a follower needs
        # no collision grid, so it can never be the thing that stalls the party.
        if not leader or leader.get("hp", 0) <= 0:
            return
        gap = math.hypot(leader["x"] - px, leader["z"] - pz)
        if gap > SWARM_FOLLOW_RADIUS:
            # Geometry-free close, but strafe off a wall if it stops translating so
            # a follower is never left frozen behind cover (it must stay glued).
            keys, _ = self._unwedge(slot, player, (leader["x"], leader["z"]), now)
            commands.append((slot, keys, .40))
            steering[slot] = (player, (leader["x"], leader["z"]), "swarm_close")
        elif gap < SWARM_SPREAD:
            off = (px + (px - leader["x"] or SWARM_SPREAD), pz + (pz - leader["z"]))
            commands.append((slot, movement_keys(player, off), .12))
            steering[slot] = (player, off, "swarm_spread")

    def _force_log(self, room, reason):
        stats = getattr(self.inputs, 'stats', None)
        if isinstance(stats, dict):
            stats['forced_door_unlock_skipped'] = {'room': room, 'reason': reason}

    def _live_forward_flags(self, state, player, room):
        """Collect the stage-flag indices that gate this room's forward progress,
        reading each object's flag index live from +0xC8 (low 16): every panel /
        switch in the room, plus the single NEAREST energy barrier (the immediate
        forward gate). Targeted - never every barrier on the floor."""
        from . import pso_coop_gates as gates
        ad = getattr(self.reader, 'ad', None) or getattr(self.inputs, 'ad', None)
        read = ad.read_memory
        px, pz = player.get('x'), player.get('z')
        decorated, barriers = [], []
        for e in state.get('entities', ())[:512]:
            cls = str(e.get('class', ''))
            is_switch = cls in gates.SWITCH_CLASSES and e.get('room') == room
            if not (is_switch or cls == 'TOBarrierEnergy01'):
                continue
            try:
                idx = struct.unpack('>I', read(int(e['ptr'], 16) + 0xC8, 4))[0] & 0xffff
            except (ValueError, KeyError, TypeError, struct.error, OSError):
                continue
            row = dict(e, flag_index=idx)
            if is_switch:
                decorated.append(row)
            elif all(type(v) in (int, float) for v in (px, pz, e.get('x'), e.get('z'))):
                barriers.append((math.hypot(e['x'] - px, e['z'] - pz), row))
        if barriers:
            decorated.append(min(barriers, key=lambda b: b[0])[1])
        return gates.forward_gate_flag_indices(decorated, room)

    def _recalled_flags(self, state, player):
        """A validated, persisted forced-unlock recipe for this exact room
        template, or None (then the live path derives and records it)."""
        if self.knowledge is None:
            return None
        from .pso_knowledge import recalled_forward_flags
        fingerprint = room_key(state, player)[0]
        return recalled_forward_flags(self.knowledge, fingerprint, state.get('floor'))

    def _remember_gate(self, state, player, flags):
        if self.knowledge is None:
            return
        from . import pso_coop_gates as gates
        fingerprint, persistent = room_key(state, player)
        if not persistent:        # a bare session-local room number must not persist
            return
        self.knowledge.remember(fingerprint, episode=state.get('episode'), floor=state.get('floor'),
            room=player.get('room'), gate='forced_flags', forward_flags=sorted(set(flags)),
            base=hex(gates.STAGE_FLAG_BASE))

    def force_forward_unlock(self, state, slot, player, now):
        """Operator's GUARANTEED fail-safe: a room stuck with no forward progress
        is opened no matter what, by SETTING the native stage flags that gate its
        forward door directly in the verified 3OE2 flag array (the per-object
        native_state is recomputed from these each frame, so the flags are the
        source of truth). Guarded hard: exact build signature over the accessor +
        r13 setup, group read-back == floor, every flag in range, the binding
        unchanged across read->compute->write, and one shot per room. Records the
        recipe for instant recall next visit. Returns the flags set, or None."""
        from . import pso_coop_gates as gates
        ad = getattr(self.reader, 'ad', None) or getattr(self.inputs, 'ad', None)
        if ad is None or not callable(getattr(ad, 'write_memory', None)) or not callable(getattr(ad, 'read_memory', None)):
            return None
        if (state.get('verified') is not True or state.get('phase') != 14
                or type(state.get('floor')) is not int or not 1 <= state['floor'] <= 17
                or set(state.get('players', {})) != {1, 2} or not player):
            return None
        room, floor, read = player.get('room'), state['floor'], ad.read_memory
        key = (state.get('episode'), floor, room, state.get('geometry_identity'))
        if key in self.forced_rooms:
            return None
        if not gates.stage_flag_code_ok(read):
            self._force_log(room, 'build_signature_mismatch')
            return None
        try:
            group = struct.unpack('>I', read(gates.STAGE_FLAG_GROUP_PTR, 4))[0]
        except (struct.error, OSError):
            return None
        if group != floor:
            self._force_log(room, f'group_ptr_{group}_ne_floor_{floor}')
            return None
        recalled = self._recalled_flags(state, player)
        flags = recalled if recalled is not None else self._live_forward_flags(state, player, room)
        if not flags:
            self._force_log(room, 'no_forward_flags')
            return None
        loci = []
        for idx in flags:
            locus = gates.stage_flag_locus(group, idx)
            if locus is None:
                self._force_log(room, f'flag_out_of_range_{idx}')
                return None
            loci.append((idx, locus[0], locus[1]))
        # Revision guard: the exact build + the group must still hold at write time.
        if not gates.stage_flag_code_ok(read) or struct.unpack('>I', read(gates.STAGE_FLAG_GROUP_PTR, 4))[0] != floor:
            self._force_log(room, 'binding_changed')
            return None
        written = []
        for idx, addr, mask in loci:
            try:
                current = read(addr, 1)[0]
            except (IndexError, OSError):
                continue
            if current & mask:
                continue
            ad.write_memory(addr, bytes([current | mask]))
            written.append(idx)
        self.forced_rooms.add(key)
        stats = getattr(self.inputs, 'stats', None)
        if isinstance(stats, dict):
            stats['forced_door_unlock'] = {'room': room, 'floor': floor, 'group': group,
                'flags': sorted(flags), 'written': sorted(written),
                'base': hex(gates.STAGE_FLAG_BASE), 'recalled': recalled is not None}
        self._remember_gate(state, player, flags)
        return sorted(flags)

    def force_adjacent_door(self, state, player, gkey, now):
        """Open the SPECIFIC forward door/gate P1 is physically adjacent to but cannot
        path PAST (its far side is a different, still-closed room), by setting THAT
        object's own native stage flag (+0xC8 low16) in the verified 3OE2 array, plus
        the room's switch / nearest-barrier flags in case the door is switch-gated.
        Keyed PER-DOOR (not per-room), so it fires for the cluster-EXIT door even after
        the room's one-shot generic fail-safe already ran - that generic pass only sets
        switches + the nearest barrier and never a plain TObjDoor's own flag, which is
        exactly why the exit door stayed shut. Same hard guards as force_forward_unlock."""
        from . import pso_coop_gates as gates
        def skip(reason):
            self._adj_skip = reason           # flat-telemetry: WHY the door-force refused
            return None
        ad = getattr(self.reader, 'ad', None) or getattr(self.inputs, 'ad', None)
        if ad is None or not callable(getattr(ad, 'write_memory', None)) or not callable(getattr(ad, 'read_memory', None)):
            return skip('no_adapter')
        if (state.get('verified') is not True or state.get('phase') != 14
                or type(state.get('floor')) is not int or not 1 <= state['floor'] <= 17
                or set(state.get('players', {})) != {1, 2} or not player):
            return skip('state_guard')
        if self._forced_doors.get(gkey, 0.) > now:
            return skip('rearm_window')       # already fired for this door within FORCE_DOOR_RETRY_S
        read, floor, room = ad.read_memory, state['floor'], player.get('room')
        if not gates.stage_flag_code_ok(read):
            self._force_log(room, 'adj_build_signature_mismatch')
            return skip('build_signature')
        try:
            group = struct.unpack('>I', read(gates.STAGE_FLAG_GROUP_PTR, 4))[0]
        except (struct.error, OSError):
            return skip('group_ptr_read')
        if group != floor:
            self._force_log(room, f'adj_group_{group}_ne_floor_{floor}')
            return skip(f'group_{group}_ne_floor_{floor}')
        # A plain TObjDoor has NO own gating-flag index at +0xC8 (read live it was
        # 48896, far outside the 0..255 stage range - it is some other packed field).
        # Doors are opened by the ROOM's switch/barrier flags, so resolve them the
        # SAME verified way force_forward_unlock does: _live_forward_flags returns the
        # room's switch flags + the barrier NEAREST P1 - recomputed HERE from P1's
        # position AT this door, so it targets THIS door's gate rather than whatever
        # was nearest when the room's one-shot generic pass ran earlier elsewhere.
        idxs = self._live_forward_flags(state, player, room)
        if not idxs:
            return skip('no_forward_flags')
        loci = []
        for idx in idxs:
            locus = gates.stage_flag_locus(group, idx)
            if locus is None:
                self._force_log(room, f'adj_flag_out_of_range_{idx}')
                return skip(f'flag_out_of_range_{idx}')
            loci.append((locus[0], locus[1]))
        if not gates.stage_flag_code_ok(read) or struct.unpack('>I', read(gates.STAGE_FLAG_GROUP_PTR, 4))[0] != floor:
            self._force_log(room, 'adj_binding_changed')
            return skip('binding_changed')
        written = []
        for (addr, mask), idx in zip(loci, idxs):
            try:
                current = read(addr, 1)[0]
            except (IndexError, OSError):
                continue
            if current & mask:
                continue
            ad.write_memory(addr, bytes([current | mask]))
            written.append(idx)
        self._forced_doors[gkey] = now + FORCE_DOOR_RETRY_S
        self._adj_fires += 1
        self._adj_skip = 'ok' if written else 'already_set'   # flags set (or all already set)
        self._adj_last = {'room': room, 'gkey': str(gkey), 'written': len(written), 'flags': len(idxs)}
        stats = getattr(self.inputs, 'stats', None)
        if isinstance(stats, dict):
            stats['forced_adjacent_door'] = {'room': room, 'floor': floor, 'group': group,
                'door': str(gkey), 'flags': sorted(idxs), 'written': sorted(written)}
        return sorted(idxs)

    def select_fence_objective(self, state, p1):
        """The nearest UN-crossed laser-fence + its hold-switch: a TObjLazerFenceNorm
        with a TLazerFenceSw within FENCE_PAIR_DIST. This is the Forest hold-puzzle
        exit, and it is chosen REGARDLESS of room-visited status (fix A) - the fence is
        the real forward frontier even in a 'visited' room, which is why plain
        convergence (prefer-unvisited) kept steering P1 away from it. None if no pair."""
        fin = lambda e: all(type(e.get(k)) in (int, float) and math.isfinite(e[k]) for k in ('x', 'z'))
        ents = state.get('entities', ())[:512]
        fences = [e for e in ents if str(e.get('class')) == 'TObjLazerFenceNorm' and fin(e)]
        switches = [e for e in ents if str(e.get('class')) == 'TLazerFenceSw' and fin(e)]
        if not fences or not switches or not fin(p1):
            return None
        px, pz = p1['x'], p1['z']
        best = None
        for f in fences:
            fk = ('TObjLazerFenceNorm', round(f['x'], 1), round(f['z'], 1))
            if fk in self._crossed_fences or self._fence_cooldown.get(fk, 0.0) > self._now_ref:
                continue                              # crossed, or on anti-stall cooldown (give up, keep moving)
            sw = min(switches, key=lambda s: math.hypot(s['x'] - f['x'], s['z'] - f['z']))
            if math.hypot(sw['x'] - f['x'], sw['z'] - f['z']) > FENCE_PAIR_DIST:
                continue                              # no hold-switch for this fence
            d = math.hypot(f['x'] - px, f['z'] - pz)
            if best is None or d < best['d']:
                best = {'fence': fk, 'fx': f['x'], 'fz': f['z'], 'fy': f.get('y'), 'fptr': f.get('ptr'),
                        'sx': sw['x'], 'sz': sw['z'], 'sy': sw.get('y'), 'sroom': sw.get('room'), 'd': d}
        return best

    def force_fence_collision_off(self, state, now):
        """BOUNDED PROBE (operator long-shot b): the fence's gate flag is already set yet
        it physically blocks, so the laser's COLLISION is a separate field in its collision
        sub-object (fence+0xA4 -> +0x14 == 1 on both live up-fences). Class-VERIFY the fence
        (object+0x0 -> 'TObjLazerFenceNorm') and, fail-closed, write that sub-object's +0x14
        to 0 to drop the laser collision. One-shot per fence; records before. Returns the
        sub-object +0x14 address on a write, else None."""
        obj = self._fence_obj
        ad = getattr(self.reader, 'ad', None) or getattr(self.inputs, 'ad', None)
        if (obj is None or ad is None or not callable(getattr(ad, 'write_memory', None))
                or not callable(getattr(ad, 'read_memory', None))
                or state.get('verified') is not True or state.get('phase') != 14
                or set(state.get('players', {})) != {1, 2}):
            return None
        fptr = obj.get('fptr')
        try:
            faddr = int(fptr, 16) if isinstance(fptr, str) else int(fptr)
        except (TypeError, ValueError):
            return None
        if not (0x80000000 <= faddr <= 0x81800000 - 0x100) or faddr in self._forced_fence_coll:
            return None
        read = ad.read_memory
        try:
            classptr = struct.unpack('>I', read(faddr, 4))[0]                 # object+0x0 -> class-name string
            if not (0x80000000 <= classptr <= 0x81800000 - 0x20):
                return None
            if read(classptr, 18) != b'TObjLazerFenceNorm':                   # CLASS VERIFY (fail-closed)
                self._fence_coll_skip = 'class_mismatch'
                return None
            subptr = struct.unpack('>I', read(faddr + 0xA4, 4))[0]            # the laser collision sub-object
            if not (0x80000000 <= subptr <= 0x81800000 - 0x40):
                self._fence_coll_skip = 'bad_subptr'
                return None
            before = struct.unpack('>I', read(subptr + 0x14, 4))[0]
        except (struct.error, OSError):
            return None
        ad.write_memory(subptr + 0x14, struct.pack('>I', 0))                  # candidate: collision-enable -> off
        self._forced_fence_coll.add(faddr)
        self._fence_coll_before = before
        self._fence_coll_skip = 'wrote'
        return subptr + 0x14

    def place_p1_across_fence(self, state, p1, now):
        """RAM fallback for the LAST step: the fence's gate flag is already set (it is
        logically open) but P1 cannot physically step through the threshold into the
        next room (the disconnected-component problem). Write P1's actor position to a
        point just PAST the fence (along P1's approach, at the fence's own y) so it
        crosses. Same verified write path/guards as placing P2."""
        obj = self._fence_obj
        ad = getattr(self.reader, 'ad', None) or getattr(self.inputs, 'ad', None)
        if (obj is None or ad is None or not callable(getattr(ad, 'write_memory', None))
                or state.get('verified') is not True or state.get('phase') != 14
                or type(state.get('floor')) is not int or not 1 <= state['floor'] <= 17
                or set(state.get('players', {})) != {1, 2} or not p1 or p1.get('hp', 0) <= 0):
            return False
        if not all(type(p1.get(k)) in (int, float) and math.isfinite(p1[k]) for k in ('x', 'z')):
            return False
        from . import pso_coop_gates as gates
        px, pz = gates.through_point(p1['x'], p1['z'], obj['fx'], obj['fz'], FENCE_PAST_OVERSHOOT)
        py = obj.get('fy')
        if not (type(py) in (int, float) and math.isfinite(py)):
            py = p1.get('y')
        if not all(type(v) in (int, float) and math.isfinite(v) for v in (px, py, pz)):
            return False
        try:
            addr = int(p1['ptr'], 16) if isinstance(p1.get('ptr'), str) else int(p1['ptr'])
        except (TypeError, ValueError, KeyError):
            return False
        if not (0x80000000 <= addr <= 0x81800000 - 0x44):
            return False
        ad.write_memory(addr + 0x38, struct.pack('>3f', float(px), float(py), float(pz)))
        self._p1_placed = True
        return True

    def place_p2_on_switch(self, state, p2, now):
        """RAM fallback: when the follower (P2) cannot physically path to the hold-switch
        across the specific boundary P1 crossed, WRITE P2's actor position directly onto
        the switch's exact 3D coords so it stands on the switch holding the fence open.
        Consistent with the bot's other verified RAM writes (force-unlock flags, the
        crit/never-miss caves, stat writes). Guarded: fence objective active, verified
        two-player slots, valid P2 actor ptr in MEM1, finite switch coords (incl the
        switch entity's OWN y), and P2's room clear. Returns True on a write."""
        obj = self._fence_obj
        ad = getattr(self.reader, 'ad', None) or getattr(self.inputs, 'ad', None)
        if (obj is None or ad is None or not callable(getattr(ad, 'write_memory', None))
                or state.get('verified') is not True or state.get('phase') != 14
                or type(state.get('floor')) is not int or not 1 <= state['floor'] <= 17
                or set(state.get('players', {})) != {1, 2} or not p2 or p2.get('hp', 0) <= 0):
            return False
        room = p2.get('room')
        if any(e.get('kind') == 'enemy' and type(e.get('hp')) in (int, float) and e['hp'] > 0
               and e.get('room') == room for e in state.get('entities', ())[:512]):
            return False                                  # room-clear only (combat owns a room with enemies)
        sx, sy, sz = obj.get('sx'), obj.get('sy'), obj.get('sz')
        if sy is None:
            sy = p2.get('y')                              # switch had no y: keep P2's current height
        if not all(type(v) in (int, float) and math.isfinite(v) for v in (sx, sy, sz)):
            return False
        try:
            addr = int(p2['ptr'], 16) if isinstance(p2.get('ptr'), str) else int(p2['ptr'])
        except (TypeError, ValueError, KeyError):
            return False
        if not (0x80000000 <= addr <= 0x81800000 - 0x44):   # P2's actor must be in MEM1
            return False
        ad.write_memory(addr + 0x38, struct.pack('>3f', float(sx), float(sy), float(sz)))  # x/y/z f32
        self._p2_placed = True
        return True

    def _next_door_toward(self, from_room, to_room):
        """BFS the learned area graph (treated UNDIRECTED - a door P1 crossed one way is
        traversable the other) for a room path from_room -> to_room, returning the
        door_str on the FIRST edge, or None. Routes P2 room-by-room through the exact
        doors P1's crossings recorded (seeding from P1's real traversal) even when P1
        recorded only the forward direction - instead of straight-driving into a wall."""
        graph = self._area_graph
        if from_room is None or from_room == to_room:
            return None
        adj = {}
        for a, doors in graph.items():
            for dstr, b in doors.items():
                adj.setdefault(a, []).append((b, dstr))
                adj.setdefault(b, []).append((a, dstr))     # doors are bidirectional
        if from_room not in adj:
            return None
        from collections import deque
        prev = {from_room: (None, None)}
        q = deque([from_room])
        while q:
            r = q.popleft()
            if r == to_room:
                break
            for nr, dstr in adj.get(r, []):
                if nr not in prev:
                    prev[nr] = (r, dstr)
                    q.append(nr)
        if to_room not in prev:
            return None
        cur, first_door = to_room, None
        while prev[cur][0] is not None:
            if prev[cur][0] == from_room:
                first_door = prev[cur][1]
            cur = prev[cur][0]
        return first_door

    def _live_gate_for(self, state, room, door_str):
        """The live gate entity whose gkey matches door_str (in ANY room - a connector
        door's single room-id tag is unreliable, which is why a room OWNS its doors via
        the graph; the door's physical coords are what P2 drives to), or None."""
        for e in state.get('entities', ())[:512]:
            try:
                gk = (str(e.get('class')), round(float(e['x']), 1), round(float(e['z']), 1))
            except (KeyError, TypeError, ValueError):
                continue
            if str(gk) == door_str:
                return e
        return None

    def fence_role(self, state, slot, player, now, commands, moves, steering):
        """Two-player hold-fence crossing (the operator's multiplayer goal, now
        load-bearing). P2 drives onto the switch and HOLDS it down (standing on it);
        P1 drives THROUGH the paired fence while it is held open. Returns True when it
        issued this slot's fence input. The caller only invokes this when there is no
        combat to do, so P2's defense stays intact via the normal swarm path otherwise."""
        obj = self._fence_obj
        if obj is None or not player or player.get('hp', 0) <= 0:
            return False
        from . import pso_coop_gates as gates
        nav = self.maps.get(state, player)
        # Is P2 standing ON the switch (holding the fence open)? P1 only COMMITS through
        # the fence once it is - otherwise P1 waits AT the fence (aims at it, no overshoot)
        # so it doesn't bounce the raised fence while P2 is still en route.
        p2 = state.get('players', {}).get(2) or {}
        p2_on = (type(p2.get('x')) in (int, float)
                 and math.hypot(obj['sx'] - p2['x'], obj['sz'] - p2['z']) <= FENCE_SWITCH_ON)
        # NOTE: the RAM position-writes (place P2 on the switch / P1 past the fence) are
        # PROVEN DEAD for this gate - the laser fence is a LIVE COLLISION check, so a
        # teleport onto the switch doesn't fire its sensor and a teleport past the fence
        # snaps back. Only the legitimate mechanic works: P2 PHYSICALLY walks onto the
        # switch (collision overlap drops the fence) and P1 PHYSICALLY walks through.
        # Is the fence ACTUALLY, PHYSICALLY down right now? (reads its live collision field)
        fence_down = self._fence_is_down(state)
        fine = False
        if slot == 1:
            # P1 FLIPS THE SWITCH ITSELF (operator: "walk up to the door, flip the switch,
            # toggle it"). The old two-player HOLD (P1 waits while P2 stands on the plate) is
            # dead (P2-to-switch unreliable), so P1 no longer WAITS: when the fence is UP it
            # WALKS to the switch and PRESSES A on the panel to toggle the fence open (the
            # stage-flag force-unlock in maybe_force_unlock drops the laser once P1 is at the
            # gate's room); when the fence reads DOWN it commits THROUGH. P2 swarm-follows.
            if fence_down or p2_on:
                target = gates.through_point(player['x'], player['z'], obj['fx'], obj['fz'], FENCE_CROSS_OVERSHOOT)
                label = 'fence_cross'
            else:
                sx, sz, sroom = obj['sx'], obj['sz'], obj.get('sroom')
                sdist = math.hypot(sx - player['x'], sz - player['z'])
                if sdist <= FENCE_SWITCH_ON or (player.get('room') == sroom and sdist <= FENCE_FINE_DIST):
                    # ON / onto the switch plate: press A to toggle it and stand on it.
                    commands.append((slot, ["a"], .25))
                    moves[slot] = (player, (sx, sz), nav, False)
                    steering[slot] = (player, (sx, sz), "fence_flip_switch")
                    _fs = getattr(self.inputs, "stats", None)
                    if isinstance(_fs, dict):
                        _fs["fence_flip"] = _fs.get("fence_flip", 0) + 1
                    return True
                if player.get('room') == sroom:
                    target, label = (sx, sz), 'fence_switch_approach'   # in the switch room, walk onto it
                else:
                    door_str = self._next_door_toward(player.get('room'), sroom)
                    ent = self._live_gate_for(state, player.get('room'), door_str) if door_str else None
                    if ent is not None:
                        target = gates.through_point(player['x'], player['z'], ent['x'], ent['z'], FENCE_CROSS_OVERSHOOT)
                        label = 'fence_to_switch_door'
                    else:
                        target, label = (sx, sz), 'fence_switch_direct'   # route straight at the switch
        else:
            # P2 PHYSICALLY onto the switch plate so the collision SENSOR fires. In the
            # switch's room: drive to the plate, and within FENCE_FINE_DIST switch to a
            # TIGHT terminal approach (short precise straight pulses, no overshoot and no
            # wedge-escape fling - that bounced P2 short at ~9u) to actually STAND ON it.
            # Else ROUTE door-by-door via the crystal graph toward the switch's room; if
            # P2 is off P1's recorded network, REGROUP toward P1's current room; last
            # resort drive straight at P1 to rejoin the network.
            sroom = obj.get('sroom')
            p1pos = state.get('players', {}).get(1) or {}
            if player.get('room') == sroom:
                target = (obj['sx'], obj['sz'])
                sdist = math.hypot(obj['sx'] - player['x'], obj['sz'] - player['z'])
                if p2_on:
                    label = 'fence_switch_hold'
                elif sdist <= FENCE_FINE_DIST:
                    label, fine = 'fence_switch_fine', True
                else:
                    label = 'fence_switch_approach'
            else:
                door_str = self._next_door_toward(player.get('room'), sroom)
                regroup = False
                if door_str is None and type(p1pos.get('room')) is int:
                    door_str = self._next_door_toward(player.get('room'), p1pos.get('room'))
                    regroup = door_str is not None
                ent = self._live_gate_for(state, player.get('room'), door_str) if door_str else None
                if ent is not None:
                    target = gates.through_point(player['x'], player['z'], ent['x'], ent['z'], FENCE_CROSS_OVERSHOOT)
                    label = 'fence_regroup' if regroup else 'fence_route'
                elif type(p1pos.get('x')) in (int, float):
                    target, label = (p1pos['x'], p1pos['z']), 'fence_to_p1'
                else:
                    target, label = (obj['sx'], obj['sz']), 'fence_switch_approach'
        if fine:
            # TIGHT terminal approach: short precise pulses straight at the plate center,
            # no overshoot/wedge-escape, so P2 lands exactly ON the trigger instead of
            # bouncing short. Short holds let the next tick correct any overshoot.
            waypoint, keys, escaping, dur = target, movement_keys(player, target), False, .08
        else:
            route, exact = nav.toward((player['x'], player['z']), target)
            waypoint = route[1] if (exact and route and len(route) > 1) else target
            keys, escaping = self._unwedge(slot, player, waypoint, now)
            dur = .40
        commands.append((slot, keys, dur))
        moves[slot] = (player, waypoint, nav, False)
        steering[slot] = (player, waypoint, (label + '_unwedge') if escaping else label)
        if slot == 2:
            st = getattr(self.inputs, 'stats', None)
            if isinstance(st, dict):
                st['p2_role'] = label
                st['p2_fine'] = int(fine)
        return True

    def _fence_is_down(self, state):
        """Read the current fence objective's LIVE collision descriptor to tell whether
        the laser has PHYSICALLY dropped. Reads native_state (+0xAC) and the collision
        sub-object's enable field (+0xA4 -> +0x14); surfaces both as telemetry
        (fence_native_live / fence_coll_live). Returns True when the collision enable
        reads 0 (laser down). Read-only; empirically reveals the real collision field
        when P2 physically triggers the switch (complements the static Ghidra RE)."""
        obj = self._fence_obj
        ad = getattr(self.reader, 'ad', None) or getattr(self.inputs, 'ad', None)
        if obj is None or ad is None or not callable(getattr(ad, 'read_memory', None)):
            return False
        try:
            faddr = int(obj['fptr'], 16) if isinstance(obj.get('fptr'), str) else int(obj['fptr'])
        except (TypeError, ValueError, KeyError):
            return False
        if not (0x80000000 <= faddr <= 0x81800000 - 0x100):
            return False
        read, coll = ad.read_memory, None
        try:
            native = struct.unpack('>I', read(faddr + 0xAC, 4))[0]
            subptr = struct.unpack('>I', read(faddr + 0xA4, 4))[0]
            if 0x80000000 <= subptr <= 0x81800000 - 0x40:
                coll = struct.unpack('>I', read(subptr + 0x14, 4))[0]
        except (struct.error, OSError):
            return False
        st = getattr(self.inputs, 'stats', None)
        if isinstance(st, dict):
            st['fence_native_live'] = native
            st['fence_coll_live'] = coll if coll is not None else -1
        return coll == 0

    def advance_on_stall(self, state, now):
        """PERPETUAL PLAY (operator: never stand still, go area-to-area). When forward
        progress has STALLED - no NEW room for ADVANCE_STALL_S and the room is clear
        (nothing to fight) - drive PSO's own native floor transition to the NEXT area
        via the build agent's verified engine (gbox.pso_fence.advance_floor), so a gate
        that can't be solved never freezes the party: it warps on and keeps playing,
        looping the game. Fail-soft (module not shipped / warp refused) and throttled;
        combat always finishes first. Returns True when a warp was attempted."""
        if not (state.get('verified') and state.get('phase') == 14 and state.get('floor', 0) > 0
                and set(state.get('players', {})) == {1, 2}):
            return False
        p1 = state['players'].get(1)
        if not p1 or p1.get('hp', 0) <= 0:
            return False
        # A FRESH stall window per area: room ids repeat across floors, so reset the
        # timer whenever the floor changes (a warp or a natural exit) - each new area
        # gets the full ADVANCE_STALL_S to be played THROUGH before any warp fires.
        floor = state.get('floor')
        if floor != self._adv_floor:
            self._adv_floor = floor
            rec = self.room_dwell.get('_cur')
            if rec:
                rec['since'] = now
            return False
        rec = self.room_dwell.get('_cur')
        dwell = now - rec['since'] if rec else 0.0
        if now - self._last_warp_at < ADVANCE_WARP_GAP_S:
            return False
        # BOSS DEFEAT (operator: KILL the boss, but don't burn 5.5 min on one we can't
        # damage yet). Suppress the warp while a boss is ALIVE *and* we're still making
        # Liveness prefers the boss agent's latched boss_alive (handles inter-phase gaps:
        # True=fight, False=confidently dead), falling back to my entity scan + grace, and
        # ALSO True whenever the advisor reports boss HP remaining (single-body Dragon).
        # ONCE WE HAVE DAMAGED THE BOSS (_boss_damaged: its HP dropped or a part died), it is
        # WINNABLE - NEVER warp off it, STAY to the kill up to the BOSS_SAFETY_S ceiling
        # (operator: the Dragon was warped off at 66%/50% HP, throwing away the kill). A boss
        # we have NOT yet damaged still gets the BOSS_NOPROG_S escape (can't hurt it -> move
        # on). So: damaged -> hold to kill; never-damaged -> ~75s then release.
        adv = self._boss_adv if isinstance(self._boss_adv, dict) else {}
        hpf = adv.get('boss_hp_frac')
        boss_still_alive = ((adv.get('boss_floor') and adv.get('boss_alive') is not False)
            or (type(hpf) in (int, float) and hpf > 0)
            or (self._boss_present_now and (self._boss_alive_now
                or (now - self._boss_alive_at) < BOSS_DEAD_GRACE_S)))
        making_progress = (now - self._boss_progress_at) < BOSS_NOPROG_S
        if boss_still_alive and (self._boss_damaged or making_progress) and dwell < BOSS_SAFETY_S:
            return False
        # ABSOLUTE anti-freeze backstop (NON-NEGOTIABLE): no new room for STALL_HARDCAP_S
        # warps REGARDLESS of enemies / cleared state - unreachable enemies behind a gate
        # (floor-7 Mine2 pin) must never freeze the party. Below the cap, the GRACEFUL
        # path warps only in a CLEARED room after ADVANCE_STALL_S (finish fights first).
        hardcap = dwell >= STALL_HARDCAP_S
        if not hardcap:
            if dwell < ADVANCE_STALL_S:
                return False
            # FULL EXPLORATION: do NOT advance a cleared area while there are still UNVISITED
            # rooms in it (frontier). Keep exploring room-to-room; only the absolute hardcap
            # (genuinely stuck, can't reach the rest) may warp past unexplored rooms.
            if self._frontier:
                return False
            room = p1.get('room')
            if any(e.get('kind') == 'enemy' and type(e.get('hp')) in (int, float) and e['hp'] > 0
                   and e.get('room') == room for e in state.get('entities', ())[:512]):
                return False                              # graceful: fight first
        ad = getattr(self.reader, 'ad', None) or getattr(self.inputs, 'ad', None)
        if ad is None:
            return False
        self._last_warp_at = now
        self._floor_advances += 1
        if hardcap:
            self._hardcap_warps += 1
        try:
            from .pso_fence import advance_floor
            result = advance_floor(ad)
        except Exception as exc:                          # noqa: BLE001 - module absent / warp refused; never block play
            result = {'error': str(exc)[:160]}
        st = getattr(self.inputs, 'stats', None)
        if isinstance(st, dict):
            st['floor_advances'] = self._floor_advances
            st['stall_hardcap_warps'] = self._hardcap_warps
            st['floor_advance'] = result if isinstance(result, dict) else {'ok': bool(result)}
        return True

    def combat_dodge(self, state, slot, player, enemies, envelope, target, now):
        """DODGE: reposition during battle to AVOID attacks instead of standing still.

        Returns None when no threat is near. Otherwise a dict describing a strafe
        waypoint and whether to ACT on it THIS tick. A threat is HOT when an enemy is
        close, is facing the bot (aimed), or is a boss within its (larger) telegraph
        range; the hot radius widens on spots the party has died at before. When hot
        AND there is no clean shot to take this tick, the bot STRAFES perpendicular to
        the strongest threat's attack line (side-stepping out of it), blending straight
        repulsion when critically close, and picking the side that both increases
        distance from every threat and moves away from learned fatal spots. When a shot
        is lined up it fires instead (act=False) and dodges the next tick - so it fights
        WHILE moving, never tanking in place."""
        px, pz = player.get("x"), player.get("z")
        if type(px) not in (int, float) or type(pz) not in (int, float):
            return None
        ep, floor = state.get("episode"), state.get("floor")
        pen = self.death_memory.penalty(ep, floor, px, pz) if self.death_memory else 0.0
        # BOSS attack window (advisor boss_special_state / phase "<aim>_attacking"): the
        # fire-breath cone / eruption fires NOW - dodge decisively (bigger step), but still
        # fire when a shot is lined up (the body is also most exposed in this window).
        adv = self._boss_adv if isinstance(self._boss_adv, dict) else {}
        boss_special = bool(adv.get("boss_special_state")
                            or str(adv.get("phase") or "").endswith("_attacking"))
        # Boss mine adds (De Rol Le): steer AWAY from them (operator: never stand on mines).
        mine_xz = [(m.get("x"), m.get("z")) for m in (adv.get("adds") or [])
                   if isinstance(m, dict) and type(m.get("x")) in (int, float) and type(m.get("z")) in (int, float)]
        threats = []
        for e in enemies:
            ex, ez = e.get("x"), e.get("z")
            if type(ex) not in (int, float) or type(ez) not in (int, float):
                continue
            if type(e.get("hp")) in (int, float) and e["hp"] <= 0:
                continue
            boss = str(e.get("class", "")).startswith(("TBoss", "TObjBoss"))
            radius = DODGE_BOSS_RADIUS if boss else DODGE_DANGER_RADIUS
            d = math.hypot(ex - px, ez - pz)
            if d > radius:
                continue
            eh = e.get("heading_deg")
            aimed = False
            if type(eh) in (int, float) and d > 1:
                bearing = math.degrees(math.atan2(px - ex, pz - ez))
                aimed = abs(delta(bearing, eh)) <= DODGE_FACING_CONE
            # Operator 11-03 (dodge far more readily): hot when the enemy is close, a boss
            # in range, OR aiming at the bot ANYWHERE in its danger radius ("taking fire").
            hot = (d <= DODGE_HOT_RADIUS * (1.0 + pen) or (boss and d <= DODGE_BOSS_HOT)
                   or aimed)
            w = (1.0 / max(d, 6.0)) * (2.4 if boss else 1.0) * (1.7 if aimed else 1.0)
            threats.append((ex, ez, d, w, aimed, boss, hot))
        if not threats:
            return None
        min_dist = min(t[2] for t in threats)
        anyhot = any(t[6] for t in threats)
        # A clean shot available THIS tick? Then take it (don't dodge) and dodge next tick.
        fire_ready = False
        if target is not None and isinstance(envelope, dict):
            dist, angle, vok = attack_geometry(player, target, envelope)
            fire_ready = (vok and dist <= envelope.get("horizontal", 0)
                          and abs(angle) <= envelope.get("horizontal_half_angle", 0)
                          and now - self.last_attack.get(slot, 0) >= ATTACK_CADENCE_S / max(self.inputs.speed(), 1e-6))
        # Strafe perpendicular to the strongest threat; choose the side that gains the
        # most distance from all threats and aligns with the fatal-spot avoid vector.
        strong = max(threats, key=lambda t: t[3])
        sx, sz = px - strong[0], pz - strong[1]
        n = math.hypot(sx, sz) or 1.0
        perp = (-sz / n, sx / n)
        avoid = self.death_memory.avoid_vector(ep, floor, px, pz) if self.death_memory else (0.0, 0.0)
        best = None
        for sign in (1.0, -1.0):
            ux, uz = perp[0] * sign, perp[1] * sign
            nx, nz = px + ux * 26.0, pz + uz * 26.0
            score = sum((math.hypot(nx - ex, nz - ez) - d) * w for ex, ez, d, w, *_ in threats)
            score += (ux * avoid[0] + uz * avoid[1]) * DEATH_BIAS_GAIN
            for mx, mz in mine_xz:                       # penalise strafing toward a mine add
                md = math.hypot(nx - mx, nz - mz)
                if md < MINE_AVOID_R:
                    score -= (MINE_AVOID_R - md) * MINE_AVOID_GAIN
            if best is None or score > best[0]:
                best = (score, ux, uz)
        ux, uz = best[1], best[2]
        if min_dist <= DODGE_CRITICAL:
            rx = ry = 0.0
            for ex, ez, d, w, *_ in threats:
                dx, dz = px - ex, pz - ez
                m = math.hypot(dx, dz) or 1.0
                rx += dx / m * w
                ry += dz / m * w
            rn = math.hypot(rx, ry) or 1.0
            ux, uz = ux * 0.5 + rx / rn * 0.7, uz * 0.5 + ry / rn * 0.7
        un = math.hypot(ux, uz) or 1.0
        ux, uz = ux / un, uz / un
        step = DODGE_STEP * (1.7 if boss_special else 1.0)   # evade the telegraphed boss attack decisively
        point = (px + ux * step, pz + uz * step)
        return {"act": bool(anyhot and not fire_ready), "keys": movement_keys(player, point),
                "dur": .10, "point": point, "min_dist": round(min_dist, 1),
                "hot": anyhot, "boss": any(t[5] for t in threats),
                "aimed": any(t[4] for t in threats), "penalty": round(pen, 3),
                "boss_special": boss_special}

    def _dodge_telemetry(self, dodge):
        st = getattr(self.inputs, "stats", None)
        if not isinstance(st, dict):
            return
        self._dodges += 1
        st["dodges"] = self._dodges
        st["dodge_active"] = 1
        st["dodge_min_dist"] = dodge["min_dist"]
        st["dodge_hot"] = int(dodge["hot"])
        st["dodge_boss"] = int(dodge["boss"])
        st["dodge_aimed"] = int(dodge["aimed"])
        st["dodge_death_penalty"] = dodge["penalty"]
        st["boss_dodge_window"] = int(dodge.get("boss_special", False))

    def _boss_target_row(self, player):
        """BOSS DEFEAT: turn the advisor's weak point into an enemy-shaped target row so
        the existing aim/fire pipeline (attack_geometry + envelope + fire cadence) shoots
        the boss's exposed section. Returns None off-boss / on any uncertainty, so normal
        targeting is unchanged. Weak point is the boss body-centre until sub-part offsets
        are pinned (interface stays the same when the build agent refines it)."""
        adv = self._boss_adv
        wp = None
        if isinstance(adv, dict) and adv.get('active'):
            wp = adv.get('weakpoint') if isinstance(adv.get('weakpoint'), dict) else adv.get('weakpoint_pos')
        if not (isinstance(wp, dict) and type(wp.get('x')) in (int, float) and type(wp.get('z')) in (int, float)):
            # FALLBACK: advisor inactive/no locked weak point this tick but a boss IS present
            # -> aim the nearest live boss entity so engagement stays CONTINUOUS (don't revert
            # to explore/idle and leave the boss un-fought between advisor ticks).
            nr = self._boss_nearest_row
            if isinstance(nr, dict) and type(nr.get('x')) in (int, float) and type(nr.get('z')) in (int, float):
                wp = nr
            else:
                return None
        _advd = adv if isinstance(adv, dict) else {}
        return {'kind': 'enemy', 'class': wp.get('class') or _advd.get('boss') or 'TBoss',
                'ptr': wp.get('ptr') or ('boss:%s' % (_advd.get('boss') or _advd.get('floor') or 'x')),
                'x': float(wp['x']), 'z': float(wp['z']),
                'y': float(wp.get('y') if type(wp.get('y')) in (int, float) else (player.get('y') or 0.)),
                'hp': wp.get('hp', 1), 'hp_max': wp.get('hp_max', 1), 'room': player.get('room')}

    def boss_combat(self, state, slot, player, envelope, boss_row, now, commands, moves, steering, enemies, attack_rows):
        """Own this slot's boss tick (always returns True so the caller stops here and the
        generic dodge/nav never hijacks it). Fire gate is the game's ACTUAL damage flag -
        adv['boss_vulnerable'] (boss agent: weak-point +0x324 != 2) - NOT boss_special_state
        (the Dragon's state never hit 21/22 while fully vulnerable, so gating fire on it
        never fired). Policy:
          - Damageable + within the forced gun's reach: FIRE at the weak point and HOLD the
            line through the boss's movement (never-miss + crit land it). Don't strafe off.
          - Not in reach: coordinate-drive toward the weak point to get within range.
          - Not damageable, or very far/relocating: hold the stand point, dodge the
            telegraphed attack (boss_special is a DODGE cue only), ready to fire.
        MOVE target and AIM target are SEPARATE: a circling boss (the Dragon orbits the
        arena centre at r~100-160) must be fired at from the ORBIT CENTRE, not chased to
        the perimeter (chasing a point going round a ring leaves the bot 220+ off on the
        far arc). adv['boss_hold_pos'] = the recommended stand point (orbit centre for the
        Dragon; the weak point for stationary bosses); we STAND there and FIRE outward at
        weakpoint_pos. Falls back to the weak point when boss_hold_pos is absent."""
        bx, bz = boss_row["x"], boss_row["z"]          # AIM target (the boss / weak point)
        adv = self._boss_adv if isinstance(self._boss_adv, dict) else {}
        hold = adv.get("hold_pos") or adv.get("boss_hold_pos")   # boss agent's shipped key is hold_pos
        has_hold = isinstance(hold, dict) and type(hold.get("x")) in (int, float) and type(hold.get("z")) in (int, float)
        aim_dist = math.hypot(bx - player["x"], bz - player["z"])
        env_h = envelope.get("horizontal", 10.) if isinstance(envelope, dict) else 10.
        # Fire within the gun's REAL cone (the Shot's 45deg is forgiving on a moving boss;
        # the narrow rifle needs tight aim - the build layer forces the Shot on boss floors).
        half = envelope.get("horizontal_half_angle", 8.) if isinstance(envelope, dict) else 8.
        _, angle, _vok = attack_geometry(player, boss_row, envelope)
        vuln = adv.get("boss_vulnerable")
        can_fire = vuln is True or vuln is None        # fire unless the game says invulnerable
        boss_special = bool(adv.get("boss_special_state") or str(adv.get("phase") or "").endswith("_attacking"))
        # Fire range = the EQUIPPED gun's real reach x margin (live from WeaponRanges), NOT a
        # fixed cap - firing beyond the gun's reach falls short and never connects.
        env_verified = isinstance(envelope, dict) and bool(envelope.get("verified"))
        fire_range = (env_h * BOSS_FIRE_MARGIN) if (env_verified and env_h > 1.0) else BOSS_FIRE_RANGE_FALLBACK
        in_fire = aim_dist <= fire_range
        # Is the weak point MOVING (circling Dragon) or STATIC (Vol Opt monitor / surfaced
        # De Rol Le head)? Track its position: a static target must be CLOSED ON (walk to it);
        # only a moving/circling boss warrants a centre-hold. This stops the bot sitting at a
        # centroid-ish hold_pos ~270u from a stationary monitor (the Vol Opt no-close blocker).
        if self._boss_wp_xz is None or math.hypot(bx - self._boss_wp_xz[0], bz - self._boss_wp_xz[1]) > 25.0:
            self._boss_wp_xz, self._boss_wp_moved_at = (bx, bz), now
        wp_moving = (now - self._boss_wp_moved_at) < 3.0
        # A CENTRE-HOLD applies ONLY to a MOVING weak point whose hold_pos is a DISTINCT orbit
        # centre (>= BOSS_HOLD_TOL from it) still within gun reach - i.e. the circling Dragon.
        # A STATIC weak point (hold_pos == it, or not moving) is CLOSED ON directly instead.
        center_hold, cx, cz = False, 0.0, 0.0
        if has_hold and wp_moving:
            hx0, hz0 = float(hold["x"]), float(hold["z"])
            if BOSS_HOLD_TOL <= math.hypot(hx0 - bx, hz0 - bz) <= fire_range:
                center_hold, cx, cz = True, hx0, hz0
        center_dist = math.hypot(cx - player["x"], cz - player["z"]) if center_hold else aim_dist
        speed = max(self.inputs.speed(), 1e-6)
        st = getattr(self.inputs, "stats", None)

        def mark(reason):
            # One-read FIRE-SKIP breadcrumb (slot 1): why we did NOT press A this tick.
            if slot == 1 and isinstance(st, dict):
                st["boss_fire_skip"] = reason

        if slot == 1 and isinstance(st, dict):
            st["boss_approach_dist"] = round(aim_dist, 1)
            st["boss_weakpoint_dist"] = round(aim_dist, 1)
            if self._boss_wp_prev is not None:
                st["boss_approach_delta"] = round(self._boss_wp_prev - aim_dist, 2)   # + = closing, ~0 = wedged
            self._boss_wp_prev = aim_dist
            st["boss_hold_dist"] = round(center_dist, 1)
            st["boss_hold_covers"] = int(bool(center_hold))
            st["boss_fire_range"] = round(fire_range, 1)
            st["boss_in_range"] = int(in_fire)
            st["boss_vulnerable"] = int(bool(can_fire))
            st["boss_strike_window"] = int(boss_special)
            st["boss_angle"] = round(angle, 1)
            st["boss_half_angle"] = round(half, 1)
            # Player action-state (+0x326) and hit-record count (+0xA8) - the game's own
            # attack gate; read live so one telemetry pass shows if we're mid-swing / idle.
            ad = getattr(self.reader, "ad", None) or getattr(self.inputs, "ad", None)
            try:
                pa = int(player["ptr"], 16) if isinstance(player.get("ptr"), str) else int(player.get("ptr"))
                st["boss_p1_action_state"] = struct.unpack(">H", ad.read_memory(pa + 0x326, 2))[0]
                st["boss_p1_hitrec"] = struct.unpack(">I", ad.read_memory(pa + 0xA8, 4))[0]
            except Exception:
                pass

        # FIRE whenever the boss is damageable and its weak point is within the gun's reach.
        # When aligned (within the gun cone) + off cadence -> press A. When not aligned, TURN
        # TO FACE by holding the stick AT the weak point (movement_keys faces+converges, which
        # PSO uses to aim a gun) - not a perpendicular strafe that orbits without ever facing.
        # boss_firing_line is set LIVE only on the tick an attack is actually issued.
        if can_fire and in_fire:
            fired = False
            if abs(angle) > half:
                commands.append((slot, movement_keys(player, (bx, bz)), .06))   # turn to face
                steering[slot] = (player, (bx, bz), "boss_aim")
                mark("aiming")                                                  # in range+vulnerable but off-cone
            elif now - self.last_attack.get(slot, 0) < BOSS_FIRE_CADENCE_S / speed:
                commands.append((slot, movement_keys(player, (bx, bz)), .04))   # hold facing between shots
                steering[slot] = (player, (bx, bz), "boss_hold")
                mark("off_cadence")
            else:
                attack_rows.setdefault(slot, {"attempts": 0})
                commands.append((slot, ["a"], .12))
                steering[slot] = (player, (bx, bz), "boss_fire")
                fired = True
                mark("")                                                        # FIRING this tick
            if isinstance(st, dict):
                st["boss_firing_line"] = int(fired)
            return True
        if not can_fire:
            mark("not_vulnerable")
        elif not in_fire:
            mark("closing")
        # POSITION. Two cases:
        #  - CIRCLING boss (hold_covers: the orbit centre keeps the weak point in reach):
        #    drive to the centre and STOP there (within BOSS_HOLD_TOL); fire outward as it
        #    circles. Don't chase the perimeter.
        #  - MULTI-BODY / stationary boss (Vol Opt monitors, De Rol Le head): CLOSE DIRECTLY
        #    on the weak point - no standoff - until it is within fire range (then the FIRE
        #    branch above fires point-blank), walking to each next weak point as they die.
        #    This is the pre-regression "walk up and fire like mad" behaviour.
        def drive_to(tx, tz):
            # ROUTE toward the target over the collision grid (A* best-effort). toward() walks
            # to the nearest reachable cell on P1's component (up to / through the arena mouth),
            # then the stage-flag force-unlock + walk-through carry it in. WEDGE FORCE-THROUGH:
            # if the approach hasn't gotten CLOSER for BOSS_WEDGE_S (parked at an ungridded
            # arena mouth - Vol Opt 227u / Dragon 335u static), stop deferring to toward()'s
            # mouth-edge cell and drive STRAIGHT at the target with a long hold to push through
            # (combined with the per-tick force-unlock). Universal: all bosses.
            nav = self.maps.get(state, player)
            d = math.hypot(tx - player["x"], tz - player["z"])
            if self._boss_close_best is None or d < self._boss_close_best - 3.0:
                self._boss_close_best, self._boss_close_at = d, now
            wedged = (now - self._boss_close_at) > BOSS_WEDGE_S
            waypoint = (tx, tz)
            if not wedged:
                try:
                    route, _exact = nav.toward((player["x"], player["z"]), (tx, tz))
                    if route and len(route) > 1:
                        waypoint = route[1]
                except Exception:
                    pass
            keys, escaping = self._unwedge(slot, player, waypoint, now)
            commands.append((slot, keys, .30 if wedged else .18))       # long straight push when forcing the mouth
            moves[slot] = (player, waypoint, nav, False)
            steering[slot] = (player, (tx, tz),
                              "boss_force_through" if wedged else ("boss_approach_unwedge" if escaping else "boss_approach"))
            if isinstance(st, dict):
                st["boss_approaching"] = 1
                st["boss_force_through"] = int(wedged)
            mark("not_vulnerable" if not can_fire else ("wedged" if wedged else "closing"))

        if center_hold:
            if center_dist > BOSS_HOLD_TOL:
                drive_to(cx, cz)    # go to the orbit centre; from there the boss is in reach
                return True
            # at the centre, boss out of reach THIS instant (far arc) -> fall to hold/wait below
        elif aim_dist <= fire_range + BOSS_CHASE_CAP:
            drive_to(bx, bz)        # close DIRECTLY on the weak point until in fire range
            return True
        # Holding the centre with the boss out of reach this instant (far arc), or the boss is
        # unreachably far/submerged/invulnerable -> dodge a telegraphed attack if close, else
        # face the boss and wait for it to come back into range.
        if enemies and boss_special:
            dodge = self.combat_dodge(state, slot, player, enemies, envelope, boss_row, now)
            if dodge is not None and dodge["act"]:
                commands.append((slot, dodge["keys"], dodge["dur"]))
                steering[slot] = (player, dodge["point"], "boss_evade")
                self._dodge_telemetry(dodge)
                mark("dodging")
                return True
        commands.append((slot, movement_keys(player, (bx, bz)), .06))
        steering[slot] = (player, (bx, bz), "boss_hold_far")
        if isinstance(st, dict):
            st["boss_hold_far"] = 1
        mark("out_of_range")           # at the stand point but the boss is out of reach (far arc / submerged)
        return True

    def _observe_boss(self, state, now):
        """BOSS DEFEAT: read boss liveness from state entities (class TBoss*/TObjBoss*) so
        advance_on_stall can SUPPRESS the warp while a boss lives (stay and kill it, don't
        skip). Conservative: an unreadable boss HP counts as ALIVE so we never warp off a
        boss we can't measure. ALSO tracks DAMAGE PROGRESS - the lowest boss hp_frac seen
        and the live boss-part count - so the warp gate can ESCAPE a boss we can't actually
        damage (weak-point not pinned yet) after BOSS_NOPROG_S instead of burning the full
        safety cap. Credits bosses_defeated once per (episode,floor) on a confirmed kill."""
        rows = [e for e in state.get("entities", ())[:512]
                if str(e.get("class", "")).startswith(("TBoss", "TObjBoss"))]
        present = bool(rows)
        alive = any(type(e.get("hp")) not in (int, float) or e.get("hp", 0) > 0 for e in rows)
        # Nearest LIVE boss part to P1, as a weak-point FALLBACK when the advisor flickers
        # inactive (no locked weak point for a tick) - so boss engagement is CONTINUOUS and
        # the bot keeps closing/firing instead of reverting to explore/idle those ticks.
        p1 = state.get("players", {}).get(1) or {}
        px, pz = p1.get("x"), p1.get("z")
        live = [e for e in rows if (type(e.get("hp")) not in (int, float) or e.get("hp", 0) > 0)
                and type(e.get("x")) in (int, float) and type(e.get("z")) in (int, float)]
        if live and type(px) in (int, float) and type(pz) in (int, float):
            self._boss_nearest_row = min(live, key=lambda e: math.hypot(e["x"] - px, e["z"] - pz))
        elif live:
            self._boss_nearest_row = live[0]
        else:
            self._boss_nearest_row = None
        dead_confirmed = present and all(type(e.get("hp")) in (int, float) and e.get("hp", 0) <= 0 for e in rows)
        live_parts = sum(1 for e in rows if type(e.get("hp")) not in (int, float) or e.get("hp", 0) > 0)
        adv = self._boss_adv if isinstance(self._boss_adv, dict) else {}
        hp_frac = adv.get("boss_hp_frac")
        key = (state.get("episode"), state.get("floor"))
        # Per-visit reset when the boss floor changes (seed the progress timer to now so the
        # escape window starts fresh on arrival, not from a stale timestamp).
        if present and key != self._boss_floor_key:
            self._boss_floor_key = key
            self._boss_hp_best = None
            self._boss_parts_prev = None
            self._boss_progress_at = now
            self._boss_approach_best = None
            self._boss_approach_at = now
            self._boss_seen_alive = False
            self._boss_damaged = False
            self._boss_wp_prev = None
            self._boss_close_best = None
            self._boss_close_at = now
        self._boss_present_now = present
        self._boss_alive_now = alive
        if alive:
            self._boss_alive_at = now
            self._boss_seen_alive = True
            # DAMAGE PROGRESS: hp_frac dropped (single-body Dragon), or a boss part died
            # (multi-body). Either marks us as HAVING DAMAGED the boss -> hold to the kill.
            hp_prog = (type(hp_frac) in (int, float) and self._boss_hp_best is not None
                       and hp_frac < self._boss_hp_best - 1e-3)        # a real DROP (not the first read)
            part_prog = self._boss_parts_prev is not None and live_parts < self._boss_parts_prev
            if hp_prog or part_prog:
                self._boss_progress_at = now
                self._boss_damaged = True
            if type(hp_frac) in (int, float):
                # First valid read seeds best; a later lower read (even the very first drop
                # from 1.0) counts as damage via hp_prog above.
                self._boss_hp_best = hp_frac if self._boss_hp_best is None else min(self._boss_hp_best, hp_frac)
        self._boss_parts_prev = live_parts if present else None
        if self._boss_kill_key != key and self._boss_seen_alive and (dead_confirmed or adv.get("boss_cleared")):
            self._boss_kill_key = key
            self._bosses_defeated += 1
            self._boss_seen_alive = False
        st = getattr(self.inputs, "stats", None)
        if isinstance(st, dict):
            st["boss_present"] = int(present)
            st["boss_alive_entity"] = int(alive)       # my entity scan (advisor's latched boss_alive stays authoritative)
            st["bosses_defeated"] = self._bosses_defeated
            st["boss_no_progress_s"] = round(now - self._boss_progress_at, 1) if present else 0.0
            if type(hp_frac) in (int, float):
                st["boss_hp_frac"] = round(hp_frac, 3)
            # LIVE per-tick boss-combat flags (reset here every tick; boss_combat sets them
            # only on the tick it actually fires / approaches). This runs before the per-slot
            # loop, so a stale 1 can't persist onto a non-boss floor - the reading is trustworthy.
            st["boss_firing_line"] = 0
            st["boss_approaching"] = 0
            st["boss_force_through"] = 0
            st["boss_fire_skip"] = ""

    def survival_tick(self, state):
        """NEVER-DIE (operator 11-03: P2 died and stayed dead). The survival write-side
        (pso_survival: infinite Scape Dolls + instant revive + death log) lives in
        pso_master_build, which the running worker CANNOT hot-reload (not a BOT_MODULE in
        the loaded hot_reload) - so it was never actually live. pso_coop IS hot-reloadable,
        so we drive the SAME write-side here for every PRESENT player every tick; a plain
        bot-reload (no worker restart) brings never-die live. Generalised to all present
        slots so players 3/4 (slots 2,3) are unkillable the moment 4-player seating lands
        (the RAM revive backstop works even before a slot is co-op-verified; native gear
        for 3/4 waits on ad._pso_verified_player_slots, per the build agent). Fully
        fail-soft: it must NEVER raise into the loop, and it keeps the death log populated."""
        ad = getattr(self.reader, 'ad', None) or getattr(self.inputs, 'ad', None)
        if ad is None:
            return
        st = getattr(self.inputs, 'stats', None)
        try:
            from . import pso_survival
        except Exception as exc:                       # module absent -> cannot help; never raise
            if isinstance(st, dict):
                st['survival_import_error'] = str(exc)[:120]
            return
        # Present players -> 0-based survival slots (slot 1 -> index 0 ... slot 4 -> index 3).
        indices = sorted({s - 1 for s in state.get("players", {}) if type(s) is int and 1 <= s <= 4})
        for player_index in (indices or [0, 1]):
            suffix = 'p%d' % (player_index + 1)
            try:
                rep = pso_survival.apply_survival(ad, player_index)
            except Exception as exc:                   # fail-soft per player; keep playing
                if isinstance(st, dict):
                    st['survival_error_%s' % suffix] = str(exc)[:120]
                continue
            if isinstance(st, dict) and isinstance(rep, dict):
                st['survival_ok_%s' % suffix] = int(bool(rep.get('ok')))
                if rep.get('scapedoll') is not None:
                    st['mb_scapedoll_%s' % suffix] = rep['scapedoll']
                st['mb_scapedoll_ok_%s' % suffix] = int(bool(rep.get('scapedoll_ok')))
                if type(rep.get('revives')) in (int, float):
                    st['mb_revives_%s' % suffix] = rep['revives']
                st['mb_downed_%s' % suffix] = int(bool(rep.get('downed')))
                # Mirror the build agent's 3x-speed attack-state probe (flat scalars, global -
                # same each call). The coordinator needs speed_probe_locked to green-light phase (b).
                for _k in ('speed_probe_n', 'speed_probe_atk', 'speed_probe_gate', 'speed_probe_locked'):
                    if _k in rep:
                        st[_k] = rep[_k]

    def _frontier_waypoint(self, state, player):
        """FULL EXPLORATION: the world position of the NEAREST unvisited area room, so P1 can
        walk INTO it. A frontier room has no P1 centroid yet (never entered), but its loaded
        entities DO carry positions - use the centroid of that room's entities as the target.
        Returns (x,z) or None (no frontier / no positioned entity there)."""
        if not self._frontier:
            return None
        px, pz = player.get("x"), player.get("z")
        if type(px) not in (int, float) or type(pz) not in (int, float):
            return None
        fset = set(self._frontier)
        sums = {}  # room -> [sx, sz, n]
        for e in state.get("entities", ())[:1024]:
            r = e.get("room")
            if r in fset and type(e.get("x")) in (int, float) and type(e.get("z")) in (int, float):
                acc = sums.setdefault(r, [0.0, 0.0, 0])
                acc[0] += e["x"]; acc[1] += e["z"]; acc[2] += 1
        best = None
        for r, (sx, sz, n) in sums.items():
            cx, cz = sx / n, sz / n
            d = math.hypot(cx - px, cz - pz)
            if best is None or d < best[0]:
                best = (d, cx, cz)
        return (best[1], best[2]) if best else None

    def publish_plan(self, state, now):
        """Publish a compact room-graph PLAN for the operator's live 2D map (the map agent
        reads it from telemetry; the i9 crystal file is not reachable from the lilspark
        server). Bounded JSON string (like steering_evidence_json) so it survives the
        telemetry path, plus the dict and a few flat scalars. Includes per-room world
        centroids (last-seen P1 position per room) for spatial node placement. Throttled,
        fail-soft; never raises into the loop."""
        st = getattr(self.inputs, "stats", None)
        if not isinstance(st, dict):
            return
        p1 = state.get("players", {}).get(1) or {}
        room, px, pz = p1.get("room"), p1.get("x"), p1.get("z")
        if type(room) is int and type(px) in (int, float) and type(pz) in (int, float):
            self._room_centroid[room] = [round(px, 1), round(pz, 1)]
        if now - self._plan_pub_at < PLAN_PUBLISH_S:
            return
        self._plan_pub_at = now
        try:
            target = self._path_next(room) if type(room) is int else None
        except Exception:
            target = None
        # EXPLORATION COVERAGE off the area's REAL room set (distinct room ids of loaded
        # entities, computed in tick), NOT the door-graph (which reads fully-explored on
        # entry). visited = rooms entered; FRONTIER = the area's rooms not yet entered.
        # Empty frontier => every real room visited = "fully mapped"; coverage rises 0->1.
        visited = set(self.p1_visited)
        reachable = set(self._area_rooms) | visited
        frontier = [r for r in self._frontier][:64]
        covered = len(visited & reachable)
        total = max(len(reachable), 1)
        plan = {"area": self._area, "episode": state.get("episode"), "floor": state.get("floor"),
                "current_room": room if type(room) is int else None, "target_room": target,
                "crit_path": [r for r in self._crit_path][:64],
                "path": [r for r in self._p1_path][:64],
                "visited": sorted(visited)[:96], "frontier": frontier,
                "coverage": round(covered / total, 3) if total else 1.0,
                "edges": {str(k): {str(dk): v for dk, v in d.items()}
                          for k, d in list(self._area_graph.items())[:80]},
                "centroids": {str(k): v for k, v in self._room_centroid.items()}}
        try:
            raw = json.dumps(plan, allow_nan=False, separators=(",", ":"))
            if len(raw.encode()) <= 7000:
                st["pso_plan_json"] = raw
                st["pso_plan"] = plan
        except (TypeError, ValueError):
            pass
        st["pso_plan_current_room"] = room if type(room) is int else -1
        st["pso_plan_target_room"] = target if type(target) is int else -1
        st["pso_plan_crit_len"] = len(self._crit_path)
        st["pso_plan_rooms_visited"] = len(self._p1_path)
        st["pso_plan_frontier"] = len(frontier)              # reachable rooms not yet entered
        st["pso_plan_coverage"] = plan["coverage"]
        st["pso_plan_explored"] = int(not frontier)          # 1 = reachable area fully explored

    def load_directive(self, now):
        """Poll the operator's map-directive file (RTS click) by mtime; parse and
        keep the current directive. Cheap and failure-tolerant - a missing or bad
        file simply means no directive (autonomous play). See pso-map-directives.md."""
        path = self.directive_path
        if path is None:
            return
        try:
            mtime = path.stat().st_mtime
        except OSError:
            self._directive = None
            return
        if mtime == self._directive_mtime:
            return
        self._directive_mtime = mtime
        from . import pso_map
        try:
            self._directive = pso_map.parse_directive(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            self._directive = None

    def publish_surface(self, state):
        """Extract the current area's collision surface and publish it once per
        area template: write pso-maps/<fingerprint>.json for the map viewer and
        fold a summary into the knowledge crystal (the growing map DB) and stats."""
        if self.map_root is None:
            return
        stats = getattr(self.inputs, "stats", None)
        def skip(reason):
            if isinstance(stats, dict):
                stats["map_surface_skip"] = reason
        if state.get("geometry_verified") is not True:
            gpk = sorted(str(k) for k in (state.get("geometry_players") or {}))
            rpk = sorted(str(k) for k in (state.get("geometry_recovery_players") or {}))
            return skip("geometry_unverified:gp=%s,recov=%s,gid=%s" % (
                gpk, rpk, bool(state.get("geometry_identity"))))
        # The collision surface is area-wide, so publish it from whichever player
        # currently PROJECTS a grid (prefer P1), not only P1 - P1 is often on a
        # recovery cell while P2 projects, and either gives the same area surface.
        gp = state.get("geometry_players") or {}
        p1 = next((state["players"][s] for s in (1, 2)
                   if s in gp and state.get("players", {}).get(s)), state.get("players", {}).get(1))
        if not p1:
            return skip("no_player")
        fingerprint = room_key(state, p1)[0]
        if fingerprint in self._published:
            if isinstance(stats, dict):
                stats["map_surface_fingerprint"] = fingerprint
            return
        # Extract inline (not via pso_map) so this fix reloads with pso_coop - the
        # pso_map module is not in hot_reload BOT_MODULES and keeps its first-loaded
        # version. Prefer whichever grid actually has floor cells (the per-player
        # Provider projection, not a present-but-floorless context grid).
        grid = state.get("collision_grid") or {}
        if not (isinstance(grid.get("floor"), (list, tuple)) and grid.get("floor")):
            grid = geometry_view(state, p1).get("collision_grid") or {}
        floor, size = grid.get("floor"), grid.get("size")
        if not isinstance(floor, (list, tuple)) or not floor or type(size) not in (int, float) or size <= 0:
            gpk = sorted(str(k) for k in (state.get("geometry_players") or {}))
            rpk = sorted(str(k) for k in (state.get("geometry_recovery_players") or {}))
            return skip("no_grid:gp=%s,recov=%s,ctxgrid=%s,ptr=%s" % (
                gpk, rpk, bool(state.get("collision_grid")), p1.get("ptr")))
        cells = [[int(c[0]), int(c[1])] for c in floor[:20000]
                 if isinstance(c, (list, tuple)) and len(c) == 2]
        xs, zs = [c[0] for c in cells], [c[1] for c in cells]
        room = p1.get("room")
        fin = lambda e: all(type(e.get(k)) in (int, float) and math.isfinite(e[k]) for k in ("x", "z"))
        gates_out, warps = [], []
        for e in list(state.get("entities", ()))[:512]:
            cls = str(e.get("class", ""))
            if not fin(e):
                continue
            if cls in ("TObjDoor", "TObjLazerFenceNorm", "TOBarrierEnergy01", "TLazerFenceSw", "TObjDoorKey"):
                gates_out.append({"class": cls, "x": round(e["x"], 1), "z": round(e["z"], 1), "room": e.get("room"),
                                  "kind": "switch" if cls in ("TLazerFenceSw", "TObjDoorKey") else "gate"})
            elif any(k in cls for k in ("Warp", "Teleport")):
                warps.append({"class": cls, "x": round(e["x"], 1), "z": round(e["z"], 1), "room": e.get("room")})
        surface = {"version": 1, "fingerprint": fingerprint, "episode": state.get("episode"),
                   "floor": state.get("floor"), "room": room, "geometry_identity": state.get("geometry_identity"),
                   "size": float(size), "bounds": {"min_x": min(xs) * size, "min_z": min(zs) * size,
                   "max_x": (max(xs) + 1) * size, "max_z": (max(zs) + 1) * size}, "cells": cells,
                   "cell_count": len(cells), "gates": gates_out[:64], "warps": warps[:16],
                   "players": {str(s): [round(p["x"], 1), round(p["z"], 1)]
                               for s, p in state.get("players", {}).items() if fin(p)}}
        try:
            maps_dir = self.map_root / "pso-maps"
            maps_dir.mkdir(parents=True, exist_ok=True)
            path = maps_dir / (fingerprint + ".json")
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(surface, separators=(",", ":")), encoding="utf-8")
            tmp.replace(path)
        except OSError:
            return
        self._published.add(fingerprint)
        summary = {"fingerprint": fingerprint, "episode": surface["episode"], "floor": surface["floor"],
                   "room": room, "size": surface["size"], "cell_count": len(cells),
                   "bounds": surface["bounds"], "gates": len(gates_out), "warps": len(warps)}
        if self.knowledge is not None and room_key(state, p1)[1]:
            self.knowledge.remember(fingerprint, episode=state.get("episode"), floor=state.get("floor"),
                                    room=room, surface=summary)
        if isinstance(stats, dict):
            stats["map_surface_published"] = summary
            stats["map_surface_fingerprint"] = fingerprint

    def goto_destination(self, state, player, now):
        """The GOTO target for P1 when the operator has clicked a point on the map
        (double-click = navigate there). None when there is no in-scope GOTO or it
        is already reached. P1 A*-routes to it over the collision grid in tick."""
        from . import pso_map
        directive = self._directive
        if not directive or directive.get("op") != "goto" or not pso_map.directive_in_scope(directive, state):
            return None
        if directive.get("id") and directive["id"] == self._directive_done:
            return None
        point = (directive["x"], directive["z"])
        stats = getattr(self.inputs, "stats", None)
        if math.hypot(point[0] - player["x"], point[1] - player["z"]) <= FALLBACK_REACH:
            self._directive_done = directive.get("id") or "reached"
            if isinstance(stats, dict):
                stats["map_directive"] = {"op": "goto", "state": "reached", "x": point[0], "z": point[1]}
            return None
        if isinstance(stats, dict):
            stats["map_directive"] = {"op": "goto", "state": "navigating", "x": point[0], "z": point[1]}
        return point

    def maybe_force_unlock(self, state, now):
        """Drive the fail-safe for P1's room: fire on a RECALLED template at once
        (we already know its flags), else only after FALLBACK_STUCK_S of no
        forward progress. Never while the room still has live enemies (that is a
        room-clear gate combat owns), and once per room per run."""
        if not (state.get('verified') and state.get('phase') == 14 and state.get('floor', 0) > 0
                and set(state.get('players', {})) == {1, 2}):
            return
        p1 = state['players'].get(1)
        if not p1 or p1.get('hp', 0) <= 0:
            return
        room = p1.get('room')
        if any(e.get('kind') == 'enemy' and e.get('hp', 0) > 0 and e.get('room') == room
               for e in state.get('entities', ())):
            return
        rec = self.room_dwell.get('_cur')
        dwell = now - rec['since'] if rec else 0.
        if self._recalled_flags(state, p1) is not None or dwell >= FALLBACK_STUCK_S:
            self.force_forward_unlock(state, 1, p1, now)

    def _forward_dwell_telemetry(self, state, now, engaged):
        """Scalar fail-safe telemetry: how long since P1 reached a NEW (unvisited)
        room. Measured by the visited-room COUNT, not the current room id - so a
        hub mill (bouncing between already-visited rooms like 5<->10) does NOT keep
        resetting the timer; it accumulates until the fail-safe opens the forward
        gate to a genuinely new room. Resets only on real forward progress.
        forward_stuck crossing FALLBACK_STUCK_S drives force_forward_unlock."""
        stats = getattr(self.inputs, 'stats', None)
        if not isinstance(stats, dict):
            return
        p1 = state.get('players', {}).get(1) or {}
        nvisited = len(self.p1_visited)
        rec = self.room_dwell.get('_cur')
        if rec is None or rec.get('nvisited') != nvisited:
            rec = self.room_dwell['_cur'] = {'nvisited': nvisited, 'since': now}
        dwell = now - rec['since']
        stats['forward_room'] = p1.get('room')
        stats['forward_rooms_visited'] = nvisited
        stats['forward_time_since_new_room_s'] = round(dwell, 1)
        stats['forward_stuck'] = dwell >= FALLBACK_STUCK_S
        stats['forward_fallback_engaged'] = bool(engaged)
        # FLAT diagnostics (telemetry drops nested dicts): is the exit ROOM-CLEAR
        # gated (live enemies in P1's room => combat must clear it) or a flag/quest
        # gate (0 enemies)? And is force_adjacent_door actually engaging?
        room = p1.get('room')
        stats['room_live_enemies'] = sum(
            1 for e in state.get('entities', ())
            if e.get('kind') == 'enemy' and type(e.get('hp')) in (int, float) and e['hp'] > 0
            and e.get('room') == room)
        stats['forced_adj_door_fires'] = self._adj_fires
        stats['forced_adj_door_skip'] = self._adj_skip
        if self._adj_last:
            stats['forced_adj_door_written'] = self._adj_last.get('written', 0)
            stats['forced_adj_door_room'] = self._adj_last.get('room')
            stats['forced_adj_door_gkey'] = self._adj_last.get('gkey')

    def tick(self, state):
        if not state.get("verified") or len(state.get("players", {})) != 2:
            return False
        # NEVER-DIE first, every tick, for BOTH players (operator: P2 must never stay
        # dead). Driven from pso_coop because pso_master_build's copy can't hot-reload.
        self.survival_tick(state)
        if (self.town_enabled and state.get("phase") == 14 and state.get("episode") == 1
                and state.get("floor") == 0):
            return self.tick_town(state)
        from .pso_coop_frontier import same_room_threats
        now = time.monotonic()
        enemies = [e for e in state["entities"] if e.get("kind") == "enemy" and e.get("hp", 0) > 0]
        # BOSS DEFEAT: on a boss floor consult the read-only weak-point advisor
        # (nav agent's gbox.pso_boss_strategy) ONCE per tick. When active it names the
        # boss's exposed weak section to aim at + the hazard to dodge; both bots then
        # PRIORITISE firing at it (via _boss_target_row below) instead of milling the
        # arena. Cheap, fail-soft, read-only: active=False on any uncertainty, so normal
        # rooms are untouched. Surfaces flat boss_* telemetry.
        self._boss_adv = None
        _bad = getattr(self.reader, 'ad', None) or getattr(self.inputs, 'ad', None)
        if _bad is not None and state.get('floor', 0) > 0:
            try:
                from .pso_boss_strategy import boss_target, boss_telemetry
                self._boss_adv = boss_target(_bad)
                bt = boss_telemetry(_bad)
                st = getattr(self.inputs, 'stats', None)
                if isinstance(st, dict) and isinstance(bt, dict):
                    st.update({k: v for k, v in bt.items() if not isinstance(v, (dict, list))})
            except Exception:
                self._boss_adv = None
        # FULL EXPLORATION: the area's REAL room set = the distinct room ids of the loaded
        # entities (PSO loads the area's objects/enemies/doors each with their room field),
        # so the FRONTIER (rooms P1 hasn't entered) is non-empty on arrival and only empties
        # as rooms are actually visited - not the trivially-maxed door-graph coverage.
        # advance_on_stall consults self._frontier to EXPLORE before advancing.
        self._area_rooms = {e.get("room") for e in state.get("entities", ())[:1024]
                            if type(e.get("room")) is int and 0 <= e.get("room") < 65535}
        _cur_room = (state.get("players", {}).get(1) or {}).get("room")
        _here = {_cur_room} if type(_cur_room) is int else set()
        self._frontier = sorted(self._area_rooms - self.p1_visited - _here)   # other rooms not yet entered
        # BOSS DEFEAT: read boss liveness BEFORE advance_on_stall so the warp is suppressed
        # while a boss lives (stay and kill it, don't warp off the boss floor).
        self._observe_boss(state, now)
        # Publish the compact room-graph plan for the operator's live 2D map (throttled).
        self.publish_plan(state, now)
        # Operator's guaranteed fail-safe: a stuck (or recognized) room's forward
        # gate is opened by setting its verified native stage flags - progression
        # never stalls. Done before movement so the same tick can walk through.
        self.maybe_force_unlock(state, now)
        # PERPETUAL PLAY: if progress has stalled at ANY gate in a cleared room, warp to
        # the next floor (native loader) so the party never stands still - it goes
        # area-to-area and loops the game. Done before movement so a stalled tick acts.
        if self.advance_on_stall(state, now):
            return False
        # DEATH-DRIVEN LEARNING: refresh the fatal-spot map (down-and-revive records the
        # build side logs) so dodge + boss positioning avoid where the party died.
        _st0 = getattr(self.inputs, "stats", None)
        if self.death_memory is not None:
            self.death_memory.refresh(now, self.map_root)
            if isinstance(_st0, dict):
                p1 = state["players"].get(1) or {}
                _st0.update(self.death_memory.stats(state.get("episode"), state.get("floor"),
                                                    p1.get("x"), p1.get("z")))
                _st0["dodge_active"] = 0           # set to 1 for the tick a dodge actually fires
        # RTS map: publish this area's collision surface (once) and read any
        # operator GOTO/PRESS/ATTACK click. P1 consumes it below; else autonomous.
        self.publish_surface(state)
        self.load_directive(now)
        # Two-player hold-fence crossing objective (the Forest exit): pick the nearest
        # un-crossed laser-fence + hold-switch pair, regardless of room-visited status
        # (fix A). Cross-detection: once P1 reaches the fence (armed), a later room
        # change away from it marks that fence crossed so P1 does not re-target it.
        self._now_ref = now
        p1row = state['players'].get(1)
        self._fence_obj = self.select_fence_objective(state, p1row) if (p1row and p1row.get('hp', 0) > 0) else None
        # ANTI-STALL (operator: never stand still): a fence attempt is time-bounded. Track
        # the current attempt; if P1 has not reached a NEW room within FENCE_GIVEUP_S, GIVE
        # UP - cool that fence down and drop the objective so P1/P2 resume exploring and
        # fighting (continuous motion) instead of parking at the fence. It is retried after
        # FENCE_RETRY_S. So the pair cycles attempt -> explore/fight -> re-attempt, forever.
        if self._fence_obj:
            fence = self._fence_obj['fence']
            visited = len(self.p1_visited)
            if self._fence_try_fence != fence:
                self._fence_try_fence, self._fence_try_since, self._fence_try_visited = fence, now, visited
            elif visited > self._fence_try_visited:
                self._fence_try_since, self._fence_try_visited = now, visited   # progress: reset the timer
            elif now - self._fence_try_since >= FENCE_GIVEUP_S:
                self._fence_cooldown[fence] = now + FENCE_RETRY_S
                self._fence_giveups += 1
                self._fence_obj = self._fence_try_fence = None
        else:
            self._fence_try_fence = None
        if self._fence_obj and p1row:
            fo = self._fence_obj
            fd1 = math.hypot(fo['fx'] - p1row['x'], fo['fz'] - p1row['z'])
            p1room = p1row.get('room')
            if fd1 <= CROSS_DIST:
                self._fence_arm = {'gkey': fo['fence'], 'room': p1room}
            elif (self._fence_arm and self._fence_arm['gkey'] == fo['fence']
                  and p1room != self._fence_arm['room'] and fd1 > CROSS_DIST * 2):
                self._crossed_fences.add(fo['fence'])     # was on the fence, now elsewhere = crossed it
                self._fence_arm, self._fence_obj = None, None
        _fstats = getattr(self.inputs, 'stats', None)
        if isinstance(_fstats, dict):
            _fstats['fence_objective'] = int(self._fence_obj is not None)
            _fstats['fence_giveups'] = self._fence_giveups
            _fstats['fence_attempt_age_s'] = round(self._now_ref - self._fence_try_since, 1) if self._fence_try_fence else 0.0
            _fstats['p2_placed'] = int(self._p2_placed)
            _fstats['p1_placed'] = int(self._p1_placed)
            _fstats['fence_coll_probe'] = self._fence_coll_skip
            if self._fence_coll_before is not None:
                _fstats['fence_coll_before'] = self._fence_coll_before
            if self._fence_obj and p1row:
                _fstats['fence_dist_p1'] = round(math.hypot(self._fence_obj['fx'] - p1row['x'],
                                                            self._fence_obj['fz'] - p1row['z']), 1)
                _fstats['fence_switch_room'] = self._fence_obj.get('sroom')
                _p2 = state['players'].get(2) or {}
                if type(_p2.get('x')) in (int, float):
                    _p2d = math.hypot(self._fence_obj['sx'] - _p2['x'], self._fence_obj['sz'] - _p2['z'])
                    _fstats['p2_switch_dist'] = round(_p2d, 1)
                    _fstats['p2_on_switch'] = int(_p2d <= FENCE_SWITCH_ON)
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
            if slot != 1:
                # Two-player hold-fence crossing: when a fence objective is active and
                # P2 has no enemy on top of it, P2 BREAKS from swarm to stand on the
                # switch and HOLD the fence open for P1 (the operator's multiplayer goal,
                # now load-bearing). Combat/defense still wins if an enemy is close.
                near_enemy = any(type(e.get('hp')) in (int, float) and e['hp'] > 0
                                 and math.hypot(e['x'] - player['x'], e['z'] - player['z']) <= COMBAT_NEARBY_RADIUS
                                 for e in enemies)
                if self._fence_obj is not None and not near_enemy and self.fence_role(
                        state, slot, player, now, commands, moves, steering):
                    continue
                _st2 = getattr(self.inputs, 'stats', None)
                if isinstance(_st2, dict):
                    _st2['p2_role'] = 'swarm'
                    _st2['p2_near_enemy'] = int(near_enemy)
                    _st2['p2_fence_obj'] = int(self._fence_obj is not None)
                # P2 (and later P3/P4) are pure swarm-followers: orbit and defend
                # P1, with NO independent navigation. P1 is the single navigating
                # brain and never waits on a follower - this ends the deadlock.
                self.swarm_follow(state, slot, player, now, enemies, envelope,
                                  commands, moves, steering, attack_rows)
                continue
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
            # BOSS DEFEAT: on a boss floor, PRIORITISE the advisor's weak point over the
            # nearest mob so the bot actually brings the boss down (aim/fire pipeline below
            # handles it); dodge still keeps it moving between shots.
            boss_row = self._boss_target_row(player)
            if boss_row is not None:
                target = boss_row
                # BOSS DEFEAT - CLOSE THE DISTANCE. The bots were landing ZERO damage
                # because they aim+fire from wherever they stand (~250u across the arena
                # from the boss): field.combat_goal/A* gives up across a boss arena, so the
                # normal path parks them and they never reach weapon range. Drive STRAIGHT
                # at the weak point (coordinate-drive + wedge-escape, bypassing the A* gate)
                # until within the weapon envelope, THEN fall through to aim/fire. Dodge
                # (below) still handles close-quarters evasion once in range.
                # This branch fully OWNS P1's boss tick (it always continues), so the generic
                # dodge below never hijacks it - the earlier bug: once inside the boss dodge
                # radius, dodge strafed every tick and P1 never held a firing line (De Rol Le
                # oscillated 29<->282u, HP flat). Priority: EVADE only during the telegraphed
                # attack window; FIRE whenever in range (hold the line through the boss's
                # movement); APPROACH when reasonably close; HOLD (don't chase) a teleporting/
                # airborne boss across the arena and fire when it returns to range.
                if self.boss_combat(state, slot, player, envelope, boss_row, now,
                                    commands, moves, steering, enemies, attack_rows):
                    continue
            # DODGE (P1): move out of attacks during battle instead of standing still.
            # When a threat is hot and no clean shot is lined up this tick, strafe out of
            # the attack line (biased away from learned fatal spots); a lined-up shot
            # fires normally and dodges next tick. Preempts the fence objective - never
            # park on a fence while being attacked.
            if enemies:
                dodge = self.combat_dodge(state, slot, player, enemies, envelope, target, now)
                if dodge is not None and dodge["act"]:
                    commands.append((slot, dodge["keys"], dodge["dur"]))
                    steering[slot] = (player, dodge["point"], "combat_dodge")
                    self._dodge_telemetry(dodge)
                    continue
            # Two-player hold-fence crossing (P1 side): with no enemy to fight and a
            # fence objective active, P1 drives THROUGH the fence while P2 holds the
            # switch - instead of oscillating in the hub. Combat still preempts (target).
            if target is None and self._fence_obj is not None and self.fence_role(
                    state, slot, player, now, commands, moves, steering):
                continue
            # FULL EXPLORATION (operator: go room to room, battle enemies, complete the level
            # - do NOT beeline the exit). P1 (the sole navigator) actively walks to the NEAREST
            # UNVISITED area room; entering it marks it visited (coverage ticks up) and its
            # enemies become combat targets. Only once EVERY room is visited (frontier empty)
            # does the normal forward nav below take the area exit/telepipe - so the exit is
            # deferred until the area is fully explored. P2 swarm-follows P1. Combat preempts
            # (target set), so this only fires in a cleared room with rooms still to explore.
            if slot == 1 and target is None and self._frontier:
                _se = getattr(self.inputs, "stats", None)
                if isinstance(_se, dict):
                    _se["explore_frontier"] = len(self._frontier)
                # FLIP THE SWITCH AT A DOOR (operator: "scan the ram and switches"). Delegate
                # FIRST to drive_forward, which detects the room's floor-panel/laser-fence
                # SWITCH (TLazerFenceSw / TObjDoorKey), WALKS to it and PRESSES A, then walks
                # THROUGH the door it gates (the stage-flag force-unlock in maybe_force_unlock
                # opens it), and already prefers UNVISITED rooms. So doors get unlocked instead
                # of the bot standing at them. Only if it finds NO forward affordance here do we
                # route straight toward the nearest frontier room to cross to unexplored areas.
                if self.drive_forward(state, slot, player, now, commands, moves, steering, fallback_slots):
                    continue
                fw = self._frontier_waypoint(state, player)
                if fw is not None:
                    nav = self.maps.get(state, player)
                    waypoint = fw
                    try:
                        route, _exact = nav.toward((player["x"], player["z"]), fw)
                        if route and len(route) > 1:
                            waypoint = route[1]
                    except Exception:
                        pass
                    keys, escaping = self._unwedge(slot, player, waypoint, now)
                    commands.append((slot, keys, .18))
                    moves[slot] = (player, waypoint, nav, False)
                    steering[slot] = (player, fw, "explore_unwedge" if escaping else "explore_frontier")
                    if isinstance(_se, dict):
                        _se["explore_frontier_dist"] = round(math.hypot(fw[0] - player["x"], fw[1] - player["z"]), 1)
                    continue
            nav = self.maps.get(state, player)
            field_owned = bool(state.get("floor", 0) > 0 and state.get("geometry_verified"))
            field_destination = self.field.destination(state, slot, nav, now) if field_owned else None
            if nav.floor is not None:
                self.margin_attempts.pop(slot,None)
            # RTS GOTO: the operator double-clicked a point on the map. P1 A*-routes
            # there over the collision grid (routing around walls), with wedge
            # recovery; gates on the way are opened by the force-unlock fail-safe.
            goto = self.goto_destination(state, player, now) if slot == 1 and target is None else None
            if goto is not None:
                route = nav.route((player["x"], player["z"]), goto)
                waypoint = route[1] if route and len(route) > 1 else goto
                keys, escaping = self._unwedge(slot, player, waypoint, now)
                commands.append((slot, keys, .08 if nav.floor is not None else .40))
                moves[slot] = (player, waypoint, nav, False)
                steering[slot] = (player, goto, 'map_goto_escape' if escaping else 'map_goto')
                continue
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
                    # forever). Still advance decisively toward the room's forward
                    # switch/door / the leader. nav.route is permissive when floor
                    # is None, and drive_forward steers straight if it yields none.
                    self.drive_forward(state, slot, player, now, commands, moves, steering, fallback_slots)
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
                    if now - self.last_attack.get(slot, 0) >= ATTACK_CADENCE_S / self.inputs.speed():
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
                # Decisive forward door/switch progression (operator 2026-11-02:
                # open and pass through EVERY door with gusto). In an enemy-free
                # room, when the field planner is only EXPLORING (timid frontier
                # hops near spawn - the live room-10 freeze), drive to the next
                # panel/door and commit THROUGH it instead. An explicit accepted
                # goal, a real gate approach, or combat are left untouched; and
                # with no grid at all, still advance when nothing else produced a
                # destination. Falls back to the field objective when no forward
                # gate remains to drive toward.
                same_room = state["players"][3 - slot].get("room") == player.get("room")
                field_dep = (self.field.status.get('players', {}).get(str(slot), {}).get('dependency')
                             if field_owned else None)
                # `exploring` only when field_owned - a wrong-build None dep must not
                # hijack the non-field goal path (that would skip wall learning).
                exploring = field_owned and field_dep in ('explore', 'unknown_geometry',
                    'no_verified_regroup_route', 'buddy_unavailable', 'buddy_regroup')
                # P1 is the SOLE navigator and drives forward itself whenever it is
                # not in combat and has no explicit accepted goal - the forward-only
                # progression (learned door links, force-unlock, walk-THROUGH) is
                # what actually advances room-to-room (reached rooms 11/14), so it
                # must own P1's movement even once the grid populates, rather than
                # defer to the field planner which stops at a gate approach and mills
                # the hub. Populating the grid is still valuable for the map + GOTO
                # A*; it just must not take over P1's autonomous progression.
                lead = slot == 1 and goal is None
                if target is None and (lead or (exploring and same_room)
                                       or (destination is None and (not field_owned or same_room))):
                    if self.drive_forward(state, slot, player, now, commands, moves, steering, fallback_slots):
                        continue
            if destination is None:
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
                self.goals.pop(slot, None)
                continue
            waypoint = route[1] if len(route) > 1 else destination
            # Five-unit collision cells need short observed pulses; a long
            # hold can cross a corner beyond the verified adjacent edge.
            duration = .08 if nav.floor is not None else .40
            commands.append((slot, movement_keys(player, waypoint), duration))
            moves[slot] = (player, waypoint, nav, not nearby)
            steering[slot] = (player, waypoint, 'native_route')
        # NEVER STAND (operator 11-03: ENDLESS visible motion; parked at a fence 80s is
        # unacceptable). Two cases, both for P1 the navigator, alive and not mid-load:
        #  (a) truly idle - produced NO command this tick (combat defer/aim-pause/cooldown
        #      or a missing route): drive it forward toward the next objective.
        #  (b) PHYSICALLY parked - it issued a command (e.g. pressing an unreachable gate)
        #      but hasn't TRANSLATED for STUCK_MOVE_S: strip that stuck push and WANDER in
        #      a rotating heading so it visibly moves around the room / toward another exit
        #      instead of pressing the gate. Skipped on boss floors (stay + kill the boss;
        #      dodge already keeps it moving there).
        p1d = state["players"].get(1)
        if p1d and p1d.get("hp", 0) > 0 and not state.get("travelling"):
            px, pz = p1d.get("x"), p1d.get("z")
            moved_fresh = True
            if type(px) in (int, float) and type(pz) in (int, float):
                if self._p1_xz is None or math.hypot(px - self._p1_xz[0], pz - self._p1_xz[1]) > WEDGE_MOVE:
                    self._p1_xz, self._p1_moved_at = (px, pz), now
                moved_fresh = (now - self._p1_moved_at) < STUCK_MOVE_S
            has_p1_cmd = any(c[0] == 1 for c in commands)
            parked = (not moved_fresh and not self._boss_alive_now
                      and type(px) in (int, float) and type(pz) in (int, float))
            _sti = getattr(self.inputs, "stats", None)
            if parked:
                commands[:] = [c for c in commands if c[0] != 1]   # drop the stuck gate-push
                moves.pop(1, None)
                self._stuck_phase = (self._stuck_phase + 1) % 8
                ang = math.radians(self._stuck_phase * 45)
                wander = (px + math.cos(ang) * WEDGE_ESCAPE_REACH, pz + math.sin(ang) * WEDGE_ESCAPE_REACH)
                commands.append((1, movement_keys(p1d, wander), .22))
                steering[1] = (p1d, wander, "wander_unstick")
                if isinstance(_sti, dict):
                    _sti["wander_unstick"] = _sti.get("wander_unstick", 0) + 1
            elif not has_p1_cmd:
                self.drive_forward(state, 1, p1d, now, commands, moves, steering, fallback_slots)
                if isinstance(_sti, dict):
                    _sti["idle_drift"] = _sti.get("idle_drift", 0) + 1
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


def mid_field_reload(state):
    """True when the live state is an ALREADY-RUNNING mid-FIELD co-op session: verified
    phase-14 gameplay on a real floor (>0), settled (not travelling), both players present.
    A hot-reload here must TRUST the run-start controller verification and skip the
    Pioneer-2 two-pad town probe (which requires floor 0 and would raise Unsupported,
    killing play() and rolling the reload back). Town starts (floor 0) return False, so
    a genuine run-start still runs the real probe."""
    return bool(state.get("verified") and state.get("phase") == 14 and state.get("floor", 0) > 0
                and not state.get("travelling") and set(state.get("players", {})) == {1, 2})


def entry_mapping_decision(ad, driver, session_id):
    """How play() handles a controller precondition (MappingPending / Unsupported)
    raised in the LOBBY/ENTRY path - it must NEVER terminate play(). This is the
    Pioneer-2 unblock: the bot was stranded at CONTROLLER VERIFICATION because the
    fresh-launch two-pad town probe raised probe_failed and killed the loop even
    though the controllers were already verified. Returns one of:
      'trust' - the pads were already PROVEN on this adapter (the marker survives a
                bot-reload: play() re-runs but `ad` persists). TRUST that and ENTER
                the game without re-running the run-start town probe - the probe is
                a run-START gate, not a per-entry gate. Mirrors mid_field_reload's
                trust and the crash-resilient tick: a failed lobby step proceeds.
      'retry' - continuous play that was NEVER yet verified: the spawn/town may not
                be ready, so wait + retry; the precondition still never propagates.
      'raise' - a one-shot cold start that was never verified: surface it, so a
                genuine first-run controller misconfiguration is not hidden.
    Only a full worker relaunch (a fresh adapter) clears the marker and re-requires
    one real probe; a probe_failed never blocks entry once the mapping is verified."""
    if getattr(ad, '_pso_controller_ever_verified', False):
        return 'trust'
    if continuous_requested(driver, session_id):
        return 'retry'
    return 'raise'


# DIRECTIVE #3 - how many failed town-probe attempts a continuous campaign tolerates
# before it TRUSTS a structurally-verified mapping and enters anyway. Each attempt is a
# full probe plus backoff (~1-5s), so this bounds the "stuck in Pioneer 2" retry window
# to roughly 15-30s instead of forever, while still giving a genuine spawn time to settle.
MAPPING_PROBE_FALLBACK_ATTEMPTS = 4


def structural_mapping_ok(reader):
    """True when the LIVE native state structurally confirms the two-player co-op
    mapping WITHOUT sending input: a verified cooperative phase-14 session with two
    distinct, correctly-indexed players (slot1 -> controller 1 / entity 0, slot2 ->
    controller 2 / entity 1, distinct pointers). This is mapping_continuity._players'
    exact invariant - strong corroboration that pad1 owns player 1 and pad2 owns
    player 2 - used only as the last-resort gate for entering when the movement
    receipt probe cannot complete. It never fabricates a mapping: a session that is
    not structurally a valid 2P co-op keeps the campaign waiting."""
    try:
        mapping_continuity._players(reader.snapshot())
        return True
    except Exception:
        return False


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


MASTER_BUILD_TICK_S = 3.0   # throttle for the periodic master-build re-check on the co-op loop
MENU_WARP_GAP_S = 6.0       # throttle for the never-stop menu-unstick warp (don't hammer the loader)
MENU_STUCK_S = 18.0         # a menu/dialogue up continuously this long -> warp (backstop if menu.stalled never trips)


def menu_unstick(ad, stats):
    """INVARIANT: the autobot must NEVER terminally stop / hand back to the operator. A
    menu or boss-end dialogue it can't navigate (campaign's 'N unchanged menu attempts'
    / needs_operator) must NOT halt the loop - instead fire the native floor-warp
    (gbox.pso_fence.advance_floor), which RAM-loads the next area and bypasses ANY
    menu/dialogue, so play resumes forever. Throttled and fail-soft; records
    menu_stuck_warps. Returns True when a warp was attempted."""
    now = time.monotonic()
    if ad is None or now - getattr(ad, '_pso_menu_warp_at', 0.0) < MENU_WARP_GAP_S:
        return False
    ad._pso_menu_warp_at = now
    try:
        from .pso_fence import advance_floor
        res = advance_floor(ad)
    except Exception as exc:                          # noqa: BLE001 - module absent / refused; never halt the loop
        res = {'ok': False, 'error': str(exc)[:160]}
    if isinstance(stats, dict):
        stats['menu_stuck_warps'] = stats.get('menu_stuck_warps', 0) + 1
        stats['menu_stuck_warp_result'] = res if isinstance(res, dict) else {'ok': bool(res)}
        # Flat mirrors (the telemetry endpoint keeps only flat/scalar keys).
        ok = res.get('ok') if isinstance(res, dict) else bool(res)
        stats['menu_stuck_warp_ok'] = bool(ok)
        stats['menu_stuck_warp_floor'] = res.get('floor') if isinstance(res, dict) else None
        stats['action'] = 'menu_unstick_warp'
    return True


# --- PSO software-license auto-dismissal (2026-11-04) ---------------------------------------------------------------
# Verified live on lilspark that the uinput pad delivers every input to Dolphin, yet PSO never left the title: its
# software-license panel is SCROLL-GATED - "Agree" is ignored until the long licence is C-stick-scrolled near the end -
# and the campaign cannot scroll it. The planner's PLAN_SCHEMA has no C-stick key at all (only a/b/x/y/l/r/start/dpad/
# stick), and the menu guard (pso_coop_menu.review) only ever presses one UP then A, so it pressed A on Agree forever
# with nothing scrolled and looped to the attempt limit (operator saw it "frozen on the TOS"). These constants + helper
# encode the exact by-hand sequence that dismissed it: C-stick-scroll to the bottom, select Agree (D-pad up), press A.
# It is gated to the independently-recognised licence panel only (a benign fixed screen where Agree is the sole sensible
# choice); every other screen keeps the existing fail-closed guard. Clean check=False taps avoid the held-ack path, and
# it is fully exception-/stop-soft so a delivery hiccup or a bad frame can never kill the loop.
LICENSE_SCROLL_TAPS = 190       # one C-stick-down tap per licence line; ~175 reached the bottom by hand, + margin (idempotent)
LICENSE_DISMISS_LIMIT = 4       # bounded re-attempts if recognition flaps; never an infinite loop
LICENSE_DISMISS_GAP_S = 12.0    # don't re-run the whole scroll pass more often than this


def _menu_tap(inputs, stopped, player, key, hold_s=0.035, gap_s=0.008):
    """One clean controller tap through the PSO input path, bypassing the held-acknowledgement check (a bare down is
    reported 'held' by the virtual pad); fail-/stop-soft. hold_s is kept >= one emulated frame so the game's menu
    poll never misses the press; gap_s is the brief idle before the next tap. Both are tuned small for a fast burst."""
    try:
        inputs.send([{"key": key, "down": True}], player, check=False)
        solo.wait(hold_s, stopped)
        inputs.send([{"key": key, "down": False}], player, check=False)
        if gap_s:
            solo.wait(gap_s, stopped)
    except InterruptedError:
        raise
    except Exception:                                     # noqa: BLE001 - a delivery hiccup must never kill the loop
        pass


def dismiss_license(ad, menu, inputs, stopped, stats):
    """Drive PSO's independently-recognised software-license panel off the screen: C-stick-scroll to the bottom,
    select Agree, confirm A. Returns True when a dismissal pass ran (caller should reobserve and continue), False when
    no licence panel is present. Bypasses the one-input menu guard for this one benign fixed screen only."""
    obs = getattr(menu, 'observation', None) or {}
    # pso_license_menu.observe returns a bare {recognized, selected in Agree/Disagree} with NO 'menu' key; the boot
    # recogniser always carries a 'menu'. That distinguishes the licence panel from every other recognised menu.
    if not (obs.get('recognized') and obs.get('selected') in ('Agree', 'Disagree') and 'menu' not in obs):
        return False
    now = time.monotonic()
    if now - getattr(ad, '_pso_license_dismiss_at', 0.0) < LICENSE_DISMISS_GAP_S:
        return False
    if getattr(ad, '_pso_license_dismiss_attempts', 0) >= LICENSE_DISMISS_LIMIT:
        return False
    ad._pso_license_dismiss_at = now
    ad._pso_license_dismiss_attempts = getattr(ad, '_pso_license_dismiss_attempts', 0) + 1
    if isinstance(stats, dict):
        stats.update(action='dismissing_license', license_dismiss_attempt=ad._pso_license_dismiss_attempts,
                     license_dismiss_reason='C-stick scroll to bottom, select Agree, confirm A (scroll-gated panel)')
    # HYPERSPEED (operator: the slow meander is maddening). Burst the scroll - one tight ~frame-long tap per line with
    # a minimal gap (~3-4 s for the whole licence, not a slow drip) - then one quick Agree + A. No dwell between taps.
    for _ in range(LICENSE_SCROLL_TAPS):                  # scroll the long licence to the bottom (one line per tap)
        if stopped():
            return True
        _menu_tap(inputs, stopped, 1, 'cdown', hold_s=0.016, gap_s=0.004)
    for _ in range(2):                                    # ensure Agree (the top option) is selected - D-pad moves it
        if stopped():
            return True
        _menu_tap(inputs, stopped, 1, 'dup', hold_s=0.28, gap_s=0.05)   # selections need a clear held deflection
    for _ in range(2):                                    # confirm; a second A rides out a one-frame drop
        if stopped():
            return True
        _menu_tap(inputs, stopped, 1, 'a', hold_s=0.28, gap_s=0.05)
    return True


# --- Pre-gameplay boot nudge (2026-11-04) ---------------------------------------------------------------------------
# Verified live: when the independent recogniser misses a boot screen, the withhold gate froze the campaign on the
# title/menus even though the vision planner had already read the screen correctly and proposed the right key. On the
# pre-gameplay boot screens (native phase != 14) nothing destructive is reachable - the worst a wrong press does is
# bounce back to the title, which the chain recovers from - so a BOUNDED pass-through lets the planner's own proposed
# player-one key go to the pad as one clear HELD press (the main menu ignores brief taps; ~0.3 s registers). Known
# screens that the recogniser does match (saved_p1/saved_p2/verify_saved/game_options...) keep the strict fail-closed
# path, so the saved-buddy selection is always driven by the existing verified logic, never by a blind confirm.
BOOT_NUDGE_HOLD_S = 0.3         # one clear held deflection per nudge (brief taps don't register on the main menu)
BOOT_NUDGE_GAP_S = 2.5          # paced: at most one nudge per gap, so the screen can react and be reobserved
BOOT_NUDGE_LIMIT = 40           # bounded per run; never an endless blind walk
BOOT_NUDGE_KEYS = {'a', 'b', 'start', 'dup', 'ddown', 'dleft', 'dright',
                   'lup', 'ldown', 'lleft', 'lright', 'up', 'down', 'left', 'right'}


def boot_nudge_allowed(ad, state, reason):
    """A nudge is only considered on a pre-gameplay boot screen whose input was withheld/unreadable, paced and capped."""
    if state.get('phase') == 14:
        return False
    text = str(reason)
    if 'withheld' not in text and 'unreadable' not in text:
        return False
    if time.monotonic() - getattr(ad, '_pso_boot_nudge_at', 0.0) < BOOT_NUDGE_GAP_S:
        return False
    return getattr(ad, '_pso_boot_nudges', 0) < BOOT_NUDGE_LIMIT


_NUDGE_DIRECTIONS = {'dup', 'ddown', 'dleft', 'dright', 'up', 'down', 'left', 'right',
                     'lup', 'ldown', 'lleft', 'lright'}


def boot_nudge(ad, inputs, stopped, stats, proposed, state=None, plan=None):
    """Pass the planner's first proposed player-one key through as one held press; True when a nudge was sent."""
    if not proposed:
        return False
    player, keys, _secs = proposed[0]
    keys = [str(k) for k in (keys or []) if str(k) in BOOT_NUDGE_KEYS][:1]
    if player != 1 or not keys:
        return False
    key = keys[0]
    # Title-as-license misread, belt + suspenders (2026-11-04, watched live): at the RAM title/attract (phase 10) the
    # vision planner repeatedly read the PRESS START title as "the software license" and proposed a direction, which
    # can never leave the title. When RAM says phase 10, the planner's own labels talk about the licence/Agree, and
    # the independent licence recogniser does NOT actually see a licence panel, the title is the overwhelmingly likely
    # screen - press START (the one key the title takes) instead of the misread direction.
    if (state or {}).get('phase') == 10 and key in _NUDGE_DIRECTIONS:
        labels = ' '.join(str((plan or {}).get(k) or '') for k in
                          ('menu_title', 'selected_option', 'intended_option', 'thought')).lower()
        if 'licen' in labels or 'agree' in labels:
            key = 'start'
    ad._pso_boot_nudge_at = time.monotonic()
    ad._pso_boot_nudges = getattr(ad, '_pso_boot_nudges', 0) + 1
    if isinstance(stats, dict):
        stats.update(action='boot_nudge', boot_nudges=ad._pso_boot_nudges, boot_nudge_key=key,
                     boot_nudge_reason='pre-gameplay boot screen: planner key passed through the withhold gate as a held press')
    _menu_tap(inputs, stopped, 1, key, hold_s=BOOT_NUDGE_HOLD_S, gap_s=0.05)
    return True


# --- Pre-gameplay stall skip (2026-11-04) ---------------------------------------------------------------------------
# The boot nudge only fires on a "withheld/unreadable" review, but the OFFLINE intro CINEMATIC produces a different
# stall ("Six unchanged menu attempts") while the vision planner only sees black transition frames and proposes
# nothing - so nothing pressed A/Start to skip the cinematic and the chain froze at phase 3 (watched live). On ANY
# pre-gameplay stall (native phase != 14, no real floor) press a bounded, paced, alternating Start/A held press: Start
# skips cinematics and leaves the title, A advances/confirms a dialog or selects on character select. Recognised
# screens (saved_p1/saved_p2/...) never reach a stall (review returns their action), so this only drives the
# unrecognised cinematics/dialogs, never a blind confirm on an independently-recognised menu.
PREGAME_SKIP_KEYS = ('start', 'a')
PREGAME_SKIP_LIMIT = 40
PREGAME_SKIP_GAP_S = 1.1


def pregame_skip(ad, state, inputs, stopped, stats):
    """A bounded Start/A skip for a pre-gameplay cinematic or unrecognised dialog that stalled; True when it fired."""
    if (state or {}).get('phase') == 14 or (state or {}).get('floor'):
        return False
    if time.monotonic() - getattr(ad, '_pso_pregame_skip_at', 0.0) < PREGAME_SKIP_GAP_S:
        return False
    n = getattr(ad, '_pso_pregame_skips', 0)
    if n >= PREGAME_SKIP_LIMIT:
        return False
    ad._pso_pregame_skip_at = time.monotonic()
    ad._pso_pregame_skips = n + 1
    key = PREGAME_SKIP_KEYS[n % len(PREGAME_SKIP_KEYS)]
    if isinstance(stats, dict):
        stats.update(action='pregame_skip', pregame_skips=n + 1, pregame_skip_key=key,
                     pregame_skip_reason='pre-gameplay stall (cinematic/unrecognised screen): bounded alternating Start/A skip')
    _menu_tap(inputs, stopped, 1, key, hold_s=0.3, gap_s=0.05)
    return True


def _flatten_master_build(stats, summary):
    """Flat scalar mirrors of the nested master_build summary so the telemetry
    endpoint (which keeps only flat/scalar keys) surfaces the applied build: p1 =
    player 0, p2 = player 1 (mb_ok_*, mb_lck_*, mb_weapon_*, mb_mag_maxed_*,
    mb_units_*, mb_never_miss_*)."""
    if not isinstance(summary, dict):
        return
    for idx, suffix in (("0", "p1"), ("1", "p2")):
        rep = summary.get(idx)
        if not isinstance(rep, dict):
            continue
        stats[f"mb_ok_{suffix}"] = int(bool(rep.get("ok")))
        if type(rep.get("lck")) in (int, float):
            stats[f"mb_lck_{suffix}"] = rep.get("lck")
        if rep.get("weapon") is not None:
            stats[f"mb_weapon_{suffix}"] = rep.get("weapon")
        stats[f"mb_mag_maxed_{suffix}"] = int(bool((rep.get("mag") or {}).get("maxed")))
        units = rep.get("units")
        stats[f"mb_units_{suffix}"] = len(units) if isinstance(units, list) else 0
        if rep.get("never_miss") is not None:
            stats[f"mb_never_miss_{suffix}"] = int(bool(rep.get("never_miss")))
        # Survival backstop mirrors (build side: Scape Doll + revive/down state).
        if rep.get("scapedoll") is not None:
            stats[f"mb_scapedoll_{suffix}"] = int(bool(rep.get("scapedoll")))
        if rep.get("scapedoll_ok") is not None:
            stats[f"mb_scapedoll_ok_{suffix}"] = int(bool(rep.get("scapedoll_ok")))
        if type(rep.get("revives")) in (int, float):
            stats[f"mb_revives_{suffix}"] = rep.get("revives")
        if rep.get("downed") is not None:
            stats[f"mb_downed_{suffix}"] = int(bool(rep.get("downed")))


def apply_master_build_tick(ad, state, stats, *, force=False):
    """Apply the operator's master build (gbox.pso_master_build) to BOTH players on
    the co-op loop: never-miss + crit rate + random gear/weapons + 4 units + maxed
    mag. apply_master_build_all is idempotent and fail-soft (it never raises; it
    re-rolls the weapon only on its own interval and re-checks patches rather than
    rewriting), so this is safe to call often. Gated to live gameplay (phase 14 on a
    real floor); throttled to MASTER_BUILD_TICK_S but FORCED at spawn (force=True)
    and whenever P1's room changes (area/room change). Returns True when a player's
    weapon was re-rolled this tick, so the caller reobserves weapon ranges.

    apply_master_build OWNS the weapon slot (equips, re-rolls, and re-arms after a
    death), so pso_coop's EquipmentRecovery equip is left off to avoid fighting it."""
    # Re-surface the LAST summary on EVERY call (even gated/throttled ones): the
    # stats dict is rebuilt each loop, so setting it only on the 3s application tick
    # made it flicker ~1 loop in every 3s and read as absent. Persist it on `ad`.
    prior = getattr(ad, "_pso_master_build_summary", None)
    if prior is not None:
        stats["master_build"] = prior
        _flatten_master_build(stats, prior)
    prior_error = getattr(ad, "_pso_master_build_error", None)
    if prior_error:
        stats["master_build_error"] = prior_error
    if not (state.get("verified") and state.get("phase") == 14 and state.get("floor", 0) > 0):
        return False
    players = state.get("players") or {}
    room = (players.get(1) or players.get("1") or {}).get("room")
    now = time.monotonic()
    last = getattr(ad, "_pso_master_build_at", 0.0)
    prev_room = getattr(ad, "_pso_master_build_room", "__none__")
    if not force and room == prev_room and (now - last) < MASTER_BUILD_TICK_S:
        return False
    ad._pso_master_build_at = now
    ad._pso_master_build_room = room
    rerolled = False
    try:
        from .pso_master_build import apply_master_build_all
        report = apply_master_build_all(ad)
        summary = {"applied_wall": time.time()}
        for idx, rep in (report or {}).items():
            weapon = rep.get("weapon") or {}
            summary[str(idx)] = {"ok": rep.get("ok"), "lck": rep.get("lck"),
                                 "weapon": weapon.get("code"), "rerolled": weapon.get("rerolled"),
                                 "frame": rep.get("frame"), "units": rep.get("units"),
                                 "mag": rep.get("mag"), "never_miss": rep.get("never_miss"),
                                 "equip_any": rep.get("equip_any"), "errors": rep.get("errors") or {}}
            if weapon.get("rerolled"):
                rerolled = True
        ad._pso_master_build_summary = summary
        ad._pso_master_build_error = None
        stats["master_build"] = summary
        _flatten_master_build(stats, summary)
    except Exception as exc:                       # noqa: BLE001 - module absent pre-ff, or unexpected; never block play
        ad._pso_master_build_error = str(exc)[:160]
        stats["master_build_error"] = ad._pso_master_build_error
    return rerolled


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
    # Operator's sidebar pick (GET/POST /api/pso/launch-config) of which Episode + Difficulty to enter
    # a game on. Applied here at launch and, below, only at a between-games boundary - never mid-floor.
    from . import pso_launch_config
    pso_launch_config.apply(ledger, root, initial=True, stats=stats)
    maps = Maps(root / "room-memory")
    controller = Controller(reader, inputs, maps)
    # Activate the convergence crystal without a worker-process restart: this worker
    # started before pso_knowledge entered BOT_MODULES, so a plain bot-reload leaves
    # the OLD pso_knowledge cached in sys.modules (no area_fingerprint) and _sync_area
    # no-ops. pso_coop imports it only inside functions, so nothing else holds its
    # classes; reload it in place here (once per run, only if stale) and build the
    # store from the fresh module so the live controller uses the new area-graph
    # KnowledgeStore. The on-disk crystal is preserved (version 1 -> version 2 on the
    # first crossing). Fail-soft: on any error fall back to whatever is importable.
    try:
        import importlib
        from . import pso_knowledge as _pk
        if not hasattr(_pk, "area_fingerprint"):
            _pk = importlib.reload(_pk)
        KnowledgeStore = _pk.KnowledgeStore
        stats["pso_knowledge_area_graph"] = hasattr(_pk, "area_fingerprint")
    except Exception as exc:                       # noqa: BLE001 - never block play on the crystal
        from .pso_knowledge import KnowledgeStore
        stats["pso_knowledge_reload_error"] = str(exc)[:160]
    # SYSTEMIC DEPLOY FIX: hot-swap EVERY non-BOT_MODULE PSO helper that pso_coop's call
    # paths use. These are cached at first-import; the build/boss/map agents keep editing
    # them, but a plain bot-reload only refreshes BOT_MODULES - so their changes SILENTLY
    # don't deploy (frozen characters from stale pso_survival, dead 3x-speed probe from
    # stale pso_speed, boss weak-point aim / 4-player build not taking from stale
    # pso_boss_strategy / pso_master_build). pso_coop calls all of these via FUNCTION-LOCAL
    # imports, so reloading each in place (updating sys.modules) makes the live loop use the
    # fresh code with no worker restart. Dependency order first (leaf probe, then survival
    # which also refreshes pso_speed, then the independents, then master_build which may
    # import survival). Each in its own try/except - a helper reload must NEVER kill play().
    # pso_accuracy/pso_crit are RAM caves that re-apply in-bot, so they are intentionally
    # excluded. pso_knowledge is reloaded above. (This reload set carries pso_survival's
    # per-tick MAX-HP survival floor, 6fb6d790, so low-level bots stop getting one-shot.)
    import importlib
    for _name in ("pso_speed", "pso_survival", "pso_fence", "pso_boss_strategy", "pso_master_build"):
        try:
            importlib.reload(importlib.import_module("." + _name, __package__))
            stats["reload_" + _name] = True
        except Exception as exc:                   # noqa: BLE001 - never block play on a helper reload
            stats["reload_" + _name + "_error"] = str(exc)[:160]
    try:
        from . import pso_survival as _ps
        stats["pso_survival_throttled"] = hasattr(_ps, "HEAVY_INTERVAL_S")
    except Exception:
        pass
    controller.knowledge = KnowledgeStore(root / "pso-knowledge.json")
    controller.map_root = root                       # published collision surfaces live here
    controller.directive_path = root / "pso-directive.json"   # operator RTS map clicks
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
                # Honor the operator's episode/difficulty pick on the next game entry only (no-op mid-run).
                pso_launch_config.apply(ledger, root, stats=stats)
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
                # LICENSE AUTO-DISMISS (2026-11-04): PSO's software-license panel is scroll-gated and the planner has
                # no C-stick key, so the guard/planner path loops on it forever. Drive it off imperatively (scroll to
                # the bottom, select Agree, press A) before anything else; dismiss_license no-ops on every other screen.
                if dismiss_license(ad, menu, inputs, stopped, stats):
                    invalidate_plan()
                    solo.wait(.15, stopped)              # hyperspeed: minimal dwell, reobserve fast
                    continue
                # Backstop to the never-stop invariant: if a menu/dialogue is up
                # continuously for MENU_STUCK_S (in case menu.stalled never trips -
                # e.g. a boss-end dialogue the campaign keeps retrying), warp to the
                # next route floor so the party never stands frozen at a menu.
                if menu_paused:
                    if getattr(ad, '_pso_menu_stuck_since', None) is None:
                        ad._pso_menu_stuck_since = time.monotonic()
                    held = time.monotonic() - ad._pso_menu_stuck_since
                    stats['menu_stuck_held_s'] = round(held, 1)
                    if held >= MENU_STUCK_S and menu_unstick(ad, stats):
                        stats['menu_stuck_reason'] = f'menu up {held:.0f}s (backstop)'
                        invalidate_plan()
                        solo.wait(.3, stopped)
                        continue
                else:
                    ad._pso_menu_stuck_since = None
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
                        # Pre-gameplay stall (cinematic / unrecognised dialog): a bounded Start/A skip instead of a
                        # warp (native warps can't run before gameplay anyway).
                        if pregame_skip(ad, state, inputs, stopped, stats):
                            invalidate_plan()
                            solo.wait(.3, stopped)
                            continue
                        # INVARIANT: never terminally stop at a stuck menu. The campaign
                        # gives up after N unchanged attempts - instead of halting to the
                        # operator, warp to the next route floor (a RAM load bypasses ANY
                        # menu/dialogue) and keep playing. A stuck menu becomes "warp on".
                        stats.update(menu_stuck_reason=str(reason)[:160])
                        menu_unstick(ad, stats)
                        invalidate_plan()
                        solo.wait(.3, stopped)
                        continue
                    for command in selected[:1]:
                        inputs.hold([command])
                        menu.previous['input_delivery_verified'] = True
                    # Let selection/transition animation settle, with Stop and
                    # takeover interruptible. Reobserve before every next input.
                    solo.wait(.6 if selected else .2, stopped)
                    continue
                # CONTENTION KILL (2026-11-04, verified live): during the pre-gameplay boot screens the mapping
                # restore/probe path fired its player-two 19-key sweep while player one tried to drive the title and
                # menus - the campaign was fighting its own forward presses, and the probe can never verify there
                # anyway ("GameCube native actions require an active offline free-play session"). One driver at a
                # time: defer ALL mapping restore/probe work until real gameplay (native phase 14); the boot chain
                # (title Start -> menu -> OFFLINE -> character select -> Start Game) belongs to player one alone.
                # (The 19-key "sweep" telemetry still shows at run start: that is inputs.release() - every key sent
                # UP, alphabetical - a benign safety release, not a probe. This is the only prove()/restore() site.)
                if state.get("verified") and state.get("phase") == 14 and not mapped and not menu_paused and not recovery.waiting:
                    retained = mapping_continuity.restore(ad, reader, session_id, game or {}, stopped)
                    stats.update(mapping_continuity.diagnostics(ad))
                    # HOT-RELOAD INTO A RUNNING MID-FIELD SESSION (operator: the reload kept
                    # rolling back). A fresh controller restarts mapping; when the reusable
                    # attestation can't revalidate, prove() runs the TWO-PAD TOWN PROBE, which
                    # requires Pioneer 2 (floor 0) and RAISES Unsupported on a real floor -
                    # that uncaught raise killed play() and hot_reload reverted to the old
                    # (starving) code. But the controllers were verified at run start and the
                    # bot has been DRIVING them here (we are mid-field), so that probe is a
                    # run-START gate, not a per-reload gate: trust the prior verification and
                    # resume driving WITHOUT a town probe, instead of dying. The real town
                    # probe still runs for a genuine floor-0 run start.
                    mid_run_resume = (retained is None and mid_field_reload(state)
                        and continuous_requested(driver, session_id))
                    if retained is not None:
                        stats["controller_mapping"] = retained['probe']
                        state = retained['state']
                        stats['controller_mapping_source'] = 'same_live_adapter_revalidated'
                    elif mid_run_resume:
                        stats['controller_mapping_source'] = 'mid_run_reload_trusted_prior_verification'
                        stats['controller_mapping_mid_run_resumed'] = stats.get('controller_mapping_mid_run_resumed', 0) + 1
                    else:
                        try:
                            stats["controller_mapping"] = mapping_continuity.prove(
                                ad, reader, inputs, state, session_id, game or {}, stopped, mapping_probe)
                            stats['controller_mapping_source'] = 'two_pad_movement_probe'
                        except (MappingPending, Unsupported) as exc:
                            # A controller precondition must NEVER terminate play() in the
                            # lobby/entry path (that is how the bot got stranded in Pioneer 2
                            # at CONTROLLER VERIFICATION: the fresh-launch town probe raised
                            # probe_failed and killed the loop even though the mapping was
                            # already verified). Three guarded outcomes, none of them "stop":
                            #   1. VERIFIED-BEFORE on this adapter -> TRUST it and ENTER the
                            #      game without re-passing the town probe. The two-pad probe
                            #      is a run-START gate, not a per-entry gate; the controllers
                            #      were proven here already (prior verification survives a
                            #      bot-reload on the same adapter). Mirrors mid_field_reload's
                            #      trust and the crash-resilient tick: one failed lobby step
                            #      proceeds, it never dies.
                            #   2. continuous play, NEVER yet verified -> wait + retry (the
                            #      spawn/town may not be ready); still never propagates.
                            #   3. a true one-shot cold start that was never verified -> raise,
                            #      so a genuine first-run misconfiguration still surfaces.
                            decision = entry_mapping_decision(ad, driver, session_id)
                            if decision == 'trust':
                                stats['controller_mapping_source'] = 'entry_trusted_prior_verification'
                                stats['controller_mapping_entry_trusted'] = stats.get('controller_mapping_entry_trusted', 0) + 1
                                stats['controller_receipt_entry_trusted'] = True
                                stats['controller_entry_probe_skipped_reason'] = str(exc)[:160]
                            elif decision == 'raise':
                                raise
                            elif (mapping_attempts + 1 >= MAPPING_PROBE_FALLBACK_ATTEMPTS
                                  and structural_mapping_ok(reader)):
                                # DIRECTIVE #3 - the town movement receipt CAN'T COMPLETE here
                                # (e.g. a probe pulse flips the party off a pristine floor-0
                                # lobby onto a teleporter/field, or input movement can't be
                                # measured in Pioneer 2), so the two-pad probe retries forever
                                # and the bot never ENTERS a game. After enough failed attempts,
                                # if the LIVE NATIVE STATE structurally confirms two distinct,
                                # correctly-indexed co-op players (pad1->slot0, pad2->slot1),
                                # TRUST that verified mapping and ENTER - a continuous campaign
                                # must play even when the movement receipt is unavailable
                                # (operator: always playing). Still never fabricates a mapping:
                                # a session that is not structurally two-player keeps retrying.
                                mapping_attempts += 1
                                stats['controller_mapping_source'] = 'entry_trusted_structural_after_probe_unavailable'
                                stats['controller_mapping_entry_trusted'] = stats.get('controller_mapping_entry_trusted', 0) + 1
                                stats['controller_receipt_entry_trusted'] = True
                                stats['controller_entry_probe_skipped_reason'] = (
                                    'town probe unavailable x%d: %s' % (mapping_attempts, exc))[:160]
                            else:
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
                    if stopped():
                        raise InterruptedError('PSO stopped before activating controller mapping')
                    mapped = True
                    ad._pso_verified_player_slots = {0, 1}
                    # Durable across bot-reloads on the same adapter (play() re-runs but `ad`
                    # persists): once the controllers are proven, a later entry in Pioneer 2
                    # TRUSTS this instead of re-running the run-start town probe. Only a full
                    # worker relaunch (fresh adapter) clears it and re-requires one real probe.
                    ad._pso_controller_ever_verified = True
                    mapping_attempts = 0
                    stats.update(controller_mapping_verified=True, mapping_retry_backoff_s=0, mapping_last_error="")
                    apply_default_speed(ad, stats)
                    state = reader.snapshot()
                    apply_master_build_tick(ad, state, stats, force=True)   # master build at spawn
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
                            # Never hand back to the operator on repeated planner
                            # failure: release inputs, warp forward, and keep playing
                            # from RAM instead of halting.
                            stats.update(menu_stuck_reason='Five planner observations failed; inputs released')
                            inputs.release()
                            menu_unstick(ad, stats)
                            invalidate_plan()
                            planner_errors = 0
                            solo.wait(.3, stopped)
                            continue
                        solo.wait(min(planner_errors, 3), stopped)
                        continue
                    planner_errors = 0
                    stats.update(planner_consecutive_errors=0, planner_last_error='', planner_retry_backoff_s=0, planner_state='observed',
                                 planner_actions=len(selected), planner_responses=stats.get('planner_responses', 0) + 1)
                    stats.update(thought=str(plan.get("thought", ""))[:400], screen=plan.get("screen", "unknown"),
                                 difficulty_locked=bool(plan.get("difficulty_locked")))
                    if plan.get("needs_operator"):
                        # Never stop on a model "needs operator" verdict (e.g. a
                        # boss-end 'Return to Pioneer 2?' dialogue): warp to the next
                        # route floor and keep playing.
                        stats.update(menu_stuck_reason=str(stats.get("thought", ""))[:160])
                        menu_unstick(ad, stats)
                        invalidate_plan()
                        solo.wait(.3, stopped)
                        continue
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
                                planner_proposed = selected[:1]          # the planner's own read, kept for the boot nudge
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
                                    # Pre-gameplay stall (cinematic / unrecognised dialog): bounded Start/A skip first.
                                    if pregame_skip(ad, state, inputs, stopped, stats):
                                        invalidate_plan()
                                        solo.wait(.3, stopped)
                                        continue
                                    # INVARIANT: never terminally stop at a stuck menu.
                                    # Warp to the next route floor (RAM load bypasses
                                    # any menu/dialogue) and keep playing forever.
                                    stats.update(menu_stuck_reason=str(reason)[:160])
                                    menu_unstick(ad, stats)
                                    invalidate_plan()
                                    solo.wait(.3, stopped)
                                    continue
                                # BOOT NUDGE (2026-11-04): a withheld/unreadable PRE-GAMEPLAY screen must not freeze
                                # the chain - pass the planner's own proposed player-one key through as one bounded
                                # held press, then reobserve. Gameplay and recognised screens keep the strict path.
                                if not selected and planner_proposed and boot_nudge_allowed(ad, state, reason) and \
                                        boot_nudge(ad, inputs, stopped, stats, planner_proposed,
                                                   state=state, plan=plan):
                                    invalidate_plan()
                                    solo.wait(.25, stopped)
                                    continue
                                # Menus are observed after every individual input.
                                # A confirm must never cascade into an unseen dialog.
                                for command in selected[:1]:
                                    inputs.hold([command])
                                    if menu.previous:
                                        menu.previous['input_delivery_verified'] = True
                    else:
                        stats["action"] = "discarded_stale_plan"
                # Operator 2026-11-02: PSO plays from RAM, not a vision LLM. During
                # verified field gameplay P1 navigates/unlocks/fights entirely from
                # the RAM-derived state (field objectives, the stage-flag door
                # system, the knowledge crystal) and followers swarm - so NO vision
                # planner is called, which frees the Spark's ollama GPU/CPU (it was
                # the continuous burn choking RE4). The planner is still used only
                # for brief visual decisions RAM cannot make: town/menus, character
                # creation and end-screen (credits) classification.
                ram_only = bool(state.get("verified") and state.get("phase") == 14
                                and state.get("floor", 0) > 0 and mapped and not menu_paused)
                if ram_only:
                    stats.update(planner_state="ram_only_no_llm", planner_suppressed_field_play=True)
                if (not ram_only and pending is None and time.monotonic() >= planner_retry_at and
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
                # Maintain the operator's master build EVERY loop, INDEPENDENT of nav /
                # recovery / mapping state, so never-miss + crit + gear persist (and
                # stats["master_build"] stays populated) even while navigation is stuck
                # or recovering - previously the only call sat inside the healthy-play
                # branch below, so a stuck/recovering bot stopped re-applying the build.
                # Idempotent and cheap; its own gate is phase-14 gameplay on a real floor.
                build_rerolled = apply_master_build_tick(ad, state, stats)
                if mapped and state.get("verified") and (not recovery.waiting or native_retry_ready):
                    # Reobserve after any planner input; Start/menu overlays leave
                    # native phase 14 unchanged and must never receive steering/L.
                    menu_paused = observe_menu_controls(menu, ad.get_frame(), state, controller, inputs, stats)
                    if not menu_paused:
                        if recovery.waiting:
                            stats.update(recovery_state="native_control_available_planner_retrying",
                                         native_control_during_recovery=True)
                        if build_rerolled:
                            # The master build re-rolled the weapon (it OWNS the weapon
                            # slot). The active item changed, so DROP the stale weapon
                            # ranges/plans - but do NOT stand still to "reobserve"
                            # (operator: never freeze). Clear the caches and fall straight
                            # into controller.tick, which recomputes the envelope fresh
                            # this same tick and keeps the party MOVING/fighting.
                            invalidate_plan()
                            controller.weapon_ranges.cache.clear()
                            controller.weapon_ranges.attempted.clear()
                            controller.engagements.rows.clear()
                            stats["weapon_reroll_reobserved_inline"] = stats.get("weapon_reroll_reobserved_inline", 0) + 1
                        stats["action"] = "coordinated_native_combat_or_navigation"
                        # CRASH-RESILIENT TICK: one bad frame (a None entity, a bad fence/boss/
                        # switch/explore read) must NEVER kill the autoplay loop (it was dying
                        # silently with no telemetry error). Catch ANY exception from the tick,
                        # SURFACE it (bot_tick_error + traceback so it's visible, not invisible),
                        # and keep looping - the next frame retries. Stop/interrupt still ends it.
                        try:
                            controller.tick(state)
                        except (InterruptedError, RuntimeError):
                            raise      # stop, and the window-focus pause handled by the outer loop
                        except Exception as tick_exc:                 # noqa: BLE001 - never let one frame kill the loop
                            import traceback as _tb
                            stats["bot_tick_error"] = ("%s: %s" % (type(tick_exc).__name__, tick_exc))[:300]
                            stats["bot_tick_tb"] = _tb.format_exc()[-1600:]
                            stats["bot_tick_errors"] = stats.get("bot_tick_errors", 0) + 1
                            try:
                                inputs.release()
                            except Exception:
                                pass
                errors = 0
                stats["input_wait_active"] = False
                solo.wait(.05, stopped)
            except StubUnavailable as exc:
                # A transient GDB-stub read/write refusal ("stub refused read at 0x...: E00") under debugger
                # contention - e.g. a hard-running RE5 on the same box momentarily starving the stub - must NOT kill
                # the campaign loop (the known "autobot silently crashes on a bad frame" pattern). It is a bad frame:
                # release inputs, back off briefly, and retry the next frame. StubUnavailable subclasses RuntimeError,
                # so this clause must stay ABOVE the RuntimeError handler below.
                speed_sampler.invalidate()
                try:
                    inputs.release()
                except Exception:                            # noqa: BLE001 - best effort
                    pass
                stats["stub_read_waits"] = stats.get("stub_read_waits", 0) + 1
                stats.update(action="waiting_for_stub_read", last_stub_error=str(exc)[:160])
                solo.wait(0.2, stopped)
            except RuntimeError as exc:
                # The host could not deliver input because the game window is not
                # in the foreground (adapters.py: "must be active to send emulator
                # input"). On a headless/hostile desktop (phantom input, wallpaper
                # engines stealing focus) this must be a transient PAUSE, never the
                # end of the run: release inputs, try to raise the game window, back
                # off, and continue so the buddies resume the instant focus returns.
                if FOCUS_WAIT_MARK not in str(exc):
                    raise
                speed_sampler.invalidate()
                inputs.release()
                controller.approaches.clear()
                planned_identity = None
                stats["input_wait_active"] = True
                stats["input_wait"] = stats.get("input_wait", 0) + 1
                stats["input_wait_s"] = round(stats.get("input_wait_s", 0.0) + FOCUS_WAIT_BACKOFF_S, 2)
                stats.update(action="waiting_for_window_focus", input_wait_reason=str(exc)[:160])
                try:
                    from .adapters import win_bring_to_front
                    proc = getattr(ad, "proc", None)
                    if proc is not None and getattr(proc, "pid", None):
                        stats["input_wait_refocus"] = bool(win_bring_to_front(proc.pid))
                except Exception as refocus_exc:
                    stats["input_wait_refocus_error"] = str(refocus_exc)[:120]
                solo.wait(FOCUS_WAIT_BACKOFF_S, stopped)
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
