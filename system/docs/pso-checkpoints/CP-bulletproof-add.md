# The panel had a gate that returned silently; now nothing can

## What the log told me

After the operator's restart and Ctrl+Shift+R, the log had **no `pip-stream-picker` exception since 11:34** - the ones recorded there predate the fix - and
nothing new. So the click reaches the handler, and `openAdd` **returns without doing anything and without throwing**. Only two paths do that:

```js
const button = event.target.closest?.('[data-stream-add]');
if (!button || !valid()) return;
```

## The wrong gate

`valid()` is the host's staleness check:

```js
valid: () => m.opening === opening && S?.apiUrl === opening.origin
```

It asks *"is the session this menu belongs to still current?"* - the right question for **switching a stream**, and the **wrong one for launching a game**, which
does not care which session the menu belongs to. It was returning false, and taking the whole feature with it, silently.

## The rewrite

1. **the `valid()` gate is gone** from the entry - launching is not conditional on the menu's session;
2. **every step logs** - `pip add: click`, `pip add: panel appended`, `pip add: sessions N catalog N recent N`, `pip add: drew N of N`, and a launch failure. The
   webview's console lands in `app-console.log`, so the next attempt is **verifiable from the filesystem**, not from guesswork;
3. **the API is self-contained**: `io.api` if the host passed it, else `globalThis.gbox.api` directly, unwrapping `{ok, data, error}`;
4. **the panel renders immediately** with "Loading your games…", so a slow or failed read still leaves a panel with a search box instead of a click that appears to
   do nothing.

`node --check` passes; all four properties verified in the source.

## What to do

**Ctrl+Shift+R**, then click the `+` tile.

Whatever happens, I will know: the log will contain `pip add: click true` and the following lines, or its absence will prove the click never reaches the handler.

## Why this shape, not another guess

The last four rounds guessed at this panel. This version makes the ambiguity impossible to sustain - **the failure has nowhere to hide**, because every branch
either logs or throws into a file I can read.
