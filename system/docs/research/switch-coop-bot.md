# Split-screen co-op with the gBox bot: RE5 and RE6 on Switch (research)

Operator, 2026-10-27 15:30-15:32:

- "like the ps3 versions, I want to be able to play and have the bot be my teammate in split screen (or system link if
  possible) and be able to play alongside the bot in games where they are able to use their level understanding bot
  skills and modifications to help me."
- "i also want to be able to have the bot team up with itself playing two play split screen and bots control both
  players."

Two modes follow from that:

- **(a) Operator + bot.** The operator plays Player 1 from the stream/PiP and the bot is their teammate as Player 2.
- **(b) Bot + bot.** Bots play both players in split screen. MercMode could rotate this in as an optional turn.

Titles: RE5 Switch `010018100CD46000` (catalog `52d15709be0fda1a`, main build `EBFFDB223149A725A93CD9B60979F6AA`) and RE6
Switch `01002A000CD48000` with update v131072 (catalog `115f9cdbba115432`, main build `061D2A06CD700785E987C42CE2D72231`),
both on Citron NEO on the Spark (`gbox.adapters.CitronLinuxAdapter`).

Every Switch fact below is **static**: it comes from the main NSO dumps (`~/gBox_alt/scratch/agent/switch/re5/` and
`~/gBox_alt/scratch/agent/re6sw/nso/`), disassembled with capstone using the scratch tools in
`~/gBox_alt/scratch/agent/re6sw/tools` plus the scripts listed at the end. None of it has been seen live with two
players yet. Addresses are main-relative: `main+X` is X past the module base that `module_base()` finds each boot.

## The short answer

1. **The PS3 "team mode" is not a working teammate yet.** It saves a role per session, fences every bot key by
   player, and has a follow/protect planner. But `re5_coop.for_player` still returns nothing, so the PS3 bot has never
   driven Player 2 in a round (section 1). The Switch work below is the first path that can actually do it.
2. **Both Switch games have native local split screen in The Mercenaries.**
   - RE6: THE MERCENARIES NO MERCY > SPLIT. **No Mercy itself supports split screen.**
   - RE5: The Mercenaries United > SPLIT-SCREEN. **No Mercy is single-player only** in RE5's menu. The game stores
     NO MERCY as "single player + No Mercy flag", and one of the four places that reads the flag also requires single
     player. So RE5 co-op is the regular Mercenaries United.
3. **Both games open the Switch controller applet** (`nn::hid::ShowControllerSupport`) when split screen is chosen,
   asking for 1-2 players in multi-player mode. Citron answers it with its Qt "Controller Applet" dialog, which waits
   for OK. gBox has to connect a second controller before boot and press OK on that dialog.
4. **Citron can take Player 2 from the keyboard.** The P2 bindings go in `qt-config.ini` (`player_1_*`), on keys P1 does
   not use. The operator's input keeps going to P1 through `send_input`. The bot's P2 keys go through a new
   `send_input_player(events, player=2)`.
5. **Player 2 is easy to find in RAM** (static):
   - RE5: `[sPlayer + 0x38]`, with the index byte at player `+0x3F2C`, and its own laser sight at player `+0x3728`.
   - RE6: `[sPlayer + 0x38]`, with the index byte at player `+0x5A2C`, its own camera at player `+0x3A28` and its
     own laser sight at player `+0x54E8`.

   The bots can therefore read each player's own body, aim and camera, rather than "the first laser on the effects
   line" as they do solo today.
6. **System link (LDN) between two emulators is possible in principle but not practical now** (section 6).
   Split screen is the path.

## 1. How the PS3 team mode works today

Code: `gbox/mercs/teamplay.py`, `session_runtime.py`, `cooperation.py`, `titles/re5_coop.py`, `gbox/rpcs3_coop.py`,
`gbox/mercs_team_tool.py`, the PiP panel in `clients/web/viz/re5-modifiers.js` ("Team and training"); tests
`test_mercs_teamplay.py`, `test_mercs_team_integration.py`, `test_mercs_cooperation.py`, `test_re5_coop.py`,
`test_rpcs3_coop.py`, `test_mercs_team_controls.cjs`. Docs: `docs/mercenaries-cooperation.md`.

