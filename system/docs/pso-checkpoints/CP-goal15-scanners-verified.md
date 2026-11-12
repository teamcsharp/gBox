# Goal round 15: the scanner test passes - the bot's perception is verified

## The fix was in the test, not the bot

Last round's scanner test failed with zero entities. The instrumented run showed exactly why:

```
first actor pointer: 0x80501000
name pointer:        0x80508000
name:                b'\x00\x00\x00...'      <- 32 zero bytes
```

The fake memory stored each class name as a **15-byte block** and the scanner reads **32 bytes**; the fake's rule returned a block only when the whole read
fit, so it rejected the name and returned zeros. **The scanner correctly saw an empty class name and skipped every actor.** The bot was never wrong - the
test's fake memory was.

Two fixes, both in the test:

* names are stored **padded to 64 bytes**, which is how a real image behaves (a string sits inside a larger allocation);
* `read` returns **whatever part of a block it can and zero-fills the rest**, instead of refusing.

## Now verified

```
PASS one enemy parsed - got 1
PASS enemy class - TObjEneSandRappy
PASS enemy hp - 120
PASS enemy distance from (0,0) is 50 - 50.00
PASS one switch parsed - got 1
PASS switch class - TObjDoor
PASS switch state 224 - 224
PASS switch distance 12 - 12.00
PASS one exit parsed - got 1
PASS exit class - TObjVrPortal
PASS exit distance 80 - 80.00

all scanner checks passed
```

That establishes the perception layer end to end against a known-good image: the **entity table** at `0x8050D460`, the **class-name pointer at offset 0**,
the **position at `+0x38`**, **HP at `+0x32C`**, **door state at `+0x18C`**, and the derived distances. If any of those offsets were wrong, the live bot
would see no enemies, no switches and no exits and wander silently - which is precisely the failure that would have looked like "the bot is confused".

## One incidental confirmation

The exit entity's class is **`TObjVrPortal`**. The broad exit match added in round 12 - `Portal · Warp · Exit · Gate · Teleport · Vr · Stair` - contains
both `Vr` and `Portal`, so exit detection will match it when it appears. That match was written as a hedge because the class name was unknown; the test
image now uses the real-looking name and it matches.

## State

| item | state |
|---|---|
| scanner test | **passes, 11 checks** |
| perception layer | **verified**: table, name pointer, position, HP, state, distance |
| exit class | `TObjVrPortal`, matched by the existing word list |
| game | not running |
