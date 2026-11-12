# Search ordered by what you actually launched, and those titles are highlighted

## The request, and why it matters

*"When I'm searching for a game, list the games by which title I recently launched … and do a special highlight around an item that has actually been launched
recently, so I don't launch something obscure by accident."*

Your screenshot is the argument: typing `phan` gives **Phantasy Star Online (USA)** — a Dreamcast title — ahead of the GameCube one you play daily, with **Phantom
2040 (USA)** sitting right below it, one misclick away.

## What the search does now

1. **Sorted by `last_played`, descending** — anything you have ever launched comes **before** anything you have not, newest first. Never-launched titles keep
   the server's relevance order **below** them, so nothing disappears.
2. **Launched titles are framed** — a blue border and tinted background. Your own sessions get the stronger accent (`#1b2b45` with a `#4a7fd4` border), other
   launched titles a quieter one (`#182130` with `#35507a`).
3. **Each launched row is dated** — `launched today`, `launched yesterday`, `launched 5d ago` — so "recent" is a fact on screen rather than a feeling.
4. **Your own sessions read `recent`** in the accent colour, because those are certain launches rather than catalog timestamps.

Never-launched rows stay plain and transparent, so the difference between "I have played this" and "this merely matched" is visible at a glance.

## Verified

```
server results sorted by last_played:  True
launched titles highlighted:           True
dated:                                 True
node check:                            OK
```

## Try it

**Ctrl+Shift+R**, click the `+` tile, type `phan`. The GameCube Phantasy Star should now sit above the Dreamcast ones, framed — and Phantom 2040 should be
visibly plain beneath it.

## Still open

**Cover-art thumbnails.** The paths are in the catalog (`media.boxart`), the serving route is not yet found, and I am not inventing one. That is the next
concrete piece of this panel.
