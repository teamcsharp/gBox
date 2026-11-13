"""Change the equipment every two minutes. Always.

The operator, twice and emphatically: *"Always change the equipment on the character every two minutes. Always. Always."*

The timer was 150 seconds (2.5 minutes) and a failed swap deferred for 90 seconds, so in a bad run the weapon could go
unchanged for four minutes or more - and "always" is not satisfied by a best-effort timer that a failure can silence.

So:

* `SWAP_SECONDS = 120.0` - exactly two minutes;
* the failure backoff drops to `FAIL_BACKOFF_S = 15.0` - still enough to avoid hammering the worker every frame, short
  enough that a swap is never skipped for long. The rotation must keep happening even when equipping is failing, because
  the operator wants the equipment to change, not the equip *attempt* to be hidden.

The flier rule still outranks the timer, as it must: melee cannot damage an airborne enemy at all, so a gun is required
regardless of where the rotation happens to be.
"""
import pathlib
import py_compile

WEAPONS = pathlib.Path(r"C:\_tools\gBox\.tmp\weapons.py")
text = WEAPONS.read_text(encoding="utf-8")
py_compile.compile(str(WEAPONS), doraise=True)
print("compiles BEFORE")

swaps = [
    ("SWAP_SECONDS = 150.0         # the operator's 2-5 minute window, taken at 2.5",
     "SWAP_SECONDS = 120.0         # exactly two minutes - the operator: change the equipment every two minutes, always"),
    ("FAIL_BACKOFF_S = 90.0        # after a failed swap, wait this long instead of retrying every iteration",
     "FAIL_BACKOFF_S = 15.0        # short, so a swap is never skipped for long: the rotation must keep happening"),
]
for old, new in swaps:
    count = text.count(old)
    print("anchor count:", count, "|", old.split("=")[0].strip())
    if count != 1:
        raise SystemExit("anchor not unique")
    text = text.replace(old, new, 1)

WEAPONS.write_text(text, encoding="utf-8")
py_compile.compile(str(WEAPONS), doraise=True)
print("compiles AFTER")
print()
print("SWAP_SECONDS is now 120 seconds and the failure backoff 15")
