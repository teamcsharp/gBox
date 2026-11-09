"""Super Smash Bros. Ultimate's `data.arc` asset archive: a read-only index + extractor.

`data.arc` is one ~14.5 GB file inside the game's RomFS and holds every asset. Its header points at two big tables near
the end of the file: table 2 (the path/file tables) and table 3 (stream + additional file groups). Paths are stored only
as CRC32 hashes ("Hash40" = `(byte_length << 32) | crc32(path)`), split into full path / extension / parent directory /
file name, so a caller must ask for an exact path. File payloads are mostly Zstandard blocks.

Facts measured on the operator's own cart image (title 01006A800016E000, `Super Smash Bros Ultimate.xci`, RomFS entry
`data.arc` = 14,460,050,172 bytes; base game, pre-update format):

  header (0x38): magic 0xABCDEF98_76543210, header size 0x38, table-1 (file data) offset, table-2 offset,
                 table-2 header offset, table-3 header offset, unused
  table-2 header (0x68): header length, then the counts used below
  table-2 layout (all offsets relative to the table-2 header):
      0x068  8-byte  stream hash -> entry      (count 0x980)
      0x4C68 12-byte stream hash -> id         (count 0x980)
      0xBE68 4-byte  stream id -> data index   (count 0x1501)
      0x1126C 16-byte stream data (len, offset) (count 0xAA1)
      0x1BC7C 12-byte unknowns                 (count 0xE)
      0x1BD24 52-byte file groups              (count 0x64EE)
      0x163D7C 28-byte group data (u64 base offset, ..., u32 table-3 ref at +20) (count 0x8DE9 + 0x19A)
      0x25EFD0 8-byte single hashes            (count 0x64D1)
      0x291658 40-byte multi hashes            (count 0x73BBA)
      0x14A6B68 16-byte file records           (count 0x860D1 + 0x3A40)
  multi hash: full path hash+len+group(3), extension hash+len, path hash+len, file name hash+len, record, unknown
  file record: local offset in 4-byte units, compressed size, decompressed size, flags (0x03000000 = Zstandard,
               0x08000000 = the payload is described in table 3)

The container structure is FIX94's MIT-licensed `ssbu-arc-extract` description; every offset above was re-measured on
this file (a few tables are shifted by a handful of bytes from a naive size sum, so each table's base is located by
validating candidates instead of trusting arithmetic alone).
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

HEADER = "<7Q"
HEADER_SIZE = 0x38
FLAG_ZSTD = 0x03000000
FLAG_TABLE3 = 0x08000000


class ArcError(ValueError):
    """The archive is not the measured SSBU layout, or the requested file is absent."""


def path_hash(path: str) -> tuple[int, int]:
    """Smash's Hash40 parts: (CRC32 of the exact path, its byte length). '/' separators, case-sensitive."""
    raw = path.encode("utf-8")
    return zlib.crc32(raw) & 0xFFFFFFFF, len(raw)


def _enum3(blob: bytes, offset: int) -> int:
    return blob[offset] | (blob[offset + 1] << 8) | (blob[offset + 2] << 16)


