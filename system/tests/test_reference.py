"""The RE4 GameCube decompilation as a queryable reference: search, structure lookup, field offsets.

A tiny fixture tree stands in for the clone, because the tool's job is text handling - locating a definition, pairing an
annotated offset with its field name, and refusing what is not there.
"""
import pytest

from gbox import reference as R

SOURCE = '''
class cEm : public cModel {
public:
    s16 hp;               // 0x320
    s16 hp_max;           // 0x322
    Vec pos;              // 0x000
    u32 status;           // 0x3C4  setStatus bits (bit0 = in battle)
    u8 unannotated;
};

// a function that mentions the player
cPlayer* PlGet(void);
'''

OTHER = '''
struct cModel {
    Vec pos;    // 0x00
    Vec rot;    // 0x0C
};
'''


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    (tmp_path / "include").mkdir()
    (tmp_path / "src" / "game").mkdir(parents=True)
    (tmp_path / "include" / "em.h").write_text(SOURCE, encoding="utf-8")
    (tmp_path / "include" / "model.h").write_text(OTHER, encoding="utf-8")
    (tmp_path / "src" / "game" / "pl_class.cpp").write_text("void PlMove() { /* player */ }\n", encoding="utf-8")
    monkeypatch.setenv(R.ROOT_ENV, str(tmp_path))
    return tmp_path


def test_available_reports_the_corpus(corpus):
    state = R.available()
    assert state["present"] is True and state["headers"] == 2 and state["sources"] == 1
    assert "git clone" in state["note"]


def test_search_finds_lines_across_headers_and_sources(corpus):
    rows = R.search("player")
    assert {row["file"] for row in rows} == {"include/em.h", "src/game/pl_class.cpp"}
    assert all(row["line"] >= 1 and row["text"] for row in rows)


def test_search_is_case_insensitive_and_can_take_a_regex(corpus):
    assert R.search("cplayEr")
    rows = R.search(r"cPlayer\s*\*\s*PlGet", regex=True)
    assert [row["text"] for row in rows] == ["cPlayer* PlGet(void);"], "the regex matches the declaration line"


def test_search_respects_the_limit(corpus):
    assert len(R.search("e", limit=3)) == 3


def test_offsets_reads_the_annotated_fields_in_order(corpus):
    table = R.offsets("cEm")
    assert table["found"] is True and table["file"] == "include/em.h"
    assert list(table["fields"].items()) == [("pos", 0x00), ("hp", 0x320), ("hp_max", 0x322), ("status", 0x3C4)]
    assert "unannotated" not in table["fields"], "a field the decompilation does not annotate is not claimed"


def test_offsets_for_a_struct_and_for_something_absent(corpus):
    assert R.offsets("cModel")["fields"] == {"pos": 0x00, "rot": 0x0C}
    missing = R.offsets("cNothing")
    assert missing == {"name": "cNothing", "found": False, "fields": {}, "file": None}


def test_structures_lists_the_header_definitions(corpus):
    assert R.structures() == ["cEm", "cModel"]


def test_a_missing_corpus_is_reported_not_raised(tmp_path, monkeypatch):
    monkeypatch.setenv(R.ROOT_ENV, str(tmp_path / "nowhere"))
    assert R.available()["present"] is False
    assert R.search("anything") == [] and R.structures() == []
    assert R.offsets("cEm")["found"] is False
