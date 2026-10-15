# Native Mario replay

New human launches of the owned NROM Super Mario Bros. (World) program under Mesen
automatically record native libretro input callbacks, the initial state, checkpoints,
successful state loads/rewinds and externally changed RAM. This is a separate tape
from the sampled ghost track and optional RetroArch BSV recording. Previously recorded
ghost tracks cannot recover missing inputs or native states retroactively.

In **Sessions → Runs → Native TAS playback**, select an entire run or a level attempt,
choose a player sprite, and press **Play**. **Loop** repeats the selection from its
initial checkpoint. Each level seeks to a preceding checkpoint, silently replays the
short lead-in, then presents gameplay. Earlier attempts are retained after rewinding.
The complete tape becomes available after closing the emulator. Refresh runs to see it.

**Use as idle screensaver** arms that run/skin for separate test sessions on available
Windows PCs. A full native replay must finish successfully first; a successful level
segment does not qualify the entire run. Dispatch checks five minutes of inactivity,
background-testing opt-in, current resource telemetry, the configured admission budget
(70% by default), memory headroom, running sessions and active jobs. It never switches
or stops another game. Playback yields on operator input/controller activity, opt-out,
resource pressure, control-plane loss or its one-hour loop limit. Full single-pass
playback allows the recorded duration plus slack (up to 24 hours). The next idle period can
start a new loop. The operating system must still allow the monitor to remain awake.

## Sprite choices

Sonic uses the extracted `s3k_sonic` animation collection. Mario 2 and Mario 3 use the
existing signature-validated readers against owned NES cartridges; World Mario uses
the owned US SNES cartridge's GFX32 stream, draw tables and palette. Native Mesen
version-106 HD tile packs fit the donor's poses into SMB1's player bounds. They do not
change the ROM, executable, physics, collisions, inputs or saved state. The replacement
is rendered by Mesen, not a floating character drawn over the app. Donor animation
poses are adapted to SMB1; they do not reproduce another game's animation engine.
Mario 3 uses its complete basic poses for actions whose full shared-bank/OAM mapping
is not yet exported; those actions do not introduce detached limb tiles.
Shared source tiles and mirroring constrain pose detail; preview and in-game inspection
remain useful. Missing source cartridges/collections produce an explicit error.

The typed `tas_play` tool also accepts `sprite:gallery_slug` for extracted sprite entries
with indexed animation clips, and `chr:build_name` for carefully restricted native CHR
variants. CHR variants must preserve the header/PRG and all non-player/shared tiles.
Mesen format-13 state ROM hashes are rebound only in a new copy after those checks.

## Identity, validation and storage

`tas.py` and `native/tas_core.c` implement the bounded GBTAS001 protocol. Every input
callback's ordering and result is recorded. Every replay frame checks callback consumption
and the FNV-1a checksum of emulated system RAM. A mismatch ends only this test session;
it never falls back to uncontrolled input. Successful full-run/segment/skin receipts
are separate. An uploaded tape is not proof that a run replays or beats the game.

The immutable recording remains under `<runtime>/tas-runs/<id>` until archival succeeds.
Spark stores indexed tapes under `gbox-data/tas-runs` and exact core binaries under
`gbox-data/tas-cores`. Replay uses the recorded engine even after an installed core update.
SHA-256 protects transfers. Replay config, core options, states, SRAM and graphics packs
live in a unique `<runtime>/tas-playback/<id>` directory. No human save slot is used.
Disposable replay tape/ROM copies are removed after that emulator exits.

Capture requires 8 GiB free and less than 20 GiB of retained local tapes; each tape has a
512 MiB budget. A budget stop seals a playable prefix and leaves the human game running.
Spark's tape budget is 64 GiB, its engine budget 4 GiB. Failed uploads retain local files;
three tape-transfer attempts are made. Worker-restart orphan recovery is not implemented.
Normal close finalizes the tape; gBox Stop requests a seal/QUIT before killing only its
emulator. A forced OS kill or power failure can leave an incomplete tape, which is kept
and rejected for playback rather than advertised as an exact run. Capture does not
preserve wall-clock pauses, fast-forward pacing, frontend menu visuals or rewind audio;
it preserves chronological emulated frames/state restores and plays at native speed.
Other games/cores, including PSO, keep their existing observation/recording limitations.

The proxy builds from the packaged C source with MSVC (Windows) or `cc` (Linux). For PCs
without MSVC, the operator can upload the Windows proxy built from that exact source
to `POST /api/tas/runtime/windows/<source_sha256>` with `x-gbox-sha256`; workers verify
the source and binary digests before caching it. No ROMs, extracted artwork or DLLs
are committed to the repository. Set `gameplay_memory_enabled = false` to disable new capture.

## Validation

`tests/test_tas_native.py` compiles an asset-free synthetic core and tests input order,
ten rewind restores, RAM modifications, reset, desync refusal, segment preroll/loops and
capture-budget failure while gameplay continues. Archive/API and managed-browser tests
cover immutable identities, upload bounds, legacy unavailable status, level/skin/loop
selection and idle admission. Isolated tests on the installed Mesen Windows core replayed
1,600 frames, including a restore, with zero RAM mismatches for the original and all four
native graphics choices. This is a bounded conformance test, not a replay of the user's
earlier unrecorded 46,111-frame completion or proof of every pose/level.
An additional isolated RetroArch frontend test captured 885 frames with 30 native rewind
commands and one disk save-state load, sealed the tape through the Stop handshake, then
played it through a second RetroArch instance with zero RAM mismatches. Test folders,
save files, input channel and processes were separate from the operator's sessions.

Primary format references: [Mesen HD packs](https://github.com/SourMesen/Mesen/blob/master/Docs/content/hdpacks/_index.md),
[Mesen state format](https://github.com/SourMesen/Mesen/blob/master/Core/SaveStateManager.cpp),
[SMW draw/decompression code](https://github.com/IsoFrieze/SMWDisX/blob/master/bank_00.asm).
