"""Auto-unlock any door the character approaches, always, through the stage-flag bytes.

The operator, unambiguously:

> *"Just flip the flag and auto unlock any door I walk up to. Just period. In the game, forever. Anytime I play this game,
> always just automatically flip the switch and just unlock the door when my character approaches it. Find the RAM byte
> flag in the game and flip it for any and every door that I ever approach."*

That is a proximity rule with no conditions, and the pieces already exist: `unlock_floor(pad)` writes the floor's stage
flags (base `0x80515CC8`, length from `0x805D5FC0`, 32 bytes per group) and the profile names every door class -
`TObjDoor`, `TObjLazerFenceNorm`, `TOBarrierEnergy01`. What was missing was running it *when a door is near* rather than
on a timer, and running it *even while the operator is playing*.

So this runs **before the operator stand-down check**, which is what makes it "forever, anytime I play":

* every frame, find door entities within `DOOR_RADIUS = 45` units of the character;
* if any are in range and the unlock has not run in the last `UNLOCK_EVERY_S = 2.5` seconds, call `unlock_floor`;
* the cooldown exists because each memory write is a worker job and a door does not need re-opening 30 times a second -
  but it re-arms immediately when the floor changes, so a new area is unlocked on the first frame.

Nothing here is conditional on the bot being "in charge": if the operator has the pad, the doors still open.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

# 1. module state
if "AUTO_UNLOCK" not in text:
    anchor = "LIVENESS = {"
    if text.count(anchor) != 1:
        raise SystemExit("LIVENESS anchor count: %d" % text.count(anchor))
    text = text.replace(
        anchor,
        'AUTO_UNLOCK = {"at": 0.0, "floor": None}   # proximity door unlocking: last run and the floor it was for\n'
        + anchor, 1)
    print("AUTO_UNLOCK state added")

# 2. the rule, placed before the operator stand-down so it runs whoever is playing
OLD = '''        operator_active = False
        if OPERATOR_PLAYING.exists():'''
NEW = '''        # AUTO-UNLOCK ANY DOOR THE CHARACTER APPROACHES - running BEFORE the stand-down check, so it applies "forever,
        # anytime", including while the operator is driving. Ram writes only; no vision, no walking, no switches.
        try:
            _au = state(pad)
            _aup = _au.get("player") or {}
            _aux, _auz = float(_aup.get("x") or 0), float(_aup.get("z") or 0)
            _aufloor = _aup.get("room")
            _door_near = any(
                str(e.get("class")) in ("TObjDoor", "TObjLazerFenceNorm", "TOBarrierEnergy01",
                                        "TObjLazerFence", "TLazerFenceSw", "TObjDoorKey")
                and e.get("x") is not None and e.get("z") is not None
                and math.hypot(float(e.get("x") or 0) - _aux, float(e.get("z") or 0) - _auz) <= 45.0
                for e in (_au.get("entities") or []))
            if _aufloor != AUTO_UNLOCK["floor"]:
                AUTO_UNLOCK["floor"] = _aufloor
                AUTO_UNLOCK["at"] = 0.0                      # new area: unlock on the first frame
            if _door_near and (time.time() - float(AUTO_UNLOCK["at"] or 0)) > 2.5:
                AUTO_UNLOCK["at"] = time.time()
                log(f"  AUTO-UNLOCK: door within 45 units - flipping floor {_aufloor} stage flags")
                unlock_floor(pad)
        except Exception:                                    # noqa: BLE001 - never let this stop the loop
            pass

        operator_active = False
        if OPERATOR_PLAYING.exists():'''
count = text.count(OLD)
print("stand-down anchor count:", count)
if count != 1:
    raise SystemExit("operator stand-down anchor not unique")
text = text.replace(OLD, NEW, 1)
print("auto-unlock installed before the operator stand-down")

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER")
