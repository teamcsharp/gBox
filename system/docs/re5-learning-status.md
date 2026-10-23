# RE5 learning and verification status — 2026-10-23

The implemented changes target PS3 Gold **BLUS30491 app 01.01**, PPU hash
`a9b0ce57ebd318bd02879751067ceca83b508dd1`. They do not establish an S rank on
every run, a perfect route on every stage, or complete unlocks across RE titles.
Deployment and measured gameplay acceptance remain separate from passing tests.

## Navigation and round evidence

`mercs/atlas.py` and the engine recorder persist the complete directed navigation
geometry supplied by the RAM reader, observed checkpoints, inputs, enemies, routes,
acquisition order, and reviews of stationary movement, reversals and efficiency.
The database is `gbox-data/mercs/navigation/BLUS30491/atlas.sqlite`; the recorder
queues `rounds/<round-hash>/round.json` and `map.svg` for each finished/interrupted
round. Queue drops and writer errors remain visible in telemetry.
Continuous measured segments can improve checkpoint-to-checkpoint route records.
Teleports and missing samples cannot become shortcut evidence. A background writer
keeps database work away from the input thread.

The bot holds its current bonus goal, prioritizes time before combo bonuses, uses
observed crossing failures to change later route costs, and recalls stage lessons.
Full geometry for a loaded stage does not prove all eight stages have been explored.
There is no verified all-stage checkpoint census yet. Geometry boundaries mean
“no ordinary directed floor link”; they do not identify a physical wall. Off-mesh
links remain candidates until traversal evidence supports them. Exhaustive typed
windows, doors, ledges, staircases, treasures and powerups still require native
object/script evidence. Character-specific abilities and gestures are not all mapped.

The curriculum/notebook retain outcomes, generated guidance and performance vectors;
the existing semantic outbox publishes round evidence to the knowledge database.
Only actual completed results can establish a rank. The combined validation passed
941 Python tests (62 skipped) and 83 UI tests. Sustained all-stage acceptance remains pending.
Live rounds have produced SQLite observations, JSON reviews and SVG maps. A circular
reference in review metrics originally prevented later exports; detached metrics and
explicit round finalization now cover repeated rounds in one engine invocation.
Three unfinished exports were rebuilt with writers stopped and a database backup:
two retained matching notebook completion outcomes and one remained interrupted.

Live follow-up found and corrected three concrete learning defects. The opening
countdown previously consumed the movement timeout and blocked Ship Deck portal
1337->1338, disconnecting every time goal. Input now waits for the countdown to
start, and genuine failed portal blocks expire for bounded rechecks. Pickup
correlation now allows the measured 1.64-2.52 second destruction animation and
ends learned routes at the actual nearby pickup sample. Finally, the old +0x194
hourglass classification was unverified: live Prison actors labelled combo had
native +0x14A4 values of 30/60/90 seconds. Verified hourglass actors are time
bonuses; native +0x13EC=1 marks collection before the shrinking actor disappears.
Combo chests require their own object evidence.

The semantic audit found all 22 sampled completed/interrupted notebook rounds in
the real 768-dimensional knowledge database, with no undelivered round outbox
rows. Storage alone did not prove recall. Background semantic search now selects
up to two source IDs that join existing measured reviews with the exact title,
geometry and mode. Only those local reviews reach the bounded 12/16-second goal
patience policy; retrieved prose and coordinates cannot control the character.
Cache selection and actual consumption have separate database/guide receipts.
The first visit queues retrieval; a later matching recall consumes its result.

## Native kill-time correction

Writing cGameSys+0x3E0 only changed the HUD momentarily. Native countdown function
0x1361C rewrites it from aGame+0x4DC each frame. The verified getter 0xBBCA0 follows
sArea [0x0191CA20]+0x3830 to aGame. The modifier now checks both object signatures,
the active original/Reunion mode and countdown state, and adds time to that owner.
It never falls back to a HUD-only write or changes score/kills.

