"""Move the stale save state aside so a launch cannot hang trying to restore a moment that no longer exists.

Evidence: the launch freezes at `state_transfer` - the "Moving the save state" step - while the server reports no such job and the artifacts directory is
**empty**. The one state file on disk is `lastState.sav`, **15 MB, last written 11/4**, a week before this session. A restore that expects a fresh artifact
and finds a week-old file (or nothing at all) has nothing to complete against, and a hang - not an error - is exactly what has been observed.

The file is renamed, never deleted: `lastState.sav.stale-<timestamp>`. If the launch was depending on it, putting it back is one copy. If the launch now
proceeds, the stale state was the blocker.

This cannot damage a game: no session is running, and the file is a saved emulator moment, not a memory card.
"""
import pathlib
import time

STATE = pathlib.Path(r"C:\_tools\gBox\system\gbox-data\pso-buddies\i9-NUC\436e0bb84d5337d1\User\StateSaves\lastState.sav")

if not STATE.exists():
    print("no state file at", STATE)
else:
    age_days = (time.time() - STATE.stat().st_mtime) / 86400
    size_mb = STATE.stat().st_size / (1024 * 1024)
    print(f"found: {size_mb:.1f} MB, {age_days:.1f} days old")
    target = STATE.with_name(f"lastState.sav.stale-{time.strftime('%Y%m%d-%H%M%S')}")
    STATE.rename(target)
    print("moved aside ->", target.name)
    print("restore with: Move-Item", target, STATE)
