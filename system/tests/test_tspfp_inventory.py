import sys, pytest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gbox.tspfp_inventory import parse_c2n, c2n_census

SAMPLE = (
    "0xa160da60  assets/ts/models/guns/tipperarms/gamecube/output/tipperarms.gcr\n"
    "0x9ec12603  textures/cc95c8.gct\n"
    "0x22e3a6a2  assets/ts/models/chrs/trainkitten/gamecube/output/trainkitten.gcr\n"
)


def test_parse_and_census():
    rows = parse_c2n(SAMPLE)
    assert rows[0] == (0xA160DA60, "assets/ts/models/guns/tipperarms/gamecube/output/tipperarms.gcr")
    c = c2n_census(rows)
    assert c["members"] == 3 and c["character_models"] == 1 and c["gun_models"] == 1
    assert c["kinds"] == {"gcr": 2, "gct": 1}
    assert c["first_character_models"] == ["trainkitten.gcr"]


def test_rejects_malformed():
    with pytest.raises(ValueError):
        parse_c2n("not a line\n")
