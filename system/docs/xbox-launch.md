# Original Xbox launch support

Original Xbox titles launch directly in Cxbx-Reloaded on Windows. They no longer
go through the collection's RocketLauncher wrapper. The old Microsoft XBOX
launcher selected PCSX2 and failed with `RLDLL.Start - Exception thrown: -2` on
the operator's PCs before an Xbox game was running.

The adapter recognizes older `windows_native` catalog rows by their physical
Xbox collection path. Entries in virtual Xbox lists whose files actually live
in the PlayStation 2 collection retain their PS2 routing. Xbox 360 uses Xenia.

Supported inputs are `default.xbe`, an extracted DVD folder, and complete ZIP/7z
archives containing exactly one `default.xbe`. All game files are extracted
together into a local reusable cache, with path, size and free-space checks.
The original ROM archive is unchanged. A read-only audit on October 15, 2026
found this boot layout in all 41 catalog entries physically stored in the
Microsoft XBOX ROM collection. This establishes container support; it is not
gameplay verification of all 41 titles. ISO/XISO/CHD images are not converted by
this adapter and produce an explicit format error.

A fresh runtime installs the official Cxbx-Reloaded `CI-585c49a` release with
SHA-256 `010d1e85bee9f82f05ae57ca483e7ae61fecba06c1637bf6b5a74ca09b03bf43`.
It uses portable local settings, a new console profile, native resolution and
an XInput controller profile. Existing local emulator settings and saves are
preserved. Shared emulator data and the old collection settings are not
imported into a fresh profile.

A successful startup requires an owned, responsive `CxbxRender` game window
that stays open for three seconds. The configuration GUI alone is insufficient.
Startup errors and timeouts retain emulator logs and clean up only the new
launch's processes. Docking retains the validated renderer window handle;
process identity includes creation time. A brief renderer handoff during a
guest reboot does not immediately end the session. This startup check does not
establish that a game can be completed or that all emulation features work.

Save states, rewind, synthetic controller input and memory editing are not
implemented by this adapter. The physical controller uses Cxbx's native XInput
support. Normal in-game saves remain in the local portable console profile.

The collection's xemu installation is not used as a fallback: its configuration
referenced missing MCPX, BIOS and HDD files. GBox does not substitute unrelated
firmware or silently launch a different console emulator.

Sources: [official Cxbx release](https://github.com/Cxbx-Reloaded/Cxbx-Reloaded/releases/tag/CI-585c49a),
[official Cxbx source](https://github.com/Cxbx-Reloaded/Cxbx-Reloaded),
[xemu required files](https://xemu.app/docs/required-files/).
