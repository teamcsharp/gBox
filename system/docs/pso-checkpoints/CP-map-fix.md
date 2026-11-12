# The Map button: `root` was undefined, and the viewer is live

## The bug in the screenshot

The toast said exactly what was wrong:

```
mod failed: root is not defined
```

The delegated handler caught the exception (so the error surface works) and the fault is one line - opening a mod's panel called `root.open(...)`, where `root`
was a name from a helper's closure that does not exist in the compact bar's scope. Changed to `window.open`, with a toast if the pop-up is blocked.

## The live map viewer

| piece | state |
|---|---|
| `minimap_live.py` | **running** (two processes) |
| `http://127.0.0.1:8802/` | **HTTP 200**, serves the viewer |
| `/api/state` | **HTTP 200**, 265 bytes of live state |
| Map mod entry | `open: 'http://127.0.0.1:8802/'` |
| open call | **`window.open`** (was `root.open`) |

So pressing the map icon in the compact bar opens the viewer in its own window, showing the live map for the running game - which is what it was built for:
game-aware SVG, radar fallback, `/api/order` and `/api/target` for clicking the map to order the bot, `/api/transform` for the player's row.

## To see it

**Press F5** to reload the client, then click the map icon.

## One thing the toast also proves

**The error surface I added works.** A failure in a mod click now says what failed instead of doing nothing - which is how this one was diagnosed from a
screenshot rather than by guessing.
