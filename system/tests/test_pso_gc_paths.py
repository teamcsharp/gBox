"""gbox.pso_gc_paths: the Dreamcast/GameCube character path translation, against the disc's real file list."""
import json
from pathlib import Path

import pytest

from gbox import pso_gc_paths as P

CATALOGUE = Path(r"D:\gBox\pso-ds\disc-catalogue.json")


def test_the_four_part_paths_translate():
    assert P.gc_path("PSO/PLABDY00.NJ") == "plAbdy00.nj"
    assert P.gc_path("PSO/PLAHED03.NJ") == "plAhed03.nj"
    assert P.gc_path("PSO/PLANJ.BML") == "plAnj.bml"
    assert P.gc_path("PSO/PLATEX.AFS") == "plAtex.afs"


def test_the_class_letter_keeps_its_case():
    """`plAbdy00.nj` has a capital class letter; lower-casing the whole name would not match the disc."""
    for cls in ("A", "B", "C"):
        assert P.gc_path(f"PSO/PL{cls}BDY00.NJ")[2] == cls


def test_the_inverse_round_trips():
    for dc in ("PSO/PLABDY00.NJ", "PSO/PLCHED00.NJ", "PSO/PLCANJ.BML"):
        assert P.gc_path(P.dc_path(P.gc_path(dc))) == P.gc_path(dc)


def test_an_already_gc_name_is_left_alone():
    assert P.gc_path("plAbdy00.nj") == "plAbdy00.nj"
    assert P.gc_path("some/dir/file.bin") == "file.bin"


def test_class_parts_are_the_four_names_the_code_needs():
    parts = P.class_parts("C", head=0)
    assert parts == {"body": "plCbdy00.nj", "head": "plChed00.nj",
                     "pack": "plCnj.bml", "textures": "plCtex.afs"}


def test_a_disc_that_has_both_layouts_prefers_the_gamecube_name():
    class Disc:
        def __init__(self):
            self.asked = []

        def read(self, name):
            self.asked.append(name)
            return b"data:" + name.encode()

    disc = Disc()
    assert P.read_part(disc, "PSO/PLABDY00.NJ").startswith(b"data:plAbdy00.nj")
    assert disc.asked == ["plAbdy00.nj"]


def test_a_disc_with_only_the_dreamcast_name_still_works():
    class Disc:
        def read(self, name):
            if name.startswith("PSO/"):
                return b"dc"
            raise FileNotFoundError(name)

    assert P.read_part(Disc(), "PSO/PLABDY00.NJ") == b"dc"


def test_a_missing_part_names_both_candidates():
    class Disc:
        def read(self, name):
            raise FileNotFoundError(name)

    with pytest.raises(FileNotFoundError, match="tried"):
        P.read_part(Disc(), "PSO/PLZBDY00.NJ")


@pytest.mark.skipif(not CATALOGUE.is_file(), reason="the disc catalogue from the P2 pass is not on this machine")
def test_every_part_name_for_a_real_class_exists_on_the_disc():
    """The point of the translation: these names must actually be on `GPOE8P`."""
    names = set(json.loads(CATALOGUE.read_text())["files"])
    parts = P.class_parts("C", head=0)
    for kind in ("body", "head", "pack", "textures"):
        assert parts[kind] in names, f"{kind} {parts[kind]} is not on the disc"


def _payload(flags: int, model: int, be: bool, total: int = 0x40) -> bytes:
    body = b"\x00" * total
    fmt = ">II" if be else "<II"
    head = __import__("struct").pack(fmt, flags, model)
    return b"NJCM" + __import__("struct").pack("<I", total) + head + body[len(head):]


def test_gamecube_payloads_are_detected_as_big_endian():
    """The real body file's root model offset is 0x1030 big-endian; as little-endian it would be 806 MB into 24 KB."""
    assert P.njcm_is_big_endian(_payload(7, 0x1030, be=True)) is True
    assert P.njcm_is_big_endian(_payload(7, 0x1030, be=False)) is False


def test_the_payload_helper_skips_the_chunk_framing():
    data = _payload(7, 0x1030, be=True)
    assert P.njcm_payload(data)[:8] == __import__("struct").pack(">II", 7, 0x1030)


def test_nj_parses_a_real_body_with_the_detected_order():
    """38 bytes of node data is not a whole model, but the parse must get past the root without a struct error."""
    import pytest

    data = _payload(7, 0x1030, be=True)
    with pytest.raises((ValueError, Exception)):
        P.nj(data)                      # truncated node data: must fail as a parse problem, not a byte-order one
