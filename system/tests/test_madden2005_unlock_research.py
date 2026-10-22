from gbox import madden2005_unlock_research as m


def test_wrong_revision_finds_nothing(tmp_path):
    p = tmp_path / "main.dol"
    p.write_bytes(b"Madden Cards\0unlocked\0")
    r = m.research(str(p))
    assert r["revision_match"] is False
    assert r["unlock_supported"] is False
    assert all(e["status"] == "not_present" for v in r["categories"].values() for e in v)


def test_categories_complete(tmp_path):
    p = tmp_path / "x"
    p.write_bytes(b"")
    assert set(m.research(str(p))["categories"]) == set(m.CATEGORIES)
