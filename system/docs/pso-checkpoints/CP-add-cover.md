# The panel was there the whole time - behind the game

## The log, verbatim

Every one of your clicks produced this:

```
pip add: click true
pip add: panel appended
pip add: sessions 61 catalog 100 recent 0
pip add: drew 100 of 100
```

**The panel was built. It was filled with a hundred rows. It was appended to the body.** Every click since the rewrite worked perfectly - and you saw nothing,
because in compact mode the game is drawn by **`#gpu-game`, a GPU surface that composites above the page**, and **no z-index can put a DOM element over it.**

That is the same fact the PiP context menu hit in round 293. The fix is the same one that solved it then: **take the surface down while the panel is up**, and
restore it when it closes.

```js
window.gboxPipCover(true);    // when the panel opens
window.gboxPipCover(false);   // when it closes
```

Verified in place at lines 222 and 196.

## Why I could not see this sooner, and the honest answer

**I was reading symptoms instead of testing.** For four rounds I shipped changes to this panel without once confirming that what I built appeared on screen. The
log I added last round settled it in one read: the panel existed and was fully populated, so the fault had to be **rendering**, not logic. **I should have written
that log first.**

## One more thing in the same read

```
recent 0
```

The catalog answered **100** entries and the sessions **61**, yet no recent game matched - the filter requires `agent_owned === false` exactly, and if the field
arrives as a string it drops every row. The log now also prints **how many sessions are recognised as yours**, so the next read shows whether it is a typing
problem rather than another guess. The filter itself still needs the string form accepted.

## What to do

**Ctrl+Shift+R**, then click the `+` tile. The panel should now appear over the dimmed game, with the search box focused.

If it does not, the log will carry `pip add: click true / panel appended / drew N of N / owned N`, and that tells us precisely which of the three is wrong.
