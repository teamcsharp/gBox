# The Mercenaries engine (gbox/mercs)

Operator, 2026-10-20: "i expect the mercenaries bot for RE to be a unified system able to be deployed on any instance
of resident evil mercenaries. I want to perfect the logic for mercenaries entirely and have the system working across
games, consoles, systems and titles. I want the lessons and learnings from RE5 working on RE4 and these games to all be
feeding a byte ram database of signatures, parry opportunities, QTE blocking and participation, combo maintenance,
pathfinding, map management, advanced navigation and strategy engines for looking up the maps and recommended route
for a mercenaries stage and able to execute it."

One engine plays every Mercenaries. A title is four things: its **RAM map** (what the game keeps where, in one shared
vocabulary, with signatures), its **menus module** (title screen to round and back, from RAM), a thin **driver**
(buttons, aim, look-ahead), and its **stage DB** (maps and routes). The engines only see the vocabulary, so what is
learned on one title (a lead time, a dodge window, a route idea) is written down in the same terms for every other.
Title #1: Resident Evil 4, GameCube NTSC-U (`G4BE08`). Title #2: Resident Evil 5, PS3 (the RE5 agent).

Who owns what: the engine (`gbox/mercs/`: vocabulary, world, threat, aim, reactions, combo, strategy, nav, stage DB,
lessons, the round loop) - the re4-combat / mercs-engine agent; the deployment layer (`gbox/mercs_bot.py`: matches,
set-up, boot and menus through each title's menus module, rounds handed to the engine) - the bot-demos-anywhere agent;
title #2 - the RE5 agent.

Rules (unchanged from the RE4 bot): RAM is read only, for perception; input only through the session's `send_input`
(gBox pad names); never write the player; game-side hacks are values in the game's own tables (re_mods), never the
player's state; vision only as the last fallback (a RAM field that can't tell says so: `Unknown`).

## Layout

| file | what |
|---|---|
| `gbox/mercs/vocab.py` | the shared field names, their units and conventions, the signature tag schema; `check(map)` reports what a title fills, marks unknown, or gets wrong |
| `gbox/mercs/world.py` | `read(rmap, reader, driver) -> World`: one RAM read through `ram_map`, normalized (units, headings, tags from signatures) |
| `gbox/mercs/threat.py` | threat engine: attacks by time to land, projectiles by time to reach, the rest by distance; shoot-or-evade |
| `gbox/mercs/aim.py` | aim model with learned rates (turn, aimed turn, pitch, pose, gun), shot scoring (shots / hits / kills) |
| `gbox/mercs/reactions.py` | prompts: QTE participate / block, parry and counter windows, melee on stun |
| `gbox/mercs/combo.py` | combo upkeep: the combo window, when a kill or a combo bonus keeps it going |
| `gbox/mercs/strategy.py` | the round plan: time-bonus tour, fight vs move by clock / combo / threat, safe spots |
| `gbox/mercs/nav.py` | paths (stage grid or graph, learned map), waypoint following, stuck handling (reuses `bot_brain.NavGraph`) |
| `gbox/mercs/stagedb.py` | stage records (nav source, bonuses, spawns, hazards, safe spots, route) |
| `gbox/mercs/lessons.py` | the lessons log (one JSONL per run) and the analyzer that proposes candidate signatures |
| `gbox/mercs/enemy_db.py` | the enemy knowledge database: per title and enemy class what dispatches him (aim zone and offset, range, fire mode, shots to kill) and how dangerous each of his states is, learned from RAM facts and outcomes (section 6b) |
| `gbox/mercs/enemy_db_seed.py` | the one-off, read-only bootstrap of that database from the round maps, the run lessons and the damage ledger |
| `gbox/mercs/engine.py` | `Engine.tick(world) -> Intent`: the engines in order; `play_round(profile, m, send, stopped, stats, lessons)` |
| `gbox/mercs/driver.py` | the `Driver` base class every title implements |
| `gbox/mercs/tactical.py` | the tactical map's frames and stages (`gbox.tactical/1`) and the publisher `play_round(tactical=)` feeds ([tactical_map.md](tactical_map.md)) |
| `gbox/mercs/titles/re4_gc.py` | title #1: `G4BE08` |
| `gbox/mercs/titles/re5_ps3.py` | title #2 (RE5 agent) |
| `gbox/mercs_bot.py` | the deployment playbook (bot-demos-anywhere): `matches` = `ram_map.detect` finds a map with a `mercs` block; boots through the title's menus module; each round -> `engine.play_round` |
| `gbox/re4_menus.py` | RE4's menus module (bot-demos-anywhere): `screen(m, merc)`, `step(scr)`, `wandered(scr)` |
| `gbox/re4_merc_bot.py` | the RE4 playbook: same name, `matches`, `setup`, `play(ad, send, stopped, ...)` as before; its rounds run on the engine |
| `profiles/gamedata/<map id>-ram.json` | the title profile = its RAM map (`gbox-ram-map/1`, docs/ram_maps.md) with the `mercs` block below |
| `profiles/gamedata/mercs/<map id>/<stage>.json` | the stage DB |
| `gbox-data/mercs/lessons/<map id>.jsonl` | notes and reports (coaching, improvement reports); `<map id>/runs/<run>.jsonl`: one run's events |

