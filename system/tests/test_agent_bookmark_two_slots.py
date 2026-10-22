"""#2846: a session keeps at most two bookmark save states (before / after), never a 20-slot ring."""
from gbox.agent import Agent


def test_bookmarks_use_two_slots_only():
    a = Agent.__new__(Agent)
    used = []

    def job(kind, args, **kw):
        used.append(args["args"]["slot"])
        return {"output": {"result": {"slot": args["args"]["slot"], "frame": 1}}}

    a._job = job
    for _ in range(10):
        a._bookmark_state("w-1", "before")
        a._bookmark_state("w-1", "after")
    assert set(used) == {20, 21}
