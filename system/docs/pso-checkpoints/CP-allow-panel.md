# The panel was hidden by the compact-mode CSS rule

## The rule

`index.html:1312` is a chain of `:not(...)` selectors naming every element allowed to show while the PiP is active:

```css
body.gbox-compact > :not(.pso-review-window):not(.game-analysis): … :not(#pipmenu)
  :not(.coach-menu):not(.coach-sub):not(.merc-weapon-menu):not(.merc-round-menu)
  :not(.flash-shortcut-menu):not(.ring-kind-menu) { display:none !important }
```

**Every other direct child of `<body>` is `display:none !important`.**

Notice what is in that list: **every context menu** - `#pipmenu`, `.coach-menu`, `.merc-weapon-menu`, `.flash-shortcut-menu`, `.ring-kind-menu` - because
each one had to be added when it was built.

**`.pip-stream-menu` was not in it.** And the add-game panel is appended to `document.body` with exactly that class.

## So this is what actually happened

* the tile renders (inside the panel, which is allowed);
* the click fires, `openAdd` runs, the panel is created, **100 rows are drawn**, appended to the body - **all visible in the log**;
* `body.gbox-compact > :not(…) { display:none !important }` **hides it**, from a stylesheet half a file away.

That is why every log line said the work succeeded, why nothing appeared, and why raising the GPU cover changed nothing - **the surface was never the obstacle.**

## The fix

```css
:not(#pipmenu):not(.pip-stream-menu)
```

One selector, in the same place every other menu was added.

## What this cost, and why

Four rounds on this panel. The log - which I should have written first - proved the panel was built and populated, which eliminated logic and pointed at
rendering. From there the remaining candidate was the compositing surface, which was wrong; **the honest gap is that I never inspected the computed style**, and
that would have shown `display:none` immediately.

## Try it

**Ctrl+Shift+R**, then click the `+` tile. It should now appear over the dimmed game with the search box focused - and the recent list should finally populate,
since that reads the sessions the filter was silently discarding.
