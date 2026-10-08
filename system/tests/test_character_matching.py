from gbox.characters import best_match


def test_canonical_slug_wins_over_shared_alias():
    remake = {"slug": "re4r_leon", "name": "Leon (RE4 2023)", "aliases": ["leon"]}
    original = {"slug": "leon", "name": "Leon S. Kennedy", "aliases": []}
    assert best_match([remake, original], "leon") is original
    assert best_match([original, remake], "re4r_leon") is remake


def test_names_aliases_and_fuzzy_queries_still_match():
    entry = {"slug": "sa2_rouge", "name": "Rouge the Bat", "aliases": ["rouge"]}
    assert best_match([entry], "Rouge the Bat") is entry
    assert best_match([entry], "rouge") is entry
    assert best_match([entry], "extract rouge bat") is entry
    assert best_match([entry], "unrelated") is None
