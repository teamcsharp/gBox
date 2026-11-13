# The operator's notes channel is live

## Where to type

**`D:\gBox\pso-ds\operator-notes.txt`**

Whatever is in that file is read on the **next loop iteration**, logged verbatim, classified, and acted on. Verified twice - once directly and once in the running loop:

```
[22:55:33]   NOTE from operator: kill the wolves in this room
[22:55:33]   note internalized: prioritising enemies
```

## What the note does

| the note says | the bot does |
|---|---|
| `stop` / `halt` / `wait` / `hold` | stands down until told otherwise |
| `go` / `resume` / `play` / `continue` | resumes |
| `kill` / `attack` / `fight` / `enemy` | prioritises enemies |
| `box` / `loot` / `rare` / `item` / `drop` | prioritises containers and rares |
| `door` / `gate` / `warp` / `exit` / `next room` / `level` | prioritises the way forward |
| `goto X Z` | walks to that coordinate |
| anything else | logged as received and kept as context - never silently dropped |

Only the **newest** line acts, and re-writing the same text does nothing, so a note is not re-applied every iteration. The file's content is treated as the full current instruction set.

## Two encoding bugs found and fixed on the way

The first attempt **silently ignored the note**, and the reason is worth recording because it is exactly the sort of thing that would have looked like "the bot isn't listening":

```
UnicodeEncodeError: 'charmap' codec can't encode character '\ufeff' in position 33
```

`Set-Content -Encoding UTF8` writes a **BOM**; `read_text(encoding="utf-8")` handed it to `print`; the console here is **cp1252**, which raised and aborted `read_notes` **before it could act**. So:

* the file is now read as **`utf-8-sig`**, which strips a leading BOM whatever wrote it;
* **`log()` is ASCII-safe** - any unprintable character becomes `?` rather than an exception.

That second one matters beyond notes: an entity class or a note in another language could otherwise take the whole loop down over one character.

## Honest current blocker

The character is **wedged at `(76, 16, 407)`** and this time the four same-height relocations are **not** freeing it - the log shows all four offsets and the position unchanged between attempts. That is different from the run an hour ago where the same mechanism freed it by **311.4 units**, so it is not the relocation being wrong in general; something about this spot is different (possibly a spot where the written position is immediately corrected back).

The consequence is the same as before: while wedged, `played 120s, 3.0 travel steps` - almost nothing else can happen.

## What is running

* **`endless.py`** - autoplay with the notes channel, weapons, Ultimate-when-strong-enough, rares, boxes/traps, the reticle rule, door keys, RAM door unlocking, and the relocation unstuck.
* **`controller_relay.py`** - the operator's controller injected through SDL, with the bot standing down while they play.
* **`operator-notes.txt`** - the chat channel.

## Next

**A real input in the UI** - a text box in the gBox window that writes `operator-notes.txt`, so the operator does not have to touch a file by hand. The plumbing behind it now exists and is proven; what is missing is the control.
