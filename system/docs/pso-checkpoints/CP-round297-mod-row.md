# Round 297: the mod row fits, and every click says what happened

## Two complaints, both real

*"Make sure all of these buttons on the panel are formatted properly and work ... I'm clicking them and they're not doing shit. and make sure the icons fit
on the row. They seem cramped"*

### Cramped

The buttons had **no sizing rules at all** - twenty-one of them were squeezed into whatever space was left, with glyphs overlapping (the screenshot
shows several mangled marks where two shapes collide). They now have:

* a fixed **22x22** box each with **14x14** icons;
* a **3px gap** and a scrollable row capped at 42% of the bar width, so they space out instead of crushing together;
* a **hover** state and a **lit border** while a toggle is on (`data-on="1"`).

### Clicks doing nothing

Three separate hazards, all removed:

1. **A per-button `onclick` set inside a builder that runs once.** If anything in the handler threw before the RPC - a missing helper, a stale element -
   the click died silently. It is now **one delegated listener** on the container, which survives rebuilds and cannot be lost.
2. **Ordering.** `gboxPsoRpc` and `gboxAsk` are defined *after* the point where the buttons are built, so a click in between found them missing. The
   delegated handler now resolves them **at click time**, not at build time.
3. **Silence.** Every failure is wrapped in a `try/catch` that raises a **toast** naming the failure - "the dialog is not loaded yet", "mod failed: ..." -
   so a dead button now tells you why instead of doing nothing.

## To get it now

**Press F5.** That is the app's existing client-refresh key, and it routes to `recoverAndRefresh()` - verified present in the page. It reloads with
these changes.

**Ctrl+R** does the same thing, but its binding is new in the main process, so it starts working after the next app restart.

## State

| item | state |
|---|---|
| mod row | **22x22 buttons, 14x14 icons, 3px gap, scrolls** |
| clicks | delegated, errors surfaced as toasts |
| get it now | **F5** (Ctrl+R after a restart) |
| game | live in Forest 1, HP 40/40, Lv 1 |
