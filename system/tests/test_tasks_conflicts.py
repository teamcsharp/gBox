from gbox import tasks_tool as t


class P:
    def __init__(self, pid, name):
        self.pid, self._n, self.killed = pid, name, False

    def name(self):
        return self._n

    def kill(self):
        self.killed = True


def procs():
    return [P(1, "Wacom_TabletUser.exe"), P(2, "wallpaper64.exe"), P(3, "WTabletServicePro.exe"),
            P(4, "dolphin.exe"), P(5, "ui32.exe")]


def test_list_groups_by_app():
    r = t.list_conflicts(procs())
    assert r["count"] == 4
    assert {x["pid"] for x in r["conflicts"]["wacom"]} == {1, 3}
    assert {x["pid"] for x in r["conflicts"]["wallpaper engine"]} == {2, 5}


def test_stop_only_known_and_selected():
    ps = procs()
    r = t.stop_conflicts(["wallpaper engine"], ps)
    assert {x["pid"] for x in r["stopped"]} == {2, 5}
    assert [p.pid for p in ps if p.killed] == [2, 5]


def test_stop_all_leaves_games():
    ps = procs()
    t.stop_conflicts(None, ps)
    assert [p.pid for p in ps if p.killed] == [1, 2, 3, 5]


def test_unknown_app_rejected():
    import pytest
    with pytest.raises(ValueError):
        t.stop_conflicts(["chrome"], procs())
