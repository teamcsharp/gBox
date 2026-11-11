"""DOA5LR EBOOT.elf embedded resource-name table (request #2450).

The decrypted PS3 EBOOT.elf carries the same obfuscated resource-name cipher
as ``chara_common.bin`` (LFMO), but WITHOUT the leading ``/`` and as a flat
NUL-separated run (no plaintext labels except ``chara_dlccos_none``).  This
module extracts that run and cross-references base codes with an LFMO.  It is
a census tool: it does NOT decode names to roster characters.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# 41-char alphabet observed in LFMO names: [0-9 A-Z _ [ ] { @]
_NAME_RE = re.compile(rb"[0-9A-Z_\[\]{@]{15,160}")
# 5-char field0 followed by '@' (type, variant R..Z, 3-char family code)
_BASE_RE = re.compile(rb"^[0-9A-Z]{5}@")


@dataclass(frozen=True)
class ElfName:
    offset: int
    name: str

    @property
    def base(self) -> str:
        return self.name.split("@", 1)[0]


def extract_names(elf: bytes, start: int = 0x1081000, end: int = 0x10F0000):
    """NUL-delimited cipher names with a 5-char base code in [start, end)."""
    out = []
    pos = start
    for chunk in elf[start:end].split(b"\x00"):
        if _NAME_RE.fullmatch(chunk) and _BASE_RE.match(chunk):
            out.append(ElfName(pos, chunk.decode("latin1")))
        pos += len(chunk) + 1
    return out


def family(base: str) -> str:
    """3-char family code (base[2:5]); groups costume variants (R..Z)."""
    if len(base) != 5:
        raise ValueError(f"bad base code {base!r}")
    return base[2:]


def family_census(bases):
    """family -> sorted set of (type char, variant char) pairs."""
    fam: dict[str, set] = {}
    for b in bases:
        if len(b) == 5:
            fam.setdefault(family(b), set()).add((b[0], b[1]))
    return {k: sorted(v) for k, v in fam.items()}
