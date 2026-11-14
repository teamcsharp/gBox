"""AES-128-XTS for Switch XCI/NCSD card images (compatibility shim).

The previous revision of this module called
``AES.new(key, AES.MODE_XTS, iv)``; pycryptodome (incl. 3.23.0) does not
implement the XTS mode, so the module was unimportable and every dependent
(probe script, old test) was broken.  The working manual AES-XTS
implementation -- ECB core with a GF(2^128) tweak multiply, conformant with
the NIST SP 800-38E F.1 known-answer test -- now lives in
``gbox.formats.nsw_xts_manual``.  This module re-exports that public API so
existing ``gbox.formats.nsw_xts`` imports keep working unchanged.
"""
from __future__ import annotations

from gbox.formats.nsw_xts_manual import (
    SECTOR_SIZE,
    XtsKeyError,
    decrypt_sector,
    decrypt_sectors,
    find_magic,
    make_xts_cipher,
    sector_iv,
)

__all__ = [
    "SECTOR_SIZE",
    "XtsKeyError",
    "decrypt_sector",
    "decrypt_sectors",
    "find_magic",
    "make_xts_cipher",
    "sector_iv",
]
