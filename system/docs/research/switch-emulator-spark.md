# Switch emulator for the Spark (Linux aarch64, NVIDIA GB10)

Decision, updated 2026-10-26 evening: **Citron NEO is canonical for RE5 and RE6** (`gbox.adapters.CitronLinuxAdapter`,
`gbox.provision.ensure_citron_linux`): it runs them multi-core. **Eden** (`SwitchLinuxAdapter`) stays the default
for every other title and remains an option for these two (`switch_linux_emulator = "eden"`). Everything below was
read on the projects' own pages on 2026-10-26; "not verified" means exactly that. First live runs on the Spark: "Live
on the Spark with Eden v0.2.1" and "Citron NEO" below (tickets #3841, #3842, #3954, #3955).

## Citron NEO (live 2026-10-26, nightly 56dad8119)

- Source: https://github.com/citron-neo/CI/releases/tag/nightly-linux,
  `citron_nightly-56dad8119-linux-aarch64-use-nopgo.AppImage` (sha256 6471eced..., SHA-1 matches the release's zsync
  manifest), placed in `~/gBox_alt/downloads/citron-neo-nightly-56dad8119/` with the operator's OK. Each node names it:
  `switch_citron_appimage = "<path>"` in `gbox.local-<host>.toml`. gBox extracts it once, like Eden's.
- RE5 No Mercy runs **multi-core** at 60 FPS (16.6 ms frames through crowd scenes, dips only while first-time shaders
  compile). Eden v0.2.1 needs single-core for these titles: 74 % speed, 86 % with async shaders. The re5_switch driver,
  the menus walk and the RAM map work unchanged, because Citron keeps the same HostMemory arena with guest = host
  under NCE.
- RE6 boots multi-core with its v131072 update applied through `external_content_dirs` (the window title reads
  "RESIDENT EVIL 6 (64-bit) | 1.0.2"). A fresh save starts the Prologue; The Mercenaries is locked until it is unlocked
  (a separate task).
