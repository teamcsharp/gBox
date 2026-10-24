"""Nintendo Switch game-card (XCI) inventory: NCA header-name reading over the shared HFS0 parser.

This module used to carry its own private HFS0 parser, which duplicated and contradicted
``gbox.formats.hfs0`` (wrong 0x1000 file-table offset, wrong ``<III`` 64-byte entry layout, wrong
hashed-size handling).  It now delegates all HFS0 geometry to the one shared reader and only adds
the Switch-specific concern that lives above HFS0: reading the plaintext NCA header-name slots
(main/program/control ids) at fixed offsets inside each ``*.nca`` member.

This is a LISTING reader only -- it parses plaintext headers to enumerate what a card holds.  It
never decrypts content: Hash0/HashIV/NAVI tables and NCA body sections are AES-encrypted with
titlekeys and out of scope.  ``gbox.formats.disc.listing`` drives the real inventory through
``gbox.formats.hfs0.list_card``; this module is a thin, testable complement for NCA names.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import BinaryIO, Callable, List

from . import hfs0

NCA3_MAGIC = b"NCA3"
# plaintext header-name slots inside an NCA header (main/program/control), fixed offsets
NCA_HEADER_NAME_SLOTS = (0x200, 0x220, 0x240)


@dataclass(frozen=True)
class Hfs0Entry:
    """Alias for hfs0.Hfs0Entry kept for callers that imported the old symbol."""

    name: str
    offset: int
    size: int
    hashed_size: int
    sha256: str

    @classmethod
    def from_shared(cls, e: hfs0.Hfs0Entry) -> "Hfs0Entry":
        return cls(e.name, e.offset, e.size, e.hashed_size, e.sha256)


@dataclass
class XciInfo:
    hfs0: dict = field(default_factory=dict)          # partition name -> list[Hfs0Entry]
    ncas: List[dict] = field(default_factory=list)    # {partition, entry, offset, size, header_names}
    warnings: List[str] = field(default_factory=list)


def _ascii(data: bytes) -> str:
    return data.split(b"\0", 1)[0].rstrip().decode("ascii", "replace")


def read_nca_header_names(read_at: Callable[[int, int], bytes], nca_offset: int) -> List[str]:
    """Plaintext NCA3 header-name slots (main/program/control ids); [] if the member is not an NCA3."""
    if read_at(nca_offset, 4) != NCA3_MAGIC:
        return []
    names = []
    for slot in NCA_HEADER_NAME_SLOTS:
        raw = read_at(nca_offset + slot, 32)
        name = _ascii(raw)
        if name:
            names.append(name)
    return names


def _file_read_at(path: str) -> Callable[[int, int], bytes]:
    fh: BinaryIO = open(path, "rb")

    def read_at(off: int, size: int) -> bytes:
        fh.seek(off)
        return fh.read(size)

    read_at.close = fh.close  # type: ignore[attr-defined]
    return read_at


def list_card_ncas(path: str) -> XciInfo:
    """Enumerate NCA header names for every ``*.nca`` member of an owned .xci via the shared HFS0 parser."""
    read_at = _file_read_at(path)
    try:
        return list_card_ncas_from(read_at)
    finally:
        read_at.close()  # type: ignore[attr-defined]


def list_card_ncas_from(read_at: Callable[[int, int], bytes]) -> XciInfo:
    info = XciInfo()
    try:
        parts = hfs0.list_card(read_at)
    except ValueError as exc:
        info.warnings.append(str(exc))
        return info
    for pname, entries in parts.items():
        info.hfs0[pname] = [Hfs0Entry.from_shared(e) for e in entries]
        for e in entries:
            if e.size < 0x300:
                continue
            try:
                names = read_nca_header_names(read_at, e.offset)
            except (ValueError, IndexError):
                names = []
            if names:
                info.ncas.append({"partition": pname, "entry": e.name, "offset": e.offset,
                                  "size": e.size, "sha256": e.sha256, "header_names": names})
    return info


# Back-compat alias so old callers/tests referencing ``list_xci`` keep a sane entry point.
def list_xci(path: str) -> XciInfo:
    return list_card_ncas(path)
