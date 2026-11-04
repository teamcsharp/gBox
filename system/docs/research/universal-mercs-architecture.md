# Universal Mercenaries Bot Architecture (design + staged plan)

Status: **DESIGN ONLY — no engine code changed by this doc.** The `gbox/mercs/` engine
is live-streaming and being edited by other agents; this is an *evolution* plan on top
of the current structure, not a rewrite. Author: autopilot research pass, 2026-11-04.

Each claim below is tagged **[grounded]** (verified in the code on branch
`arsenal-instant-swap`) or **[design-guess]** (proposed, not yet in the code).

---

## 0. The operator's vision, decomposed

> "A universal Mercenaries bot, plug-and-play with modules for pertinent titles,
> importing what each session needs. The main logic has classes that are customizable,
> interchangeable and expandable — a DYNAMIC NAVIGATIONAL AIMBOT. All these games with
> the same mods, switches and customizations (to an extent) — consistent magnum
> behavior and aim-speed calibration — with each match TRAINING and IMPROVING the
> behavior for not only that title but ALL titles — universally compatible."

Four pillars:
1. **Core = dynamic navigational aimbot** — swappable base components (nav, targeting/aim,
   combat, survival, menu-walk) a title *composes*.
2. **Plug-and-play title modules** — RAM map + adapter + overrides per title; the core
   imports only the active session's module.
3. **Shared control surface** — one named set of mods/switches/behavior axes consistent
   across titles, with bounded per-title adaptation. Operator's intended UI: a **radial
   behavior graph** of draggable dots (§4).
4. **Cross-title learning** — a match's universal lessons (aim-speed, magnum behavior,
   survival tuning) transfer to all titles; title-specific lessons stay local.

---

## 1. What the current engine already is (grounded map)

The engine already follows a **"title-agnostic core + per-title driver"** split. The core
pieces and their locations:

| Layer | File | What it does | Title-agnostic? |
|---|---|---|---|
| Round loop | `mercs/engine.py` `play_round()` | Per-tick: snapshot → screen → prompt-press → brain tick → key diffing; frame sync; evidence/notebook; crash-resilient ticks (`TICK_ERRORS_MAX`); latency metrics | **Yes** [grounded] |
| Driver interface | `mercs/driver.py` `Driver` | `snapshot / screen / brain / prompt_source / prompt_keys / progress / learning_stage`; `load(prof)` dynamic-imports the module named in the profile's `mercs.driver` | **Yes — this is the plug point** [grounded] |
| Universal QTE | `mercs/reactions.py` `PromptPresser` | RAM-first (driver `prompt_source`) → vision fallback; burst/rest cadence; mash mode for grab-shake | **Yes** [grounded] |
| Aim rates / shot scoring | `mercs/aim.py` `AimRates`, `Shots` | Learns turn/aim/pitch rates from observed motion; `ready_in()` time-to-shot; scores hits by enemy HP deltas | **Yes, but instanced per-bot, not persisted** [grounded] |
| Navigation primitives | `mercs/navcommon.py` | `StuckDetector`, `PortalMemory`, `height_cost`, `sight_gate` (LoS gate — the no-wall-shot primitive), `bonus_priority` (S-rank time-first) | **Yes** [grounded] |
| Enemy knowledge DB | `mercs/enemy_db.py` | `dispatch_plan(title, cls, …)`, `record_shot/record_damage/observe`; SQLite, background fold; **per-title keyed** | **Yes (universal engine, per-title data)** [grounded] |
| Damage→cause clustering | `mercs/damage_clusters.py` | incidents → per-(game,cause) clusters → batch requests; `GAMES` maps game_id→title | **Yes, per-title keyed** [grounded] |
| Learning loop | `mercs/learning.py`, `tuner.py`, `tuning.py`, `gate.py` | rounds→causes→bounded constant step→8-round confirm→auto-revert; code-change gate | **Per-title** [grounded] |
| Arsenal swap | `mercs/weapon_swap.py` | title-agnostic `decide()` policy + per-title resolvers (`re6_desired_index`, `re5_rampage_families`) onto each title's native-equip path (no item wheel) | **Yes — the model pattern** [grounded] |
| Live cheat mods | `merc_live_controls.py` `MODS` | per-title (re5/re6) native cheats via the `re5_mods` job | Per-title [grounded] |
| Live behavior knobs | `mercs/bot_logic.py` `KNOBS` | per-title module-constant dials set live, saved to `bot-logic.json`, re-applied each round after the tuner | Per-title [grounded] |
| Operator directives | `mercs/directives.py` | one-shot/standing commands ("fight", "mine_trail", "rush") the bot reads each tick | **Yes** [grounded] |

