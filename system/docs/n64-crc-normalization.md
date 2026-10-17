# N64 checksum normalization for built images

The launch path for built `.z64`, `.v64` and `.n64` mods checks the header
checksum using the recognized IPL3 algorithm. If it is stale, gBox launches a
verified copy with corrected CRC1/CRC2 in big-endian byte order. The built mod,
its manifest directory and original game remain untouched.

This does not establish that a game boots, that a cast replacement is valid, or
that the GoldenEye/SM64 hang reports are fixed. CPU, RDP and RSP choices are
unchanged. The prior SM64 CPU comparison used different ROM bytes and sizes;
it is not a controlled demonstration of a CPU fix.

## Supported behavior

- The normalizer recognizes the existing `romexport.n64_cic` algorithms from
  the complete IPL3 block and needs the full `0x1000..0x101000` checksum window.
- A matching CRC returns the original path, including `.v64` and `.n64` files.
- A stale CRC produces a same-length `.z64` copy. Apart from reversible byte
  order conversion, only header bytes `0x10..0x17` can change.
- ROM length alone never triggers rewriting or padding. Valid 12 MiB and
  larger non-power-of-two images are preserved, as are arbitrary trailing
  payload bytes. Hardware-specific alignment is a separate build decision.
- Unknown/custom IPL3 or a short checksum window leaves the launch image
  unchanged with an explicit unverified diagnostic. Explicit `finalize_bytes`
  and `finalize_file` calls raise `UnsupportedChecksum` for these cases.
- Unknown magic, incomplete swapped units, oversized input or a source changing
  during its read fails explicitly; the normalizer does not guess missing data.

The upstream [libdragon ROM builder](https://github.com/DragonMinded/libdragon/blob/trunk/tools/n64tool.c)
uses 16 KiB default alignment and supports custom IPL3 and explicit sizes. This
supports keeping hardware padding policy separate from checksum repair; a
power-of-two file length is not a general ROM validity test.

## Integrity and publication

Reads accept regular files up to the existing N64 reader's 128 MiB limit. They
check descriptor size before allocation, use a bounded read with one sentinel
byte, and reject size/time changes observed during the read.

The launch cache remains outside the mod's manifest directory. Its versioned
filename contains SHA-256 of the entire captured source. Every cache hit must
match the entire expected output byte for byte, including bytes outside the
header checksum window. File size/mtime and a valid header CRC are insufficient
cache evidence. Returned receipts include source/output SHA-256, CIC, CRC pair,
size, cache reuse/conflicts and `gameplay_verified: false`.

`finalize_file` never replaces an existing output, including a hard link or
symlink. Publication first writes and verifies a unique temporary file in the
same directory, then atomically hard-links it to the absent destination.
Filesystems without same-directory hard links fail explicitly. Temporary files
are removed on failure. Cache writers use the same exclusive publication and
reuse a concurrent winner only after full comparison. A corrupt/conflicting
cache file stays untouched; up to 16 numbered slots permit automatic recovery.
A symlinked cache directory is refused.

## Validation

Tests cover equal size/mtime but changed source content, a cached image with a
valid header CRC and wrong payload, existing outputs and source aliases,
concurrent publication, publication failures, bounded reads, all three byte
orders, and preservation of valid/non-power-of-two images. Synthetic tests
isolate filesystem behavior; separate owned-file tests use actual IPL3 bytes
from GoldenEye and Mario builds without mocking CIC detection. They verify the
CRC independently through the existing GoldenEye checksum implementation and
leave those source builds unchanged.

Set `GBOX_N64_GOLDENEYE` and `GBOX_N64_MARIO` to local owned builds for those
checks. Missing private fixtures are reported as skips. No emulator is launched
by the suite. A same-ROM, same-core, controlled runtime check and gameplay
acceptance are still required before resolving a reported hang.
