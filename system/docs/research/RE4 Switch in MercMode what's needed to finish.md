# RE4 Switch in MercMode: what's needed to finish

Nov 6, 2026 · @Ehm Eckx

## Bottom line

RE4 Switch is not in MercMode yet, but you read it correctly: the game is functional and input reaches it. What remains is the bot's senses, its brain and some MercMode wiring, not the emulator.

**What you saw.** The session log from 00:03 to 00:15 today shows RE4 going from the title to a save load, the merchant shop and the attaché case, where it stayed for over 5 minutes. The main-menu cursor starts on LOAD, so pressing A without first moving down to EXTRAS loads a story save instead of Mercenaries. The correct route is already written, on a branch that was never merged.

**The biggest gap.** The bot cannot read the player or the enemies fast enough to play. Finding the player takes a 9-second scan each round, the health and facing reads are disputed, and no enemy list has been found.

**Act on this first.** Tell DeepSeek to stop working on input. The handover's "input wall" is a misreading, and three other claims in it are also wrong (see the corrections below).

**What's needed from you:** a Spark window with the RE5 rotation paused, credit for the steps below, and answers to the two questions under "Needed from you".

## Where things stand

Everything up to a live round works when driven by hand. Above that, the bot's senses are only partly built and its brain is a stub.

| Layer | State | Evidence |
| --- | --- | --- |
| Boot and picture on Citron | Works | Launched at 00:03 today on lilspark, Citron build d3df71e55 |
| Input | Works | Drove rounds on 11-04 and 11-05 (a walk test measured 147.94 units in three boots). Moved the game from title to case today |
| Menu route to a round | Works by hand only | Path recorded 11-04: `a`, `ddown` x4, `a`, `ddown` x2, `a` x4. It exists only on branch `re4-switch-driver-20261104`, and nothing checks the screen between presses |
| Round start | Works | Three A presses start the clock, measured 11-04 |
| Locating the game in memory | Works | A 64-byte signature finds the module base each boot, verified live |
| Round clock | Found, too slow | Float seconds from 120.0, checked against the HUD. Needs a 12.8 s scan, with no fixed pointer yet |
| Player position | Found, too slow | Fixed at spawn, about a 9 s scan each round, with no fixed pointer yet |
| Player health | Disputed | An `int16` at position −0x2478 fell 1336 to 1054 once, then the layout from the decompiled code failed a cross-check |
| Player facing | Probably wrong | The measured pair is very likely the camera's yaw, not Leon's heading |
| Enemy list | Missing | `units()` returns 5 spawn markers, not Ganados. Best lead: class `0xaed3b0`, 26 objects at health 1000 |
| Score and kills | Missing | The kill-score routine is located in code (`FUN_002cccc0`), with no live read yet |
| Combat brain | Stub on main | `Bot.tick()` returns nothing. The branch has a first cut, but it turns with the d-pad, which is item select in this game |
| MercMode wiring | Blocked | See the next section |

### Corrections to the handover

Four claims in `re4-state-handover.md` would send the next agent the wrong way.

| Handover says | What the evidence shows | Do this instead |
| --- | --- | --- |
| No input reaches Citron (2.1) | The tests ran on session `dc24b3292ccd4728-f3233eb954974641`. Its saved frames show the title at 00:06:40, a save loading at 00:07:21, the BUY screen at 00:08:03 with the cursor on the fourth row, and the case from 00:08:44 until the kill at 00:15. Going by commit times, the failed tests compared frames of that nearly static case screen | Drop the window-manager and emulator-flag work. Run one check at the title: press A, compare frames 3 s later |
| `prepare` makes re4 `playable=True` (section 1) | That row is the GameCube disc. lilspark's status lists re4 as `78ab9efa...`, platform gamecube, because `preferred_editions` names only re5 | Adding `re4` to `titles` today would launch GameCube. Select the Switch edition as well |
| Sample `module+0xc25d78` (2.2, 5) | That is a Ghidra address, and Ghidra adds 0x100000. The real offset is `0xb25d78`. The module ends at `0xb2e738`, so the zeros came from reading past its end. The expected health range `0x1..0x64` would also reject the measured 1336 | Use `0xb25d78`, which a live round already read as a real pointer. Widen the health range |
| GameCube is the closer path (3) | You decided on 11-04 that RE4 always means Switch. GameCube was dropped as a menu dead end, and the input wall was this recommendation's main reason | Stay on Switch |

