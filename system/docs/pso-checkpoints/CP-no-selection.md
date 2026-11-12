# Text selection is off

## The request, and the screenshot

*"turn off text selection in the application. There's no reason to select text. I hate that. Turn off the ability to do text selection via click and drag."*

Your screenshot showed exactly that: the Streams panel with **its text highlighted blue** from a drag that was meant to click it.

## What was already there, and what was missing

The app had disabled selection in **three narrow places** - the titlebar during a drag, `body.chatresizing *`, and `#remote-pip img` - which shows the intent
existed but was never general.

## The change

The **global reset** now carries it:

```css
* { box-sizing:border-box; -webkit-user-select:none; user-select:none; }
```

and the few places where selection is legitimate opt back in:

```css
input, textarea, select, [contenteditable=""], [contenteditable="true"], .selectable,
input *, textarea * { -webkit-user-select:text; user-select:text; }
```

So the **search box in the new panel**, the **chat composer**, and any future text field keep working normally - copy, paste, select-all - and **everything else
stops highlighting when you drag.**

Verified at lines 13 and 15-16.

## What this fixes for you

* dragging to move or click no longer leaves text highlighted;
* clicking a panel's text no longer selects it;
* the blue sweep across the Streams panel cannot happen.

## Reload

**Ctrl+Shift+R**.

Committed alongside the search fix, so one reload brings both: the search that finds any title, and no more accidental selection.
