# CHD fingerprint version dispatch

The shared disc listing used by `assimilate` selects its CHD reader from the
validated header: version 4 uses `PSXDisc`; version 5 uses `ChdDisc`. Unknown
versions and incomplete headers fail explicitly. Both routes read the requested
prefix or bounded executable range directly, rather than reading a whole member
and slicing it afterward. Listing closes the reader even when collection fails;
both CHD reader constructors close opened handles if parsing fails.

Version 4 `PSXDisc.read(name)` retains its existing full-file behavior. Optional
`offset` and `size` arguments provide bounded ranges. Shared listing limits must
be nonnegative integers; zero means no bytes/entries for that phase.

Read-only owned-source verification reproduced the original failure for Devil
May Cry 2 (USA) (Disc 1), then fingerprinted the same source successfully:

- CHD v5, declared content SHA1 `e9b349350264d1f894cf130a3ddf853ea561c954`.
- Nine files; executable `SLUS_204.84`, 4,446,168 bytes.
- Executable SHA256 `09040e703963acd105a8f52e72f850dd8c179d5b57934dfca70e4db763f422f0`.
- 4,134 executable strings and observed CRI AFS signatures.
- Twenty member reads requested 9,133,906 bytes total; largest requested range
  was the executable, and the reader handle closed. No whole image was exported.

Source size, modification time and recomputed CHD header digest matched before
and after. The declared CHD SHA1 was not independently recomputed over the full
logical image. Fingerprinting provides source evidence; it does not prove a
complete character reader/writer, a playable mod, unlock support or completion
of any broader inbox request.

Tests use actual synthetic v4 and v5 images, constructor/listing failure paths,
range boundaries, invalid options and optional owned fixtures. Set
`GBOX_DMC2_PS2_CHD` for the exact owned Disc1 test and `GBOX_ETM_PS2_CHD` for the
existing Enter the Matrix reader test.
