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


def set_available(store, name: str, available: bool) -> set[str]:
    ex = excluded(store)
    (ex.discard if available else ex.add)(name)
    store.put("setting", SETTING, {"excluded": sorted(ex)})
    return ex