Live RAM confirmed kills 15->19 with clock 163.68->203.40 over 0.251 seconds, and
independent one-kill increments of approximately ten seconds. Evidence and bounded
RAM witnesses are retained at `gbox-data/analysis/re5-authoritative-timer/` on Spark.
The latest operator request changes the fixed bonus to **three seconds**. Both the
launch profile and live setting now use three; the restarted normal-health session
reported two kills and six seconds added. The earlier ten-second receipt documents
the native clock correction rather than the current setting.
Raw clock gains and actor removals are separate from confirmed hourglass counters.
An active Prison run exceeded 60,000 points; completion and all-time-bonus acceptance
must still be verified before calling it an S-rank result.

## Mines, damage and recovery

Earlier live evidence verified actual armed Proximity Bomb actors and enemy-triggered
detonation, followed by gunplay without recovery. New movement takes a supported
floor route at least 600 game units away. Deployment preflight requires a supported
escape route; absence of one defers equipping and planting. An observed detonation
followed by disappearance can release an obsolete escape goal, while recording that
the retreat was unachieved. Round maps/reviews retain plants, detonations and escape
segments; kills and damage remain unattributed unless the reader can prove the source.

An observed HP loss now records preceding movement, goals, inputs, combo/QTE state,
nearby enemies/mines, a 2D map and bounded read-only RAM witnesses. Witnesses cover
at most 48 KiB of selected objects with addresses, timestamps and hashes; they are
sequential observations, not an atomic or complete RAM dump. Optional JPEG capture
has an explicit budget. The native RPCS3 checkpoint is marked skipped because its
current save-state operation reloads gameplay. No exact resumable incident save is
claimed. The incident/persistence tests passed 45 focused checks.

The operator subsequently rejected infinite life. The current profile explicitly
disables unlimited health on launch and every round, and the live operator override
was switched off with all 13 recorded collision entries restored. Native HP/max
returned to 1000/1000. Five genuine HP-loss reports were observed before the bot
died and began a fresh round. Earlier scores and zero-loss samples used the health
guard and do not establish normal-health damage avoidance or an expert S run.
Conservative deployment gates are now active, with a ten-second operator cadence:
nearby enemies, unsupported escape paths and existing mine hazards defer planting.
Routes avoid ground mines and require a supported retreat before gun restoration.
This does not establish damage-free mine use on every stage.
Verified resuscitation prompts receive alternating Circle down/up at 1/60 second
per phase; this does not establish instantaneous revival on every game state.

The native health reader distinguishes active spray/green/mixed-herb actors by
class, item ID, pickup volume and handle. An exact, fresh health prompt can permit
pickup through the otherwise strict anti-mine-recovery guard. Low HP pauses the
time goal for a measured health route or carried healing. Nonquick inventory
selection uses ordinary Triangle, acknowledged cursor moves and L1; item use
requires observed consumption and HP gain before counting a heal. Its live native
menu decoder is verified, but full pickup-to-HP-gain acceptance remains pending.

The measured Prison ladder approach now faces the entry portal rather than the
offset upper landing. The bot approaches within 35 cm and requires the stage
climb prompt before Square. A recorded geometry regression covers that stall;
live traversal acceptance remains separate from the test.

PiP's right-click menu includes session-scoped modifier switches and numeric
sliders for fire rate, damage, turning, kill time and mine cadence. It also exposes
mines-only and next-mode/character/stage selection. Fresh verified readback controls
the displayed state; closed or replaced sessions cannot receive new changes.

Longbow firing uses a separate ordinary-input controller because its projectile
path supplies no laser ray. Direct guns also have a camera/body-pitch fallback
when laser feedback is absent. A straight supported floor corridor rejects known
intervening navigation boundaries, but does not establish projectile visibility
through props or overhead cover. Missing feedback and blocked corridors yield
to route acquisition rather than indefinite aimed waiting. Trigger requests are
kept separate from native shot events; the bow receives no unverified animation
rate writes. Live arrow cadence and sustained hit accuracy require gameplay proof.

## Guides and unlock coverage