- Two host specifics:
  - The Spark's usb4 bus hangs every sysfs read, and Citron calls `libusb_init` on its main thread for its GameCube
    adapter driver, so it never opened a window. gBox builds `gbox/native/libusb_noinit.c` with the host's compiler
    (`provision.switch_usb_shim`, cached by the source's digest; never a committed binary) and preloads it. Citron's
    sharun loader passes LD_PRELOAD on only with `SHARUN_ALLOW_LD_PRELOAD=1`.
  - Citron's renderer enum is {Vulkan=0, Null=1}, against Eden's {OpenGL=0, Vulkan=1}. `backend=1` runs the game on the
    Null renderer: it is fast, and the screen stays black.
- Selection (`adapters.switch_linux_kind`): `switch_linux_emulator = auto` (the default) starts SWITCH_CITRON_TITLES
  (RE5, RE6) in Citron once it is configured, and everything else in Eden. LayeredFS builds use Citron's own load
  folder and [DisabledAddOns] (`switch_mods.citron`).
- Boot watch, both emulators: after the memory map, RE5 and RE6 must draw three different frames within 45 s, after
  8 s for the emulator's loading overlay. A still or dead boot is stopped and started once more. Eden single-core
  stayed black in 1 of 7 boots.

## Why Eden

| | Eden | Citron NEO | Ryubing / Ryujinx | Sudachi, torzu, Suyu, Kenji-NX |
|---|---|---|---|---|
| Linux aarch64 build | official: `Eden-Linux-v0.2.1-aarch64-gcc-standard.AppImage` (and `-clang-pgo`), release v0.2.1 2026-06-01, nightly 2026-10-18 | official GitHub releases: `citron_stable-0db11ed05-linux-aarch64.AppImage` 2026-04-17, nightlies to 2026-10-25 | `ryujinx-1.3.3-arm64.AppImage` 2025-10-11 (archive copy; git.ryujinx.app down 2026-10-26) | none found (dead, 404, or x86_64 only) |
| NCE on Linux arm64 | yes: `if (ARCHITECTURE_arm64 AND (ANDROID OR LINUX)) set(HAS_NCE 1)` in the root CMakeLists | yes, same rule | no: .NET JIT (ARMeilleure / LightningJit; the hypervisor path is Apple only) | - |
| Renderer | Vulkan 1.1+ (OpenGL 4.6 alternative) | Vulkan only | Vulkan | - |
| Maintained | master commit 2026-10-26 | pushed 2026-10-25 | last stable 2025-10, canary tags to 2026-07 | no |
| RE5 / RE6 reports | no compat list published | none | in-app list: 010018100CD46000 RE5 and 01002A000CD48000 RE6 both "playable" (label nvdec) | - |

Links: Eden https://eden-emu.dev/ , releases https://git.eden-emu.dev/eden-emu/eden/releases (tag v0.2.1), nightlies
https://git.eden-emu.dev/eden-ci/nightly/releases , system requirements https://eden-emu.dev/system-requirements .
Citron NEO https://citron-neo.github.io/ , https://github.com/citron-neo/emulator , https://github.com/citron-neo/CI .
Ryubing https://ryujinx.app/download (source mirror https://codeberg.org/Software_arch/Ryubing). The February 2026
takedown wave removed the GitHub mirrors of Eden, Citron, Ryubing, Sudachi and others (github.com/eden-emulator/Releases
answers HTTP 451): Eden's own Forgejo is the source of truth.

NCE matters here: the Spark is an ARM64 host, so with NCE the game's ARM64 code runs natively (Eden patches only
system instructions) instead of through a JIT. Eden enables it when `cpu_backend` is NCE, fastmem is on and the host
page size is 4 KiB (Settings::IsFastmemEnabled; the Spark's `getconf PAGESIZE` is 4096) and the title uses a 39-bit
address space (RE5/RE6 are 64-bit titles). Eden's own docs call Linux NCE experimental.

## Spark facts checked over ssh (2026-10-26)

Ubuntu 24.04.5, glibc 2.39, kernel 7.0.0-1019-nvidia, NVIDIA GB10 driver 580.178.04 with `nvidia_icd.json`,
`/dev/fuse` + fusermount3 present (gBox extracts AppImages anyway), Xvfb / xdotool / xdpyinfo / xset / ffmpeg installed,
606 GB free on the NVMe root, load average 22-29 (RPCS3 + ollama + whisper, the operator's MercMode game). The NSPs
are local: `/home/ehm_eckx/gBox_alt/switch/Resident Evil 5/Resident Evil 5.nsp` (20.0 GB), `.../Resident Evil 6/
Resident Evil 6 [01002A000CD48000].nsp` (18.8 GB) + `[01002A000CD48800][v131072].nsp` (105 MB, the title update);
keys at `/mnt/gbox/quickswap2/Emulation/_switch/prod.keys` (read-only CIFS; the quickswap-switch library root, where
`gbox.provision.switch_keys_source` finds them). Catalog ids: RE5 `52d15709be0fda1a`, RE6 `115f9cdbba115432`,
update `5d50031f5c8057b1` (sha1 of `quickswap-switch:<relative path>`).

## How gBox drives Eden (from Eden's sources, master 2026-10-26)

- Command line (`src/core/launch_params.cpp`): `-f/--fullscreen`, `-g/--game <file>`, `-u/--user`, `-d/--debug <gdb
  port>`, `-c/--config`. gBox starts `AppRun -f -g <nsp>` on the session's Xvfb display with `QT_QPA_PLATFORM=xcb`
  (Eden's docs: Wayland is problematic, there is a "Force X11" switch).
- Folders (`src/common/fs/fs_paths.h`, `path_util.cpp`): `$XDG_DATA_HOME/eden/{keys,nand,sdmc,load,log/eden_log.txt}`,
  `$XDG_CONFIG_HOME/eden/qt-config.ini`, `$XDG_CACHE_HOME/eden/shader`. gBox points the three XDG variables at its
  runtime folder `eden-linux/`, so the operator's own Eden (if any) is never touched.
- Settings written (`src/common/settings.h`, `src/qt_common/config/uisettings.h`; section = TranslateCategory):
  `[Renderer] backend=1` (Vulkan), `[Cpu] cpu_backend=1` (NCE; 0 Dynarmic on other hosts), `[Debugging] use_gdbstub`
  + `gdbstub_port` for debug launches, `[UI] firstStart=false confirmStop=2 check_for_updates=false`, each with its
  `\default=false` twin (how the frontend knows to read the stored value). Controls stay at Eden's defaults: player 1
  is a Pro Controller on the keyboard with yuzu's layout (A=C, B=X, X=V, Y=Z, L=Q, R=E, ZL=R, ZR=T, +=M, -=N, left stick
  WASD, right stick IJKL, d-pad arrows), the same table gBox already uses for Yuzu on Windows (`gbox.yuzu_runtime.
  SWITCH_KEYS`). Not verified: that a fresh Eden config indeed binds the keyboard this way (yuzu did).
- Readiness: a window or an error dialog is not a booted game (the Windows failures #3688 / #3769 "Yuzu did not open a
  game window within 60 seconds" were exactly that gap). gBox waits for Eden's **HostMemory arena** in
  `/proc/<pid>/maps`: Eden backs guest RAM with a memfd named `HostMemory` and reserves the guest's address space as
  one arena (`src/common/host_memory.cpp` ChooseVirtualBase: 2 MiB-aligned, between 2^36 and 2^39 on arm64, 1<<38 bytes
  with NCE built in per `src/core/device_memory.cpp`), created when the game boots.
- Guest memory for the bots (`gbox.eden_memory`): NCE runs the game's own loads and stores on the host, so guest
  pointers must be host pointers. Eden's code agrees: `EnableDirectMappedAddress()` sets virtual_base to null, and
  `arm_nce.cpp`'s fault handler passes the host fault address on as the guest address. So **under NCE a guest address
  is the host address**, and `/proc/<pid>/mem` reads it directly (the same mechanism `RPCS3LinuxAdapter` uses, verified
  live there). Under Dynarmic, host = arena base (aligned up to 2 MiB) + guest address. Reads and writes are refused
  unless the range lies in a HostMemory row.
- Debugging: Eden's NCE backend has no breakpoints or watchpoints and `StepThread` is a stub (`arm_nce.cpp`), so a
  gBox debug launch (`debug=True`: `use_gdbstub=true`, `GdbDebugger("arm64")`) writes `cpu_backend=0` (Dynarmic) and
  reads memory in offset mode. Play and the bots use NCE. Offset mode takes the arena's lowest row as its start. An
  unrelated anonymous mapping right below the reservation would shift that, which is unlikely on arm64 (random hint
  between 2^36 and 2^39) but possible on x86 hosts. The first debug session should check one module base from the
  stub against the maps rows.
- Pointing the XDG folders at gBox's own runtime folder also keeps Eden's first-start migration dialog away: it offers
  to import yuzu/Citron/Sudachi/Suyu/Ryujinx folders only when it finds them under the same XDG roots.
- Save states: Eden (yuzu) has none; rewind stays unsupported for Switch.
- Mods: builds are LayeredFS overlays in `load/<TID>/` selected through `[DisabledAddOns]`, edited in place, applied
  to a running game by restarting the title in the same session; never a copy of the NSP (docs/switch-mods.md).

## Live on the Spark with Eden v0.2.1 (2026-10-26)

Eden v0.2.1 gcc-standard (sha256 494014f6...) from gBox's Eden home. Keys from the share, **no firmware installed**:
neither game needs it to boot or play.

**Boot crash (both games) and the fix.** With multi-core on, RE5 and RE6 stopped 3-4 s after Eden's "Launching" screen,
right after the game's HID init (`SetPollingMode` in the log). RE5's main NSO creates an npad style-set watcher thread
(main+0xCE7EA0: `BindNpadStyleSetUpdateEvent`, `CreateThread`, `StartThread`). The thread's first call
(main+0xCE7FC0) is `nn::os::SetThreadCoreMask(self, 1, 0b110)`: it moves itself off core 0. From there Eden v0.2.1
loses that thread's state. svcSetThreadCoreMask returns InvalidHandle (0xE401) for a handle that `CreateThread` had
just filled in. Eden then dispatches SignalProcessWideKey twice and Break once with the stale registers of that same
SVC: "Unmapped Write32 @ 0xE400", then `svcBreak` reason 0xE401 info 1, 6 at PC sdk+0x371658, the instruction after
`svc #0xF`. Other threads jump to PC=4, and an IPC "SFCI magic" assert or a SIGSEGV follows. NCE and Dynarmic (debug
launch) both fail, and the symptoms change from run to run, so this is a race in Eden's multi-core thread migration,
not a setting. `game_settings.cpp` applies nothing to these titles; the line "Applied game settings for title ID" is
only a log line. **Single-core (`[Core] use_multi_core=false`) boots both games**, so gBox writes it per title into
Eden's per-game file (`EDEN_TITLE_SETTINGS`, `custom/<TITLE ID>.ini` with the `\use_global=false` / `\default=false`
twins Eden writes itself). Every other game keeps multi-core.

**RE6's v131072 update.** Eden v0.2.1 scans `[UI] Paths\external_content_dirs` for update/DLC NSPs at boot. gBox
points it at the game's own folder when `switch_nsp.companions()` finds an update or DLC there, so nothing is
installed into the NAND. The log confirms it: "ExeFS: Update (v0.2.0) applied successfully", main build id
061D2A06...

**Timings and speed** (windowed test runs, Eden reniced +10, Spark load average 21-32 from the operator's MercMode
sessions):
- RE5: title screen about 35 s after launch, menus at 60 FPS / 100 %. First boot: "No saved data was found" creates
  the save, then the game asks "Open the privacy policy webpage?". Answer B (No). A, or Eden's web applet, ran
  xdg-open, which opened the Spark user's Firefox on the session display. gBox now puts a no-op `xdg-open` first on
  Eden's PATH (`provision.switch_linux_env`).
- RE5 No Mercy is selectable from a fresh save: Play Game > Extra Content > The Mercenaries United > Start >
  **No Mercy** ("more enemies than the original") > Stage select (Public Assembly) > Character select (Chris BSAA). A
  round started: timer 2:00:00 counting down, score 000000, Majini on screen. Single-core gameplay measured about
  36 FPS at 66 % speed, with stalls on first-time shader compiles (async shaders off); the death screen ran 58 FPS at
  93 %. Not yet good enough for MercMode, so next: other emulators and Eden settings.
- RE6 (with the update): "PRESS ANY BUTTON" about 31 s after launch, 60 FPS. A fresh save is forced into the Prologue
  and never reaches the main menu, so The Mercenaries / No Mercy (always enabled in EXTRA CONTENT) are out of reach;
  gBox sets the save's "Prologue cleared" bit in RAM at the title screen (`gbox/re6_switch_unlock.py`; gate, proof and
  RAM map in docs/research/re6-switch-ram.md, measured on Citron NEO).

## Caveats and what is still unverified

1. Eden's release page publishes no checksum for the AppImage, so gBox does **not** download it. Place
   `Eden-Linux-v0.2.1-aarch64-gcc-standard.AppImage` on the Spark and set `switch_appimage = "<path>"` in
   `gbox.local-lilspark.toml`; gBox extracts it once (`--appimage-extract`, no FUSE at launch).
2. Firmware: Eden's quick start lists "firmware dumped from your console" as a prerequisite (Tools > Install
   Firmware), but RE5 and RE6 boot and play without it (2026-10-26). `/mnt/gbox/quickswap2/Emulation/_switch/backup/`
   holds a raw NAND backup of the operator's console (BOOT0/1, rawnand.bin.*), not a firmware folder. It was not used.
