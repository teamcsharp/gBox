"""Focused test for MK:DA inventory module — re-verifies identity hashes against
the actual owned disc bytes on this host (no reference-hash copying)."""
import hashlib
import sys

sys.path.insert(0, ".")

from gbox.mkda_inventory import verify, HASHES  # noqa: E402
from gbox.gcdisc import GCDisc  # noqa: E402

ISO = ("/home/ehm_eckx/gBox_alt/gbox-cache/modbase/cebc0be06b2ec8c7/"
       "Mortal Kombat - Deadly Alliance (USA).iso")


def test_iso_identity_streams_to_recorded_hash():
    assert verify(file_key="iso"), "ISO sha256 does not match recorded identity"


def test_dol_and_elf_identity():
    a = GCDisc(ISO)
    assert hashlib.sha256(a.dol()).hexdigest() == HASHES["dol"]
    assert hashlib.sha256(a.read("mk5gc_release.elf")).hexdigest() == HASHES["elf"]


def test_fst_tiles_disc_exactly():
    a = GCDisc(ISO)
    tot = sum(len(a.read(f)) for f in a.files)
    assert tot == 1453814660 and len(a.files) == 315, \
        f"FST does not tile exactly: {len(a.files)} files / {tot} bytes"


def test_fighter_ssfs_present():
    a = GCDisc(ISO)
    ssf = [f for f in a.files if f.startswith("artgc/scorpion.ssf")]
    assert ssf, "native scorpion slot missing"
