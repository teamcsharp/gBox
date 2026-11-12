# Round 294: the mod buttons now show a real dialog

## The report

*"when I click on these buttons, I need a pop-up that gives me the ability to choose the specifics of what these are doing. Apparently it's not showing."*

## The cause, and it was not the button wiring

**Electron's renderer does not implement `window.prompt`.** It returns without showing anything. Every `askFor()` in the toolbar called `prompt()`, so the
dialog never appeared and the op was either sent with nulls or not sent at all - the buttons looked dead exactly as described.

That also explains why the earlier four-button version (Equip / Mag / Warp / Map) never asked for a weapon code or mag stats: it was calling a function
the host platform has disabled.

## What replaced it

A real DOM dialog, created on demand:

```js
window.gboxAsk(fields) -> Promise<values | null>
```

* one labelled input per field, `type=number` for numeric values, each validated before it is accepted;
* **OK / Cancel** buttons, **Enter** to send, **Escape** to cancel, and a click on the backdrop cancels;
* it is listed in the compact-mode allow-list, because the PiP hides everything outside that list;
* it takes the **GPU game surface down while it is open** - the same reason the context menu needed it: a DOM element cannot out-stack a composite
  surface.

`askFor` now **awaits** it, and the caller was changed to `await` as well, which matters: without the await the op would have been sent before the user
answered.

## What the buttons do now

Clicking **Equip** asks for a weapon code; **Mag** asks for DEF, POW, DEX and MIND; **Warp** asks which floor; **Give** asks code and count; **Set a
stat** asks which stat and its value - and so on for the 21 entries. Toggles (Scape Doll, crit, always-hit, walk-through, Ultimate, drops) flip on click
without asking anything, and **Map** opens the viewer directly.

## State

| item | state |
|---|---|
| mod dialog | **real DOM dialog**, awaits the values |
| why it was missing | **Electron disables `window.prompt`** |
| needs | an app window reload (the game keeps running - separate process) |
| Ultimate | verified on; applies to the next offline area |
| session | `4b43bd602a584d8f…`, in Pioneer 2, Lv 1, HP 40/40 |
