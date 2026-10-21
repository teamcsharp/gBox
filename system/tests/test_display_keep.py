"""#1881: a Windows worker keeps its display awake while gBox uses the PC, the way the desktop app does from Electron."""
from gbox import display_keep as K


def _status(**kw):
    base = {"online": True, "background_testing": True, "worker": {"os": "windows", "idle_seconds": 600}, "sessions": [], "active": []}
    return base | kw


def test_the_policy_matches_the_desktop_power_module():
    assert K.wanted(_status(), host_os="windows") == (True, "idle status display")
    assert K.wanted(_status(worker={"idle_seconds": 10}), host_os="windows")[0] is False, "the PC is in use by a person"
    assert K.wanted(_status(worker={"idle_seconds": 10}), active_jobs=1, host_os="windows") == (True, "gBox is using this PC")
    assert K.wanted(_status(worker={"idle_seconds": 10}, active=[{"state": "running"}]), host_os="windows")[0] is True
    assert K.wanted(_status(worker={"idle_seconds": 10}, sessions=[{"agent_owned": True}]), host_os="windows")[0] is True
    assert K.wanted(_status(sessions=[{"agent_owned": False}]), active_jobs=3, host_os="windows") == (False, "the operator's game runs here")
    assert K.wanted(_status(background_testing=False), host_os="windows")[0] is False, "not opted in: idle display off"
    assert K.wanted(_status(background_testing=False), active_jobs=1, host_os="windows")[0] is True, "but a running job still keeps it"
    assert K.wanted(_status(worker={"idle_seconds": None}), host_os="windows")[0] is False
    assert K.wanted(_status(online=False), active_jobs=1, host_os="windows") == (False, "offline")
    assert K.wanted(_status(), host_os="linux")[0] is False and K.wanted(None, host_os="windows")[0] is False


def test_the_keeper_sets_the_thread_state_once_per_change_and_releases():
    calls = []
    keeper = K.Keeper(setter=calls.append)
    assert keeper.apply(True, "gBox is using this PC") is True and keeper.held
    assert keeper.apply(True, "still") is True
    assert calls == [K.ES_CONTINUOUS | K.ES_DISPLAY_REQUIRED], "one hold for the whole stretch"
    keeper.apply(False, "PC active")
    assert calls[-1] == K.ES_CONTINUOUS and not keeper.held
    keeper.apply(True, "again")
    keeper.release()
    assert calls[-1] == K.ES_CONTINUOUS and keeper.reason == "worker stopped"


def test_without_display_control_the_keeper_only_reports():
    keeper = K.Keeper(setter=None) if K.HOST_OS != "windows" else K.Keeper(setter=lambda flags: None)
    k = K.Keeper.__new__(K.Keeper)
    k._set, k.held, k.reason = None, False, "not started"
    assert k.apply(True, "x") is False and k.reason == "no display control on this host"
    assert keeper is not None


def test_the_heartbeat_thread_holds_the_display_from_the_worker_status(monkeypatch):
    """The worker's own heartbeat thread reads its background status and holds the display, then releases on stop."""
    from gbox import worker, display_keep
    applied = []

    class FakeKeeper:
        def apply(self, keep, reason):
            applied.append((keep, reason))

        def release(self):
            applied.append(("released", None))

    class Reply:
        def __init__(self, data=None):
            self.data = data

        def raise_for_status(self):
            return self

        def json(self):
            return self.data

    class Client:
        def __init__(self, **_):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def post(self, path, *, json):
            return Reply()

        def get(self, path):
            assert path == "/api/background/workers/test/status"
            return Reply({"online": True, "background_testing": True, "worker": {"idle_seconds": 900}, "sessions": [], "active": []})

    class Stop:
        calls = 0

        def wait(self, _):
            self.calls += 1
            return self.calls > 2

    monkeypatch.setattr(display_keep, "Keeper", FakeKeeper)
    monkeypatch.setattr(display_keep, "HOST_OS", "windows")
    monkeypatch.setattr(worker.httpx, "Client", Client)
    monkeypatch.setattr(worker, "user_idle_seconds", lambda: 900)
    info = worker.WorkerInfo(id="w", name="test", os="windows", tools=["get_frame"])
    worker._heartbeat_loop(Stop(), lambda: info, set(), "http://fixture", {})
    assert applied == [(True, "idle status display"), ("released", None)], applied