class DataArc:
    """Read the archive index once, then extract files by exact path."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._file = open(self.path, "rb")
        try:
            self._read_header()
            self._read_tables()
        except Exception:
            self._file.close()
            raise

    # --- raw access ------------------------------------------------------------------------------

    def _read_at(self, offset: int, length: int) -> bytes:
        self._file.seek(offset)
        data = self._file.read(length)
        if len(data) != length:
            raise ArcError(f"{self.path.name}: short read at 0x{offset:x} ({len(data)} of {length} bytes)")
        return data

    def _read_header(self):
        magic, header_size, self.table1, self.table2, self.hdr2, self.hdr3, unused = \
            struct.unpack(HEADER, self._read_at(0, HEADER_SIZE))
        self.size = self.path.stat().st_size
        if magic != 0xABCDEF9876543210 or header_size != HEADER_SIZE:
            raise ArcError(f"{self.path.name}: not an SSBU data.arc (magic {magic:#x}, header {header_size:#x})")
        for name, value in (("table 1", self.table1), ("table 2 header", self.hdr2)):
            if not 0 < value < self.size:
                raise ArcError(f"{self.path.name}: {name} offset 0x{value:x} is outside the file")

    # --- tables ----------------------------------------------------------------------------------

    def _read_tables(self):
        head = struct.unpack("<26I", self._read_at(self.hdr2, 0x68))
        self.hdr_len = head[0]
        self.group_count = head[1]
        self.group_data_count = head[2] + head[8]
        self.multi_count = head[3]
        self.record_count = head[4] + head[9]
        self.single_count = head[6]
        self.stream_count = head[14]
        self.stream_id_count = head[15]
        self.stream_data_count = head[16]
        if not (self.multi_count and self.record_count and self.group_count):
            raise ArcError(f"{self.path.name}: table-2 header has empty tables")
        base = self.hdr2 + 0x68
        expected = {
            "groups": (base + 8 * self.stream_count + 12 * self.stream_count + 4 * self.stream_id_count
                       + 16 * self.stream_data_count + 12 * 0xE, 52, self.group_count),
            "group_data": (base + 8 * self.stream_count + 12 * self.stream_count + 4 * self.stream_id_count
                           + 16 * self.stream_data_count + 12 * 0xE + 52 * self.group_count, 28,
                           self.group_data_count),
            "multi": (base + 8 * self.stream_count + 12 * self.stream_count + 4 * self.stream_id_count
                      + 16 * self.stream_data_count + 12 * 0xE + 52 * self.group_count + 28 * self.group_data_count
                      + 8 * self.single_count, 40, self.multi_count),
            "records": (base + 8 * self.stream_count + 12 * self.stream_count + 4 * self.stream_id_count
                        + 16 * self.stream_data_count + 12 * 0xE + 52 * self.group_count
                        + 28 * self.group_data_count + 8 * self.single_count + 40 * self.multi_count, 16,
                        self.record_count),
        }
        self.groups_at, self.groups = self._locate("groups", *expected["groups"], self._valid_group)
        self.group_data_at, self.group_data = self._locate(
            "group_data", self.groups_at + 52 * self.group_count, 28, self.group_data_count, self._valid_group_data)
        self.multi_at, self.multi = self._locate(
            "multi", self.group_data_at + 28 * self.group_data_count + 8 * self.single_count, 40,
            self.multi_count, self._valid_multi)
        self.records_at, self.records = self._locate(
            "records", self.multi_at + 40 * self.multi_count, 16, self.record_count, self._valid_record)
        self.record_part1 = head[4]
        self.group_enum = [_enum3(self.groups, 52 * i + 5) for i in range(self.group_count)]
        self.group_base = [struct.unpack_from("<Q", self.group_data, 28 * i)[0] for i in range(self.group_data_count)]
        self.group_table3 = [struct.unpack_from("<I", self.group_data, 28 * i + 24)[0]
                             for i in range(self.group_data_count)]
        self.files: dict[tuple[int, int], int] = {}
        for i in range(self.multi_count):
            full, length = struct.unpack_from("<IB", self.multi, 40 * i)
            self.files.setdefault((full, length), i)

    def _locate(self, name: str, offset: int, stride: int, count: int, validator) -> tuple[int, bytes]:
        """Read a table, trying small shifts around the arithmetic offset and keeping the best-validated base."""
        span = min(count, 400)
        best, best_score = offset, -1
        for shift in range(-40, 41, 8):
            candidate = offset + shift
            if candidate < 0 or candidate + stride * span > self.size:
                continue
            blob = self._read_at(candidate, stride * span)
            score = sum(1 for i in range(span) if validator(blob, stride * i))
            if score > best_score or (score == best_score and abs(shift) < abs(best - offset)):
                best, best_score = candidate, score
        if best_score < span * 0.75:
            raise ArcError(f"{self.path.name}: {name} table not found (best candidate validated "
                           f"{best_score}/{span} entries)")
        self._file.seek(best)
        return best, self._file.read(stride * count)

    def _valid_group(self, blob: bytes, offset: int) -> bool:
        return (1 <= blob[offset + 4] <= 120 and _enum3(blob, offset + 5) < self.group_data_count
                and 1 <= blob[offset + 12] <= 120 and 1 <= blob[offset + 20] <= 120
                and struct.unpack_from("<I", blob, offset + 32)[0] < self.multi_count)

    def _valid_group_data(self, blob: bytes, offset: int) -> bool:
        base_offset = struct.unpack_from("<Q", blob, offset)[0]
        size = struct.unpack_from("<I", blob, offset + 12)[0]
        return base_offset < self.size and base_offset % 4 == 0 and size < (1 << 30)

    def _valid_multi(self, blob: bytes, offset: int) -> bool:
        lengths = (blob[offset + 4], blob[offset + 12], blob[offset + 20], blob[offset + 28])
        record = struct.unpack_from("<I", blob, offset + 32)[0]
        return (all(1 <= n <= 120 for n in lengths) and _enum3(blob, offset + 5) < self.group_count
                and record < self.record_count)

    def _valid_record(self, blob: bytes, offset: int) -> bool:
        local, comp, decomp, flags = struct.unpack_from("<4I", blob, offset)
        return local < (1 << 28) and flags < 0x10000000 and (comp == 0 or decomp >= comp)

    # --- lookup / extraction -----------------------------------------------------------------------

    def find(self, path: str) -> dict:
        key = path_hash(path)
        index = self.files.get(key)
        if index is None:
            raise ArcError(f"{path}: not in {self.path.name} (no entry for its Hash40)")
        entry = self._resolve(index)
        return entry | {"path": path, "hash40": key, "multi_index": index}

    def _record(self, index: int) -> tuple[int, int, int, int]:
        local, comp, decomp, flags = struct.unpack_from("<4I", self.records, 16 * index)
        return flags, local, comp, decomp

    def _row(self, index: int) -> tuple[int, int]:
        """(group index, file record index) of a multi-hash entry."""
        group = _enum3(self.multi, 40 * index + 5)
        record = struct.unpack_from("<I", self.multi, 40 * index + 32)[0]
        return group, record

    def _resolve(self, index: int) -> dict:
        group_index, record = self._row(index)
        if not (0 <= group_index < self.group_count and 0 <= record < self.record_count):
            raise ArcError(f"file record {record} / group {group_index} is out of range")
        group_data = self.group_enum[group_index]
        flags, local, comp, decomp = self._record(record)
        redirect = None
        if comp == 0:                                     # a shared file: this record names the real entry's hash row
            redirect = flags & 0x00FFFFFF
            if not (0 <= redirect < self.multi_count):
                raise ArcError(f"shared-file redirect {redirect} is out of range")
            group_index, record = self._row(redirect)
            group_data = self.group_enum[group_index]
            flags, local, comp, decomp = self._record(record)
            if comp == 0:
                raise ArcError("the file record redirects to another empty record")
        if flags & FLAG_TABLE3:
            group_data = self.group_table3[group_data]
            record = self.record_part1 + (flags & 0x00FFFFFF)
            flags, local, comp, decomp = self._record(record)
        if group_data >= len(self.group_base):
            raise ArcError(f"group data index {group_data} is out of range")
        offset = self.table1 + self.group_base[group_data] + (local << 2)
        if offset + comp > self.size:
            raise ArcError(f"file data 0x{offset:x}+{comp} runs past the end of the archive")
        return {"offset": offset, "size": comp, "decoded_size": decomp,
                "compressed": (flags & FLAG_ZSTD) == FLAG_ZSTD, "flags": flags, "record": record,
                "redirect": redirect, "shared": offset > self.table2,
                "local": local, "group_ref": group_data}

    def read(self, path: str) -> bytes:
        return self.read_entry(self.find(path))

    def read_entry(self, entry: dict) -> bytes:
        payload = self._read_at(entry["offset"], entry["size"])
        if not entry["compressed"]:
            return payload
        try:
            import zstandard
        except ImportError as exc:                        # pragma: no cover - a project dependency
            raise ArcError("zstandard is required to read this archive's compressed files") from exc
        try:
            return self._decode(payload, entry["decoded_size"])
        except ArcError:
            # A handful of table-3 records carry a stale/unclear group self-reference: the recorded decoded size and
            # compression still identify the payload, so try the nearby group bases. Measured on
            # fighter/mario/model/body/c00/eye_mario_w_nor.nutexb (its reference is 7 entries off).
            for delta in range(1, 33):
                for ref in (entry.get("group_ref", 0) - delta, entry.get("group_ref", 0) + delta):
                    if not 0 <= ref < len(self.group_base):
                        continue
                    offset = self.table1 + self.group_base[ref] + (entry.get("local", 0) << 2)
                    try:
                        data = self._read_at(offset, entry["size"])
                    except ArcError:
                        continue
                    try:
                        out = self._decode(data, entry["decoded_size"], raise_on_short=True)
                    except ArcError:
                        continue
                    return out
            raise

    @staticmethod
    def _decode(payload: bytes, decoded_size: int, raise_on_short: bool = False) -> bytes:
        import zstandard
        try:
            out = zstandard.ZstdDecompressor().decompress(payload, max_output_size=decoded_size)
        except Exception as exc:
            raise ArcError(f"zstandard frame is invalid: {exc}") from exc
        if len(out) != decoded_size:
            raise ArcError(f"decoded {len(out)} bytes, expected {decoded_size}")
        return out

    def exists(self, path: str) -> bool:
        return path_hash(path) in self.files

    def probe(self, paths) -> dict:
        out = {}
        for p in paths:
            try:
                out[p] = self.find(p)
            except ArcError:
                out[p] = None
        return out

    def close(self):
        self._file.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
