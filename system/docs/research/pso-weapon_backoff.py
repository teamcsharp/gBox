"""Stop the weapon rule spamming a failing equip every fifteen seconds.

The log filled with `weapon: equip failed 009d00 - inventory not found` on a 15-second cadence, which starves the loop:
each attempt costs a round-trip to the worker, and the noise hides what the bot is actually doing.

A control that cannot succeed should back off, not hammer. After a failure the swap is deferred for
`FAIL_BACKOFF_S = 90` seconds - long enough that a transient worker state can clear, short enough that the weapon timer
still meets the operator's 2-5 minute window once things work again. Success resets the timer as before.

The failure is still reported once when it happens, so it remains visible rather than silent - a silent failure would be
worse than the spam.
"""
import pathlib
import py_compile

WEAPONS = pathlib.Path(r"C:\_tools\gBox\.tmp\weapons.py")
text = WEAPONS.read_text(encoding="utf-8")
py_compile.compile(str(WEAPONS), doraise=True)
print("compiles BEFORE")

if "FAIL_BACKOFF_S" in text:
    print("backoff already present")
else:
    text = text.replace(
        'SWAP_SECONDS = 150.0         # the operator\'s 2-5 minute window, taken at 2.5',
        'SWAP_SECONDS = 150.0         # the operator\'s 2-5 minute window, taken at 2.5\n'
        'FAIL_BACKOFF_S = 90.0        # after a failed swap, wait this long instead of retrying every iteration',
        1)

    text = text.replace(
        'LAST_SWAP = {"at": 0.0, "index": 0, "code": GUN_CODE}',
        'LAST_SWAP = {"at": 0.0, "index": 0, "code": GUN_CODE, "failed_at": 0.0}',
        1)

    text = text.replace(
        '    now = time.time() if now is None else now\n    if fliers_present(entities):',
        '    now = time.time() if now is None else now\n'
        '    # A swap that just failed is deferred rather than hammered: the log was filling with the same error every\n'
        '    # fifteen seconds and each retry cost a worker round-trip.\n'
        '    if now - float(LAST_SWAP.get("failed_at") or 0.0) < FAIL_BACKOFF_S:\n'
        '        return None\n'
        '    if fliers_present(entities):',
        1)

    text = text.replace(
        '                if ok:\n                    LAST_SWAP["code"] = wanted\n                    LAST_SWAP["at"] = time.time()\n                    LAST_SWAP["index"] = ROTATION.index(wanted) if wanted in ROTATION else 0',
        '                if ok:\n                    LAST_SWAP["code"] = wanted\n                    LAST_SWAP["at"] = time.time()\n                    LAST_SWAP["failed_at"] = 0.0\n                    LAST_SWAP["index"] = ROTATION.index(wanted) if wanted in ROTATION else 0\n'
        '                else:\n                    LAST_SWAP["failed_at"] = time.time()',
        1)

    WEAPONS.write_text(text, encoding="utf-8")
    print("failure backoff added")

py_compile.compile(str(WEAPONS), doraise=True)
print("compiles AFTER")