**The three model patterns to generalize** (operator's intent already prototyped here):
- `reactions.PromptPresser` — a **shared module + per-title hook** (`prompt_source`,
  `prompt_keys`). This *is* the universal-QTE pattern today. (A dedicated
  `gbox/mercs/qte.py` is in flight on branch `mercs-universal-qte`, agent `abd04906`;
  it should land as the §2 `QTEComponent`.) [grounded + in-flight]
- `weapon_swap.decide()` — a **pure title-agnostic policy + thin per-title resolver**.
- `enemy_db` — a **universal engine with per-title data buckets** (already the operator's
  explicit "universal mercenaries engine" quote, 2026-10-27).

---

## 2. Pillar 1 — Core as a dynamic navigational aimbot

### 2.1 Grounded state

- The **Driver interface and dynamic `load(prof)`** already make titles pluggable. [grounded]
- `engine.play_round` is already title-agnostic and crash-resilient. [grounded]
- `navcommon`, `aim`, `reactions`, `weapon_swap` are already title-agnostic components. [grounded]

### 2.2 The gap

The **brain itself is not decomposed.** Each title's `Bot` is a monolith:
`re5_switch.Bot` begins at line 1455 of a 320 KB file; `re6_switch.Bot` at line 2194 of a
377 KB file; `re5_ps3.py` is 312 KB. These bots **re-implement** targeting, aiming,
navigation, crowd handling and survival inline and import almost no shared logic (a grep
of `re5_switch`/`re6_switch` finds only `..directives`, `..weapon_swap`, `..tuning`
imported into the bot — **not** `navcommon` or `aim`). So "consistent magnum behavior and
aim-speed across titles" is currently **convention, not shared code**. [grounded]

### 2.3 Target shape — composable aimbot components

Introduce a component protocol under `mercs/core/` (new package) that the existing
`Driver.brain()` can *optionally* delegate to. Each component is a small object with a
`tick(ctx) -> Intent | None` method; the title composes a list and the first non-None
intent wins (priority order), exactly mirroring how `play_round` already lets
`PromptPresser` pre-empt the brain.

```
mercs/core/
  context.py     # WorldView: normalized per-tick snapshot (player, enemies[], bonuses[],
                 #   prompt, clock, stage) — the one shape every component reads
  intent.py      # Intent: {hold:set, tap:key, aim:(yaw,pitch), equip:family, note:str}
  nav.py         # NavComponent      (base): goal picking, path, stuck recovery
  target.py      # TargetComponent   (base): census → threat ordering (wind-up first)
  aimbot.py      # AimComponent      (base): LoS gate (navcommon.sight_gate) + aim rate
  combat.py      # CombatComponent   (base): fire policy, rampage, arsenal swap (weapon_swap)
  survival.py    # SurvivalComponent (base): heal, flee, grab/bomb walk-off
  menu.py        # MenuWalkComponent (base): select-stage/char/costume walk, Retry avoidance
  qte.py         # QTEComponent      (base): wraps reactions.PromptPresser (universal)
  brain.py       # ComposedBrain: ordered [QTE, Survival, Target+Aim+Combat, Nav, Menu]
```

- **Base classes are concrete and usable** — they hold the operator's universal rules
  (no wall shots via `sight_gate`; never idle among foes; keep-moving; blast-margin for
  mines). A title **subclasses to override only what differs** ("to an extent"). [design-guess]
- `ComposedBrain` exposes the same duck-typed surface `play_round` already calls
  (`tick`, `prompt_ok`, `save`, `_threats`, `recall`), so **the engine does not change.**
  A title's `Driver.brain()` may return a `ComposedBrain` or keep its legacy `Bot`. [design-guess]
- `WorldView` is the **single normalization boundary**: each title's `snapshot()` already
  produces a dict; a thin `to_worldview(snap)` per title feeds the components. This is the
  only new per-title glue required. [design-guess]

Why this is safe: it is **additive**. The monolith bots keep working untouched; a new
title (RE4 Switch — currently a skeleton in `titles/re4_switch.py`) is the first to be
*born composed*, proving the components against a title with no legacy to break. [grounded skeleton]

---

## 3. Pillar 2 — Plug-and-play title modules

### 3.1 Grounded state

`driver.load(prof)` already imports `prof["mercs"]["driver"]` and reads its `DRIVER`
symbol. A title ships: its driver module (`titles/<t>.py`), a RAM map JSON
(`profiles/gamedata/<title_id>-ram.json`), and the adapter is chosen by the session
(Citron/Eden/RetroArch/Dolphin). The RE4-Switch skeleton documents exactly this
"pending live RAM measurement" contract. [grounded]

### 3.2 The gap & target

Formalize a **TitleModule manifest** so the core imports *only* what a session needs and
new titles are declarative:

```python
# titles/<t>.py  (addition, not a rewrite)
MODULE = TitleModule(
    title_id = "010099A00BC1E000",         # RE4 Switch
    driver   = RE4Switch,                   # existing Driver subclass
    ram_map  = "profiles/gamedata/010099A00BC1E000-ram.json",
    adapters = ("citron", "eden"),
    to_worldview = re4_to_worldview,         # snap dict -> core.WorldView
    components   = dict(                      # which base/override component each slot uses
        qte=QTEComponent, nav=RE4Nav, target=TargetComponent,
        aim=AimComponent, combat=RE4Combat, survival=SurvivalComponent, menu=RE4Menu),
    control_map  = RE4_CONTROL_MAP,           # universal axis -> this title's knobs (§4)
    arsenal      = weapon_swap.PROFILES["re4"],
    learning     = LearningProfile(...),      # universal vs local constants (§5)
)
DRIVER = RE4Switch   # unchanged, still what driver.load() reads
```

- A central **registry** (`mercs/core/registry.py`) maps `title_id → MODULE`; the engine
  still goes through `driver.load`, so **nothing in `play_round` changes.** [design-guess]
- `components` lets a title say "use the base nav, but my own combat" — the
  customizable/interchangeable/expandable requirement, declaratively. [design-guess]
- Titles that never expose a native-equip primitive (3DS, VR today) simply omit `arsenal`
  and the swap resolver returns `None` → stock behavior, matching `weapon_swap`'s current
  fallback contract. [grounded fallback]

---

## 4. Pillar 3 — Unified control surface (+ radial behavior graph)

### 4.1 Grounded state — three overlapping, per-title surfaces

1. `merc_live_controls.MODS["re5"|"re6"]` — native cheats as `(op, label, status_path, bounds)`:
   e.g. re5 `fire_rate`(1–80), `turn_speed`(1–10), `bullet_damage`; re6 `fire_rate`,
   `magnum_speed`(1–6), `throw_speed`(1–20), `quick_attack`, `down_fire`. [grounded]
2. `bot_logic.KNOBS["re5"|"re6"]` — behavior dials set as **live module constants**, saved
   to `bot-logic.json`, re-applied each round after the tuner (operator's word wins):
   re5 `CROWD_FIRE`, `RAMPAGE_R`, `MINES`, `GRENADES`, `AIM_LOCK`, `HEADING_GOV_DEG_S`,
   `HEAL_CRITICAL`…; re6 `NADES`, `FLASH_N`, `BOMB_DROP`, `AUTO_SWITCH`, `KITE_R`,
   `SURVIVAL_HP`… [grounded]
3. `weapon_swap.PROFILES["re5"|"re6"]` — arsenal crowd-swap profile. [grounded]

`merc_live_controls.control_inventory()` **already merges** native mods (`mod.<op>`) and
behavior knobs (`behavior.<knob>`) into one list of rows carrying
`{id, label, group, kind, value, min, max, step, available}`. `change_input()` routes
`behavior.*` → `{op:"bot_logic", values:{…}}` and `mod.*` → the native op. The MCP path
is `game_live_controls` tool → `POST /api/sessions/{sid}/live-controls` → `Controls.call`
→ `re5_mods` job. [grounded]

**The gap:** the *same concept has different names per title* (re5 `turn_speed` vs re6 has
no turn knob; re5 `CROWD_FIRE`+`RAMPAGE_R` vs re6 `FLASH_N`+`CROWD_R`; re5 `MINES`/
`MINE_EVERY_S` vs re6 `BOMB_DROP`). There is **no universal axis vocabulary** — so a dot on
the radial graph cannot bind to one consistent param across titles.

### 4.2 Target — a universal AXIS layer over the existing knobs

Add a **third control namespace, `axis.<name>`**, defined once in a new
`mercs/core/control_axes.py`, that each title maps onto its existing `mod.*`/`behavior.*`
params. The axes are the operator's radial-graph dots plus the main-brief sliders. This is
a **thin mapping layer — it invents no new live-apply mechanism**; it expands each axis to
the title's already-wired knobs. [design-guess, built on grounded plumbing]

**Universal axis set** (name, range, default, meaning — "0..1 intensity" unless noted):

| Axis | Range | Default | Meaning |
|---|---|---|---|
| `aggression` | 0.0–1.0 | 0.6 | push-in vs kite; raises crowd-fire/rampage radius & lowers flee thresholds |
| `aim_speed` | 0.25–10× | 2.0× | turn+aim rate (maps to a real native speed where one exists) |
| `fire_rate` | 1–80× | 1× | shot time-scale (direct native mod) |
| `magnum` | 0.0–1.0 | 0.8 | magnum preference + magnum-specific speed/recoil |
| `weapon_switching` | 0.0–1.0 | 0.6 | how eagerly arsenal swaps (crowd→launcher/shotgun, back to magnum) |
| `grenade_use` | 0.0–1.0 | 0.6 | flash/frag/throw frequency & crowd threshold |
| `mine_place` | 0.0–1.0 | 0.4 | mine/remote-bomb cadence while relocating |
| `melee` | 0.0–1.0 | 0.5 | quick-attack/melee-after-flash eagerness |
| `knife` | 0.0–1.0 | 0.3 | knife finisher / close-range blade preference |

**Per-title mapping (`control_map`)** — each title declares, for each axis, the concrete
knobs it drives and the transfer function (bounded "to an extent"). Example (grounded knob
names; transfer curves are design-guess):

```python
# re5 (010018100CD46000)
RE5_CONTROL_MAP = {
  "aim_speed":        [("mod.turn_speed",       lin(0.25,10)),          # native, grounded 1..10
                       ("behavior.HEADING_GOV_DEG_S", lin(60,360))],     # governor rises with speed
  "fire_rate":        [("mod.fire_rate",        passthru(1,80))],
  "aggression":       [("behavior.RAMPAGE_R",   lin(300,800)),
                       ("behavior.CROWD_FIRE",  gate(0.3)),              # on past 0.3
                       ("behavior.HEAL_CRITICAL", inv_lin(0.6,0.1))],    # more aggressive = heal later
  "weapon_switching": [("arsenal.enabled",      gate(0.2)),
                       ("behavior.UNLOAD",      gate(0.5))],
  "grenade_use":      [("behavior.GRENADES",    gate(0.25))],
  "mine_place":       [("behavior.MINES",       gate(0.2)),
                       ("behavior.MINE_EVERY_S",inv_lin(60,3))],
  "magnum":           [("arsenal.default_family","magnum" if >0.5)],
  "melee":            [("behavior.WINDUP",      gate(0.3))],            # RE5 has no quick-attack knob → bounded
  "knife":            [NO_OP],                                          # RE5 knife not wired → axis clamped/greyed
}
# re6 (01002A000CD48000)
RE6_CONTROL_MAP = {
  "aim_speed":        [("mod.magnum_speed",     lin(1,6)),              # grounded native
                       ("behavior.SPIN_DEG_S",  lin(60,360))],
  "fire_rate":        [("mod.fire_rate",        passthru(1,80))],
  "magnum":           [("mod.magnum_speed",     lin(1,6))],
  "weapon_switching": [("behavior.AUTO_SWITCH", gate(0.2)),
                       ("arsenal.enabled",      gate(0.2)),
                       ("behavior.GRAB_SWAP",   gate(0.5))],
  "grenade_use":      [("mod.throw_speed",      lin(1,20)),
                       ("behavior.NADES",       gate(0.25)),
                       ("behavior.FLASH_N",     inv_lin(8,2))],
  "mine_place":       [("behavior.BOMB_DROP",   gate(0.3))],
  "melee":            [("mod.quick_attack",     lin(1,10)),
                       ("behavior.PERIODIC_QA", gate(0.3))],
  "aggression":       [("behavior.CROWD_R",     lin(150,400)),
                       ("behavior.KITE_R",      inv_lin(1500,300)),
                       ("behavior.SURVIVAL_HP", inv_lin(0.7,0.1))],
  "knife":            [NO_OP],
}
```

Rules that keep it honest:
- An axis a title cannot express maps to `NO_OP` → the graph greys that dot for that title
  (reuses the existing `available:false` + `reason` row contract in `control_inventory`). [grounded contract]
- Transfer functions are **bounded** by each knob's existing `(low, high)` in
  `bot_logic.KNOBS` / `merc_live_controls.MODS` → nothing can push a value out of its
  already-vetted safe range. [grounded bounds]
- The operator's hard rules are **not** axis-reachable: `aggression=1.0` still cannot fire
  through a wall (LoS gate is in `AimComponent`, not a knob) or stand on a mine (blast
  margin stays in `SurvivalComponent`). The axis layer tunes *style within the rules*. [design-guess, honors gbox-bot-no-wall-shots-no-mine-standing]

### 4.3 MCP / live binding (build on the existing facade)

- **Reuse `op:"set"`** with `control:"axis.<name>"`. `control_inventory()` gains a third
  source that emits `axis.*` rows (id/label/kind/min/max/step/value) computed from the
  title's `control_map`; `change_input()` gains one branch: `axis.*` → expand via
  `control_map` → emit the underlying `{op:"bot_logic", values:{…}}` and/or native
  `{op:…, multiplier:…}` calls in one job. **No new HTTP route, no new auth path.** [design-guess on grounded `set`/SCHEMA]
- `ALLOWED["set"]`/`SCHEMA` already permit `{session_id, op:"set", control, value}` — axis
  ids pass unchanged; only the server-side expander is new. [grounded]
- Live & no-restart: `bot_logic.handle()` already sets module constants instantly and
  persists them; native mods already apply live via the `re5_mods` job. The axis expander
  calls exactly these. [grounded]
- Programmatic callers and the future radial UI hit the **same** `set axis.*` path, so they
  never diverge. [design-guess]

### 4.4 Follow-on deliverable — the radial behavior graph

The circular/radial graph with draggable dots (AGGRESSION, WEAPON_SWITCHING, GRENADE_USE,
MINE_PLACE, MELEE, KNIFE + AIM_SPEED, MAGNUM, FIRE_RATE) is the **operator's intended UI and
an explicit "eventually" follow-on**. It is a thin front-end: each dot's angle = axis,
radius = value; dragging issues `POST /api/sessions/{sid}/live-controls {op:"set",
control:"axis.<name>", value}`. Greyed dots = `available:false` axes for the current title.
**Designing the axis schema + MCP binding now (§4.2–4.3) is the prerequisite so the dots
later bind to real, consistent, cross-title knobs.** The widget itself is out of scope here.

---

## 5. Pillar 4 — Cross-title learning (transferable vs local)

### 5.1 Grounded state

- `tuner.py`/`tuning.py`: `RULES`/`PARAMS` are **keyed by title_id**; the tuner writes
  per-title `gbox-data/mercs/learned/<title>/tuning.json`; the bot reads it at round start
  via `tuning.apply(MAP_ID, stage, stats)` (grounded hooks in `re5_switch` and `re6_switch`;
  RE5 PS3 hook is on the in-flight `mercs-learning-close-the-loop` branch). [grounded]
- `aim.AimRates` learns turn/aim/pitch rates live but **per-bot-instance, not persisted**
  and not shared. [grounded]
- `enemy_db` is already a **universal engine with per-title data** — the right shape, but
  its data never crosses titles. [grounded]
- Known efficacy problem (memory `gbox-mercs-learning-loop`): per-stage trials expire
  unconfirmed; fix pools to `'*'` per-title. **Still per-title.** [grounded]

### 5.2 The gap

Nothing transfers a lesson learned in RE5 to RE6/RE4. "Each match improves ALL titles"
is unmet. But **not every constant should transfer** — `re5_switch.BEHIND_R` (a RE5 Majini
grab range) is title-physics-specific; `aim_speed` calibration and "magnum behavior" are
meant to be universal.

### 5.3 Target — a two-tier tuning store

Split every tunable into **UNIVERSAL** (transferable) vs **LOCAL** (stays in the title's
`tuning.json`), declared in each title's `LearningProfile`:

```
gbox-data/mercs/learned/
  _universal/tuning.json        # shared across all titles  (NEW)
  <title>/tuning.json           # per-title, as today       (unchanged path)
```

- **Universal constants** (operator's named cross-title behaviors): aim-speed calibration
  (the fired-shot time-to-hit / overshoot that `aim.AimRates` already measures), magnum
  fire/recoil cadence preference, heal-fraction floor *as a normalized ratio*, grab-escape
  mash cadence, blast-margin safety ratio. These live in `_universal/tuning.json`. [design-guess]
- **Local constants**: anything in game-world units tied to one title's RAM/physics
  (`BEHIND_R` cm, `CROWD_R` cm, stage avoid-spots, per-enemy-class dispatch). Stay per-title. [grounded split rationale]
- **Transfer rule:** a universal trial is confirmed using **pooled evidence from every
  title that declares the constant universal** — directly fixing the "not enough same-stage
  rounds to confirm" leak by widening the pool across titles, not just stages. The tuner's
  existing `metric()`/`judge()` math is unchanged; only the round set it draws from widens. [design-guess, extends grounded tuner]
- **Normalization is mandatory for transfer:** a universal constant is stored as a
  dimensionless ratio (e.g. aim_speed as "fraction of a full turn per 100 ms of measured
  motion"), and each title's `tuning.apply` denormalizes it to its native unit on read —
  the same read-hook the bots already call. RE5's `turn_speed` native scale and RE6's
  `magnum_speed` are the denormalizers for `aim_speed`/`magnum`. [design-guess]
- `enemy_db` stays per-title (enemy physics do not transfer), but its **aim-offset learning
  per zone** can feed the universal `aim_speed` prior — one read path, no schema break. [design-guess]

Safety: `_universal` writes keep the tuner's existing bounded-step + 8-round-confirm +
auto-revert-on-10%-worse discipline (deaths weighted 3×). A universal revert reverts for
all titles; because it is normalized and bounded, worst case is back to shipped. [grounded discipline]

---

## 6. Staged, low-risk refactor plan

Each stage **keeps the live engine working** and is independently shippable. Ordered by
(risk ↑, value) with the **lowest-risk / highest-value / non-colliding** step first.
Deploy via `git merge`+push in a **supervised restart window**, never the unattended ~05:00
cron, and batch with other driver changes to avoid confounding the code-change gate
(memory `gbox-mercs-learning-loop`). GitHub PR flow is paused — merge+push only
(`gbox-github-rate-limit-pause`).

### Stage 1 — Universal axis layer (additive, read-mostly) — **DO FIRST**
New `mercs/core/control_axes.py` + per-title `control_map` tables + the `axis.*` source in
`merc_live_controls.control_inventory()` and one `change_input()` branch. **Touches only the
control-surface read/expand path; the bots and drivers are unchanged.** Highest value
(unblocks the radial UI and gives the operator consistent cross-title dials now), lowest
risk (expands to already-bounded, already-live knobs; an unmapped axis just greys out).
**Non-colliding:** does not touch the files the RE4/PSO/arsenal/tuner agents are editing.
- *Coordination:* confirm final axis↔knob mapping with the **arsenal/weapon-swap agent**
  (`a3823894`) since `weapon_switching`/`magnum` drive `weapon_swap.PROFILES`.

### Stage 2 — `WorldView` normalization + component protocol (no behavior change)
New `mercs/core/{context,intent,*.py}` base classes and `ComposedBrain`, plus a
`to_worldview()` per title. **No existing bot is switched over** — base components are
written and unit-tested against recorded snapshots (`run_capture` round maps already exist).
Risk: isolated new package; zero runtime path until a driver opts in.
- *Coordination:* agree the `WorldView` field names with the **PSO-nav** and **RE4-driver**
  agents so their snapshots map cleanly; fold the in-flight `qte.py` (`mercs-universal-qte`,
  `abd04906`) in as `QTEComponent` rather than a parallel module.

### Stage 3 — First composed title = RE4 Switch (born composed)
Build the RE4 Switch driver (today a skeleton) **on the components** once its RAM map is
measured on the Spark. Proves the component stack on a title with no legacy to regress.
Risk contained to a not-yet-live title.
- *Coordination:* **RE4-driver agent** owns this; the component bases must land (Stage 2)
  first. RE4 means **RE4 Switch** (`010099A00BC1E000`, Mercenaries), never GC (memory
  `gbox-re4-means-switch`).

### Stage 4 — Two-tier learning store (`_universal/tuning.json`)
Add `LearningProfile` universal/local split + pooled cross-title confirmation + normalized
denormalize-on-read. Wrap every new path in the tuner's existing exception discipline;
reverts to shipped. **Do this only after the in-flight `mercs-learning-close-the-loop`
branch (agent `a0c1b07a`) has merged and been verified post-restart** — stacking two tuner
changes would confound the gate and the 8-round confirmation.
- *Coordination:* hand off to the **learning/tuner agent**; sequence strictly after their
  pooled-`'*'` fix rides a restart and `/api/mercs/learning` shows kept/reverted (not
  expired). RE5 PS3 (`BLUS30491`) must be in tier-a first.

### Stage 5 — Migrate a legacy title's brain onto components (one at a time)
Only after Stages 2–4 are proven: refactor `re6_switch.Bot` (or `re5_switch.Bot`) to
delegate to `ComposedBrain`, piece by piece (survival first, then nav, then combat),
keeping the old code path behind a module flag for instant rollback. **Highest risk —
large live-streamed files — so last, one title at a time, in a supervised window.**
- *Coordination:* must not overlap the arsenal and no-wall-shot work still landing in those
  files; coordinate the window with whichever agent last touched the target `Bot`.

---

## 7. Coordination summary (agents currently in this code)

| Agent / area | File(s) | Interaction with this plan |
|---|---|---|
| Arsenal / weapon-swap (`a3823894`) | `weapon_swap.py`, `re*_switch_mods.py` | Stage 1 maps `weapon_switching`/`magnum` onto `weapon_swap.PROFILES`; align axis↔family mapping. Becomes `CombatComponent`'s swap input (Stage 2). |
| Universal QTE (`abd04906`) | `mercs/qte.py` (branch `mercs-universal-qte`) | Land as `QTEComponent` (Stage 2); today `reactions.PromptPresser` holds the pattern. Do not build a parallel QTE path. |
| Learning / tuner (`a0c1b07a`) | `tuner.py`, `tuning.py`, `gate.py`, `re5_ps3.py` hook | Stage 4 extends their store; **must sequence after** `mercs-learning-close-the-loop` merges + verifies. |
| PSO nav | `titles/` + nav | Stage 2 `WorldView`/`NavComponent` field names agreed with them; PSO is a non-Mercenaries consumer that proves the nav base generalizes. |
| RE4 driver | `titles/re4_switch.py` | Owns Stage 3 (first composed title). Needs the Spark RAM map + the component bases first. |

---

## 8. Honesty ledger

**Grounded in the code:** the Driver interface + `load()`, `play_round`, `PromptPresser`
(universal QTE), `aim`/`navcommon`/`weapon_swap`/`enemy_db` as title-agnostic engines, the
per-title `MODS`/`KNOBS`/`PROFILES` surfaces and their live-apply + MCP facade, the tuner's
per-title bounded-step/confirm/revert loop, the monolithic title `Bot` classes, the RE4
skeleton, and the operator rules in the cited memories.

**Design-guess (proposed, not yet code):** the `mercs/core/` component package and
`ComposedBrain`, the `TitleModule`/registry manifest, the `axis.*` namespace + `control_map`
transfer functions and their exact curves, the `_universal/tuning.json` two-tier store with
normalized denormalize-on-read and pooled cross-title confirmation, and all axis
ranges/defaults in §4.2 (starting points, to be calibrated live like every other constant).
