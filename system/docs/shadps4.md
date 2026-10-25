# PS4 through shadPS4

gBox can discover extracted PS4 game folders and launch them with its Windows x64
`ShadPS4Adapter`. The integration uses the official standalone emulator core;
QtLauncher is optional. Opening an emulator window is reported separately from
verified gameplay. This does not establish compatibility for every PS4 game.

## Prepared on JAYBUILTFINALE (2026-10-25)

The official portable core 0.20.0 is installed at
`C:/_tools/gBox/system/gbox-data/runtime/shadps4/shadPS4.exe`. Its ZIP matched the
published SHA-256
`d5cdc55c57e85e5fe44ff867b420246dc832077356d943ccc43c5d950c878b37`.
`gbox-shadps4-install.json` in that folder records the release URL, archive digest
and individual payload digests. A hidden `--help` check exited 0; its output is in
`gbox-help-check.json`. This verifies that the core loads and accepts the CLI;
no game, graphics workload, firmware or input was exercised.

The ignored `gbox.local-jaybuiltfinale.toml` selects this executable. No active
worker or game was restarted. A worker started with the updated code/config will
read the overlay. Other hosts retain their existing settings.

This is prepared in the local checkout. The active control plane and worker need
the updated code/config before PS4 appears in their live UI; activate them when
the current RE5 session has ended, then rescan the configured PS4 library.

For another Windows worker, run from `system` with Python 3.11 or newer:

```powershell
python scripts/provision_shadps4.py --destination D:/gBox/runtime/shadps4
```

The helper downloads the pinned [official release](https://github.com/shadps4-emu/shadPS4/releases/tag/v.0.20.0),
checks its size/hash and stages extraction before publishing. It never launches
the emulator, changes games/saves or overwrites an existing destination. An
existing matching release ZIP can be supplied with `--archive`. Then configure
`gbox.local-<hostname>.toml` next to `gbox.toml`:

```toml
[emulators.ps4]
adapter = "shadps4"
executable = "D:/gBox/runtime/shadps4/shadPS4.exe"
```

## Game files and the pending PKG

The configured PS4 library is the `QuickSwap2/Emulation/PS4` folder. The scanner
recognizes extracted folders containing root `eboot.bin` and
`sce_sys/param.sfo`, with a valid CUSA title ID. It keeps the title ID and app
version for later build-specific analysis. A copied PKG is not an executable.

The current [official quick-start](https://github.com/shadps4-emu/shadPS4/wiki/I.-Quick-start-%5BUsers%5D)
uses dumped game folders named `CUSAxxxxx`, update folders named
`CUSAxxxxx-patch`, and firmware modules in the emulator's `sys_modules` folder.
Finish the transfer, then provide the extracted game tree before attempting a
load. gBox does not extract or decrypt PKGs in this integration.

The current QtLauncher [command-line entry point](https://github.com/shadps4-emu/shadps4-qtlauncher/blob/main/src/main.cpp)
has no package installation command. Its
[directory dialog](https://github.com/shadps4-emu/shadps4-qtlauncher/blob/main/src/qt_gui/game_install_dialog.cpp)
selects existing dumped-game, DLC and emulator-version folders. Do not expect
an `--install-pkg` option or infer that QtLauncher converts the copied package.

## Runtime operations

| Operation | Implemented scope |
|---|---|
| Launch, stop, runtime status | Session-owned native Windows process/window |
| Pause/resume | Exposed only after the running core advertises IPC emulator control |
| Frame capture | Native game-window capture |
| Input | shadPS4 default keyboard mappings; physical controllers remain emulator-managed |
| RAM map/read | 64-bit process virtual addresses, including emulator/host allocations |
| Byte replacement | Existing writable committed pages only, bounded transfers and readback verification |
| Static analysis | Existing Ghidra tools can analyze an appropriate extracted ELF; no live Ghidra debugger bridge is claimed |
| Save states, rewind, frame stepping | Unsupported |
| Breakpoints, frame-accurate replay | Unsupported |
| PS4 model conversion or full-playthrough validation | Not implemented/verified |

Process memory is not a resolved PS4 guest RAM map. A module's virtual address,
file offset and a process address are different things. Existing PS3/Xenia game
offsets must never be reused. Writes do not change page protections; executable
pages that are not writable are refused. Generic input can support scripted
interaction, but does not create a verified game-specific autonomous player.

Inspect offers the live process-region list; PS4 memory searches require explicit
ranges totaling at most 16 MiB. Candidate lists are bounded. IPC pause/resume
reports a request because upstream sends no completion acknowledgement. Enabling
upstream IPC also disables its automatic cheat/patch loading; gBox does not import
QtLauncher patch selections. The pending edition-specific unlock report is kept
under `detail.unlocks.edition_profile` alongside the generic build-unlock policy.

## Resident Evil 5 and 6

Both PS4 releases contain No Mercy. RE5 also includes The Mercenaries United:
[RE5 release content](https://store.playstation.com/en-us/product/UP0102-CUSA04437_00-RE5HDPS400000000),
[RE6 release content](https://news.capcomusa.com/lets/browse/resident-evil-6-is-now-available-on-playstation-4-xbox-one).
`gbox.re_ps4` makes that content distinction visible in the launch unlock report,
without claiming a working unlock routine.

| Edition | Existing gBox specialization | PS4 status |
|---|---|---|
| RE5 | PS3 Gold save unlocks, Reunion, RPCS3 Mercenaries driver and model writer | No verified PS4 save/RAM unlock, menu/combat driver or model writer |
| RE6 | Pinned Xbox 360 save template and Xenia model writer; No Mercy absent from that disc | No verified PS4 save/RAM unlock, menu/combat driver or model writer |

Upstream Windows observations dated 2026-09-12, checked 2026-10-25, report
shadPS4 0.18.0 reaching gameplay with limitations. RE5 CUSA04437 crashed around
the first enemy and had cutscene audio synchronization problems
([report](https://github.com/shadps4-compatibility/shadps4-game-compatibility/issues/178#issuecomment-5648040893)).
RE6 CUSA03856 still crashed when two boxes were broken together
([report](https://github.com/shadps4-compatibility/shadps4-game-compatibility/issues/179#issuecomment-5646681563)).
These are dated upstream observations, not results for the installed 0.20.0
build or proof of complete No Mercy rounds.

PS4 unlock-on-load remains `research_pending` with `applied=false`. Enabling it
requires binding the exact executable/version, checking the mode's real menu
availability, testing any necessary save routine and rollback, and verifying a
complete round. No PS3 or Xbox 360 save/byte patch is applied to PS4 by title
similarity. The current running RE5 session is unaffected.

## Validation (2026-10-25)

256 Python tests passed across the PS4 adapter/catalog/analysis/provisioner,
launch routing, RAM inspection, Home library and existing RE6 paths. Tests include
real Win64 process-memory reads and writes to a test-owned buffer, process-exit
cleanup, IPC handshake, stale-reader isolation, package rejection and 64-bit
address handling. 17 focused JavaScript tests and the changed JS syntax checks
passed. The installed core's hidden `--help` probe exited 0.

The existing desktop-capture test failed with Windows access denied (gdigrab
error 5) in this tool session, so that environment-dependent test was excluded
from the final 256-test run. The browser interaction test could not start its
isolated Chromium process. Neither live PS4 input/capture, actual Ghidra import,
nor gameplay has been verified; no running game or service was restarted.
