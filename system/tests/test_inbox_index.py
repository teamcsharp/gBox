"""Parent lookup preserves imported inbox meaning while avoiding repeated scans."""
import copy
import random

from gbox import inbox


def legacy_organize(requests):
    # parent_for remains the public, unindexed reference for individual callers.
    out = [r | {"automated": inbox.automated(r), "parent_request_id": inbox.parent_for(r, requests)}
           for r in requests]
    by_id = {r["id"]: r for r in out}
    for request in out:
        seen = {request["id"]}
        parent = request.get("parent_request_id")
        while parent:
            if parent in seen:
                request["parent_request_id"] = None
                break
            seen.add(parent)
            parent = by_id.get(parent, {}).get("parent_request_id")
    return out


def organized(requests):
    original = copy.deepcopy(requests)
    actual = inbox.organize(requests)
    assert actual == legacy_organize(requests)
    assert requests == original
    return {r["id"]: r for r in actual}


def root(id, body="Replace Ein", created=1, **extra):
    return {"id": id, "body": body, "created": created, **extra}


def task(id="child", body="Follow-up", created=10, **extra):
    return {"id": id, "source": "gap", "body": body, "created": created, **extra}


def test_exact_id_wins_over_colliding_number_and_number_uses_first_input_record():
    rows = organized([
        root("first", number=7), root("second", number=7), root("7", number=8),
        task("by-id", parent_request_id=7),
        task("by-number", context={"request_id": 8}),
        task("missing", parent_request_id="unknown", context={"session": "same"}),
    ])
    assert rows["by-id"]["parent_request_id"] == "7"
    assert rows["by-number"]["parent_request_id"] == "7"
    assert rows["missing"]["parent_request_id"] is None
    without_numeric_id = organized([root("first", number=7), root("second", number=7),
                                    task(parent_request_id="7")])
    assert without_numeric_id["child"]["parent_request_id"] == "first"


def test_duplicate_prompt_timestamp_ties_future_exclusion_and_normalization():
    rows = organized([
        root("old", "replace EIN", 1), root("tie-first", " Replace\n Ein ", 5),
        root("future", "Replace Ein", 20), root("tie-second", "REPLACE EIN", 5),
        task(body="## What the operator asked\nREPLACE EIN\n## Context\nDetails"),
        task("early", body="## What the operator asked\nReplace Ein", created=2),
    ])
    assert rows["child"]["parent_request_id"] == "tie-first"
    assert rows["early"]["parent_request_id"] == "old"


def test_quotes_review_and_conversation_precedence_do_not_invent_parent():
    standing = "examine the requests I give gBox and how it responds"
    review = 'gBox request review (operator\'s request: "' + standing + '").\nCheck.'
    context = {"conversation": "same", "session": "shared"}
    rows = organized([
        root("standing", standing, 1), root("quoted", "Replace Ein", 2),
        root("unrelated", "Make thumbnails larger", 9, context=context),
        task("review", body=review, context=context),
        task("quote-review", body=review + "\n## What the operator asked\nReplace Ein", context=context),
        task("missing-review", body='gBox request review (operator\'s request: "unknown").', context=context),
        task("unquoted-review", body="gBox request review\nCheck.", context=context),
    ])
    assert rows["review"]["parent_request_id"] == "standing"
    assert rows["quote-review"]["parent_request_id"] == "quoted"
    assert rows["missing-review"]["parent_request_id"] is None
    assert rows["unquoted-review"]["parent_request_id"] is None


def test_auto_reports_self_parent_and_automated_roots_stay_unlinked():
    rows = organized([
        root("operator", context={"session": "same"}),
        task("automated-root", "Replace Ein", created=9, context={"session": "same"}),
        task("auto-report", parent_request_id="operator", context={"auto_report": True}),
        task("self", parent_request_id="self"),
        task("follow", context={"session": "same"}),
    ])
    assert rows["auto-report"]["parent_request_id"] is None
    assert rows["self"]["parent_request_id"] is None
    assert rows["follow"]["parent_request_id"] == "operator"


def test_conversation_selection_ties_and_no_fallback_to_session_when_conversation_present():
    rows = organized([
        root("conversation-first", created=4, context={"conversation": "c"}),
        root("conversation-second", created=4, context={"conversation": "c"}),
        root("session", created=9, context={"session": "s"}),
        task("both", context={"conversation": "c", "session": "s"}),
        task("unknown-conversation", context={"conversation": "missing", "session": "s"}),
        task("session-only", context={"conversation": "", "session": "s"}),
    ])
    assert rows["both"]["parent_request_id"] == "conversation-first"
    assert rows["unknown-conversation"]["parent_request_id"] is None
    assert rows["session-only"]["parent_request_id"] == "session"


def test_structured_imported_context_uses_equality_without_stringification():
    rows = organized([
        root("list", context={"session": ["c", 1]}),
        root("dict", context={"conversation": {"part": 1}}),
        root("string", created=8, context={"session": "['c', 1]"}),
        task("list-child", context={"session": ["c", True]}),
        task("dict-child", context={"conversation": {"part": True}}),
    ])
    assert rows["list-child"]["parent_request_id"] == "list"
    assert rows["dict-child"]["parent_request_id"] == "dict"


def test_missing_created_values_and_cycle_cleanup_preserve_original_order():
    rows = [{"id": "no-time", "body": "Replace Ein"},
            {"id": "follow", "source": "gap", "body": "## What the operator asked\nReplace Ein"},
            {"id": "a", "parent_request_id": "b"}, {"id": "b", "parent_request_id": "a"},
            {"id": "c", "parent_request_id": "a"}]
    result = organized(rows)
    assert result["follow"]["parent_request_id"] == "no-time"
    assert result["a"]["parent_request_id"] is None
    assert result["b"]["parent_request_id"] == "a"
    assert [r["id"] for r in inbox.organize(rows)] == [r["id"] for r in rows]


def test_seeded_mixed_import_snapshots_match_unindexed_public_behavior():
    rng = random.Random(1138)
    for batch in range(12):
        rows = []
        for i in range(80):
            r = {"id": f"{batch}-{i}", "number": rng.randrange(10), "created": rng.randrange(8),
                 "body": rng.choice(["Replace Ein", "Replace Amy", " unrelated ", ""]),
                 "context": {rng.choice(["conversation", "session"]): rng.choice(["a", "b", "", [1], {"k": 1}])}}
            if rng.randrange(2):
                r["source"] = rng.choice(["gap", "characters", "system", "review"])
                r["body"] = rng.choice(["## What the operator asked\nReplace Ein\n## Context\nDetails",
                                        "gBox request review\nNo standing instruction", "Follow-up"])
            if rng.randrange(5) == 0:
                r["parent_request_id"] = rng.choice([f"{batch}-{rng.randrange(80)}", str(rng.randrange(10)), "missing"])
            if rng.randrange(10) == 0:
                r["context"]["auto_report"] = True
            rows.append(r)
        rng.shuffle(rows)
        organized(rows)


def test_bulk_context_lookup_normalizes_roots_once(monkeypatch):
    rows = [root(f"root-{i}", created=i, context={"session": "same"}) for i in range(500)]
    rows += [task(f"child-{i}", created=1000, context={"session": "same"}) for i in range(1000)]
    original = inbox.normalize
    calls = []
    def normalize(text):
        calls.append(1)
        return original(text)
    monkeypatch.setattr(inbox, "normalize", normalize)
    actual = inbox.organize(rows)
    assert all(r["parent_request_id"] == "root-499" for r in actual[500:])
    assert len(calls) == 500
