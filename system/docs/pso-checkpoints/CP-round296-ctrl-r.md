# Round 296: Ctrl+R now updates and reloads the app

## The request

*"make it where ctrl + R fixes and reloads the latest version of the app"*

## What it does

Ctrl+R is routed to the **same path F5 already uses**, rather than reimplemented, because that path does the whole job:

```
Ctrl+R  ->  hotkey "client-refresh"
        ->  this checkout is fast-forwarded to GitHub's main (app-update.cjs)
        ->  win.webContents.reloadIgnoringCache()
```

A bare `location.reload()` would have been the wrong answer twice over: it would serve **stale files from the cache**, and it would **not** run the
update step - so a new `game-mods.js` or a new page would not reliably appear.

The binding sits in the existing `before-input-event` handler with the other guarded keys, so it keeps their exclusions: windows owned by the
Mercenaries viewer or the task dashboard keep their own keys, and Ctrl+Alt+R is untouched.

```js
else if (input.control && !input.alt && String(input.key).toLowerCase() === "r") {
  win.webContents.send("hotkey", "client-refresh"); ev.preventDefault(); return;
}
```

`main.js` passes `node --check`.

## One thing to know

**This binding lives in the Electron main process, so it needs one app restart to take effect** - a page reload cannot install a main-process
shortcut. That same restart is also what the rest of this round's UI work needs:

* the **real mod dialog** (the one that was missing because Electron disables `window.prompt`);
* the **game-aware toolbar** with 21 PSO entries and the **Area** picker;
* the **context menu covering the game** while it is open.

So: **restart the app once**, and from then on **Ctrl+R** picks up every future change in one keystroke.

## State

| item | state |
|---|---|
| Ctrl+R | bound to `client-refresh` (update + ignore-cache reload) |
| takes effect | after one app restart |
| same restart picks up | mod dialog, mod icons, area picker, menu cover |
| game | unaffected - the emulator is a separate process |