- **Roles, per exact session** (`TeamStore`, files under `gbox-data/mercs/teamplay/`): `solo_p1` (the default),
  `teammate_p2` (human P1, bot P2) and `observe_human` (no bot input; records a human demonstration). There are also two
  training profiles, `assisted` and `unmodified_evaluation`. Saving a role changes no modifier and sends no input.
- **The app** (`mercs_team` tool, operator only): `status`, `configure` (role/profile), and `prepare_player2`. On
  RPCS3, `prepare_player2` writes a `Player 2 Input` keyboard pad (F13-F24, digits, brackets) into a separate input
  config for the **next launch**. It never restarts the game. `game_prefs` keeps the saved choice per game.
- **The fence** (`SessionRuntime`): every bot key is tagged by player. P2 keys go only through
  `adapter.send_input_player(..., player=2)`. A missing P2 never falls back to P1, and cleanup releases only the
  bot's own keys, never a human P1 button. A role other than `solo_p1` also turns off pad takeover (P1 belongs to the
  human; `tools._mercs_human_controls`), autoplay hacks and the menus walk (the human drives the menus).
- **Native evidence**: `re5_coop.participants` reads the PS3 player manager (`sPlayer+0x28/+0x2C`, count `+0x38`,
  actor index byte `+0x2F14`). Read-only, it proves P2's actor exists.
- **The level understanding offered to P2**: `FollowProtect` plans a standoff route on the measured navigation mesh,
  about 3.5 m from the human: follow beyond 6 m, back off under 2.2 m. It biases targets toward exposed enemies near
  the human, and pauses for QTEs, healing and mine escapes.
- **What is missing**: `re5_coop.readiness` never reports `controller2_verified`, `camera2_verified` or
  `prompt2_verified`, and `for_player` returns `None`. In `mercs_bot`, P2 therefore waits forever
  (`team_phase=waiting_p2`). RE6 team play is marked unverified throughout. The planner has unit tests only.

The Switch work reuses all of this: the roles, the fence, the tool, the panel and the follow/protect ideas. It adds what
PS3 never had: a P2 input path, P2 RAM readers and a P2 brain.

## 2. How each game enters local split-screen Mercenaries

### RE5 (The Mercenaries United)

Path from boot, as the solo walk does today: PLAY GAME > EXTRA CONTENT > THE MERCENARIES UNITED > START, then the mode
list (`uIdStartUp29 +0x1C4 = 1`, cursor `+0x1C8`). The entries are SINGLE PLAYER 0, CO-OP 1, SPLIT-SCREEN 2 and NO MERCY 3.

uIdStartUp29's update (vtable `main+0x1B42E38` slot 9, `main+0x59DF50`), on confirm (`main+0x59E2FC..+0x59E340`):

```
cGameSys+0x898 = (cursor == 3) ? 0 : cursor      ; players / session type: 0 single, 1 online co-op, 2 split screen
cGameSys+0xA76 = (cursor == 3)                    ; the No Mercy flag
```

The bits in `uIdStartUp29 +0x1D8` say which entries can be confirmed. Readers of the No Mercy flag:

- **`main+0x10046C`** applies it only when `cGameSys+0x64` is 2 or 5 (the Mercenaries modes) **and `+0x898 == 0`**.
- **`main+0x103F74`, `+0x106A44`, `+0x107FA8`** read it with only the mode check.

So in split screen (`+0x898 = 2`) some of No Mercy might apply if the flag were written by hand, but not all of it.
That would be an untested RAM write, not a native mode. **RE5 co-op is therefore the regular Mercenaries United.** The
optional experiment (write `+0xA76 = 1` at the split-screen stage select) is kept off by default and needs a live run
before anyone relies on it.

SPLIT-SCREEN (cursor 2) goes to state `0x32` (`main+0x59E3C0..+0x59E480`). There the game sets up the controller applet
in `sBioPad` (instance pointer `main+0x26A2288`, class size 0x8F70):

```
sBioPad+0x8D29 = 01 02 00 01   ; ControllerSupportArg: player_count_min 1, max 2, take_over 0, left_justify 1
sBioPad+0x8D2D = 01 00         ;   permit_joy_dual 1, single_mode 0
sBioPad+0x8D2F = 00            ;   identification_color 0
```