## 1. The title profile = the RAM map

The map is the "byte RAM database": every field and every signature carries `source` (`ghidra`, `scan`, `manual`),
`evidence` (the routine, the search, the live check and its date) and, for signatures, `confidence`. Nothing new is
invented for storage: a title's profile is `profiles/gamedata/<map id>-ram.json`, read with
`ram_map.load(game).read(reader)`, plus a top-level `mercs` object.

### The vocabulary

A title fills each name with one of its map's fields, or marks it unknown (`null`), or leaves it to its driver
(`"driver"`: derived from other fields, e.g. RE4 has no single screen byte). Names are the engine's; the map's own
field names stay what they are, and `mercs.vocab` says which is which.

| name | type | units / values | |
|---|---|---|---|
| `screen` | enum | `title`, `menu`, `char_select`, `stage_select`, `briefing`, `loading`, `playing`, `paused`, `results`, `dead` | required (field or driver) |
| `merc.stage` | enum / int | the stage (RE4: room 0x0400 Village ...) | |
| `merc.timer` | number | seconds left | required |
| `merc.combo` | int | the current combo | |
| `merc.combo_timer` | number | seconds left in the combo window | |
| `merc.score` | int | points | |
| `merc.kills` | int | kills this round | |
| `player.pos` | 3 numbers | world units, y up | required |
| `player.facing` | number | heading, see `heading` below | required |
| `player.hp`, `player.hp_max` | int | | |
| `player.state` | enum + signatures | tags `control`, `aiming`, `hit`, `held`, `down`, `action`, `dead` | required |
| `player.aim_pitch` | number | radians, + up (while aiming) | |
| `player.weapon`, `player.ammo` | int | | |
| `enemies` | struct array | the live enemies (the map's `live` condition) | required |
| `enemies.pos` | 3 numbers | world units | required |
| `enemies.facing`, `.hp`, `.hp_max`, `.type` | | | |
| `enemies.state` | enum + signatures | the top-level routine: tags `spawning`, `acting`, `hurt`, `down`, `stunned`, `dying`, `gone` | required |
| `enemies.act` | enum + signatures | what it does now (the attack signatures live here) | |
| `enemies.motion`, `.motion_frame`, `.motion_frames`, `.motion_speed`, `.motion_events` | | the animation, its frame, its per-frame event bits (signatures: which bit is the hit window) | |
| `enemies.target` | ptr / int | who it is after | |
| `projectiles` | struct array | thrown or fired things: `pos` (required), `kind`, `owner` | |
| `prompt.kind` | enum + signatures | the action prompt / QTE up now, 0 = none | |
| `prompt.button` | string | what it asks for (`a`, `a+b`, `l+r`, `wiggle`, ...) | |
| `bonuses` | struct array | `pos`, `kind` (`time`, `combo`, `item`), `taken`, `hp` (breakable ones) | |
| `drops` | struct array | what enemies drop: `pos`, `kind` (`ammo`, `health`, `grenade`, `time`, ...) | |
| `partner.pos`, `partner.hp`, `partner.state` | | co-op titles (unused where Mercenaries is solo) | |

### The `mercs` block

```json
"mercs": {
  "driver": "gbox.mercs.titles.re4_gc",
  "menus": "gbox.re4_menus", "package": [["mercenaries_unlock", {"on": true}], ["merc_loadout", {"character": "leon"}]],
  "early_ops": ["mercenaries_unlock"], "jump_at": "select_player",
  "vocab": {"screen": "driver", "merc.timer": "merc.timer", "merc.combo": "merc.combo", "merc.score": null,
            "player.state": "player.routine", "enemies": "enemies", "enemies.act": "act",
            "projectiles": "thrown", "prompt.kind": "prompt.kind", "bonuses": "aev.items"},
  "units_per_m": 1000,
  "heading": {"zero": "+z", "positive": "toward +x"},
  "aim": {"turn_rad_s": 3.0, "aim_turn_rad_s": 1.5, "pitch_rad_s": 0.5, "pose_s": 0.25, "gun_gap_s": 1.167},
  "rules": {"melee_kill_time_s": 0, "combo_window_s": 30, "bonus_time_s": 90}
}
```

`rules` are the title's Mercenaries rules the strategy and combo engines weigh (RE5 adds clock time for melee kills: stun
then melee when the clock matters; RE4 does not). `driver` is the title's driver module (section 4). `menus`, `package`, `early_ops`, `jump_at` belong to the deployment
layer: the menus module (`screen(m, merc)` -> where the game is, `step(scr)` -> one pad key or None, `wandered(scr)` ->
it left the Mercenaries), the hack package (re_mods ops), the ops that must run before the menus, and the screen at
which the menu moment is saved (a jump state) and the hooks applied. A map with a `mercs` block is a Mercenaries title
for `gbox/mercs_bot.py`.

