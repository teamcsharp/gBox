# Round 290: the PiP toolbar is now game-aware - PSO gets PSO actions

## The operator's request, verbatim

*"whenever I'm playing PSO, I want options in the top to change the equipment that I have, to adjust the stats of my mag, to teleport different areas,
and bring up the live map viewer for controlling the bot on a 2d map"*

The screenshot showed why: the compact bar was hardcoded to **Resident Evil** actions - round replay, stage choices, primary weapon, **emergency
flashbang**, **grenade ring** and a "Flash" grenade-type label - while a Phantasy Star Online game was in the PiP.

## What was added

A **PSO action group** in the same toolbar, hidden unless the active game is PSO:

| button | what it does |
|---|---|
| **Equip** | `equip` on the live session with a weapon code (`000600` Handgun, `000700` Rifle, `000200` Sword are shown as examples) |
| **Mag** | `mag_set` with DEF / POW / DEX / MIND collected one at a time, then IQ 200 and synchro 120 |
| **Warp** | `floor_warp` with a floor number, and the reply's own `name` is reported (0 city, 1 Forest 1 ... 11 Dragon) |
| **Map** | opens the live 2D minimap viewer at `http://127.0.0.1:8802/` |

Each button calls the plane's **`pso_controls`** RPC on the current session, so it changes the real game rather than a mock, and failures are surfaced
with a toast instead of disappearing.

## How the game is detected

Not by an id that does not exist: the first pass read `COMPACT.gameId`, but the controller's state is `{on, aspect, returnMode, sid}` and the game's
identity arrives as `compactTitle` (set from `sessionTitle(session)`). The painter now tests that title for `phantasy star` / `episode i & ii`, so it
works whether the game arrives by id or by name:

```js
window.gboxPaintPso = () => {
  const pso = /phantasy\s*star|episode\s*i\s*&\s*ii/i.test(String(compactTitle || ''));
  ...
};
```

It is a **hoisted** `window.` function rather than a block-scoped `const`, because the bar is repainted from two places outside the branch that builds
it - `typeof` on a block-scoped `const` from outside its block throws instead of returning "undefined". It is repainted on every compact update and
again whenever the title is written, so switching games in the PiP switches the toolbar.

## What it looks like for PSO now

```
[title] [critique box] [Equip] [Mag] [Warp] [Map] [⚠ Flawed] [Full app]
```

and the Resident Evil controls - round replay, stage choices, primary weapon, flashbang, grenade ring, grenade type - are **hidden**, not greyed, because
they mean nothing in this game.

## To see it

The app renders this file, so **the window needs a reload** (Ctrl+R in the gBox window, or restarting the app) for the new toolbar to appear. The map
button also needs `minimap_live.py` running, which it is, on port 8802.

## State

| item | state |
|---|---|
| PiP toolbar | game-aware: PSO actions shown, RE actions hidden |
| buttons | Equip, Mag, Warp, Map - all wired to the live session |
| detection | by session title, repainted on every update |
| needs | an app window reload |
| minimap viewer | running on 8802 |
