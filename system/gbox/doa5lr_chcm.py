"""Reader for Dead or Alive 5 Last Round (PS3 JP, BLJM61258) character containers.

Owned source identity
---------------------
  /mnt/gbox/quickswap2/Emulation/PS3/Dead or Alive 5 - Last Round (Japan).7z
  sha256 = 85b2366710c82b8dc9da5ca2cfbcb818c95f8113078babe79c7731ca1de13ac7
  (8,051,996,479 B; PS3 Japan disc folder dump, BLJM61258, app 04.6500.
   Catalog label ``windows_native`` is disconfirmed: the owned build is PS3.)

Containers (USRDIR/)
--------------------
  chara_common.lnk : CHCM archive (primary character container, 1,809,051,648 B)
  chara_common.bin : LFMO index  (141,373 B, 2355 obfuscated slot names)

CHCM layout (verified against the owned build's byte-exact samples)
-------------------------------------------------------------------
  @0x00  magic "CHCM"
  @0x08  u64 BE  entry_count
  @0x10  u64 BE  file_size  (must equal the on-disk size; decisive anchor)
  @0x18  u64 BE  alignment hint (2048 for chara_common.lnk)
  @0x20  u64 BE  table_end  (0x12800 for chara_common.lnk; table occupies
                             0x28 .. table_end)
  @0x28  entry_count * 32-byte entries, BIG-endian, each:
         (u64 size, u64 size_dup, u64 zero, u64 absolute_offset)
  Entry payloads live at ``absolute_offset`` (2048-aligned), starting at
  table_end rounded up per the alignment hint.

Known edge rows in chara_common.lnk (skipped, not fatal):
  * rows 2345 / 2352: near-EOF offsets whose declared size crosses EOF.
  * row 2354: offset 0 (footer record).

LFMO layout (chara_common.bin)
------------------------------
  @0x00  magic "LFMO"
  @0x08  u32 BE  entry_count (2355 -- agrees with CHCM entry_count)
  @0x0c  u32 BE  32 (record-stride hint)
  @0x10  u32 BE  header size (40)
  @0x28  entry_count * 12-byte rows: (u32 idx, u32 zero, u32 record_offset)
  record_offset -> null-terminated ~49-byte OBFUSCATED slot-name string.

Name deobfuscation is NOT yet derived: observed plaintext anchors are the
literal "chara_common.order" at LFMO offset 28300 and charset-shifted names
such as "BRAK3", "BTAK3", "/2V963@1S100@...". Decoding the shift is the next
milestone (see request #2450 checkpoint). The names are therefore kept as raw
bytes here -- never presented as decoded character names.

Payloads (e.g. the 80-byte entry 0) begin with obfuscated-looking bytes
(0000a670 0000737e ...) from the same family as the DATA/ G1L_ banks; CHCM
extraction yields byte-exact container members, not decoded meshes.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

CHCM_MAGIC = b"CHCM"
LFMO_MAGIC = b"LFMO"

CHCM_HEADER_SIZE = 0x28
CHCM_ENTRY_SIZE = 32
LFMO_HEADER_SIZE = 40
LFMO_ROW_SIZE = 12
ALIGN = 2048


class ChcmError(ValueError):
    """Raised when a CHCM/LFMO structure fails structural validation."""


def _is_edge(size: int, size_dup: int, offset: int, file_size: int) -> bool:
    return bool(offset == 0 or size == 0 or size != size_dup
                or offset % ALIGN or offset + size > file_size)


@dataclass(frozen=True)
class ChcmEntry:
    index: int
    size: int
    size_dup: int
    reserved: int
    offset: int

    def is_edge(self, file_size: int) -> bool:
        """Footer/edge rows that must be skipped rather than fail the parse."""
        return _is_edge(self.size, self.size_dup, self.offset, file_size)


@dataclass(frozen=True)
class ChcmArchive:
    file_size: int
    alignment: int
    table_end: int
    entries: tuple[ChcmEntry, ...]

    def validated(self) -> list[ChcmEntry]:
        out = []
        prev = -1
        for e in self.entries:
            # skip edge rows: footer (offset 0), duplicated-size mismatch,
            # declared size crossing EOF (2345/2352 class), non-aligned offsets.
            if _is_edge(e.size, e.size_dup, e.offset, self.file_size):
                continue
            if e.offset < prev:
                raise ChcmError(f"non-monotonic offset at entry {e.index}")
            prev = e.offset
            out.append(e)
        return out


def parse_chcm(buf: bytes, file_size: int | None = None) -> ChcmArchive:
    if buf[:4] != CHCM_MAGIC:
        raise ChcmError(f"bad magic {buf[:4]!r}")
    if file_size is None:
        file_size = len(buf)
    count, fsz, align, table_end = struct.unpack_from(">QQQQ", buf, 8)
    if fsz != file_size:
        raise ChcmError(f"header file_size {fsz} != actual {file_size}")
    expected = CHCM_HEADER_SIZE + count * CHCM_ENTRY_SIZE
    if table_end < expected:
        raise ChcmError(f"table_end {table_end} too small for {count} entries")
    entries = []
    for i in range(count):
        off = CHCM_HEADER_SIZE + i * CHCM_ENTRY_SIZE
        size, size_dup, zero, abs_off = struct.unpack_from(">QQQQ", buf, off)
        entries.append(ChcmEntry(i, size, size_dup, zero, abs_off))
    return ChcmArchive(fsz, align, table_end, tuple(entries))


def extract_entry(archive: ChcmArchive, data: bytes, entry: ChcmEntry) -> bytes:
    if entry.offset + entry.size > len(data):
        raise ChcmError(f"entry {entry.index} payload exceeds buffer")
    payload = data[entry.offset : entry.offset + entry.size]
    if len(payload) != entry.size:
        raise ChcmError(f"entry {entry.index}: short read {len(payload)} != {entry.size}")
    return payload


@dataclass(frozen=True)
class LfmoRecord:
    index: int
    reserved: int
    record_offset: int
    name: bytes  # raw obfuscated bytes; deobfuscation pending


def parse_lfmo(buf: bytes) -> list[LfmoRecord]:
    if buf[:4] != LFMO_MAGIC:
        raise ChcmError(f"bad magic {buf[:4]!r}")
    count = struct.unpack_from(">I", buf, 8)[0]
    records = []
    for i in range(count):
        off = LFMO_HEADER_SIZE + i * LFMO_ROW_SIZE
        idx, reserved, rec_off = struct.unpack_from(">III", buf, off)
        end = buf.index(b"\x00", rec_off)
        records.append(LfmoRecord(idx, reserved, rec_off, buf[rec_off:end]))
    return records
