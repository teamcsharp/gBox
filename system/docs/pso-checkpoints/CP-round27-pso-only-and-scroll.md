# Round 27: PSO-only controls, and a scrollable mod bar

Two things the operator asked for while the game was on screen.

## 1. Only PSO's options while playing PSO

The menu bar offered **Flash → Hand (unavailable), Incendiary (unavailable)** during Phantasy Star Online. Those are **Resident Evil 4's** flashbang and
grenade-ring controls, bound into the compact bar for **every** game - so the app advertised options that cannot work in PSO at all.

The gate uses the game-aware manifest already in place: `gboxGameMods.modsFor(title)` returns PSO's 21 entries when PSO is running and nothing otherwise, so
"this game has its own mods" is exactly "this game is not RE". When it returns entries, the RE-only controls are hidden:

```
[data-flash]            the flashbang button
.flash-shortcut-menu    its pop-up menu (the one in the screenshot)
[data-ring]             the grenade ring
.ring-control           its type chooser
```

Nothing is removed - they are hidden with `hidden` and restored when the title stops being PSO, so switching games in the same window still works.

## 2. A scrollable row, actually usable

*"I need them to be a scrollable row where I'm able to access them and adjust them adequately."*

The strip was capped at **42vw** with `overflow-x:auto` and a **hidden** scrollbar - on a narrow window the icons past the fold were unreachable, with
nothing to grab. Now:

| property | before | after |
|---|---|---|
| width | 42vw | **64vw** |
| scrollbar | hidden | **thin, visible**, highlighted on hover |
| wheel | page scroll | **scrolls the strip sideways** |
| scrolling | instant | **smooth** |

The wheel handler only acts when the pointer is over the strip and the strip actually overflows, so it never steals scrolling from the page for no reason.

Nothing about the buttons changed: same size, same tooltips, same behaviour.

## State

| item | state |
|---|---|
| RE controls during PSO | **hidden**, restored for other titles |
| mod strip | **scrollable**, visible scrollbar, wheel scrolling |
| takes effect | **after a page reload (F5)** |
| worker | still hung on round 23's executing jobs - needs the restart |
