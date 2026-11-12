# Round 295: every area one click away

## The request

*"unlock all areas of the game to be available by default in every session."*

## What is actually possible here, stated plainly

A **true unlock** - every area selectable in the game's own menus without having beaten the preceding boss - is a change to the **progress flags held in
the save**. Two routes were checked and neither is available:

* **`pso_ragol_unlock`** is a research gate for a *different* build ("Return To Ragol V1.0.3") and says of itself: **"Deliberately contains NO write
  targets"**;
* the **memory card payload is encrypted** - earlier probing found no repeating XOR key, not the documented LCG, and not PRS - so the save cannot be
  edited blindly, and I will not guess at a write into a save.

## What was built instead, and it satisfies the intent

Every area is now **reachable in one click, in every session**, through the plane's own `floor_warp` - the same call that moved this session between
Forest, the Caves and the Dragon's arena:

* the dialog gained a **`select`** field type (a real dropdown), because thirteen destinations must not be typed from memory;
* the toolbar gained an **Area** entry listing **all fifteen Episode I destinations**:

```
Pioneer 2 (city) · Forest 1 · Forest 2 · Cave 1 · Cave 2 · Cave 3
Mine 1 · Mine 2 · Ruins 1 · Ruins 2 · Ruins 3
Dragon arena · De Rol Le arena · Vol Opt arena · Dark Falz arena
```

* the existing **Boss arena** entry covers `boss_warp` for the three bosses by name;
* **Ultimate** is already verified on ("next offline game selects Ultimate").

So the answer to "available by default": **no progress is needed to reach any area** - it is one click, from any session, including the boss arenas.

## Honest difference

This is **not** the same as editing the save so the game's own teleporter lists every area. It is a first-class warp that the operator (and the bot)
can use at will. If the game-menu unlock is wanted, the save format has to be solved first, and that is a research task, not a call.

## State

| item | state |
|---|---|
| Area picker | **all 15 destinations**, one click |
| Boss picker | `boss_warp` by name |
| Ultimate | verified on |
| dialog | real DOM dialog with text, number and **select** fields |
| needs | an app window reload |
| game session | live in Pioneer 2; F3 armed |
