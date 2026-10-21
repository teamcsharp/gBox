"""Coaching notes reach the agents at once (operator 2026-10-20: "chat about the gameplay placing reports for
improvements ... in realtime via live reporting"): each new note the operator types in the coach box is surfaced by the
inbox hook and `agent_ledger.py list` as a new operator message, and the bulk Hermes queue never takes the ticket."""
from gbox import hermes_work_queue as q
from scripts import agent_ledger as ledger


def ticket(notes, rid="c" * 16, created=100.0, extra_msgs=()):
    msgs = [{"id": f"m{n}", "author": "operator", "ts": ts, "text": f"note {n}\n\n[coach note #{n} · ...]",
             "coach": {"note": n, "session_id": "w-s", "worker": "lilspark",
                       "captures": {"frame": {"state": "done"}, "state": {"state": "pending"}, "ram": {"state": "done"}}}}
            for n, ts in notes] + list(extra_msgs)
    return {"id": rid, "number": 77, "title": "Autoplay coaching: Resident Evil 4", "status": "open", "source": "coach",
            "kind": "text", "created": created, "context": {"coaching": True, "game_id": "re4"}, "messages": msgs,
            "metrics": {}}


def test_the_hook_prints_each_new_note_once_oldest_first():
    st, out = {"seen_notes": []}, []
    rows = [ticket([(1, 1000.0), (2, 1010.0)])]
    shown = ledger.hook_coaching(st, rows, now=1020.0, out=out.append)
    assert [m["id"] for _, m in shown] == ["m1", "m2"]
    text = "\n".join(out)
    assert "new coaching notes" in text and "note #1" in text and "operator: note 2" in text and "frame done" in text
    out.clear()
    rows = [ticket([(1, 1000.0), (2, 1010.0), (3, 1030.0)])]               # the operator typed another one
    shown = ledger.hook_coaching(st, rows, now=1031.0, out=out.append)
    assert [m["id"] for _, m in shown] == ["m3"] and "note #3" in "\n".join(out)
    out.clear()
    assert ledger.hook_coaching(st, rows, now=1040.0, out=out.append) == [] and out == []     # nothing new


def test_the_first_run_does_not_replay_old_notes():
    st, out = {}, []
    rows = [ticket([(1, 1000.0), (2, 9000.0)])]
    shown = ledger.hook_coaching(st, rows, now=9100.0, out=out.append)
    assert [m["id"] for _, m in shown] == ["m2"]                            # an hour old: already seen
    assert set(st["seen_notes"]) == {"m1", "m2"}


def test_list_puts_a_ticket_with_a_fresh_note_first_and_shows_that_note():
    old = ticket([(1, 100.0), (5, 5000.0)], rid="a" * 16, created=50.0,
                 extra_msgs=[{"author": "agent", "ts": 4000.0, "text": "on it"}])
    newer = {"id": "b" * 16, "number": 90, "title": "Fix the menu", "status": "open", "source": "app", "kind": "text",
             "created": 3000.0, "messages": [{"author": "operator", "ts": 3000.0, "text": "please"}], "metrics": {}}
    rows = sorted([newer, old], key=ledger.activity, reverse=True)
    assert [r["id"] for r in rows] == ["a" * 16, "b" * 16]                  # the note at 5000 beats a ticket from 3000
    assert "operator: note 5" in ledger.describe(rows[0])                    # its newest note, not the agent's reply


def test_hermes_never_takes_a_coaching_ticket():
    data = {"version": 1, "items": {}, "last_lane": "inbox"}
    coach = dict(ticket([(1, 10.0)]), status="open")
    plain = {"id": "d" * 16, "number": 5, "title": "Fix it", "status": "open", "source": "app"}
    q.sync(data, {"count": 0, "items": []}, [coach, plain], now=100)
    assert set(data["items"]) == {"inbox:" + "d" * 16}
    data["items"]["inbox:" + coach["id"]] = {"lane": "inbox", "request_id": coach["id"], "attempts": 0,
                                             "last_dispatched": 0, "created": 1}     # queued before this change
    q.sync(data, {"count": 0, "items": []}, [coach, plain], now=101)
    assert "inbox:" + coach["id"] not in data["items"]
    assert q.is_live_coaching(coach) and not q.is_live_coaching(plain)
    options = q.candidates(data, [coach, plain], [], set(), set(), now=102)
    assert [i["request_id"] for _, i in options] == ["d" * 16]
