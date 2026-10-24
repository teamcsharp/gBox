# MercMode

The panel now includes an edition-by-edition coverage inventory from
`gbox/mercs/research_profiles.py`: RE3 Mad Jackal, RE4 classic/VR/remake,
RE5 original/Reunion/United/No Mercy, RE6 original/No Mercy, Mercenaries 3D,
and Village/Additional Orders. This inventory is a development target list.
Only the host-verified RE4 and RE5 adapters can currently participate in
rotation. Other entries require native drivers and are never silently enabled.

The operator's cross-title **Mercenaries United** project uses the separate
project key `mercenaries-cross-title-united-v1`; it is not the existing RE5
United edition. Actual Hermes inbox requests, pinned to `sparkDeux`, are:

| Request | Work | Completion evidence |
| --- | --- | --- |
| #3111 / `95d7e20cadc244e3` | Shared architecture, exact owned asset/build inventory and vertical slice | One loaded stage with collision/navigation, character moveset/loadout, enemies, clock/combo/score, human control, autoplay and replay |
| #3112 / `ab0e702203aa451a` | Bow-specific 10x fire/reload, native collision context and post-DYING healing | Guarded reversible native rates and measured owned projectile launches/impacts; ordinary healing; no invulnerability |
| #3113 / `54ceec01e2ef47af` | Per-edition/character guide research and behavior evaluations | Attributed summaries, prerequisite observations, counterexamples and measured evaluation; inaccessible sources identified |
| #3114 / `412028856f044524` | RE6 PS3 BLUS30855 native lifecycle and observer, then gameplay | Exact-build character/stage/menu ACK, actor ownership, timer/score/health/navigation, terminal results and idle-worker acceptance |

Requests are persisted in the normal Hermes queue. A request number or queue
entry is not proof of a running job or completed work. Existing GPU capacity,
claims and tasks remain in place. Native changes use isolated task workspaces
and reviewable patches, preserving the watched solo run.

Recovering C-like functions in Ghidra does not produce a complete rebuildable
game. Moving RE6 Leon's behavior to an RE5 stage requires compatible animation,
state machines, damage, inventory, collision, traversal, scripting and scoring,
in addition to skeleton retargeting. The first prototype must prove an owned
asset can be decoded, round-tripped and used with those systems. Private game
binaries and extracted assets stay outside source control.

MercMode is an independent screensaver choice per registered PC, including
`lilspark`, `i9-NUC`, and `JAYBUILTFINALE`. It is off until enabled for that host.
Open the MercMode panel, choose titles and rounds per title, and save that PC.
Opening the panel and checking cached assets never launches a game.
For a paired desktop, its local control plane owns scheduling and continues
offline. The central panel delegates the operator's requested settings to that
exact PC and displays its last observed settings separately from the pending
request. The central scheduler starts no competing automatic launch there.
An already owned central run may still finish through its exact callbacks.

The scheduler uses the screensaver's existing idle/resource admission and exact
session ownership. It launches one game, starts its native playbook, and waits
for that game's real round boundary before stopping it and selecting another
ready title. It waits for the previous session to end before launching the next
emulator. The general screensaver's minute limit cannot cut off a MercMode round.
Host readiness requires this exact host's prior real launch or a recent worker
probe resolving the ROM through that PC's own library roots. An unknown host
queues one bounded read-only preparation check; tools on another PC are not ROM
access evidence. The random-selection hint lives inside the typed launch recipe
so it survives validation and worker handoff.
Disc availability is checked per catalog ID; a prior RE4 Disc 2 launch cannot
prove Disc 1 is reachable. Preparation checks both supported discs and prefers
the first one with this PC's own access evidence.
When preparation runs through a local control plane, the central scheduler reads
the receipt from its exact accepted worker job. It checks the worker, host, probe
timestamps and read-only flags; an unrelated job or another host's paths cannot
make the title ready.
If only one selected title is ready, its existing session stays warm and the
native menu policy continues selecting rounds. Returning operator input hands
the session over; it is no longer rotated by the scheduler.