`main+0xCDEFB0` then calls `nn::hid::ShowControllerSupport(&result, &arg)` (the call is at `main+0xCDEFF8`).
`sBioPad+0x8A00` caps the requested maximum. After the applet, the game expects two players' character selections. The
stage select is `uIdStartUp21` and the character select is `uIdStartUp22` (P1 cursor `+0x1D0`). How P2's cursor shows
up there has not been measured: it may be a second cursor field, or a second unit.

### RE6 (THE MERCENARIES NO MERCY)

Path from boot, as the solo walk does today: PLAY GAME (3 = EXTRA CONTENT) > EXTRA CONTENT (NO MERCY) > `uIdStartUp30`.
Its cursor `+0x50` lists SOLO 0, CREATE GAME (DUO) 1, JOIN GAME (DUO) 2, **SPLIT 3**, SKILL SETTINGS 4, LEADERBOARDS 5.
`sGameMan+0x54` stays 2 (No Mercy), so **split screen keeps No Mercy**.

uIdStartUp30's update (vtable `main+0x269A080` slot 9, `main+0xAB28E0`) prepares two controller-applet arguments in the
pad manager (instance pointer `main+0x2A5FB90`):

- a single-player one (`+0x8D0B = 1`, styles `0x1F` through `SetSupportedNpadStyleSet`);
- a multi-player one (`+0x8D0B = 0`).

It copies each, 0x21C bytes, into an applet job (`+0x8CA8`, `+0x8F28`) and runs it (`main+0x171B420`;
`ShowControllerSupport` is called at `main+0x17150EC`). After the applet, `main+0x35BCC0(pad)` counts the connected
controllers, and **SPLIT continues only with 2 or more** (`main+0xAB2AE8`). The stage select (`uIdStartUp31`) and
the character select (`uIdStartUp32`, P1 cursor `+0x1CC`) follow, as in solo. P2's select cursor has not been
measured.

### What the bot presses

| step | RE5 | RE6 |
|---|---|---|
| mode | mode list target 2 (SPLIT-SCREEN) instead of 3 | `uIdStartUp30` target 3 (SPLIT) instead of 0 |
| controller applet | Citron's dialog: gBox presses OK (section 3) | the same |
| stage | P1 picks as in solo | P1 picks as in solo |
| characters | P1 picks; P2 confirms its default with A on P2's pad | the same |

In mode (a) the operator drives the menus with P1, as on PS3. The bot then only presses P2's A on the character select,
and only once the operator has confirmed P1's character. In mode (b) the existing walk drives P1 and the coop step
answers for P2.

## 3. Two players in Citron

### The controller config

`CitronLinuxAdapter.write_settings()` already rewrites `qt-config.ini` before every start. Citron reads controllers
**only at boot**, and the file is shared by every Citron session on the node, MercMode's included. So co-op is a
**per-launch** choice:

- a co-op launch writes `player_1_connected=true`, `player_1_type=0` (Pro Controller) and the full set of
  `player_1_*` bindings below;
- every other launch writes `player_1_connected=false`, so MercMode's solo boots stay exactly as they are.

Player 1 keeps Citron's default keyboard pad (`yuzu_runtime.SWITCH_KEYS`): C X V Z Q E R T M N F G, the arrows, WASD,
IJKL, Shift as the left stick's modifier, and 7 / 8 as the motion keys. Citron's hotkeys use F2, F4-F6, F8-F11, Esc, `-`,
`=` and Ctrl chords. Player 2 gets keys that none of those use, each present in the default Xvfb keymap (an xdotool key
outside the keymap is remapped onto a spare keycode, which breaks when two such keys are held at once):

| P2 | key (Qt code) | P2 | key (Qt code) | P2 | key (Qt code) |
|---|---|---|---|---|---|
| L-stick up | `y` (89) | R-stick up | `1` (49) | L | `[` (91) |
| L-stick down | `h` (72) | R-stick down | `2` (50) | R | `]` (93) |
| L-stick left | `b` (66) | R-stick left | `3` (51) | plus | `;` (59) |
| L-stick right | `o` (79) | R-stick right | `4` (52) | minus | `'` (39) |
| ZL | `p` (80) | A | `5` (53) | D-pad up / down | `,` (44) / `.` (46) |
| ZR | `u` (85) | B | `6` (54) | D-pad left / right | `/` (47) / `\` (92) |
| L-stick click | `` ` `` (96) | X / Y | `9` (57) / `0` (48) | R-stick click, home, capture, motion | unbound |

