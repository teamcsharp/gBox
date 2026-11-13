# Endless cycling, Ultimate, and what was actually re-launching the game

## 1. The re-launching was the operator's typing, not the loop - and it is a setting

`Dolphin.ini`:

```
[Interface]
BackgroundInput = True
```

**Dolphin was accepting keyboard input while its window was not focused**, so typing anywhere on the desktop went into the game - which is how the game got exited. Changed to
**`BackgroundInput = False`**: the keyboard now only drives the game when the game window is focused.

**The bot is unaffected**: its input goes through gBox's **virtual pad (XInput)**, which does not depend on focus at all, and the same is true of the operator's controller relay.

## 2. Ultimate is now actually set - it never was before

The sidebar showed **Ep 1 / Ultimate**, but:

* **`pso-launch-config.json` did not exist** - the file `pso_launch_config.FILENAME` defines and `pso_coop` reads - so the selection reached nothing;
* the game's difficulty global **`0x805D5550` read 0 = Normal**.

Both fixed and verified:

```
wrote C:\_tools\gBox\system\gbox-data\pso-launch-config.json
     {"episode": 1, "difficulty": "ultimate", "difficulty_index": 3, ...}

difficulty global: 0 -> 3      and it held across four samples two seconds apart
```

The JSON shape comes from the module's own `normalize()` return, so the fields are what a reader expects rather than invented.

**The gate that remains**: PSO GameCube only offers **Ultimate at level 80** (Hard 20, Very Hard 40, Ultimate 80). The character **BQF is level 5**. The global is written, but
whether the game spawns Ultimate content for a level-5 character is a different question from whether the flag is set - and if it does, 68 HP will not survive it. **That is
exactly the operator's own conclusion**: "the bot must have the best weapons and fight properly". Power is the route to Ultimate, and the app has the machinery
(`psoitems`, `pso_loadouts`, `pso_inventory`).

## 3. The endless cycle works

`endless.py` is a lifecycle daemon, not one run: ensure a session (launching the game if there is none) -> ensure the character is in the world (drive the menus, wait out the
intro cutscene) -> play (fight the nearest enemy by its profile `hp`, otherwise travel, never stand still) -> recover or relaunch -> repeat.

**Verified by watching it do exactly that after the game was closed:**

```
[17:59:46] === cycle 1 ===
[17:59:46] no session - launching the game
[18:00:02] launch: succeeded
[18:00:02] session 9757b8b9a1f24524-f1a5e0ca5e6b4952
[18:00:06] boot attempt 1: pressing through the title and menus
[18:02:29] character is in the world
```

Two bugs were found and fixed while building it:

* **an open pause menu reads exactly like "no player"** - the entity table is suspended - so the loop navigated the pause menu instead of the title. It now presses START and B
  and re-checks before deciding to boot.
* **waiting for a player in a session that had died** left it pressing into nothing. It now checks `live_sessions()` on every wait iteration and hands back to the outer loop.

## 4. Still to do for "best weapons and fight properly"

* the character is **level 5 with 68 HP**; giving it gear and levels so Ultimate is survivable is the next concrete step, and the modules for it already exist;
* the app's **UI still reacts to keystrokes** in places - the settings panel has "Restarted with the new settings" (`index.html:2337`, `restartGame(el.dataset.sid)`), so its
  controls need to ignore keys when a text field or the chat has focus. That is a front-end fix in the same family as the `BackgroundInput` one.
