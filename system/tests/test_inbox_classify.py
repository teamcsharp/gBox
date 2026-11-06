"""The inbox classifier: what a ticket is, from its title alone."""
import pytest

from gbox.decrypt_lab import INBOX_CATCH_ALL, classify_request


@pytest.mark.parametrize("title,expected", [
    ("Improve Resident Evil 5 - Gold Edition: combat", "improve a title"),
    ("improve re4 mercs", "improve a title"),                       # case does not matter
    ("Mercenaries 010018100CD46000 rank_not_verified e65", "rank not verified"),
    ("<agent-message from=x>", "agent message"),
    ("<cross-session-message from=uds>", "agent message"),
    ("<pasted_content id=\"c9c3\">", "pasted content"),
    ("<ide_opened_file>The user opened the file", "editor context"),
    ("Build report: cast_crazy_taxi_usa_sonic_ad", "build report"),
    ("Custom build: Dead or Alive 3 (USA) - DOA3", "custom build"),
    ("Extraction engineering: Marvel vs. Capcom", "extraction"),
    ("Launch failed: re5", "launch failure"),
    ("stop crashes session", "crash report"),
    ("Mercenaries BLUS30491 round", "mercenaries"),
    ("RAM hook: RE5", "RAM hook"),
    ("unlock all costumes", "unlocked content"),
    ("Native character replacement for RE5", "character replacement"),
    ("what does the gidra do here", "gidra systems"),
    ("hermes lanes are idle", "hermes fleet"),
])
def test_a_ticket_is_classified_by_what_it_is(title, expected):
    assert classify_request(title) == expected


def test_the_catch_all_is_only_for_titles_nothing_matches():
    assert classify_request("Thrasher") == INBOX_CATCH_ALL
    assert classify_request("") == INBOX_CATCH_ALL


def test_order_prefers_the_generated_classes_over_subject_matter():
    """A generated report that happens to mention mercenaries is still a generated report of its own kind."""
    assert classify_request("Build report: mercenaries test") == "build report"
    assert classify_request("<pasted_content id=\"x\"> hermes lanes") == "pasted content"
    assert classify_request("Improve mercenaries: helipad") == "improve a title"


def test_a_prefix_rule_does_not_fire_mid_title():
    """`unlock` and `improve` are prefix rules: a mention inside a sentence is subject matter, not the class."""
    assert classify_request("the game will unlock costumes") != "unlocked content"
    assert classify_request("how do I improve aim") != "improve a title"
@pytest.mark.parametrize("title,expected", [
    ("GAP: unlock all characters", "gap: missing content"),
    ("Session observation: Crazy Taxi (USA)", "session observation"),
    ("JSRF not playing", "playability issue"),
    ("freezes during character select", "playability issue"),
])
def test_the_named_leftovers_have_their_own_classes(title, expected):
    assert classify_request(title) == expected