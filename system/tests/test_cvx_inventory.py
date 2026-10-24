import json
from pathlib import Path
import pytest
from gbox import cvx_inventory as ci

MANIFEST = Path(__file__).resolve().parents[1] / "gbox" / "data" / "cvx_disc2_manifest.json"


def test_classify():
    assert ci.classify_member("adv.afs") == "afs_container"
    assert ci.classify_member("x.sfd") == "sfd_movie_stream"
    assert ci.classify_member("zzz.bin") == "other"


def test_manifest_counts():
    m = ci.load_manifest(MANIFEST)
    assert len(m["source_sha256"]) == 64
    assert m["disc_game_code"] == "GCDE08"
    assert m["member_count"] == len(m["members"]) == 48
    assert m["role_counts"]["afs_container"] == 8
    assert len(m["afs_entry_counts"]) == 8


@pytest.mark.skipif(not Path(ci.SOURCE_PATH).exists(), reason="owned disc not mounted")
def test_live_matches_manifest():
    from gbox.gcdisc import GCDisc
    d = GCDisc(ci.SOURCE_PATH)
    live = ci.build_manifest(d)
    m = ci.load_manifest(MANIFEST)
    assert live["afs_entry_counts"] == m["afs_entry_counts"]
    assert live["role_counts"] == m["role_counts"]