| Title / exact backend | Rotation support | Known limit |
| --- | --- | --- |
| RE4 GameCube G4BE08 / Dolphin | Five character and four stage cursor targets; timer-zero/native room or actual player death boundary | Final score/rank reader is absent; random selections have simulated cursor coverage and still need new live traversal acceptance |
| RE5 PS3 BLUS30491 app 01.01 / RPCS3 | Existing original/Reunion roster and eight-stage coverage; terminal score settling or actual player death boundary | Full all-character/all-stage traversal and unmodified maximum-rank runs remain unproven |
| RE6 Xbox 360 / Xenia | Unavailable | Existing module has no combat driver, measured menu cursor, clock, score, enemy map, or terminal-round reader |
| RE6 PS3 / RPCS3 | Unavailable | Archive now present on the requested share: native `PARAM.SFO` identifies `BLUS30855`, app 01.00. It contains an extracted-disc folder layout inside `.7z`, requiring staging before RPCS3 can boot; Mercenaries combat/menu/round readers remain unverified |

A verified RE6 save-unlock writer does not make its gameplay driver ready.
MercMode preserves existing modifier settings and uses the existing title-specific
unlock/launch paths. It does not guess unlock bits, patch health, or promise a
maximum rank. RE4's random cursor policy is instance-local; ordinary launches
retain their previous default selection.

RPCS3 preparation means retained installed data, firmware and shader/PPU/SPU
caches followed by native menu navigation. A normal sequential launch warms those
caches. `mercmode op=prepare` only inspects existing cached assets and records a
bounded host receipt. It does not launch a second emulator, capture a disruptive
RPCS3 state, or claim instant gameplay. Dolphin may reuse an existing matching
menu jump state through its established boot mechanism.

`GET /api/mercmode` reports host settings and exact readiness reasons.
`POST /api/mercmode` saves `{host, enabled, titles, rounds_per_title}`.
`POST /api/mercmode/prepare` queues a tracked read-only check for an exact
`worker_id`; its completed receipt can then establish that host's readiness.
The `mercmode` worker tool exposes status/configure/prepare. Native round callbacks
use `/api/autoplay-screensaver/round-boundary`: exact owned session, matching
autoplay start job/worker, fresh running telemetry, unique round ID, and native
terminal witness are required. Arbitrary telemetry round counters cannot rotate
games. Interrupted, loading, human-observation and local co-op rounds cannot
authorize rotation. A rotation acknowledgment releases inputs and ends autoplay
before it can select the next round.
For a relayed launch, the central job and the native local launch have distinct
IDs. The scheduler retains the actual native session ID and requires the accepted
output, both federation job mappings, worker, game, adapter and process identity
to agree. The same check preserves an explicitly requested bot-demo badge and
autoplay request; a different session of the same game is never adopted.

The accompanying RE4 reader fix preserves player health separately from enemy
health; the previous enemy loop could overwrite the returned player HP.

RE4 legacy rounds now also write measured two-Hz native player/enemy/held-input
samples, a JSON round artifact and SVG path into the shared atlas, plus an exact-ID
Notebook row, generated guide and durable vector-KB outbox. The reviewer opens
those paths without a live emulator. Coordinates retain RE4's 1000 native units
per metre; interpolation, travel-distance checks and SVG rendering account for
that scale. Room IDs identify the trace, and collision geometry, wall labels,
bonus acquisitions, score and rank remain explicitly unavailable. Such paths
cannot authorize a walkable navigation suggestion. Existing RE4 bot learning
continues; shared reviews are retrieved for inspection, with policy consumption
explicitly false until a validated RE4 consumer exists. KB delivery still needs
the connected service and its acknowledgment; pending outbox rows are not called
delivered. No corresponding RE6 path recording is claimed without a real driver.
New round artifacts also retain the exact session ID and scoped autoplay job ID
provided by their invocation. Older artifacts without that origin remain
unattributed; a current session playing the same title cannot supply the missing
identity for export to another control plane.