Struct sub-fields are named by the vocabulary's last part (`enemies.act` -> the `enemies` array's `act` sub-field, or
whatever `vocab` maps it to). `heading` says how the title measures facing; `world.read` turns it into the engine's
convention (radians, `atan2(dx, dz)`: 0 = +z, + toward +x). `aim` holds the starting rates; the aim model learns the
real ones as it plays and logs them as lessons.

### Signatures

Tags on enum values, on the field that holds them: a `signatures` object beside `enum` (value -> tags). A value with no
signature is just a label.

```json
"act": {"offset": "0xFD", "type": "u8", "format": "hex", "enum": {"0x26": "swing"},
        "signatures": {
          "0x26": {"attack": "melee", "phase": "windup", "lead_s": 0.5, "reach": 1200,
                   "active": {"field": "motion_events", "mask": "0x1"}, "lookahead": "motion_seq",
                   "source": "ghidra", "evidence": "module 0x81718908: Leon is checked only while the motion's bit 0x1 is on; SEQ 125 frames 15-21",
                   "confidence": "static"}}}
```

| tag | on | values |
|---|---|---|
| `attack` | enemy act / state / motion | `melee`, `grab`, `throw`, `projectile`, `explosive`, `charge` |
| `phase` | " | `approach`, `windup`, `active`, `recover` |
| `lead_s` | " | seconds from the start of this value to the hit (when nothing better is known) |
| `reach` | " | world units from the enemy at which it lands |
| `active` | " | `{field, mask}`: the bit that is on during the hit window |
| `lookahead` | " | a field the driver can read ahead for the exact frames to the hit (RE4: the motion's event words) |
| `hold` | enemy act | it is holding the player: shoot it, mash |
| `stunned` | enemy state / act | `{"opportunity": "melee" / "kick" / "suplex", "window_s": ..., "from": "front" / "behind" / "any", "trigger": "head" / "knee" / "arm" / "any"}`: melee on stun, where to stand, what set it up |
| `down`, `dying`, `gone` | enemy state | not a threat; dying / gone: never a target |
| `stun_by`, `emerge` | enemy type | which shot sets up the stun (`head`, `knee`); the type can turn into another threat in the same slot (RE5's Plaga): a type change is a new contact |
| `qte` | prompt kind | `press`, `mash`, `dodge`, `wiggle`, `counter`, `parry` |
| `buttons`, `window_s` | prompt kind | what to press - a list of chords, alternatives allowed: `[["l1", "r1"], ["square", "circle"]]` - and how long it is open |
| `participate` / `block` | prompt kind | press it / never press it (a prompt that would waste the moment, e.g. a ladder in a fight) |
| `control`, `aiming`, `hit`, `held`, `down`, `action`, `dead` | player state | |
| `kind`, `blast_r` | projectile | `axe`, `sickle`, `dynamite`, `molotov`, `arrow`, ...; the blast radius |
| `priority` | enemy type | shoot first (RE4: the chainsaw) |
| `take` | bonus kind | how it is taken: `touch` (walk over), `action` (a button: RE4's TAKE), `shoot`, `melee` (RE5's statues); with the bonus's `hp` when it breaks |

`confidence` is `candidate` (proposed by the lessons analyzer, not checked), `static` (found in the code), or `live`
(checked in the running game, the evidence says how). The engines use `static` and `live`; `candidate` only shows in
coaching until it is checked (a `ram_search` labeled search, then promoted with its evidence).

## 2. The world (what the engines see)

`world.read(rmap, reader, driver)` -> `World`: one batched read of the map (`ram_map`), then

```python
World(t, screen, stage, timer, combo, combo_timer, score, kills,
      player=Player(pos, facing, hp, hp_max, state, tags, aim_pitch, weapon, ammo),
      enemies=[Enemy(id, pos, facing, hp, hp_max, type, state, act, motion, frame, frames, speed, events, target,
                     tags, sig)],            # sig: the merged attack signature of state / act / motion, or None
      projectiles=[Projectile(id, pos, kind, owner)],
      prompt=Prompt(kind, button, tags) | None,
      bonuses=[Bonus(id, pos, kind, taken)],
      partner=Player | None, values=RamValues)
```

Units: positions in the title's world units (`units_per_m` converts when an engine needs meters), headings in the
engine convention, times in seconds. Unknown fields are `None`; engines degrade (no `merc.combo_timer`: combo upkeep by
the kill rate; no `motion_events`: lead times from `lead_s`).

## 3. Engines

All game-agnostic: they take a `World` (and the stage record) and return parts of an `Intent`.

* **threat** (`ThreatEngine.update(world) -> [Threat]`): an enemy whose state / act / motion has an attack signature is
  ranked by its time to land: the `active` bit on = 0, else the driver's `lookahead` (exact frames), else `lead_s`
  minus the time in that value, plus the time to close to `reach`; projectiles by their time to closest approach
  (velocity from consecutive reads; dropped ones are not threats); the rest by distance and the turn to face them;
  `dying` / `gone` never; `down` last; `priority` types first among equals. Decision: shoot the most urgent if a shot
  can leave the gun before it lands (`aim.ready_in`), else evade: out of its reach (away, toward open ground on the
  stage nav, away from other enemies; a quick turn when the way out is behind) or across a projectile's line. Two or
  more in reach, or one as the player gets up from a hit: out first, then one by one. Stats: attacks seen /
  prevented (killed in it) / avoided / landed, projectiles seen / shot / dodged.
* **aim** (`AimModel`): turn toward a heading (stick, pulsed close), aim pose, pitch, a press per shot (`gun_gap_s`),
  lead for the target's velocity; `ready_in(target)`; rates learned from what the player's facing / pitch did under
  held input. `Shots`: a press the gun could fire is a shot; any enemy's health falling (or one starting to die) within
  0.5 s is a hit.
* **reactions** (`Reactions.decide(world)`): a prompt with `participate` is pressed with its `buttons` (mash at the
  title's rate for `mash` / `wiggle`), `block` ones never; `dodge` / `counter` / `parry` inside their `window_s`;
  a `stunned` enemy in reach gets its melee (`opportunity`) when no attack lands first.
* **combo** (`Combo`): the combo window from `merc.combo_timer` (or the last kill): keep a kill inside it, take a combo
  bonus when enough enemies are near (they all score more), don't start a long run with the window about to close.
* **strategy** (`Strategy.plan(world, stage)`): the round's plan: the stage's recommended route (time bonuses in tour
  order), when to fight (threats, combo) and when to move (clock low: the next time bonus), safe spots to fight from.
* **nav** (`Nav`): paths on the stage's grid or graph (RE4: `re4_navmap` from the disc; any title: the learned map
  from position traces, `bot_brain.NavGraph` for graphs), waypoint actions (vault, ladder), stuck handling (vault,
  detour, back off), the learned map saved after every round.

## 4. Intent and the driver

```python
Intent(turn=0.0,          # -1..1 (+ = larger heading), or heading=<radians> to turn toward
       move=0.0,          # -1 back .. 1 forward
       run=False, aim=False, fire=False,       # fire = one press now
       pitch=0.0,         # -1..1 while aiming (+ = up)
       action=False, quick_turn=False, melee=False,
       chord=None,        # a prompt's buttons: [("a",), ("a", "b")...]
       goal="")           # what the engine is doing (coaching, logs)
```

```python
class Driver:                         # gbox/mercs/driver.py; one per title (the map's mercs.driver)
    map_id = "G4BE08"
    def screen(self, values, m) -> str           # when vocab says "driver" (RE4: re4_menus.screen + the round fields)
    def keys(self, intent, world) -> set[str]    # gBox pad names held this tick (stick, buttons)
    def prompt_keys(self, prompt) -> list        # chords for a prompt's button ("a+b" -> [("a", "b")], wiggle ...)
    def lookahead(self, enemy, m) -> float | None     # exact seconds to the hit, if the title can read it ahead
    def stage(self, world) -> str                # the stage DB key for this round ("r400")
```

Menus, set-up and recovery are not the driver's: they are the deployment layer's, through the map's `mercs` block
(the menus module and the package). A round hands over at the `playing` screen and comes back when the screen is not
`playing`, `paused` or `dead` (the round loop answers "You Are Dead - Continue" itself: it is in the round).

```python
def play_round(profile, m, send, stopped, stats, lessons) -> str
    # profile: the title (map + mercs block + driver + stage DB); m: RAM (rd(addr, n)); send(rows): pad events;
    # stopped(): the caller's stop flag; stats: live dict (the watch panel); lessons: a lessons.Run or None.
    # Returns why it ended: "round" (results / menus / title showed), "stopped", "lost" (the player pointer gone
    # for TRANSIENT_MAX: a black screen or a hang - the caller recovers: menu save or relaunch).
```

## 5. Stage DB

`profiles/gamedata/mercs/<map id>/<stage>.json`:

```json
{"map": "G4BE08", "stage": "r400", "name": "Village",
 "nav": {"source": "re4_navmap", "file": "profiles/gamedata/re4_r400_navmap.json"},
 "bonuses": [{"id": "ita23", "kind": "time", "seconds": 90, "pos": [x, y, z], "stand": [x, y, z], "reachable": true}],
 "spawns": [], "hazards": [], "safe_spots": [{"pos": [x, y, z], "why": "one way in"}],
 "route": {"order": ["ita21", "ita23"], "source": "planner", "evidence": "re4_navmap.tour from the start"}}
```

`nav.source` is `re4_navmap` (the disc's collision), `learned` (cells walked / blocked, from position traces), or a
graph file. Learned maps go to `gbox-data/mercs/learned/<map id>/<stage>.json` and are merged into the stage record
when they settle.

## 6. Lessons

`gbox.mercs.lessons.append(map_id, entry, run=None)` is the one way in. Without `run`: notes and reports (coaching,
improvement reports from the deployment layer) go to `gbox-data/mercs/lessons/<map id>.jsonl`, one JSON line each:
`{"ts", "kind": "coach" | "report", "text", "session_id", "worker", "telemetry", "captures", "summary", "request_id",
"note"}`. With `run` (a run id): the engine's events go to `gbox-data/mercs/lessons/<map id>/runs/<run>.jsonl`, one
event per line, `{"t": <s>, "kind": ..., ...}`; `lessons.Run(map_id)` opens one and is what `play_round` takes:

| kind | fields |
|---|---|
| `run` | map id, stage, driver, engine version, package |
| `hit_taken` | the player's state before / after, hp lost, and the nearest enemies just before the hit: id, type, state, act, motion, frame, events, distance, bearing, how long in that act |
| `shot` | target, distance, hit, kill, the aim error |
| `evade` | from what, which way, whether it landed |
| `prompt` | kind, button, pressed, outcome (the player's state after) |
| `stuck` | position, what freed it |
| `bonus`, `combo`, `death`, `round` | what was taken, combo length and how it ended, score and kills |
| `rates` | the aim model's learned rates |

`python -m gbox.mercs.lessons analyze <map id>` turns them into candidates: enemy values seen just before hits that
have no signature (with their lead-time spread), prompts that ended in a hit, stuck spots, rates. A candidate becomes a
signature after a check (a `ram_search` labeled search, or a live check) and goes into the map with that evidence.
Coaching (`gbox/coaching.py`) shows the live threats, the signatures behind them, and the candidates.

## 6b. The enemy knowledge database

Operator, 2026-10-27: "the goal is that the aimbot learns enemy activity and builds a database of how to dispatch them
and the aimbot improves based on the ram byte information to keep the bot aware of enemies and where and how to aim to
dispatch them."

`gbox/mercs/enemy_db.py` is bot-side (stdlib only, hot-reload safe: its state is in `_STATE`, kept by `RELOAD_KEEP`).
The combat brain (`gbox/mercs/brain/knowledge.py`) calls it. Units are metres and seconds.

```python
from gbox.mercs import enemy_db as K
cls = K.class_key(enemy)              # "uEm10" (the class name), "em16.0b.hp1400" (RE4 EmMgr id.type.health), "hp800"
plan = K.dispatch_plan(title, cls, state, dist_m, weapon, hp=..., hp_max=..., defaults=None)
K.observe(title, [{"id": ptr, "cls": cls, "state": s, "dist_m": d}, ...])   # 5-20 Hz: exposure and state onsets
K.record_shot(title, cls, state, dist_m, weapon, (up_m, lateral_m), "hit" | "miss" | "kill", hp_delta, enemy_id=ptr)
K.record_damage(title, cls, state, dist_m, what_hit_us, hp_loss, enemy_id=ptr)
K.record_outcome(outcome_dict)        # the brain's own outcome dict (distance in cm)
```

* **The plan.** Each field is `Learned(value, confidence, samples, source)`:
  - `aim`: `Aim(up_m, lateral_m, zone)`, the offset from his reported position to aim at;
  - `range`: `(near_m, far_m)`;
  - `fire_mode`: tap, hold or burst;
  - `danger`: the chance he hurts the player within 1 s;
  - `windup` and `lead_s`: whether, and how soon, an onset of this state is followed by damage;
  - `attack`, `shots_to_kill`, `hit_rate`.

  With no data every field is the title's current constants (`DEFAULTS`, copied from the drivers): chest at 1.10 m,
  RE5 Switch rain-fire hold, the threat radius rule, and so on.
* **Learning.** Facts are queued in memory and folded by a background thread (single flight). SQLite is written off the
  tick.
  - Aim: per zone, the hit rate and the damage per hit, and the centre of the hits.
  - Range: the bands with the most damage per shot.
  - Fire mode: damage per second.
  - Danger: damage events per second of exposure in a class, state and band. The states that come right before a hit
    (attack wind-ups, grabs, throws) show as a high `windup`, together with their `lead_s`.
  - Weights halve every 21 days without new evidence, and each cell's effective count is capped.
* **Levels.** A field falls back from the class in this title, to his family in this title, to his family in every
  title, to every class of this title, and finally to the default.
  - The families come from `CLASS_MAP`: Ganado ≈ Majini ≈ zombie as `humanoid`, plus `chainsaw`, `crawler` and
    `critter`. It is an explicit table where every row carries its evidence. Drivers add rows with `extend_classes`
    and name raw states with `extend_states`.
  - Another title only shares where hits land on such a body, and the danger. Zone, range, fire mode, shots to kill and
    hit rate come from the title's own shots.
* **Storage.** `gbox-data/mercs/knowledge/<title>/enemies.sqlite` holds:
  - the raw samples (the newest 100,000, none older than 90 days);
  - daily exposure buckets;
  - the learned cells.

  `rebuild()` replays the samples into fresh cells. A running bot reloads the cells when their generation changes.
* **Humans and sparkDeux.**
  - `GET /api/mercs/enemy-knowledge[?title=&enemy_class=&recent=]` (gbox/mercs/reviewer.py, read only) shows per
    class the plan, the danger by band, the states before damage, the sample counts and the recent outcomes.
  - The engine's round hooks put `enemy_db_*` into stats. The round report carries them as
    `metrics.enemy_knowledge`, plus a one-line `enemy_knowledge` summary for Spark2.
* **Seeding.** Run `python -m gbox.mercs.enemy_db_seed --data-dir <gbox-data> [--dry-run]`. It reads, read only:
  - the round maps (RE5 PS3 shot records, every title's hit events; RE4's name the attacker's em id, type and health);
  - RE5 PS3's run-lesson shot rows;
  - the player-damage ledger's receipts (the nearest living enemy at each hit, his class key and distance, a held
    player, and the bot's `stats.look` shots inside each receipt).

  It replaces only its own earlier seed samples.

## 7. The tick

```
play_round:                                      # ~20 Hz until the round is over
  values = rmap.read(m)                          # one batched read
  world = world.read(...)
  if world.screen not in (playing, paused, dead): return "round"
  intent = reactions.decide(world)               # a prompt to take, melee on stun, "Continue" when dead
        or threat.decide(world)                  # shoot the most urgent / evade
        or strategy.plan(world, stage)           # route, bonuses, the stand
  keys = driver.keys(intent, world); send(...)   # gBox pad names through send_input
  lessons.log(...)
```

`gbox/re4_merc_bot.py` stays the RE4 playbook (`matches`, `setup`, `play(ad, send, stopped, sleep, m, tick_s, stats,
clock, learn_dir, rerun, prompt, ram_prompt)` unchanged) and runs its rounds on the engine with the RE4 driver; the
autoplay button keeps calling it the same way until `gbox/mercs_bot.py` takes over the playbook name.

## Title #1: Resident Evil 4, GameCube (G4BE08)

Filled from `profiles/gamedata/G4BE08-ram.json` (the evidence is in each field):

* `screen`: driver (out of a round `gbox/re4_menus.screen` - the title task's work area: main menu, GAME START,
  Select Player, Select Stage; in a round pG+0x20 game routine 3, the room 0x04RR, the clock, the player pointer,
  hp 0 = dead; pG+0x20 = 2 with the clock at 0 is the black screen seen 2026-10-20: `lost`);
  `merc.timer` 0x80279308, `merc.combo` 0x80213954, `merc.combo_timer` 0x80213958; `merc.score`, `merc.kills`: unknown.
* `player.*`: the player em (*0x802B3044): pos +0x94, facing +0xA4, state = routine +0xFC (0 control, 1 hit / held,
  2 dead, 4 action; 00 06 .. aiming), hp pG+0x4FB0. Where the gun points is the aim routine's (0x8014415C): facing
  plus the aim's own horizontal offset +0x400 (the stick moves it first, inside the weapon's cone, then turns him),
  and the aim's vertical blend, the global 0x80218738 (-1 .. +1, kept between aims). +0x258, read as the pitch
  before, is a motion value that never follows the stick.
* `enemies` = the EmMgr slots: `state` +0xFC (0 setting up, 1 acting, 2 hurt, 3 dying, 0xFF gone), `act` +0xFD (the
  attack signatures: 0x21 / 0x22 throw, 0x23 dynamite, 0x24-0x2C swings, 0x2D grab, 0x2E-0x38 hold), the motion at
  +0x1D8 (`motion_seq` +0x280: per-frame event words, bit 0x01 the hit window; frame +0x290, frames +0x294, speed
  +0x298), the Ganado code module (REL id 20 in em/em16.drs) decoded with capstone.
* `projectiles` = EmMgr slots of em id 0x42 (made by 0x80011944 from the throw actions); dynamite's blast: 800.
* `prompt.kind` 0x80279320 (`gbox/re4_ram_prompts.py`: KICK, SHAKE OFF, the QTEs, TAKE ...).
* `bonuses` = the ITA item entries 0x73 / 0x75 (AevMgr), the stage DB from `re4_navmap`.
* driver: R aims, A fires (one press a shot) / acts, B runs, back + B quick turn, the stick turns (aimed: the
  package's `aim_turn_speed` x3); the motion look-ahead for the frames to a Ganado's hit; menus: `gbox/re4_menus.py`
  with the menu moment saved at Select Player and the hack package (re_mods).

## Title #2: Resident Evil 5, PS3 (the RE5 agent)

Fills the same vocabulary in its own map (`profiles/gamedata/<map id>-ram.json`, `platform: ps3`, big-endian): the
Mercenaries clock and combo, the player and partner, the enemies' state / act / motion with their attack signatures,
the melee prompts (RE5's stun melee, counters) as `prompt` signatures, the stages in the stage DB. Its driver maps the
same Intent to RE5's buttons. What RE5 teaches (a counter window, a combo rule, a route idea) goes into the shared tags,
so RE4 gets it where the same thing exists.

## Player assignment, demonstrations and original-rules qualification

The target is repeated S ranks under the game's original gameplay rules. Current
training aids are intentional operator choices. Saving team/training preferences
does not revert them, and a high assisted score does not qualify as unmodified
mastery. `Notebook` retains the observed rank separately from
`unmodified_s_rank_verified`. Missing historical settings remain `unknown`.
`RoundAssistance` latches known aids and unknown readback for the entire round;
turning a switch off at the results screen cannot change that history. The guide
counts assisted, unknown and positively verified unmodified results separately.
Automatic reduction is off; opting in records intent, without treating an
assisted score as evidence that a reduction is warranted.

The shared PiP RE controls use the worker tool `mercs_team`, scoped to an exact
live session, with roles `solo_p1`, `teammate_p2` and `observe_human`. Preferences
live under `gbox-data/mercs/teamplay`. `SessionRuntime` fences every bot input by
the selected role, releases only its actual held keys during transitions and on
F3, and never sends a pending P2 action to P1. Human/co-op sessions retain their
menus and are excluded from automatic black-screen resets. Observation constructs
no gameplay brain, prompt presser or modifier-maintenance loop. A requested
unmodified evaluation waits without input until original gameplay settings can
be positively verified; an unchecked UI alone cannot provide that proof.

For BLUS30491 01.01, `re5_coop.participants` verifies sPlayer's vtable, its
`+0x28/+0x2C` array, each actor's native `+0x2F14` player index, finite position
and HP, and stable pointer readback. Native functions `001AD7B4` and `001AE010`
establish that relationship. Frames preserve separate `players` with actor,
slot, control assignment, HP and ownership provenance, plus assistance context.
Positions observed under an explicit human role are RAM-position demonstrations;
they do not claim to contain physical controller input or a replayable save state.

The reviewer selects a recorded player and inclusive timeline sample range.
`POST /api/mercs/reviewer/demonstrations` derives all route points from stored
samples and preserves source run, player, mode, full geometry identity, sample
digest and assistance. Bot/unknown ownership, actor changes, gaps and teleports
cannot be relabeled as human teaching. Only validated adopted routes can be
assigned to a live instance. `Guidance.practice` advances checkpoints on measured
arrival, retains progress through combat interruptions and revalidates native
floor, action links and current mine margins. QTEs, healing, leaving a planted
mine and immediate threats take priority. An unverified traversal stays draft;
neither an annotation nor a demonstration licenses walking through a wall.

Current capability limits are explicit: separate RPCS3 P2 keyboard preparation
persists for a future launch, preserves P1 and validates conflicts/readback, but
does not claim that the running emulator reloaded its controller configuration.
RE5 P2 actor discovery is verified; P2 camera/displayed-prompt ownership and live
controller response still require validation before teammate combat is enabled.
RE6 has no verified equivalent runtime yet. These roles remain pending instead
of starting a solo P1 bot. Full pristine-rule verification is also pending, so
the present readback can positively identify assistance without certifying a
clean run from an incomplete sample of tables.

Co-op join behavior must follow the appropriate edition's official manuals:
[RE5 PS3](https://static.capcom.com/manuals/re5/RE5_PS3_DMNL_EN.pdf) and
[RE6 manuals](https://www.capcom-support.com/hc/en-us/articles/6586143302684-Resident-Evil-6-Online-Manual).
The operator's GameWith link covers Mercenaries United, while the running PS3
Gold build has separate original/Reunion modes. Its edition-specific menu and
loadout instructions must not be silently substituted for this build's rules.
