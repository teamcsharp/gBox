# Original Xbox launch support

Original Xbox titles launch directly in Cxbx-Reloaded on Windows, with the
DOA3 USA exception below. They no longer
go through the collection's RocketLauncher wrapper. The old Microsoft XBOX
launcher selected PCSX2 and failed with `RLDLL.Start - Exception thrown: -2` on
the operator's PCs before an Xbox game was running.

The adapter recognizes older `windows_native` catalog rows by their physical
Xbox collection path. Entries in virtual Xbox lists whose files actually live
in the PlayStation 2 collection retain their PS2 routing. Xbox 360 uses Xenia.

Supported inputs are `default.xbe`, an extracted DVD folder, a recognized Xbox
ISO/XISO image, and complete ZIP/7z archives containing exactly one `default.xbe`
or one disc image. All game files are extracted
together into a local reusable cache, with path, size and free-space checks.
The original ROM archive is unchanged. A read-only audit on October 15, 2026
found this boot layout in all 41 catalog entries physically stored in the
Microsoft XBOX ROM collection. This establishes container support; it is not
gameplay verification of all 41 titles. CHD and unknown disc layouts still
produce an explicit format error.

Disc images use the official portable XboxDev `extract-xiso`
`build-202609111233` Win64 release. The download archive and executable must
match their pinned SHA-256 checksums. Installation is private to the worker;
the system PATH and shared emulator folders are unchanged. Recognized XDVDFS
descriptors support XISO and full-disc layouts. The descriptor and root table
must fit the input image, and the complete bounded tool listing must have safe,
unique Windows paths, consistent counts/sizes, and one root `default.xbe`.
Xbox 360 images cannot pass the original-Xbox boot-file requirement.

Extraction explicitly disables media patching with `-m`; it never rewrites the
input image or changes XBE bytes. It publishes a DVD cache only after its exact
file inventory and hashes are checked and the source image is rehashed. The
cache key uses the complete image SHA-256, and reuse checks every cached file.
Incomplete or changed caches fail without being overwritten. Tool output and
runtime are bounded, including malformed or cyclic-image failures. Emulator
saves remain outside the disposable extraction cache.

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

The owned catalog entry `b8edf7040116f3aa` and the independently verified
`quickswap-xbox` copy `f03a801797a90506` use the
[DOA3 native Windows runtime v0.2](https://github.com/NoRain211/doa3-re/releases/tag/v0.2).
The collection's TC-001 executable uses SDK 3925; its Cxbx session remained
black while reporting `Unknown blend source factor: 0x40348`. Creating a stable
window did not establish a working game. Other Xbox titles keep their existing
Cxbx routing, including manually configured command overrides. DOA3 asset builds
use the same native runtime, provided their executable still matches the exact
supported USA checksum. Builds that modify guest executable code fail this check;
they are not silently routed to Cxbx. Native routing alone does not establish
that replacement geometry, textures or animations are playable.
The QuickSwap alias is restricted to that library and the exact relative path
`Dead or Alive 3 (USA) (En,Ja).7z`. A real extraction produced the supported XBE
SHA-256 `e523dd15d0765899a43a1824c023e0219d129e9a8b41e8213e4e645755d2bfa3`.
Other similarly named archives, including the larger full-DVD copy, do not gain
native routing from their display title. The XBE checksum is checked again
before every native launch.

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
directory. Each reviewed catalog identity has its own persistent play-disc holding
native `.recomp-storage` saves; the original entry's existing location stays the same.
Each named asset build and each content revision gets a separate play-disc and
save directory, keyed by the build identity and the complete source inventory.
Switching between cast variants cannot overwrite the original disc or its saves.
An unchanged build reuses its verified view; rebuilding changed assets retains
the prior revision and its saves. Personal saves are not imported into mod builds.
Replacing runtime binaries does not delete saves. Mismatched files or unsafe
linked paths fail with an explanation and leave existing saves intact.

A successful native launch requires both its owned window and a nonuniform,
nonblack image read directly from its GPU back buffer. Startup captures a bounded
set of twelve back buffers, and the launch receipt retains a PNG of the proven
output. A blank window alone cannot satisfy this check. This establishes rendered
output; title screens, controls and gameplay still require actual session evidence.

The native adapter can inspect guest RAM through a read-only bridge. It opens
only its already owned renderer PID with query/read rights, checks its creation
time and exact executable/source checksums, and requires one unique 64 MiB RAM
allocation matching the reviewed XBE's mapped header and all immutable executable
sections. The only normalized header fields are the documented section reference
counts changed by upstream's load/unload-section routines; their exact addresses
are included in the verification metadata. Other changed header or code bytes,
ambiguous allocations and changed process identities fail closed.

`query_memory_map` reports the verified x86 little-endian guest address space,
the source-derived image analysis range and retail entry point. Reads support
RAM at zero and its native cached/physical aliases. Every read rechecks the
process, source and immutable RAM anchors before returning data. The image span
includes the game's persistent profile data without initially capturing the
entire heap. This interface does not expose writes, unlock switches or synthetic
input; locating and validating game-specific flags remains separate research.

Sources: [official Cxbx release](https://github.com/Cxbx-Reloaded/Cxbx-Reloaded/releases/tag/CI-585c49a),
[official Cxbx source](https://github.com/Cxbx-Reloaded/Cxbx-Reloaded),
[official XboxDev extractor release](https://github.com/XboxDev/extract-xiso/releases/tag/build-202609111233),
[pinned XboxDev extractor source](https://github.com/XboxDev/extract-xiso/blob/build-202609111233/extract-xiso.c),
[xemu required files](https://xemu.app/docs/required-files/).
