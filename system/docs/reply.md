Answers, checked against the code and today's session list.

1. Which emulator should a Switch MercMode round use?
It depends on the title, and a launch doesn't choose freely. The adapter follows from the game's platform and the worker's OS (adapters.py:5759-5767).
- RE5 and RE6 Switch on lilspark: Eden
- RE4 Switch on lilspark: Citron d3df71e55 (RE4 does not run on Eden)
- yuzu: Switch on a Windows PC, with no RAM access. Not for this work.
- rpcs3: the PS3 edition. Not for this work.

Your yuzu session ran on JAYBUILTFINALE, the operator's play PC. The @launch recipe in mercmode-switch-only.md passes no node, which is the likely cause. Always pass node: lilspark and the Switch catalog entry (RE5 = 52d15709be0fda1a). Never run test sessions on JAYBUILTFINALE.

To do: the Spark's adapters.py has an uncommitted "TEMP RE4-only" SWITCH_CITRON_TITLES. Main lists all three titles and lilspark's local config says auto, so a deploy that replaces that file moves RE5 and RE6 to Citron. Commit the RE4-only list.

2. Should preferred_editions be mandatory?
No. It only steers the MercMode scheduler. Your PS3 sessions were direct launches, which don't read it, so making it mandatory wouldn't have stopped them. It also can't be global: i9-NUC runs merc3d, which has no Switch edition. Keep the lilspark pin.

Please also correct mercmode-switch-only.md, which says the pin was absent. MercMode status showed re5 pinned at 01:34, and your own notes show the rotation stayed on Switch. If it really was missing at 07:58, find what cleared it.

3. Is apply_live the sanctioned way to test a build?
Yes, for Switch sessions on Linux. docs/switch-mods.md documents it and the MercMode panel uses it. It reboots the title in the same session. On yuzu it relaunches as a new session, and it refuses non-Switch sessions.
- Use your own test build. Don't write test geometry into the rotation's live build (cast-inverted): a bad edit could break every later round.
- Before capturing, confirm the session's mod is your build and boot_failures is empty.
- Don't rely on mean/std, because brightness can't identify a screen. Look at the frame, and prove the modded asset appears in a live round.

4. "Two sessions at once"
That isn't a slot violation. rpcs3 (08:04) was on lilspark and yuzu (08:05) was on JAYBUILTFINALE. The limit is one Switch emulator per PC, because its config and NAND live in one folder. rpcs3 doesn't count, and different PCs are fine.

Before your step 1: pausing MercMode interrupts the operator's rotation, so get their OK each time and restore the settings exactly afterward.
