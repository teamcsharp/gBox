# Round 291: one icon per mod, and F3 to take over

## The request

*"I want icons in the toolbar for each and every game that we load pertaining to the mods that we've created ... every mod that we have for PSO, I want
an icon in the top bar that I'm able to click on and use to modify the game in action even while the bot is playing."*

## What was built

**`game-mods.js`** - a manifest of mods **per game**, matched by title, with **21 PSO entries**, each with an inline SVG icon, a tooltip, the
`pso_controls` op it sends, and any prompts it needs:

| mod | what it does |
|---|---|
| Raise a stat | `stat` (mst gives TP) |
| Give an item | `give` by code |
| Equip a weapon | `equip` by code |
| Fill every slot | `multi_equip` |
| Ignore requirements | `equip_any` (toggle) |
| Set mag stats | `mag_set` (DEF/POW/DEX/MIND, IQ 200, synchro 120) |
| Feed the mag | `mag_feed` |
| Permanent Scape Doll | `survival` (toggle) |
| Every hit critical | `crit` (toggle) |
| Every attack connects | `always_hit` (toggle) |
| Walk through walls | `walk_through` (toggle) |
| Ultimate difficulty | `legendary` (toggle) |
| Randomised gear | `randomized` with an interval |
| Photon blast max | `pb` |
| Teleport to a floor | `floor_warp` |
| Go to a boss arena | `boss_warp` |
| Clear the floor | `floor_clear` |
| Spawn items | `floor_spawn` |
| Enemy drops | `enemy_drops` (toggle) |
| Revive | `revive` |
| Live map | opens the 2D viewer |

**They work while the bot plays** because they are **RPCs** (`pso_controls`), not keystrokes - so they need no window focus and cannot collide with the
bot's own input. That is the whole point of putting the mods in the toolbar rather than on keys.

Toggles keep their state on the button (`data-on`), prompts validate numbers, and every click reports through a toast so a refusal says why instead of
looking like nothing happened.

## How it is wired

* `<script src="game-mods.js">` loads the manifest before the app;
* the four hardcoded buttons from the previous round are replaced by `[data-game-mods]`, which the builder fills;
* `buildMods()` renders one button per mod for the **active title**, and is exposed as `window.gboxBuildMods` so it rebuilds whenever the compact title
  changes - switching games in the PiP switches the icon set;
* `window.gboxPsoRpc(op, fields)` targets the **live session**, with a generated `command_id` and a 5 s expiry, the same envelope the plane expects.

The mod block is balanced (25/25 braces, 43/43 parens), the manifest passes `node --check`, and no reference to the superseded painter remains.

## F3: take over immediately

`f3_takeover.py` is armed and running:

* **F3 is polled with `GetAsyncKeyState`**, which is global - the operator can press it with any window in front;
* pressing it **takes the screen** (raises the game) and starts playing **at once** - no idle window, no focus gate;
* pressing it again **stops every send** and returns control;
* the operator's pad still wins (30 s back-off), and the `PAUSED` file stops it outright.

Its hunting branch was also repaired - it contained two placeholder expressions from an editing pass, harmless but the hunt did nothing at all. It now
walks the planned height-aware route.

## To see it

**Reload the gBox window** (Ctrl+R): both `game-mods.js` and the toolbar changes are in the app's renderer.

## State

| item | state |
|---|---|
| PSO mod icons | **21**, data-driven, clickable mid-play |
| other games | manifest structure is per-title; only PSO is populated so far |
| F3 takeover | armed and running |
| need | app window reload |
