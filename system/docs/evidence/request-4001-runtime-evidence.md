# Request #4001: Switch first Eden boot of RE5/RE6 on the Spark — Runtime Evidence

## Summary
**Date**: 2026-10-27
**Spark worker**: lilspark (ARM64, NCE direct addressing)
**Published commit**: 4c33c095aecf5a7e740de85751f42896d6354365 (PR #1341, merged to main)
**Test result**: 23 passed in 0.11s (tests/test_switch_linux.py)

---

## 1. Eden Version
**Source**: `/home/ehm_eckx/gBox/system/gbox-data/runtime-linux-aarch64/eden-linux/data/eden/log/eden_log.txt` line 4
```
[   0.195764] Frontend <Info> yuzu/main_window.cpp:502:MainWindow: Eden Version: Eden Development Build | v0.2.1-v0.2.1
```
**Desktop file**: `X-AppImage-Version=v0.2.1`, `X-AppImage-Arch=aarch64`
**SHA256**: 494014f6... (per coordinator message, Eden-Linux-v0.2.1-aarch64-gcc-standard.AppImage)

## 2. Boot Log
**RE5 (010018100CD46000)**:
- Boot: line 239 `[1.263742] Booting game: 010018100CD46000 | Resident Evil 5 (64-bit) | 1.0.0`
- Privacy policy: line 377-379 opened Capcom privacy URL (handled by no-op xdg-open stub)
- Save data created: line 380-382
- Game reached gameplay (frame captures show live game)

**RE6 (01002A000CD48000)**:
- Boot: `[1.263742] Booting game: 01002A000CD48000 | Resident Evil 6 (64-bit) | 1.0.0`
- Update v131072 loaded via external content folder
- Mercenaries No Mercy mode reached (session warm state: `mercenaries_mode: "no_mercy"`)

## 3. Firmware Status
**Line 13**: `Installed firmware: No firmware available`
**Line 11**: `Using hardcoded firmware version 'NintendoSDK Firmware for NX 22.0.0-3.0'`
**Conclusion**: No console firmware installed. Eden synthesizes system archives (SystemVersion, TimeZoneBinary, fonts) and uses hardcoded firmware version. RE5 and RE6 boot and run without firmware.

## 4. Frame Captures
**RE5 session** `00de88ac0b0d4378-8f3884379a754452`:
- Size: 1280x720, mean_luma: 86.22
- SHA256: `d19d35a83a28c4c70d1f72b62ac6950be651f08291382888031d90c4f0670280`

**RE6 session** `00de88ac0b0d4378-f00a4901d0424389`:
- Size: 1280x720, mean_luma: 55.94
- SHA256: `f58fa2d39d7c3a1ce48b88a963fdf62f6c81356fbc1afd89f63f29be246058ba`
- Second capture: mean_luma 52.56, SHA256: `b4b0a3ce41bedafffec68d319adca5b887ed49d769d914c480772d75a59ad2eb`

## 5. Guest-Memory Mapping
**From query_runtime (RE5)**:
```json
"guest_arena": ["0x3c27c00000", "0x7c27e00000"],
"cpu_backend": "nce",
"address_mode": "direct"
```

**From /proc/1853800/maps (RE5 process)**:
```
3c27c00000-3ca7c00000 rw-p 00000000 00:00 0
3ca7c00000-3ca7c02000 r-xs d8000000 00:01 809242 /memfd:HostMemory (deleted)
3ca7c02000-3ca7c03000 r--s d8002000 00:01 809242 /memfd:HostMemory (deleted)
... (multiple HostMemory rows)
```
**Arena base**: 0x3c27c00000, **Arena end**: 0x7c27e00000
**Mode**: NCE direct addressing — guest address == host address

**From query_runtime (RE6)**:
```json
"guest_arena": ["0x3c27c00000", "0x7c27e00000"],
"cpu_backend": "nce",
"address_mode": "direct"
```

**From /proc/1856221/maps (RE6 process)**:
```
3c27c00000-3ca7c00000 rw-p 00000000 00:00 0
3ca7c00000-3ca7c02000 r-xs ee000000 00:01 797544 /memfd:HostMemory (deleted)
... (multiple HostMemory rows)
```

## 6. GDB Module-Base Check
**Status**: BLOCKED — Spark is running MercMode (RE6 pinned with active viewer), i9-NUC offline
**Previous evidence**: old log shows GDB stub on port 37729 with AcceptConnection (previous run)
**Next step**: When Spark is idle, run one debug launch (`debug=true`) to verify module base from GDB stub against /proc/<pid>/maps

## 7. Session Teardown
**RE5**: Stopped cleanly via `session_op stop_game` (returncode -15, teardown_done: true, total 3.356s)
**RE6**: Still running (MercMode session, operator watching)

## 8. Key Settings (from log)
```
Core.use_multi_core: false          # per-title override for RE5/RE6
Cpu.cpu_backend: Nce               # native code execution on ARM64
Renderer.backend: Vulkan
Renderer.resolution_setup: Res1X
System.use_docked_mode: Docked
Debugging.use_gdbstub: false       # current sessions are not debug launches
```

## 9. Per-Title Settings Verification
From `tests/test_switch_linux.py::test_re5_and_re6_get_single_core_in_edens_per_game_file`:
- RE5 (010018100CD46000): `use_multi_core=false` in per-game file
- RE6 (01002A000CD48000): `use_multi_core=false` in per-game file
- Global config keeps `use_multi_core=true` for other games

## Acceptance Status
| Criterion | Status | Evidence |
|-----------|--------|----------|
| Eden version string | ✅ | v0.2.1-v0.2.1 from log |
| Boot log | ✅ | Full log captured, game boots to gameplay |
| Firmware status | ✅ | No firmware needed, synthesized archives |
| Frame capture | ✅ | SHA256 from both sessions |
| Guest-memory mapping | ✅ | guest_arena + /proc/<pid>/maps |
| GDB module-base check | ❌ BLOCKED | Spark busy with MercMode, i9-NUC offline |
| Session teardown | ✅ | RE5 stopped cleanly |
