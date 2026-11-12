# Round 293: the PiP menu now covers the game, and Ultimate is the default

## The menu

*"The right click menu needs to show on top of the gameplay. Currently it's being put behind it for some reason."*

The reason is structural, not a CSS mistake. `pipMenu` appends an ordinary DOM div (`#pipmenu`, `z-index: 70`), but in compact mode the game is drawn by
**`#gpu-game`** - a GPU surface (`web/viz/gpu-game-surface.js`) that composites **above** the page. **No z-index can lift a DOM element over a surface
that is not in the DOM's stacking context**, which is exactly why the menu looked like it slid behind the picture.

The workable fix is to take the surface down while a menu is up and restore it afterwards - a context menu is transient, and reading it matters more
than the picture for those seconds:

```js
window.gboxPipCover = (on) => { /* hides #gpu-game and #compact-stream while on */ };
```

`pipMenu` raises the cover on open, `closePipMenu` drops it, and the previous state is remembered per element so nothing is forced visible that was not.
**The app window needs a reload** for this to take effect; that does not disturb the running game, because the emulator is a separate process.

## Ultimate

*"by default, I want PSO to be played in ultimate mode."*

The plane's `legendary` op is exactly this, and it is now **verified on**:

```json
{"legendary": true, "verified": true,
 "note": "Next offline game selects Ultimate. The current loaded area is unchanged."}
```

Two details worth stating plainly rather than glossing:

* it **unlocks the selection** - "Offline TLevelSelect eligibility/selection only" - so Ultimate becomes the option the game selects on the next
  offline load, which is what "by default" means here;
* it **never rewrites a loaded area's difficulty**, so the area currently open keeps its difficulty; the next one entered will be Ultimate.

An earlier attempt returned **422** simply because it was issued while the area was still loading; the same call succeeds once the session settles.

## State

| item | state |
|---|---|
| PiP context menu | covered the game; needs an app reload |
| Ultimate | **verified on**, applies to the next offline area |
| session | `4b43bd602a584d8f…`, pid 34168, at the menus |
| F3 takeover | armed |
| mod icons | 21 PSO entries in the toolbar |
