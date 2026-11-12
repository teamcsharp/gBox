# The Streams menu was showing a loading sentence instead of itself

## The cause, in one line

```js
root.innerHTML = '<p class="pip-stream-empty" role="status">Loading streams…</p>';
```

Until `refresh()` finished, **that sentence was the entire panel** - no heading, no carousel, no `+` tile. And `refresh()` awaits `io.read()` (the session list)
before it draws anything, then starts a preview request per stream. **The ten seconds you saw was that wait rendered in full.**

## The fix

Draw the real panel **immediately**, with no entries:

```js
root.innerHTML = html([], io.current ? io.current() : '', io.title, !!io.broadcast);
```

`html([], …)` already produces the heading, the carousel **with the `+` tile**, and "No active streams. Waiting for a game to be ready." So the menu is **usable
the moment it opens** - you can click `+` or a running card - and `refresh()` replaces the carousel when the data lands.

**The data path is untouched.** Only what is on screen while it runs changed.

## Verified

```
no loading placeholder:  True
renders html at once:    True
refresh still fills:     True
node check:              OK
```

## What this means

* right-click → the panel is **there**, with the `+` tile, without waiting;
* the running streams appear a moment later, as a **replacement** rather than a wall;
* the add-game panel and the recent strip were already fetching in parallel and are unaffected.

## To use it

**Ctrl+Shift+R**, then right-click.

Committed alongside the prompt removal, so this reload also confirms whether the earlier unresponsiveness is gone.