## What MercMode requires

RE4 Switch has to pass eight gates to rotate, and it fails most of them today. RE5 and RE6 Switch pass all of them, so they are the working templates.

| # | Gate | Where | RE4 Switch today | Change needed |
| --- | --- | --- | --- | --- |
| 1 | Correct game ID | `re_switch.py:35` | Bug: it hashes a filename that doesn't exist, giving `c89d2c2e...`. The real catalog entry is `270a15eb...`, the `[UPDATE 1.0.2]` file | Hash the real path and update `test_re_switch.py` |
| 2 | Switch edition selected | lilspark `preferred_editions` | Only re5 is set, so re4 resolves to GameCube | `job_mercmode op=configure` with the re4 edition and `titles` |
| 3 | Edition marked playable | `re_switch.py:74` and `:136`, `mercmode.py:99-100` | Hardcoded `playable: False`, `available: False`, `game_id: None`, `verified: False` | Flip these only after the first unattended round |
| 4 | RAM map with a `mercs` block | `profiles/gamedata/010099A00BC1E000-ram.json` | Missing on main, so autoplay stops with "no Mercenaries profile". The branch has a scaffold with `ready: false` | Bring it over and fill it in. Set `ready: true` last |
| 5 | Menu functions | `screen`, `step`, `wandered` in the driver module | Missing on main. The branch has them, but they depend on menu offsets nobody has measured | Merge them, backed by frame checks or measured menu state |
| 6 | Driver | `snapshot`, `screen`, `brain`, `progress` | Skeleton. `player` is always None, so `screen` can never say playing | Steps 4 to 7 below |
| 7 | Live telemetry | `adopt_current` and round accounting | Needs `screen` = playing, `team_role` = solo\_p1, under 8 s old | Follows from gate 6 (`solo_p1` is already set) |
| 8 | ROM access receipt | `valid_preparation` | Lasts 30 minutes and is keyed on the game ID, so it depends on gate 1 | Run `prepare` right before starting |

Queued character and stage picks aren't needed for the first rotation. They route to `re_mods`, which refuses RE4 Switch until it has a live mod writer.

## Remaining work, in order

There are nine steps. Steps 1 to 3 are short and get RE4 to a round on its own, and steps 4 and 5 are the long pole.

My estimate is 3 to 6 long agent sessions in total, nearly all the uncertainty being in steps 4 and 5. That is a judgment, not a measurement. Each RAM measurement costs a boot of about 40 s plus a 2-minute round.

| # | Step | Spark needed | Done when |
| --- | --- | --- | --- |
| 1 | **Fix the wiring.** Correct the game ID. Port the menu path, menu functions, keymap and map scaffold from the branch. Don't merge the branch whole: it drops RE5 and RE6 from Citron's title list | No | `test_re_switch.py` passes and the RE4 map loads with `ready: false` |
| 2 | **Back up the save, confirm input.** Snapshot `savegame00.sav` with `switch_saves`. Press A at the title | About 5 min | The frame differs 3 s later, a real screenshot shows the main menu, and the backup hash is recorded |
| 3 | **Reliable menu walk.** Check the screen between presses and leave room for menu fades. Stop and reset if a save list or shop appears. Finish with three A presses | Yes | 5 of 5 boots reach a round with the clock counting, and none loads a story save |
| 4 | **Player.** Replace the scan with a fixed pointer, then read health and heading from the same object | Yes, long | Position, health and heading read at 20 Hz across two boots. Health falls on a hit and heading follows a turn |
| 5 | **Enemies.** Find the live Ganado list with position and health | Yes, long | Count rises as Ganados spawn, health falls when shot, positions match the screen, across two boots |
| 6 | **Round state.** Clock by pointer, score, kills, then `snapshot`, `screen` and `progress` | Yes | `screen` is correct through loading, playing, death and results in a full round |
| 7 | **First brain.** Port the branch `Bot`, turn with `lleft`/`lright`, and steer closed-loop on the angle because measured turn rates varied from 16 to 42 degrees per second | Yes | One unattended Leon/Village round with kills above 0 and no story load |
| 8 | **Turn MercMode on.** Set `ready: true`, flip gate 3, set `preferred_editions`, `titles` = re4 and re5, `keep_warm` = 0, and run `prepare` | Yes | MercMode starts RE4 itself and the round appears in `mercs_rounds`, with no "showed only black" entry |
| 9 | **Soak.** Run RE4 and RE5 in rotation unattended | Yes | 10 rounds with clean swaps and no manual rescue |

