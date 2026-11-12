# The menu dismissed itself on the click that opened it

## The log named it, once per click

```
11:34:00.170 [window:error] Uncaught (in promise) TypeError: Cannot read properties of null (reading 'querySelector')  (pip-stream-picker.js:245)
```

**Four times in one second** - one per press. Line 245 is `addMenu.querySelector('[data-add-previous]')`, so `addMenu` was null by the time `openAdd` got there.

## The cause, and it was mine

```js
function onAddAway(event) { if (!addMenu || !addMenu.contains(event.target)) dismissAdd(); }
document.addEventListener('pointerdown', onAddAway, true);
```

A press on the `+` tile fires **`pointerdown` before `click`**. After the first attempt a menu is always open, so on every subsequent press:

1. `pointerdown` on the tile → `onAddAway` → the target is *outside* the menu → **`dismissAdd()` → `addMenu = null`**
2. `click` → `openAdd` → builds the HTML, then reaches `addMenu.querySelector` → **TypeError**

**The panel worked exactly once and then killed itself on every later click.** That is why it looked completely dead.

## The fix

**Two narrow changes:**

1. **`onAddAway` ignores presses on the tile** - that press is the one meant to *open* the menu, not dismiss it:
   ```js
   if (event.target.closest?.('[data-stream-add]')) return;
   ```
2. **`openAdd` re-checks `addMenu` after its `await`s** before touching it, so a concurrent dismissal can never produce a TypeError again.

`node --check` passes, and all three guards are verified present.

## What this says about the earlier attempts

Two previous rounds "fixed" this panel without once looking at the error. **The app had been recording the exception all along**, in `app-console.log`, because the
webview's console is captured there - the log I built in round 43 for exactly this reason. **I should have read it before the second attempt, not the fourth.**

## Reload

**Ctrl+Shift+R**, then right-click in the PiP → **Streams** → **`+` tile**. If anything still fails, **it will throw into the same log** and I will have the line
number rather than a guess.