3. The RE6 v131072 update is a separate NSP. gBox refuses to "launch" the update file (`gbox.switch_nsp.launchable`)
   and has Eden apply it from the game's folder (external content folders, above); no NAND install is needed.
4. The Spark is busy (load ~25) with the operator's live game: the first Eden run there must be short, `nice -n 15`,
   on a private Xvfb display, and torn down; it was not run on 2026-10-26. The i9-NUC (the only PC for agent test
   sessions) was offline, so no Windows run either.
5. glibc / AppImage runtime of Eden's build: not verified (Ubuntu 24.04's glibc 2.39 is recent; Citron NEO's AppImages
   are documented as fully bundled, hence the backup).
6. Windows (Yuzu on the i9-NUC): #3688 / #3769 failed because readiness never saw a window that started minimized.
   Main has fixed that since `39b27800` (2026-10-26 05:59 -0500, after #3769's 03:48 failure): Yuzu now starts shown
   but not activated (`capture_start`), covered by `test_yuzu_launch_shows_nonminimized_window_before_publishing`.
   PR #1180, still open, takes the other route: readiness accepts iconic windows. It was written against the older
   minimized start. Neither has been run live yet.

## RAM and No Mercy: what carries over from the PS3 work (no addresses assumed)

The Switch builds are ARM64 ports of the 2016 PS4/Xbox One remasters: little-endian with 8-byte pointers, where the
PS3 builds are big-endian with 4-byte pointers. **No PS3 offset carries over**: every struct with an embedded pointer
shifts. What carries over is the method and the names:

- MT Framework singletons (`gbox/mercs/titles/re5_ps3.py`): each manager's instance pointer sits next to its class
  descriptor (MtDTI), and an object's class comes from its vtable's getDTI, whose MtDTI holds the class name. The
  same names should exist in the Switch main NSO: sPlayer, sEnemy, sBioMain (cGameSys), sUnit / uLaserSight,
  sBioCamera / uCameraCtrl, uPl00ChrisCos4, uEm10 / uEm11. So the chains can be found by name in Ghidra (main NSO
  from Eden's ExeFS dump or `dump_nso`) and then confirmed live in `/proc/<pid>/mem`.
- Field meanings to look for again, with the PS3 offsets as hints only: player position (3 floats, cm, y up) and
  rotation quaternion; the health s16 pair (Majini 800 / 700 maximum is game data and should match); action byte;
  inventory slots; cGameSys timer (f32 counting down at 1 s/s), start time, kills, combo, combo window, score and the
  round phase (terminal state 3 on PS3).
- RE6: `re6_ps3.py` has no measured addresses. Field names in the Xbox 360 map (docs/re6-ram-map-0871eee3b68cdea3.json)
  are hints only, not offsets.
- No Mercy spawns more enemies than standard Mercenaries: check the enemy array's capacity (re5_ps3 caps it at
  MAX_ENEMIES = 64).

### Next tickets (text to file)

1. **Eden on the Spark: first boot of RE5 and RE6 Switch (needs the operator's OK to place the AppImage).** Place
   Eden-Linux-v0.2.1-aarch64-gcc-standard.AppImage from git.eden-emu.dev/eden-emu/eden/releases/tag/v0.2.1 and set
   switch_appimage in gbox.local-lilspark.toml. Launch catalog 52d15709be0fda1a, then 115f9cdbba115432, through
   gBox (SwitchLinuxAdapter) only when the Spark is idle: one short `nice -n 15` session on a private Xvfb display,
   torn down after. Record the Eden version, the eden_log, whether firmware is required, frames, fps and the
   HostMemory arena. Do one debug launch (Dynarmic) and check a module base from the GDB stub against
   /proc/<pid>/maps.
2. **RE5 Switch Mercenaries RAM map, revision-pinned (title 010018100CD46000, program NCA sha256 15af72f2...).**
   Find sPlayer / sEnemy / sBioMain (cGameSys) / sUnit / sBioCamera by their MtDTI names in the main NSO (Ghidra),
   then measure live in No Mercy: player position, rotation, health and max, action; the enemy count, array and
   capacity; timer, start time, kills, combo, combo window, score, phase. Write a re5_switch title driver on the
   shared engine with tests on the measured values. Same for RE6 (01002A000CD48000, v131072 installed) as its own
   ticket.
3. **No Mercy and Mercenaries unlocked by default (RE5 Switch, then RE6).** Find the save in Eden's NAND
   (nand/user/save/.../010018100CD46000) and the unlock flags for No Mercy, Mercenaries stages and characters, by
   diffing saves around an unlock and confirming the flag in RAM at the menu. Implement unlock-on-load like
   re5_tool (backup, readback, refuse an unknown revision) and update re_switch.unlock_profile.
4. **Menu automation into Mercenaries No Mercy.** Name the title, main menu, extras, mode, character and stage
   screens from RAM (the menu state machine), never from blind press counts. Drive Eden's keyboard pad into No Mercy
   with the chosen stage and character, confirmed by RAM state and frames. Then MercMode TITLES: turn the Switch RE5
   edition (re_switch.preferred_spec) playable only after a complete logged round (round_maps evidence).
5. **RE6 v131072 update in Eden's NAND.** Install catalog 5d50031f5c8057b1 into gBox's Eden NAND (headless) and
   check the version Eden reports. gBox refuses to boot an update NSP as a game (`switch_nsp.launchable`).