All P2 bindings are written explicitly, so P2 never inherits P1's default keys. Holding Shift would change the digit and
punctuation keys' Qt codes (`1` becomes `!`). No gBox path sends Shift, and the operator's pad maps onto SWITCH_KEYS,
which has no Shift.

### Routing

- **Mode (a), operator + bot.** The operator's pad events keep their current route: `POST /api/sessions/{sid}/input`,
  then `tools._pump`, then `ad.send_input`, which reaches P1's keys. The bot's events go through `SessionRuntime.send`
  (role `teammate_p2`), then `ad.send_input_player(events, player=2)`, which reaches P2's keys. Pad takeover must not
  claim P1 from a teammate bot. `tools._mercs_human_controls` already skips it for any non-solo role; it needs the
  Switch game ids.
- **Mode (b), bot + bot.** One engine loop runs a pair brain that returns P1 keys as usual and P2 keys prefixed `p2:`.
  `SessionRuntime.send` (role `bots_p1_p2`) sends unprefixed keys through `send_input` (P1) and prefixed ones through
  `send_input_player` (P2). Both brains are released on stop.
- `StandaloneAdapter.send_input` already drops any event whose `player` is not 1, so a P2-tagged event can never reach
  P1's keys.

### The controller applet

Citron (yuzu lineage) shows `QtControllerSelectorDialog` (window title "Controller Applet") for a multi-player
`ShowControllerSupport` request, and `exec()`s it until OK. Only single mode with its parameters met skips the dialog.
Both games ask in multi-player mode, so the dialog will appear on the session's Xvfb display. The adapter watches for
it during a co-op session (`xdotool search --onlyvisible --name "Controller Applet"`), focuses it, and presses Return
(the dialog's default OK). The applet then returns two connected players because `player_1_connected=true`. The window
fitter (`FIT_NAME = "."` on Switch) would stretch any window, the dialog included, in the first 45 s after a boot, but
the applet only comes up minutes later, in the menus.

### Starting co-op

Citron only reads controllers at boot. **Prepare Player 2** for a running Switch session therefore sets this session's
adapter to two players and, with the operator's explicit OK in the panel, calls `restart_title()`. That restarts
Citron in place: the same session, display and stream, and the same LayeredFS build. The round in progress is lost.
MercMode co-op turns set it at launch (`game.launch.mercmode.coop`). Nothing persists on the node, so the next launch
is solo again unless it asks.

## 4. Player 2 in RAM (static)

### RE5

- **Player slots.** `sPlayer` (`main+0x1CF1C98`) holds four player pointers at `+0x30 + 8 * index`, with the count at
  `+0x50`. The add-player routine (`main+0x1EC6F4..+0x1EC730`) stores the index byte at player `+0x3F2C`, the player
  at `[sPlayer + 0x30 + 8 * index]`, and increments `+0x50`. About a hundred sites index the array by the `+0x3F2C`
  byte (for example `main+0x7A6D3C`, `main+0x7C9F28`). This is the PS3 layout (`+0x28` slots, `+0x38` count,
  `+0x2F14` index) with 8-byte pointers.
- **The player's own laser sight.** The player's init (`main+0x7974C4..+0x797550`) creates a `uLaserSight` (DTI
  `main+0x1D5B370`), writes the player's index into the laser's `+0x374`, and stores the laser at **player
  `+0x3728`**. The solo driver walks sUnit line 19 for the first `uLaserSight`. In split screen there are two, so a
  P2 reader must follow `+0x3728` and check `+0x374 == 1`.
- **The player's per-viewport mask.** The same init compares the player's index with four u32 at **`sBioCamera
  +0x1084..+0x1090`** (instance pointer `main+0x26A1550`): one player index per viewport. That mask is how the game
  knows which half of the split screen shows whom.
- **Per-player round data** from `cGameSys`: the add-player routine copies `+0x740 + 4i` into player `+0x3F40`,
  `+0x780 + 4i` into `+0x3F48`, and `+0x750 + 4i` into `+0x3F49`. Health (`+0x1EB8 / +0x1EBA`), position, rotation,
  the motion byte (`+0x8F8`) and the inventory (`+0x30F0`) are the same class's fields for both players, so the solo
  readers work on P2's pointer unchanged.
- **Mode.** `cGameSys+0x898` is 2 in split screen; `snap['scoring_players'] = 2` marks a team round.

### RE6

- **Player slots.** `sPlayer` (`main+0x28EAC10`) holds eight player pointers at `+0x30 + 8 * index` (index 0-7, clamped
  at 7 by every reader), with the count at `+0x70`. The add-player routine (`main+0x3E6E24..+0x3E6E70`) stores the
  index byte at player `+0x5A2C`, the 1-based player number at `+0x2BDC`, the player in the slot, and increments
  `+0x70`.
- **The player's own camera.** `main+0xB2E180` creates the player's `uCameraCtrl` (0x4CF0 bytes) and stores the
  player in the camera's `+0xB0`, `+0x1750`, `+0x33C0`, `+0x45F0` and `+0x49B0`. It links the camera onto sUnit move
  line 14, the line the solo driver searches, and stores it at **player `+0x3A28`**. The camera's `+0xB0` is read back
  as its owner (for example `main+0x337A00`, which then reads the owner's `+0x5A2C`). Solo RE6 picks "the uCameraCtrl
  riding within 6 m". In split screen both cameras are on line 14, so P2 must use `[player + 0x3A28]` and check
  `[camera + 0xB0] == player`.
- **The player's own laser sight.** `main+0xBCC014..+0xBCC0AC` creates a `uLaserSight` (DTI `main+0x291AA20`),
  writes the player's index (clamped at 7) into the laser's `+0x590`, and stores it at **player `+0x54E8`**.
- Health (`+0x1368`), the action byte (`+0x6E2`), the motion (`+0x598`), the inventory (`+0x5070`) and the ammo fields
  are class fields, so the solo readers work on P2's pointer.

### Reading them in gBox

The solo drivers read `[sPlayer + 0x30]`. A co-op reader passes a player index (as PS3 does with
`m.mercs_player_index`) and reads `[sPlayer + 0x30 + 8 * index]`. It accepts the pointer only if the index byte matches
the slot (RE5 `+0x3F2C`, RE6 `+0x5A2C`). It also takes that player's laser (and camera, on RE6) from the player's own
pointer and checks the owner field. Solo play (index 0, no co-op) keeps today's readers unchanged.

## 5. The bot per player

The same brain plays either player from that player's RAM: `re5_switch.Bot` or `re6_switch.Bot`, fed a snapshot built
for that player index. The team module adds behaviour by changing what each brain sees (which enemies, in which
order) and by overriding movement for the few things a solo bot never does:

- **Mode (a), the teammate.**
  - **Follow and cover**: beyond 8 m from the operator with nothing threatening it, P2 walks back toward them,
    turning by its own heading (RE5) or its own camera (RE6).
  - **Don't steal targets**: enemies the operator's own laser is on, or that sit in their aim cone close in front of
    them, drop out of P2's list unless they threaten P2.
  - **Help when grabbed**: when the operator's motion or state byte says held, P2's list is reduced to the enemies on
    top of them.
  - **Help when dying**: at the operator's dying health, P2 walks to them and taps A, the partner action ("Help" /
    "Resuscitate" on both titles' Switch controls).
- **Mode (b), two bots.**
  - **Splitting crowds**: each bot keeps the enemies nearer to itself than to its partner, plus any within 3 m of it.
  - **Covering each other**: a held partner's grabber goes to the top of the other bot's list, and a dying partner is
    helped as above.
  - Each bot keeps its own aim, heal, escape and reload logic.
- The PS3 `FollowProtect` planner needs a navigation mesh. The Switch maps have none yet, so the Switch teammate uses
  the straight-line rules above. When the Switch navigation map exists, the planner can take over.

## 6. System link / LDN between two emulators

Both mains import `nn::ldn` (Initialize, Scan, Connect, CreateNetwork, OpenAccessPoint, OpenStation ...), so both games
have a local-wireless mode. Citron inherits yuzu's LDN emulation over multiplayer rooms. Two Citron instances in one
room can therefore see each other's LDN network in principle, and each player would get a full screen instead of half
of one. It is not practical now:

- it needs **two emulators**, about twice the CPU and GPU, on a Spark that sits at load 20-25 with MercMode alone;
- joining a room happens in Citron's Qt GUI ("Multiplayer > Direct Connect"). There is no config key that joins at
  boot. yuzu's SDL frontend had a `--multiplayer` argument, but Citron NEO's AppImage ships the Qt frontend, so
  headless use would mean automating dialogs or running a dedicated room server;
- both instances need different user profiles and saves;
- the games' local-wireless menus (RE5 CO-OP, RE6 CREATE / JOIN GAME (DUO)) are unmapped, and the bot would need a
  second RAM reader per instance;
- each emulator would also need its own stream.

Recommendation: split screen first (one emulator, one stream, both views in one frame). Revisit LDN if the operator
wants full-screen views and the Spark has headroom, starting with a room server plus two GUI joins in private
sessions.

## 7. What a live run must still show

Each item is one short guarded private run (`~/gBox_alt/scratch/agent/switch/guard.py`), or a run on the i9-NUC with
the operator's background-testing tick once Citron is set up there:

1. With `player_1_connected=true`, the Controller Applet dialog appears on choosing split screen, Return accepts it,
   and the games see two controllers. RE6 continues only with 2 or more.
2. P2's keys move P2 in the menus and in a round, and P1's keys do not.
3. P2's pointer at `[sPlayer + 0x38]` with index byte 1, P2's laser (RE5 `+0x3728`, RE6 `+0x54E8`) and P2's camera
   (RE6 `+0x3A28`) during a split-screen round.
4. P2's character select: its cursor field, and whether P2's A alone confirms it.
5. The round's end in split screen: results, game over when either player dies, and RE6's dying / help states.
6. RE5's No Mercy flag in split screen (`cGameSys+0xA76 = 1` at the stage select): does the No Mercy enemy set load?
7. Frames: the split-screen round with both bots, and with the operator as P1, labelled real.

## Live runs (2026-10-27, a guarded private Citron session on the Spark)

Real frames from run 1 are in `docs/evidence/switch-coop/`, cropped to nothing: the session's 1280x720 Xvfb display.
They show the No Mercy menu, the controller applet, the stage select and the split lobby. The run script is
`~/gBox_alt/scratch/agent/switch/coop/coop_run.py` on the Spark (`COOP_LULL=1` for a window with MercMode down).

- **RE6 run 1.**
  - The menus walk reached THE MERCENARIES NO MERCY and took SPLIT.
  - Citron's Controller Applet came up: "Players 1-2", Player 1 and Player 2 as Pro Controllers on "Use Current
    Config", "Connected 1 2", OK enabled, and the game's own line "Play with 2 players on one screen. (Only P1's
    Leaderboard data will be submitted.)". One Return closed it.
  - Player 1's keys then took the stage select to Rail Yard.
  - The next screen is **RE6's split lobby**: "THE MERCENARIES NO MERCY · Rail Yard", Player 1 joined (Leon, DEFAULT),
    Player 2's slot "Press -/+ to join", and the hints "L / R Change skills, - Change stage, X / Y Character select, A
    Start game, B Quit game".
  - Its unit is not in the screen table yet. The title unit stays listed, so the first reader called it the title and
    pressed A, which does nothing while Player 2's slot is empty. The reader now names it `split_lobby`, and Player 2
    presses + there.
- **RE6 runs 2-4** were each stopped by the guard on a MercMode stream gap, every time before the lobby:
  - run 2: 367 ms, 16 s into the boot, Citron on the little cores (taskset 10-14);
  - run 3: 406 ms, in the gbox.service restart window, at the first sample once MercMode played again;
  - run 4: 308 ms, after a clean boot, in the menus, with ionice -c3 as well.

  The rest waits for a window with MercMode down.
- **Still to see live:** Player 2's + join, Player 2's pointer, laser and camera in a split round, Player 2's stick, and
  RE5's split-screen menus.
- **RE5's character select** (static): in split screen it seems to run once per player. `uIdStartUp22 +0x1C4` names
  the player selecting, and `cGameSys +0x794 + 0x20 * player` holds that player's choice (`main+0x5B12E4`). Player 2's
  A is pressed there.
## How it is built (#1363, #1369, #1371)

- **Citron** (`gbox/switch_coop.py`, `SwitchLinuxAdapter`):
  - A co-op launch reads its own copy of the emulator's config folder (`runtime/<emu>/coop-config/<token>/`) with
    Player 2 on the keys in section 3. The node's shared `qt-config.ini` never gets Player 2.
  - `send_input_player(events, player=2)` types Player 2's keys after validating the whole batch, and only for a
    verified co-op launch of the running process.
  - A watcher presses OK on the Controller Applet dialog.
  - `prepare_teammate_pad(restart=True)` adds Player 2 by restarting the title in place.
- **The bots** (`re5_switch` / `re6_switch`, `gbox/mercs/titles/switch_team.py`):
  - A memory view per player (`View`) reads that player's own pointer, laser and camera (section 4).
  - `Teammate` adds the partner action for a dying or held partner and follows back when the bot is far.
  - `shape()` leaves the operator's targets to them and splits a crowd between two bots.
  - `Pair` runs two brains on one engine loop, with Player 2's keys prefixed `p2:`.
  - `CoopDriver` plays either mode, and `MenuPartner` presses Player 2's A on the character select.
- **The app** (`teamplay`, `SessionRuntime`, `mercs_bot`, the team tool, the panel, MercMode):
  - Roles: `teammate_p2` (operator P1, bot P2) and `bots_p1_p2` (bots on both).
  - Player 2's keys reach Player 2's pad only once Player 2's actor and pad are proved.
  - MercMode's `coop_turns` is off by default.

## Starting co-op

- **Operator + bot**:
  1. In an RE5 or RE6 Switch session's PiP, open Team and training.
  2. Choose "Player 2: follow and protect human Player 1" and save.
  3. Press "Connect Player 2 and restart this title now". This restarts the title in the same session with Player 2
     connected, and the round in progress is lost.
  4. Start the autobot.
  5. Drive the menus with your pad: RE6 No Mercy > SPLIT, or RE5 Mercenaries United > SPLIT-SCREEN. gBox presses OK on
     the controller dialog, and the bot confirms Player 2's character a few seconds after you pick yours.
- **Bot + bot**:
  - In your own session: the same steps with "Bots on Player 1 and Player 2", and the bot walks the menus too.
  - For MercMode: set "Bot+bot split-screen turns" (co-op : solo, off by default, for example 6:1) in its settings
    panel or the PiP menu. From the next launch, each Switch turn draws co-op or solo by that ratio, and co-op rounds
    count as team rounds.
- **Play with bot**: in the PiP MercMode menu of an RE5 / RE6 Switch session. It sets the teammate role, restarts the
  title with Player 2 connected and starts the autobot, all in one go.

## Reproducing the static findings

- `main` dumps: RE5 `~/gBox_alt/scratch/agent/switch/re5/main-EBFFDB22....nso`, RE6
  `~/gBox_alt/scratch/agent/re6sw/nso/main-061D2A06....nso` (0x100-byte header, then the image at vaddr 0).
- `nsodis.py <nso> sym 'hid|ldn'` lists the imports. `nsodis.py <nso> xref <PLT>` finds the callers of
  `ShowControllerSupport`.
- `fieldrefs.py <nso> <sPlayer global>` gives sPlayer's field histogram:
  - RE5: `+0x30 / +0x38 / +0x40 / +0x48` (1265 / 972 / 895 / 879 sites), `+0x50` 35;
  - RE6: `+0x30` ... `+0x68`, `+0x70`.
- An index scan (an `add xN, sPlayer, idx, lsl #3` followed by `ldr [xN, #0x30]`, with idx traced back to its byte
  load) gives RE5 `+0x3F2C` and RE6 `+0x5A2C`. The stores into those bytes are the add-player routines above.
- The DTI references (`adrp/add` to the uLaserSight and uCameraCtrl DTIs) lead to the creation sites that link
  laser/camera and player.
