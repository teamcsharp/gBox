# The bot can press buttons - proven on screen

## What changed

Three things had to be true at once, and now they are:

1. **the worker registers** - restoring `main.js` from `ec73b7a6^` (before my console patch) fixed it; my `CONSOLE_FILE`/`appendFileSync`/`console.log` wrapper was breaking
   the Electron main process's worker handshake;
2. **a virtual pad exists** - `GBOX_DOLPHIN_VPAD=on`; `XInput` slot 0 reads `lx=0 ly=0`, `GCPadNew.ini` binds `Device = XInput/0`, `Always Connected = True`;
3. **the screen is readable** - `GET /api/sessions/{sid}/mjpeg` is the viewer stream (`multipart/x-mixed-replace; boundary=f`); one part is a real JPEG.

## Proof the presses arrive

**START opened PSO's main menu** - ONLINE GAME / OFFLINE GAME / OPTIONS / WEBSITE - captured and read directly:

```
before: 81601 bytes  (PSO title, no menu)
press START (session_op send_input) -> succeeded
after:  83655 bytes  (main menu visible)
```

**DOWN moved the menu highlight** - the cursor left ONLINE GAME.

So `session_op` with `op: "send_input"` **does** reach the game through the virtual pad. The bot has an input path.

## Why every earlier judgement was wrong

Earlier rounds judged input by **memory**: `floor` at `0x805D5FC0`, the player pointer at `0x8050EA10`, and a game counter at `0x805D53A4`. **None of those move on a menu**, so
"the game did not advance" was a wrong conclusion drawn from the wrong evidence - the screen was changing the whole time and nothing was looking at it.

That is exactly why the frame route mattered more than another memory read.

## What is still unreliable

Presses land **inconsistently**. A single DOWN moved the cursor; two short DOWNs afterwards did not, and the highlight stayed on WEBSITE. Each press is currently two jobs (down,
then up) with a pause between them, so the emulator sees a press whose duration depends on job latency - and a missed release would leave the pad held.

**The fix**: one job that carries the down and up together, with a tuned hold, and a frame check after each press to confirm the cursor actually moved. That is the next
concrete step, and now it is verifiable on screen rather than by inference.

## The right-click menu

Two separate behaviours, both from `index.html:675`:

* the document-level context menu **excludes the game screen** - `e.target.closest(".tchip, .card[data-gid], [data-lh-game], #photocraft-popup, input, textarea, select,
  #scr, #nativeslot, .gbox-gpu-video, img…")` - so **right-clicking the game does nothing at all**;
* everywhere else it opens the **"report a problem about this option"** form (`#issuemenu`) with a text `<input>`, **which takes focus** - so typing lands in that box
  instead of reaching the game.

That matches both halves of the report: it "doesn't work" on the game, and it "reacts to typing" when it does open.
