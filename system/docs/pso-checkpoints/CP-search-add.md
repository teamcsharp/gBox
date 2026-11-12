# The add panel: it opens now, it searches, and it lists your games

## Why nothing popped up

`openAdd` began with:

```js
if (!valid() || typeof io.launch !== 'function') return;
```

and `io.launch` only exists after the **host page** is reloaded. The tile renders from `pip-stream-picker.js` alone - so a cached page shows the tile with **no
launch behind it**, and the guard returned silently. **A click that does nothing, by design, for a reason invisible from the outside.**

## What it does now

**The launch is self-contained**: the component posts `@launch` itself through `io.api('/api/jobs', …)`, using `io.launch` only if the host happens to supply
one. No host reload needed for the button to work.

**A search bar at the top**, filtering **as you type**:

* matches **title** and **system** (the catalog's `platform`, or its first collection);
* the list is fetched once when the panel opens, so typing is instant;
* an empty search shows everything; no match says "No games match".

**Two groups in one list**, recent first:

1. **your recent launches** - from `/api/sessions` where `agent_owned === false`, deduped by game id, newest first, tagged `· recent`;
2. **the rest of the catalog**, so any title can be found;
3. **Merc titles dropped** by name from both.

Each row shows **title and system** on two lines. Clicking one starts it into the PiP and the status line says `Starting <game>…`.

## Verified

```
node check:               OK
search input:             True
dynamic filter:           True
does not require io.launch: True
falls back to io.api:     True
Merc dropped:             True
tile still there:         True
```

## One caveat worth stating

`/api/catalog` currently holds **six** entries. The search can only find what the catalog knows - so if a title you expect is missing from search, it is missing
from the catalog, not from the panel. That distinction matters before anyone concludes the search is broken.

## To use it

**Reload (F5)** → right-click in the PiP → **Streams** → click the **`+` tile** → type to filter, click to launch.
