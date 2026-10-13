"""Which PCs the automated background testing may use (#1383).

The operator ticks PCs in the Tasks icon's right-click menu. An unticked PC is never chosen for other-PC
launches (server idle_worker) or Hermes test runs (mcp_server.select_background_worker), whatever its idle
time says; the setting is keyed by worker name because worker ids change on every restart.
"""
SETTING = "background_testing"


def excluded(store) -> set[str]:
    rec = store.get("setting", SETTING) or {}
    return {str(n) for n in rec.get("excluded") or []}


def allowed(worker: dict, excluded_names) -> bool:
    return worker.get("name") not in excluded_names and worker.get("id") not in excluded_names


def agent_owned(label: dict | None, job: dict | None) -> bool:
    """A session an agent started for testing (tray label owner=agent, or launched by an agent_use job) and not one the
    operator claimed (owner=you). Agent tools that inject into or drive a process only ever touch these."""
    label, job = label or {}, job or {}
    if label.get('owner') == 'you':
        return False
    return label.get('owner') == 'agent' or bool(job.get('agent_use'))


def worker_testing_reason(testing: dict, worker_id: str) -> str | None:
    """Why this worker may not be used for agent test launches (None = it may). `testing` is GET /api/testing/workers:
    a PC the operator unticked in the Tasks menu is never used, whatever its idle time says (#1383)."""
    rows = testing.get('workers') or []
    me = next((w for w in rows if worker_id in (w.get('id'), w.get('name'))), None)
    if me is None:
        return f'worker {worker_id} is not registered with the control plane'
    if not allowed(me, set(testing.get('excluded') or [])) or me.get('background_testing') is False:
        return f"{me.get('name') or worker_id} is excluded from background testing (Tasks menu); agent launches are not allowed there"
    return None


def set_available(store, name: str, available: bool) -> set[str]:
    ex = excluded(store)
    (ex.discard if available else ex.add)(name)
    store.put("setting", SETTING, {"excluded": sorted(ex)})
    return ex
