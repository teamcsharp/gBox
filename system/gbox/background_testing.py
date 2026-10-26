"""Which PCs the automated background testing may use (#1383).

The operator ticks PCs in the Tasks icon's right-click menu. An unticked PC is never chosen for other-PC
launches (server idle_worker) or Hermes test runs (mcp_server.select_background_worker), whatever its idle
time says; the setting is keyed by worker name because worker ids change on every restart.
"""
SETTING = "background_testing"
DEFAULT_BUDGET = 70
RESOURCE_MAX_AGE_S = 30
IDLE_MIN_S = 300


def policy(store, name, setting=None):
    """`setting` is the stored SETTING document when the caller already read it (server.workers reads it once for all PCs)."""
    row = ((store.get('setting', SETTING) or {}) if setting is None else setting).get('policies', {}).get(name) or {}
    return {'budget_percent': row.get('budget_percent', DEFAULT_BUDGET)}


def admission_reason(worker, excluded_names, budget_percent=DEFAULT_BUDGET, *, now=None, allow_active=False, require_gpu=True):
    """Admission for new background compute, including competing non-gBox load.

    This is a measured admission budget, not an OS/GPU hard throttle. Running
    non-cooperative programs still require bounded work units and yield points.
    """
    import time
    from .worker_resources import percent
    if not allowed(worker, excluded_names):
        return 'Gaming mode: background work is disabled on this PC.'
    if worker.get('os') == 'windows' and not allow_active:
        idle = worker.get('idle_seconds')
        if idle is None or idle < IDLE_MIN_S:
            return 'Waiting for five minutes without operator input.'
    resources = worker.get('resources') or {}
    stamp = resources.get('sampled_at')
    now = time.time() if now is None else now
    if not isinstance(stamp, (int, float)) or not 0 <= now - stamp <= RESOURCE_MAX_AGE_S:
        return 'Waiting for current resource telemetry from this worker.'
    cpu = percent(resources.get('cpu_percent'))
    if cpu is None:
        return 'Waiting for a measured CPU interval.'
    if cpu >= budget_percent:
        return f'CPU is at {cpu:g}%; background admission budget is {budget_percent:g}%.'
    for gpu in (resources.get('gpus') or []) if require_gpu else []:
        load = percent(gpu.get('utilization_percent'))
        if load is None:
            return 'Waiting for measured utilization of an installed GPU.'
        if load >= budget_percent:
            return f"{gpu.get('name') or 'GPU'} is at {load:g}%; background admission budget is {budget_percent:g}%."
    memory = percent(resources.get('memory_percent'))
    available = resources.get('memory_available_bytes')
    if memory is None or not isinstance(available, (int, float)):
        return 'Waiting for measured memory headroom.'
    if memory >= 90 or available < 2 * 1024**3:
        return 'Waiting for memory headroom (at least 2 GiB free and under 90% used).'
    return None


def requires_admission(job):
    # Live controls and diagnostics must remain available even after a PC is
    # unticked or loaded: they are how an owned test saves and yields its place.
    # autoplay drives a session that was already admitted (the screensaver's own games): it must not wait behind a busy GPU.
    controls = {'session_op', 'get_frame', 'state_transfer', 'read_memory', 'tasks', 'autoplay'}
    if job.get('tool') == 'ghidra_bridge' and (job.get('input') or {}).get('op', 'status') in {
            'status', 'info', 'functions', 'strings', 'xrefs_to', 'xrefs_from', 'containing'}:
        return False  # bounded inspection of existing analysis never replaces the watched game
    if (job.get('tool') in {'ollama_assist', 'decomp_pipeline', 'xenonrecomp', 'rexglue'}
            and (job.get('input') or {}).get('op') == 'status'):
        # These explicit status operations only discover configured programs.
        # Keep diagnostics available while busy/excluded; all compute stays gated.
        return False
    return bool(job.get('agent_use') or job.get('low_priority')) and job.get('tool') not in controls


def requires_gpu(job):
    # These bounded native recipes decode/quantize with NumPy/Pillow and use
    # software previews. A busy image-generation GPU cannot block CPU work.
    return job.get('tool') not in {'smb1_sprite_build','photo_sprite_build'}


def guarded_reason(store, worker, *, now=None, allow_active=False, require_gpu=True, running=None, setting=None):
    """Controller play may not update input-idle time. Ownership is authoritative.
    `running` (store.running_sessions()) and `setting` (the SETTING document) may be passed by a caller that checks
    every PC at once (server.workers): the same answer from one read instead of three per worker."""
    from .operator_guard import operator_sessions
    owned = operator_sessions(store.running_sessions() if running is None else running, lambda sid: store.get('slabel', sid),
                              lambda jid: store.get('job', jid), [worker['id']])
    from .screensaver import telemetry_get
    owned = [s for s in owned if not telemetry_get(s['session_id'], now=now).get('running')]
    if owned:
        return 'Human gameplay is active on this PC; background compute is waiting.'
    return admission_reason(worker, excluded(store, setting=setting), policy(store, worker['name'], setting=setting)['budget_percent'],
                            now=now, allow_active=allow_active, require_gpu=require_gpu)


def excluded(store, setting=None) -> set[str]:
    rec = (store.get("setting", SETTING) or {}) if setting is None else setting
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
    store.put("setting", SETTING, (store.get('setting', SETTING) or {}) | {"excluded": sorted(ex)})
    return ex
