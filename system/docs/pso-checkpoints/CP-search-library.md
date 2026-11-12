# The search finds any title now

## Why it said "No games match" for a game in the library

The panel filtered a **local snapshot**: one `/api/catalog` call, then `String.includes` over that page. The log showed **100** entries - a page, not the
library. **A title outside the page could never match**, and the search said so with confidence, which is worse than saying nothing at all.

## The fix

**The API has a ranked search** — `/api/catalog/best?q=<text>&limit=N`, which the agent tools use with the comment *"ranked: the real game first"*. Verified
directly:

```
phantasy       -> 1  Phantasy Star Online Episode I
phantasy star  -> 1  Phantasy Star Online Episode I
crazy taxi     -> 1  Crazy Taxi (USA)
```

The panel now:

* **asks the server as you type**, debounced 180 ms, and draws the ranked matches - so any title in the library is findable;
* **still draws local matches immediately**, so there is no wait for the common case;
* **orders the list by `last_played` descending** - **most recently opened first**, which was the other request; the operator's own sessions stay at the top, then
  everything else by recency;
* logs every server search and its count, so a miss is diagnosable rather than mysterious.

`node --check` passes; both changes verified present.

## Cover art: found, not yet wired

The catalog entry carries the art paths:

```json
"media": {
  "boxart": ["collections/Nintendo GameCube/boxart/Phantasy Star Online Episode I & II Plus (USA)"],
  "cartart": […], "snap": […], "wheel": […]
}
```

They are **relative paths into the library**, and I have **not** found the route that serves them - `/api/art?path=` and `/api/media/boxart?path=` both 404. So the
thumbnail row is **not** in this round rather than guessed at; the next step is to find how the library cards themselves display cover art and reuse it.

## Try it

**Ctrl+Shift+R**, click the `+` tile, type `phantasy` - it should find it now, and the opening list should be ordered by what you last played.
