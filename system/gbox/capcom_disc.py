"""Capcom Generations (PS1) disc writer: sector-exact .DEE replacement in a raw MODE2/2352 image.

Builds on gbox.psxdisc.RawBin (EDC/ECC rewrite) and gbox.capcom_dee (pack/unpack).
A replacement must fit the original file's sector span (the ISO directory
record is not rewritten); shorter data is zero-padded to the original file size,
which is safe because the DEE header carries its own compressed length.
Originals are never modified: output is a copy.
"""
from __future__ import annotations

import shutil

from . import capcom_dee as dee
from .psxdisc import RawBin


class DeeDoesNotFit(ValueError):
    pass


def replace_dee(bin_in: str, bin_out: str, replacements: dict[str, bytes]) -> dict:
    """Copy bin_in to bin_out and replace each ISO path (e.g. '1943/43CHAR7.DEE')
    with a complete .DEE file image. Returns {name: sectors_rewritten}."""
    if bin_in == bin_out:
        raise ValueError("refusing to modify the original image in place")
    shutil.copyfile(bin_in, bin_out)
    disc = RawBin(bin_out)
    done = {}
    try:
        for name, blob in replacements.items():
            if name not in disc.files:
                raise KeyError(name)
            lba, size = disc.files[name]
            span = (size + 2047) // 2048 * 2048
            if len(blob) > span:
                raise DeeDoesNotFit(f"{name}: {len(blob)} bytes > {span} byte sector span")
            hdr = dee.dee_header(blob)
            if hdr["comp_len"] != len(blob) - dee.DEE_HEADER_SIZE:
                raise ValueError(f"{name}: header comp_len inconsistent with data")
            done[name] = disc.write_data(lba, blob.ljust(size, b"\0"))
    finally:
        disc.close()
    return done


def read_dee_tim(bin_path: str, name: str) -> bytes:
    d = RawBin(bin_path, writable=False)
    try:
        return dee.dee_unpack(d.read(name))
    finally:
        d.close()
