# The PiP add-game tile, listing only the operator's own launches

## What was asked, twice

1. *"I want the add button to be represented as a viewing tile that I'm able to click."*
2. *"one of the first options it should ask me is to launch the previous game. Always offer a list of the most recently launched titles for me to launch that I
   manually launch. Don't list Mercenary titles from Merc mode."*

## The tile

The `+` is no longer a button in the heading - it is a **card in the carousel**, styled like a stream entry:

```html
<button class="pip-stream-card pip-stream-add-tile" data-stream-add>
  <span class="pip-stream-picture" style="…font-size:34px">+</span>
  <strong>Add game</strong><span>Recent launches</span>
</button>
```

It sits after the running streams, carries `data-stream-add` so the existing click routing reaches it, and reads as a tile rather than a glyph.

## The list

Sourced from **`/api/sessions`**, not the catalog - because a session records `agent_owned`, which is exactly "did I launch this myself":

| step | rule |
|---|---|
| 1 | fetch sessions and catalog together |
| 2 | keep **`agent_owned === false`** only |
| 3 | **dedupe by game_id**, newest first |
| 4 | **drop any `/mercenar/i` title** |
| 5 | the **first row is "Launch the previous game"** with that title, highlighted |
| 6 | then the recent operator-launched titles, up to 12 |

The catalog is used **only** to turn a `game_id` into the full entry `@launch` requires.

**The data backs this up**: the operator's seven operator-owned sessions are **all PSO**, while the catalog separately holds *"Resident Evil: The Mercenaries 3D"* -
a Merc title they never launched. Sourcing from sessions excludes it by construction, and the explicit name filter is the second guard.

## Verified

```
tile in carousel:         True
previous row built:       True
previous row wired:       True
header says yours:        True   ("Your recent launches")
operator sessions only:   True
Merc titles dropped:      True
launches via io.launch:   True
node check:               OK
```

## To use it

**Reload (F5)**, right-click in the PiP → **Streams** → click the **`+` tile** → **"Launch the previous game"** is the first row, then your recent launches.
