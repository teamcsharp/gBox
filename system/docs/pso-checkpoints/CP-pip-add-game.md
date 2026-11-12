# The PiP Streams panel can start a game

## What was asked

*"the right click option of PiP Mode allow me to start games through an addition indicator on this … it'll offer me a drop down list of my recently played games,
allowing me to start and initialize games from PiP Mode. Basically the application is loading in pip mode before I'm able to even start the game."*

## What was built

The Streams panel is `pip-stream-picker.js`. It draws a carousel of **running** games - every card is a session already live - so there was no way to start
anything from the PiP.

**Four additions, all verified present:**

| piece | where |
|---|---|
| **a `+` button** in the heading | `html()` |
| **the recent-games dropdown** | `openAdd()` in `mount()` |
| **click routing** | the first line of `async function click` |
| **the launch itself** | `io.launch(game)`, supplied by the host |

**How it behaves:**

* click **`+`** → a menu appears under it headed *"Recently played"*;
* the list comes from `GET /api/catalog`, sorted by `last_played`, **12 most recent**;
* each row shows the game's title, platform, and that it was played;
* choosing one calls the host's `launch`, which posts `@launch` with the catalog entry - the same tool the app's own Play button uses;
* the status line under the carousel says **"Starting <game>…"** or names the failure;
* **Escape or a click outside** dismisses it, reusing the panel's existing menu habits.

`node --check` passes on the picker.

## Why `@launch` and not `launch_game`

`LaunchIn` requires a **full `CatalogEntry`** in `game` (established in round 29 when `launch_game` refused a bare id), and `@launch` is the endpoint the app itself
uses for a play action. The picker already has the catalog row, so it passes exactly what the server expects.

## To use it

**Reload the app (F5).** Right-click in the PiP → **Streams** → the **`+`** beside the carousel → pick a game.

That starts it and initialises it **from inside the PiP**, which is what the request was - the app already being in PiP mode is no longer a dead end.