The requested [Fandom RE5 guide](https://residentevil.fandom.com/wiki/The_Mercenaries_(RE5))
was accessible: collect time, maintain combos and finish the round to earn a grade.
The requested [GameWith article](https://gamewith.net/resident-evil-5/article/show/12370)
covers **Mercenaries United**. Its broad routing/combo advice is applicable; its
combined roster and timing claims must not replace measured PS3 original/Reunion
state. [FAQ 55979](https://gamefaqs.gamespot.com/ps3/929198-resident-evil-5/faqs/55979)
could not be retrieved and is not claimed ingested. Existing Berserker original
and Reunion guide references remain in the [evidence manifest](evidence/re5-mercenaries-curriculum.json).
No copyrighted maps or full guide text are copied into the atlas.

| Release | Existing support | Remaining acceptance |
| --- | --- | --- |
| RE4 GC G4BE08 / Wii RB4P08 | Live Mercenaries roster/stage/extra-mode operations; GC bot applies its early unlock | Universal boot integration and every story weapon/costume/category; USA Wii is a separate revision |
| RE5 BLUS30491 01.01 | Hash-scoped original menu access and measured Mercenaries availability; original/Reunion rotation | Full story/item/extra inventory and two-boot acceptance; other executable revisions |
| RE6 Xbox 360 catalog `0871eee3b68cdea3` | Pinned native-save template on launch | Fresh/second launch and rollback acceptance; menu/navigation fields remain partial; absent DLC, No Hope and No Mercy excluded |

## Streaming and Hermes

Streaming changes use latest-frame asynchronous MJPEG delivery, source-gap/viewer-skip
diagnostics, fewer encoder threads, and reconnect only after actual stream trouble.
A controlled capture reduced 73 threads to 25 and CPU from 71.5% to 61.3%; observed
client traces still contained stalls, so seamless playback is not yet established.
Telemetry now accepts finite UTF-8 JSON stats up to 64 KiB: the former 4,000-character
limit rejected rich RE5 packets and falsely displayed a stopped bot. Its focused
telemetry/screensaver/recovery suite passed 36 tests. PiP was observed retaining its
last picture and following replacement sessions, including a visible Capcom boot logo.
An added FFmpeg passthrough timestamp setting caused duplicate-PTS encoder exits under
load; it was removed after stderr tracing, with an actual duplicate-PTS regression test.
The subsequent capture had no encoder restarts, but still showed intermittent gaps;
that is not proof of a seamless gameplay stream. RPCS3 focus recovery targets only the
owned visible renderer on its private display. Startup mapping and RAM-read checks are
tracked separately from video connectivity.

Live startup exposed a separate cached-RAM bug: a nonzero NVIDIA host mapping at
`0xe22b00000000` was mistaken for guest memory before the real reservation existed.
The finder now requires a complete guest reservation, rejects device/library mappings,
and revalidates cached bases. It selected the live PS3 base `0x300000000` during
read-only verification. Initial transient RAM failures receive a bounded 120-second
retry; established-game read errors remain visible. These safeguards avoid treating a
running emulator process or a nonzero host address as proof of readable game state.

Profiling also found idle demo polling decoded a 205 MB / 48,115-document job archive
every 30 seconds. It now queries only indexed queued/running jobs. MJPEG frame delivery
no longer awaits recurring session/lease database operations; those use single-flight
background checks with ordered lease cleanup. A subsequent active gameplay sample
delivered 55.34 fps, versus 48.89 in the preceding sample, with zero encoder restarts.
Maximum gaps were 556 ms and 1.13 seconds respectively; these are separate observed
windows, not a controlled benchmark. Native emulation still slowed to about 18 fps
under competing GPU/CPU load, so seamless playback remains unproven. A temporary
RSX affinity experiment was restored because it did not prove a consistent benefit.

Hermes now excludes pool routes with recorded provider cooldowns before assigning
work (96 focused routing tests). Six existing RE tasks
were returned to normal gated review/queue routing, retaining their job IDs. MiniMax
returned HTTP 429 for the account's monthly usage limit and remains unavailable;
Spark2 remains the available implementation route; existing task #2042 resumed there,
while the remaining retries await normal review/admission. The later audit found
SparkDeux review network failures, pending work and a conflicting draft PR; there
was no additional completed branch ready to merge. The inspected Mercenaries PRs
retain their branches: skipped bonuses, guessed roster pages and unverified save
edits are not accepted as completion. Deployment/requeue/test receipts are retained
under `gbox-data/hermes-re-merge-audit/` on Spark.
