# Original Xbox launch support

Original Xbox titles launch directly in Cxbx-Reloaded on Windows, with the
DOA3 USA exception below. They no longer
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

Automation prefers the release's standalone `cxbxr-ldr.exe /load <XBE>` entry,
with explicit kernel log arguments. This initializes the emulator directly
without opening the configuration GUI. The GUI's positional XBE launch remains
a fallback for manually installed runtimes that lack the standalone loader.
Startup dialogs include their actual message and button text in the failure
report; a dialog caption alone is insufficient for diagnosis. No warning is
clicked automatically and the emulator's warning settings remain unchanged.

Verified staging hashes keep an extracted archive reusable when the staging
cache updates its LRU timestamp. Changed content or stale staging records still
invalidate extraction. Older extraction markers require one initial extraction
under this identity; later cache touches do not unpack the game again.

The emulator starts without activation and is parked off-screen for docking.
It must not start minimized: Cxbx honors that flag and can leave its game client
at zero size. Renderer discovery includes owned child windows as well as
top-level windows.

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

## Dead or Alive 3 (USA)

The specific owned catalog entry `b8edf7040116f3aa` uses the
[DOA3 native Windows runtime v0.2](https://github.com/NoRain211/doa3-re/releases/tag/v0.2).
The collection's TC-001 executable uses SDK 3925; its Cxbx session remained
black while reporting `Unknown blend source factor: 0x40348`. Creating a stable
window did not establish a working game. Other Xbox titles keep their existing
Cxbx routing, including manually configured command overrides. Custom DOA3
builds retain Cxbx routing: the native program is verified only for the
unmodified USA disc, and mod playability is not established by this exception.

GBox enables the native runtime's supported `--vsync` option. This synchronizes
presentation to the display and avoids its default `DXGI_PRESENT_DO_NOT_WAIT`
path, which treats a temporarily busy presentation queue (`0x887A000A`,
`DXGI_ERROR_WAS_STILL_DRAWING`) as a fatal error. This changes presentation
settings without replacing the runtime binary or modifying the disc.

The native runtime is built privately from the user's existing USA disc. Its
generated program must match upstream's manifest. Only the exact supported
original XBE or the independently verified media/region-patched copy is accepted;
restoring those two certificate fields in a separate copy must produce the
exact upstream full-file checksum. The source ROM and its extraction remain
unchanged. No game code or assets are included in the gBox source repository.

The fixed runtime bundle is fetched from the authenticated Spark artifact store.
Its archive, executable, DLLs, release receipt and generated-program checksums
must match the reviewed build. Installation is local under the worker's runtime
directory. A separate persistent play-disc holds native `.recomp-storage` saves;
replacing runtime binaries does not delete saves. Mismatched files or unsafe
linked paths fail with an explanation and leave existing saves intact.

A successful native launch requires both its owned window and a nonuniform,
nonblack image read directly from its GPU back buffer. Startup captures a bounded
set of twelve back buffers, and the launch receipt retains a PNG of the proven
output. A blank window alone cannot satisfy this check. This establishes rendered
output; title screens, controls and gameplay still require actual session evidence.

Sources: [official Cxbx release](https://github.com/Cxbx-Reloaded/Cxbx-Reloaded/releases/tag/CI-585c49a),
[official Cxbx source](https://github.com/Cxbx-Reloaded/Cxbx-Reloaded),
[xemu required files](https://xemu.app/docs/required-files/).
