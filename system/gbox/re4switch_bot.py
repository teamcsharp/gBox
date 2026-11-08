"""RE4 (Switch) Mercenaries playbook: get to a round from the screen, start it, and keep it running.

This title has a verified **round entry** - three A presses once the stage draws - and a frame classifier for its menus
(`re4_switch_screens`), but no RAM anchors yet, so it cannot aim. What it can do is what the operator asked for first:
stop sitting on the briefing and play. That is a playbook, not the vision fallback, because the route is known.

Deliberate limits, so nobody reads more into it than it does:

* it reads **frames only** - no memory - so it cannot see enemies or aim at them;
* in a round it advances, turns and fires on a cadence, and it re-enters the next round from the results screen;
* it never claims a kill count: `stats` carries what it actually did (screen, presses, rounds entered).

The one thing it must get right is not mistaking a menu for a round: the classifier is the same one the driver uses, and
`unknown` only counts as in-round after a stage screen has been seen (`re4_switch`'s own rule).
"""
import time

from .mercs.titles import re4_switch as driver
from .mercs.titles import re4_switch_screens as screens

GAME_IDS = ("270a15eb98dab4d7",)          # Resident Evil 4 (Switch) [UPDATE 1.0.2], the catalog entry MercMode uses
ROUND_ENTRY_PRESSES = 3
# The trapped-menu escape, one press per still picture: back out of the save list, then move the prompt's cursor off
# "No" and confirm it. A picture that changes resets the sequence, so a wrong guess costs one press, not the run.
STALL_ESCAPE = ("b", "up", "a")                    # measured: three A presses after the stage draws start the clock
IDLE_TICKS_BEFORE_ACTION = 2


def matches(ad, g: dict) -> bool:
    """Switch RE4 only: the Mercenaries edition, whatever screen it is on."""
    if (g or {}).get("platform") != "switch":
        return False
    if str((g or {}).get("game_id") or "") in GAME_IDS:
        return True
    return "Resident Evil 4" in str((g or {}).get("title") or "")


def setup(ad) -> dict:
    """Nothing to install: RE4 Switch Mercenaries needs no unlock and this playbook applies no mods.

    Mods arrive as a LayeredFS build on the launch (`mod=`), which is where every other title's mods live too.
    """
    return {"hacks": [], "note": "screen-only playbook: round entry and movement, no memory reads"}


def _press(send, key: str, hold_s: float = 0.08) -> None:
    send([{"key": key, "down": True}])
    time.sleep(hold_s)
    send([{"key": key, "down": False}])


def play(ad, send, stopped, sleep=time.sleep, stats: dict | None = None, *, clock=time.time,
         max_seconds: float | None = None, still_s: float = 12.0, **_) -> dict:
    """Walk the menus to a round, start it, and keep moving until `stopped()`.

    Returns a dict of what it did. `stats` (when given) is filled live for the watch panel.

    `still_s` is how long the picture may stay byte-identical before the driver's own story-save-list recovery is asked for
    its cancel key. A stray confirm lands in LOAD and the save list then holds the walk for as long as nothing acts on it
    (measured on 2026-11-07: identical frames for 260 s); the driver owns that recovery and this loop has to call it, or the
    bot sits there looking exactly like a hang.
    """
    stats = stats if stats is not None else {}
    stats.update({"screen": None, "presses": 0, "rounds": 0, "started": clock(), "stage_seen": False,
                  "story_recoveries": 0, "stall_steps": 0})
    last_frame, last_change = None, clock()
    reader = screens.Reader()
    driver.begin_run()
    started = clock()
    last_step = 0.0
    ticks = 0
    in_round = False

    while not stopped():
        if max_seconds is not None and clock() - started > max_seconds:
            break
        ticks += 1
        try:
            frame = ad.get_frame()
        except Exception:                                    # noqa: BLE001 - a missing frame is not a screen
            sleep(0.5)
            continue
        if frame != last_frame:
            last_frame, last_change = frame, clock()
            stats["stall_steps"] = 0                             # the picture moved: the escape starts over
        screen = reader.read(frame)
        where = screen.get("where")
        stats["screen"] = where
        # a still picture before a stage is a trapped menu, whatever the classifier calls it: the save list itself is
        # "unknown" once it darkens its background, and skipping those left the bot on "Cancel loading? Yes/No" with No
        # selected for minutes at mean 19.4 (2026-11-07). The escape is a fixed sequence, one press per failure to
        # change the picture, and it restarts as soon as the picture moves.
        if not stats["stage_seen"] and clock() - last_change > still_s:
            step = min(stats["stall_steps"], len(STALL_ESCAPE) - 1)
            _press(send, STALL_ESCAPE[step])
            stats["presses"] += 1
            stats["stall_steps"] += 1
            if step == 0:
                stats["story_recoveries"] += 1
            last_change = clock()
            sleep(0.6)
            continue
        stats["stage_seen"] = stats["stage_seen"] or where == "select_stage"

        # --- menus: the same route the driver walks, one press at a time
        if where != "unknown":
            in_round = False
            target = (driver.EXTRAS_ROW if where == "main_menu"
                      else driver.MERCENARIES_ROW if where == "extras_menu" else None)
            # one confirm per screen per gap: a second A while the fade runs lands on the next screen's default row
            gap = driver.CONFIRM_GAP_S.get(where, 3.0)
            key = driver.step({**screen, "target": target}) if clock() - last_step > gap else None
            if key:
                _press(send, key)
                driver.pressed(screen, key)
                stats["presses"] += 1
                last_step = clock()
            sleep(0.4)
            continue

        # --- unknown: in the stage (the classifier cannot read a live round)
        if not stats["stage_seen"]:
            sleep(0.4)
            continue                       # a screen nobody can classify before a stage: do not press into the dark
        if not in_round:
            in_round = True
            stats["rounds"] += 1
            for _ in range(ROUND_ENTRY_PRESSES):
                if stopped():
                    break
                _press(send, "a")
                stats["presses"] += 1
                sleep(0.8)
            continue

        # --- playing: advance, sweep the aim, fire. Screen-only, so this is deliberately blunt.
        if ticks % IDLE_TICKS_BEFORE_ACTION == 0:
            _press(send, "dup")            # aim up is harmless in a menu-free round and lifts the camera
            _press(send, "w", 0.35)        # advance
            _press(send, "a")              # fire/action
            stats["presses"] += 3
        sleep(0.35)

    stats["ended"] = clock()
    stats["seconds"] = round(stats["ended"] - started, 1)
    return {"ok": True, "mode": "re4-switch-screen", "rounds": stats["rounds"], "presses": stats["presses"],
            "seconds": stats["seconds"], "note": "screen-only: no enemy perception, no aim"}