**Methods for steps 4 and 5.** Three leads are ready to try, cheapest first:

1. Read `module+0xb25d88` during a round. Code gates on health at `+0x3c2` of that object, and it has only been read outside a round.
2. Test class `0xaed3b0`: do its 26 objects move and lose health when shot?
3. Set a write watchpoint on the position field through Citron's GDB stub and `gbox.debug.GdbDebugger`. That names the code writing it, and so the real object layout.

If Leon's heading stays hard to find, the camera yaw already measured may do as a stand-in for aiming. That is untested.

**After step 9.** Your "auto improving" request (#8261) comes next: the learning loop, QTE calibration, the other characters and stages, then mod parity with RE5 and RE6.

## Needed from you

You don't need to buy or download anything. The Citron build, the main module dump, Ghidra 12.1.4 and the cached game file are already on the Spark.

- **A Spark window.** RE5 is running on lilspark from your dispatch, and only one Switch emulator runs at a time. Steps 2 to 9 need that slot, and an agent shouldn't stop your run unless you say so. Steps 2 and 3 fit a short window, while steps 4 and 5 need long blocks.
- **Credit.** Enough for the 3 to 6 sessions estimated above, or for DeepSeek to take the parts it can.

**Two questions:**

1. **Is a basic first version acceptable?** That means Leon on Village, aiming at the nearest enemy, with a 12 m range limit standing in for wall checks until stage geometry exists. I recommend yes because it gets RE4 rotating sooner. The catch is that your no-wall-shots rule is only approximated at first.
2. **Should DeepSeek take steps 1 to 3 now?** I recommend yes: they're bounded, and a real frame proves each one. Steps 4 and 5 are where past passes produced false finds, so DeepSeek should take those only under the rules below.

## Risks and DeepSeek

The main risk is the enemy list: 28 measurement passes on 11-05 didn't produce one. If step 5 fails after two focused sessions, stop and decide on a fallback, such as vision-based targeting, rather than continuing to scan.

### Rules for DeepSeek

Each of these comes from a mistake in the log.

- Stop the input, window-manager and emulator-flag work.
- Look at a real frame before concluding what is on screen. Text summaries and brightness can't tell you which menu is up.
- Prove a live round before any RAM read: clock counting, plus a screenshot. Title-screen probes invalidated two runs.
- Module offset = Ghidra address − 0x100000.
- A RAM find counts only after a behavior test across two boots: it moves, or it loses health. The "entity table" and the early "globals" were both false finds.
- Launch test sessions with `x-gbox-actor: agent`. Today's session was logged as yours, which is why #8735 says "the operator is playing".
- Leave your RE5 run alone unless you've cleared it. Run one Citron at a time, and never SIGSTOP Citron.

I couldn't confirm what DeepSeek is doing right now. At 01:34 only RE5 was running on lilspark, and the latest RE4 commit was at 01:27. Commits are authored "gBox agent", so I can't tell which are DeepSeek's.

### Other risks

| Risk | Why it matters | Handling |
| --- | --- | --- |
| Your story save | The wander loaded a real save (1,751,510 ptas). A later wander could reach a save prompt | Back up in step 2, safety stop in step 3 |
| Watchpoints under NCE | Guest code runs natively, so the GDB stub may not catch writes. Unverified | Try Dynarmic, which also boots RE4, though addresses may differ |
| RE4 and RE5 swaps | RE5 ran on Eden at 01:33, and RE4 can't run on Eden. A swap between the two emulators is untested | `keep_warm` = 0 first, proven in step 9 |
| `skin_swap: random` on lilspark | Unverified for a title with no mod writer | Check before step 8 |
| Update-only game file | The log reports base version 0. Everything tried so far works | Watch for failures on other stages |

### Open questions

- Which call pressed the buttons in today's session? I didn't trace it. Step 2 makes that moot by testing input directly.
- Why did `w` move nothing in the 28th pass on 11-05? Leon may already have been dead, as happened in an earlier pass. Step 2 and the walk tests will settle it.
- Is Mercenaries available on a fresh save? The code says yes, but a note on the branch says locked. lilspark's save reached Mercenaries on 11-04, so this only matters if the save is ever reset (#8063).
