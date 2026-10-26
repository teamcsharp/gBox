"""Preserve explicit autoplay intent across an exact session replacement."""
import json
import time


HANDOFF = 'autoplay_handoff'


def latest_control(store, sid, exclude_job_id=''):
    # Status polling is not intent. Order by creation time, not replacement rowid.
    with store.lock:
        row = store.db.execute(
            "SELECT body FROM docs WHERE kind='job' "
            "AND json_extract(body,'$.tool')='autoplay' "
            "AND json_extract(body,'$.input.session_id')=? "
            "AND json_extract(body,'$.input.op') IN ('start','stop') "
            "AND id!=? ORDER BY json_extract(body,'$.created') DESC,id DESC LIMIT 1",
            (sid, exclude_job_id)).fetchone()
    return json.loads(row[0]) if row else None


def note_handoff(store, sid, source_job_id):
    """Persist a human takeover only for the exact current autoplay run."""
    if not source_job_id:
        return False
    with store.lock:
        row = latest_control(store, sid) or {}
        if row.get('id') != source_job_id or (row.get('input') or {}).get('op') != 'start' \
                or row.get('state') not in ('running', 'succeeded'):
            return False
        if not revoked(store, sid, source_job_id):
            store.put(HANDOFF, sid, {'source_job_id': source_job_id, 'at': time.time()})
    return True


def revoked(store, sid, source_job_id):
    return bool(source_job_id and (store.get(HANDOFF, sid) or {}).get('source_job_id') == source_job_id)


def effective_input(row):
    inp = row.get('input') or {}
    result = (row.get('output') or {}).get('result') or {}
    active = result.get('effective_input')
    if inp.get('op') == 'start' and result.get('already_running') and isinstance(active, dict) \
            and active.get('session_id') == inp.get('session_id') and active.get('op') == 'start':
        return active
    return inp


def continuous(store, sid):
    row = latest_control(store, sid) or {}
    inp = effective_input(row)
    return (row.get('state') == 'succeeded' and inp.get('op') == 'start' and inp.get('continuous') is True
            and not revoked(store, sid, row.get('id')))


def snapshot(store, sid, telemetry):
    row = latest_control(store, sid) or {}
    inp = effective_input(row)
    if row.get('state') != 'succeeded' or inp.get('op') != 'start' or inp.get('screensaver') \
            or revoked(store, sid, row.get('id')):
        return None
    # A deliberate start with continuous recovery also survives a hung bot's
    # final running=false report. Ordinary manually assisted play needs fresh
    # evidence that it was actually running when Restart was requested.
    live = telemetry.get('running') is True and telemetry.get('age_s', 999) < 30
    if not live and inp.get('continuous') is not True:
        return None
    if (telemetry.get('stats') or {}).get('team_role', 'solo_p1') != 'solo_p1':
        return None
    return {'job_id': row['id'], 'input': dict(inp)}


def replacement_input(store, old_sid, new_sid, captured):
    if not captured or old_sid == new_sid:
        return None
    old, new = store.get('session', old_sid) or {}, store.get('session', new_sid) or {}
    if old.get('replaced_by') != new_sid or new.get('state') != 'running' \
            or not old.get('game_id') or old.get('game_id') != new.get('game_id'):
        return None
    latest = latest_control(store, old_sid) or {}
    if latest.get('id') != captured['job_id'] or latest.get('state') != 'succeeded' \
            or revoked(store, old_sid, captured['job_id']) or latest_control(store, new_sid):
        return None  # Stop or a changed start during the replacement wins.
    from .tools import AutoplayIn
    inp = AutoplayIn.model_validate(captured['input']).model_dump()
    inp.update(session_id=new_sid, op='start', reset=False)
    return inp


def claim_reason(store, job):
    """Recheck automatic carryover under the claim lock after it sat queued."""
    origin = job.get('origin') or {}
    if job.get('tool') != 'autoplay' or origin.get('via') != 'autoplay_resume':
        return None
    inp = job.get('input') or {}
    old_sid, new_sid = origin.get('from_session'), inp.get('session_id')
    source = origin.get('source_job_id')
    old, new = store.get('session', old_sid or '') or {}, store.get('session', new_sid or '') or {}
    latest = latest_control(store, old_sid) or {}
    if (not source or not old_sid or not new_sid or old_sid == new_sid or inp.get('op') != 'start'
            or old.get('replaced_by') != new_sid or new.get('state') != 'running'
            or not old.get('game_id') or old.get('game_id') != new.get('game_id')
            or latest.get('id') != source or latest.get('state') != 'succeeded'
            or (latest.get('input') or {}).get('op') != 'start' or revoked(store, old_sid, source)
            or latest_control(store, new_sid, exclude_job_id=job['id'])):
        return 'Automatic autoplay resume cancelled: its source intent or replacement session changed.'
    return None
