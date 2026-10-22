import hashlib
from gbox import sfxt_unlock as s
from gbox import game_unlocks as gu


def test_profile_for_pending_and_unverified():
    p = gu.profile_for({"game_id": s.GAME_ID, "platform": s.PLATFORM})
    assert p["status"] == "pending_research" and p["verified"] is False and p["profile"] is None
    assert p["guard"]["xex_sha256"] == s.OWNED_XEX_SHA256


def test_other_platform_not_matched():
    assert gu.profile_for({"game_id": "c2e913cb9acdd381", "platform": "windows_native"})["status"] == "unsupported"


def test_digests_are_64_hex():
    for d in (s.OWNED_ISO_SHA256, s.OWNED_XEX_SHA256):
        assert len(d) == 64 and int(d, 16) >= 0


def test_guard_rejects_wrong_bytes():
    assert s.revision_guard_xex(b"XEX2" + b"\0" * 8)["match"] is False
    assert s.revision_guard_xex(b"")["match"] is False
