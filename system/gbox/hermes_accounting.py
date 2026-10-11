"""Finalize bounded Hermes inbox usage without changing task acceptance.

This module has no scheduler hook. A caller may explicitly reconcile ended cron
runs against the read-only Hermes databases and the ordinary gBox Store. Only
token deltas and their provenance are written. Tools, turns, duration, status,
solver credit, provider configuration and games are never changed.
"""
from __future__ import annotations

from contextlib import closing
import copy
import errno
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import urllib.error

from . import hermes_tasks

_RID = re.compile(r'[0-9a-f]{16}\Z')
_RUN = re.compile(r'[0-9a-f]{32}\Z')
_OWNERS = ('reply_request', 'set_request_status', 'start_job',
           'capture_request_screenshot', 'record_request_metrics', 'launch_game',
           'prepare_task_workspace')
_TOKEN_FIELDS = ('input_tokens', 'cache_read_tokens', 'cache_write_tokens',
                 'output_tokens', 'reasoning_tokens', 'api_call_count')


class Deferred(ValueError):
    """Accounting lacks evidence required to allocate a session safely."""


def _count(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise Deferred('Invalid nonnegative integer ' + name)
    return value


def _json(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            raise Deferred('Unparseable structured tool data') from None
    return value


def _action(name):
    return name.removeprefix('mcp__gbox__') if isinstance(name,str) else ''


def _transport_rejected(value, action=None, args=None):
    if any(value.get(k) for k in ('error','isError','is_error')) or value.get('ok') is False:
        return True
    if value.get('status') not in ('error','failed','blocked','denied'):
        return False
    # A blocked ticket is not a failed transport. Accept only a verifiable
    # request receipt or the exact acknowledged status the caller requested.
    owner = value.get('request_id') or value.get('id')
    receipt = isinstance(owner,str) and bool(_RID.fullmatch(owner))
    if receipt and value.get('ok') is True:
        return False
    if (receipt and _action(action) == 'set_request_status' and isinstance(args,dict)
            and args.get('request_id') == owner and args.get('status') == value['status']):
        return False
    return True


def _result(content, *, action=None, args=None):
    """Unwrap known MCP envelopes; never find success in arbitrary log prose."""
    if isinstance(content, str) and content.startswith('<untrusted_tool_result'):
        if '\n\n' not in content or '</untrusted_tool_result>' not in content:
            return None
        content = content.split('\n\n', 1)[1].rsplit('</untrusted_tool_result>', 1)[0].strip()
    for _ in range(6):
        try:
            content = _json(content)
        except Deferred:
            return None
        if not isinstance(content, dict):
            return content
        if _transport_rejected(content,action,args):
            return None
        if 'result' in content:
            content = content['result']
            continue
        blocks = content.get('content')
        if isinstance(blocks, list) and len(blocks) == 1 and isinstance(blocks[0],dict) and blocks[0].get('type') == 'text':
            content = blocks[0].get('text')
            continue
        return content
    return None


def _rejected(content, *, action=None, args=None):
    if isinstance(content,str) and content.startswith('<untrusted_tool_result') and '\n\n' in content:
        content = content.split('\n\n',1)[1].rsplit('</untrusted_tool_result>',1)[0].strip()
    for _ in range(6):
        try:
            content = _json(content)
        except Deferred:
            return False
        if not isinstance(content,dict):
            return False
        if _transport_rejected(content,action,args):
            return True
        if 'result' not in content:
            return False
        content = content['result']
    return False


def _calls(messages):
    """Pair arguments with their own response ID, including single-call wrappers."""
    responses = {}
    for message in messages:
        if message.get('role') == 'tool' and message.get('tool_call_id'):
            responses.setdefault(message['tool_call_id'], []).append(message)
    calls = []
    seen = set()
    for message in messages:
        if message.get('role') != 'assistant' or not message.get('tool_calls'):
            continue
        raw = _json(message['tool_calls'])
        if not isinstance(raw, list):
            raise Deferred('Tool calls are not a structured list')
        for call in raw:
            if not isinstance(call, dict):
                raise Deferred('Malformed structured call')
            fn = call.get('function') or {}
            if not isinstance(fn,dict):
                raise Deferred('Malformed structured function')
            arguments = _json(fn.get('arguments') or '{}')
            if not isinstance(arguments, dict):
                raise Deferred('Tool arguments are not an object')
            cid = call.get('id')
            if cid and cid in seen:
                raise Deferred('Duplicate tool call identity')
            if cid:
                seen.add(cid)
            reply = responses.get(cid, [])
            name = fn.get('name') or ''
            nested = arguments.get('calls') if name == 'tool_call' else None
            if isinstance(nested, list):
                names = [_action(member.get('name')) for member in nested if isinstance(member,dict)]
                if len(names) != len(nested) or len(set(names)) != len(names):
                    raise Deferred('Ambiguous duplicate wrapper action')
                for member in nested:
                    member_name = member.get('name') or ''
                    paired = [r for r in reply if _action(r.get('tool_name')) == _action(member_name)]
                    if len(paired) > 1:
                        raise Deferred('Ambiguous wrapper member response')
                    content = paired[0].get('content') if paired else None
                    member_args = _json(member.get('arguments') or {})
                    calls.append({'name':member.get('name') or '',
                                  'args':member_args,'call_id':cid,
                                  'result':_result(content,action=member_name,args=member_args),
                                  'rejected':_rejected(content,action=member_name,args=member_args),
                                  'has_response':bool(paired), 'wrapped_ambiguous':bool(reply) and not bool(paired)})
            else:
                paired = [r for r in reply if _action(r.get('tool_name')) == _action(name)]
                if len(paired) > 1:
                    raise Deferred('Ambiguous tool response identity')
                content = paired[0].get('content') if paired else None
                calls.append({'name':name,'args':arguments,'call_id':cid,
                              'result':_result(content,action=name,args=arguments),
                              'rejected':_rejected(content,action=name,args=arguments),
                              'has_response':bool(paired),'wrapped_ambiguous':bool(reply) and not bool(paired)})
    return calls


def _owners(calls, run, messages):
    confirmed = set(hermes_tasks.confirmed_request_ids(messages))
    owners = set(run.get('request_ids') or [])
    for call in calls:
        args = call['args']
        if not isinstance(args, dict):
            raise Deferred('Mutation arguments are not an object')
        mutation = call['name'].endswith(_OWNERS) or bool(re.search(r'(?:__|_)job_[a-z_]+\Z',call['name']))
        for values in (args, args.get('input'), args.get('inputs'), args.get('metrics')):
            if isinstance(values, dict):
                for key in ('request_id', 'parent_request_id'):
                    if values.get(key) and (mutation or key == 'parent_request_id'):
                        owners.add(values[key])
    if len(owners) != 1 or not all(isinstance(rid, str) and _RID.fullmatch(rid) for rid in owners):
        raise Deferred('Mixed or missing request attribution; session left unallocated')
    if owners != confirmed:
        raise Deferred('Successful work receipt does not confirm the sole request owner')
    return next(iter(owners))


def _identity(record):
    return record['provider'], record['model'], record['task']


def _task(value):
    # Installed Hermes SessionUsageMixin._record_model_usage uses task="" for
    # main-loop calls and explicit names for auxiliary calls. Missing/null is
    # different from that documented empty-string convention and stays invalid.
    if not isinstance(value,str):
        raise Deferred('Model task identity unavailable')
    return 'primary' if value == '' else value


def _records(run, session, ledger):
    if not _RUN.fullmatch(str(run.get('id', ''))) or run.get('state') not in ('completed', 'failed'):
        raise Deferred('Execution is not a finalized supported run')
    sid = session.get('id')
    if not isinstance(sid, str) or not sid or run.get('session_id', sid) != sid:
        raise Deferred('Execution/session identity mismatch')
    start, end = session.get('started_at'), session.get('ended_at')
    if not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in (start, end)) or end <= start:
        raise Deferred('Inference session has not ended')
    if not isinstance(ledger, list) or not 1 <= len(ledger) <= 64:
        raise Deferred('Exact final model ledger unavailable')
    records, identities = [], set()
    for row in ledger:
        if row.get('session_id') != sid:
            raise Deferred('Model ledger belongs to another session')
        provider, model, task = row.get('billing_provider'), row.get('model'), _task(row.get('task'))
        if not all(isinstance(x, str) and x for x in (provider, model, task)):
            raise Deferred('Model/provider/task identity unavailable')
        values = {k:_count(row.get(k), k) for k in _TOKEN_FIELDS}
        if values['reasoning_tokens'] > values['output_tokens']:
            raise Deferred('Reasoning is not a subset of output')
        identity = provider, model, task
        if identity in identities:
            raise Deferred('Duplicate model ledger identity')
        identities.add(identity)
        estimate = row.get('estimated_cost_usd')
        if isinstance(estimate, bool) or not isinstance(estimate, (int, float)) or not math.isfinite(estimate) or estimate < 0:
            estimate = None
        actual = row.get('actual_cost_usd')
        actual_known = (row.get('cost_status') == 'actual' and not isinstance(actual,bool)
                        and isinstance(actual,(int,float)) and math.isfinite(actual) and actual >= 0)
        record = {'run_id':run['id'], 'session_id':sid, 'provider':provider,
                  'model':model, 'task':task, 'ledger_task':row['task'], 'system':'Hermes', 'availability':'measured_final',
                  'input_uncached':values['input_tokens'], 'input_cache_read':values['cache_read_tokens'],
                  'input_cache_write':values['cache_write_tokens'],
                  'tokens_in_including_caches':sum(values[k] for k in _TOKEN_FIELDS[:3]),
                  'tokens_out':values['output_tokens'],
                  'reasoning_tokens_included_in_output':values['reasoning_tokens'],
                  'api_call_count':values['api_call_count'],
                  'inference_session_duration_s':round(end-start, 1),
                  'duration_credited':False, 'tools_added':False, 'turns_added':0,
                  'actual_cost_usd':actual if actual_known else None, 'billed_credits':'unavailable',
                  'estimated_cost_usd':estimate,
                  'cost_status':'actual' if actual_known else 'estimate only; no measured bill',
                  'source':'Finalized Hermes session_model_usage'}
        records.append(record)
    primary = [row for row in ledger if _task(row.get('task')) == 'primary']
    # Current Hermes session counters aggregate primary calls; auxiliary models
    # are separate ledger rows. Do not use them as substitutes for missing rows.
    if primary and all(session.get(k) is not None for k in _TOKEN_FIELDS):
        if any(_count(session[k], k) != sum(row[k] for row in primary) for k in _TOKEN_FIELDS):
            raise Deferred('Primary session counters disagree with final model ledger')
    return sorted(records, key=_identity)


def _snapshots(calls, rid, records, run):
    credited = {_identity(record):[0, 0] for record in records}
    for call in calls:
        if not call['name'].endswith('record_request_metrics'):
            continue
        outer = call['args']
        values = outer.get('metrics') or outer
        if not isinstance(values, dict):
            raise Deferred('Invalid prior metric payload')
        owner_values = [d.get('request_id') for d in (outer, values) if d.get('request_id')]
        if not owner_values or any(owner != rid for owner in owner_values):
            raise Deferred('Metric snapshot ownership mismatch')
        incoming, outgoing = (_count(0 if values.get(k) is None else values[k], k) for k in ('tokens_in', 'tokens_out'))
        if call.get('rejected'):
            continue
        result = call['result']
        if result is None:
            # A paired explicit failure is known to credit nothing. Missing or
            # unpaired responses to a nonzero call cannot be assumed rejected.
            if (incoming or outgoing) and (not call['has_response'] or call['wrapped_ambiguous']):
                raise Deferred('Nonzero snapshot has no unambiguous response')
            if (incoming or outgoing) and call['has_response']:
                # _result(None) alone is insufficient to prove422 versus a
                # malformed success; retain the distinction in _calls below.
                if not call.get('rejected'):
                    raise Deferred('Nonzero snapshot outcome unavailable')
            continue
        if not isinstance(result, dict) or result.get('ok') is not True or not isinstance(result.get('metrics'), dict):
            if incoming or outgoing:
                raise Deferred('Nonzero snapshot has no successful metric receipt')
            continue
        receipt_owners = [result.get(k) for k in ('request_id', 'id') if result.get(k)]
        if not receipt_owners or any(owner != rid for owner in receipt_owners):
            raise Deferred('Successful metric receipt belongs to another request')
        if not incoming and not outgoing:
            continue
        stored = result['metrics']
        if (_count(stored.get('tokens_in'),'snapshot receipt input') < incoming or
                _count(stored.get('tokens_out'),'snapshot receipt output') < outgoing):
            raise Deferred('Successful snapshot receipt counters do not cover its payload')
        source = values.get('tokens_detail') or {}
        if not isinstance(source,dict):
            raise Deferred('Invalid snapshot token detail')
        if source.get('run_id') and source['run_id'] != run['id']:
            raise Deferred('Snapshot identifies another run')
        options = [record for record in records if
                   (not values.get('provider') or record['provider'] == values['provider']) and
                   (not values.get('model') or record['model'] == values['model']) and
                   (not source.get('task') or record['task'] == source['task'])]
        if len(options) != 1:
            raise Deferred('Snapshot cannot be attributed to one actual model ledger')
        identity = _identity(options[0])
        credited[identity][0] += incoming
        credited[identity][1] += outgoing
    return credited


def _marker(run, record):
    identity = json.dumps(_identity(record), separators=(',', ':')).encode()
    return 'hermes_run_' + run['id'] + '_model_' + hashlib.sha256(identity).hexdigest()[:20] + '_final_recorded'


def _matches(old, record):
    return (old.get('run_id') == record['run_id'] and old.get('session_id') == record['session_id'] and
            old.get('provider') == record['provider'] and old.get('model') == record['model'] and
            old.get('task', record['task']) == record['task'] and
            old.get('tokens_in_including_caches') == record['tokens_in_including_caches'] and
            old.get('tokens_out') == record['tokens_out'] and
            all(old.get(k,record[k]) == record[k] for k in ('input_uncached','input_cache_read',
                'input_cache_write','reasoning_tokens_included_in_output','api_call_count')))


def _manual_credits(detail, records, run):
    credited = {}
    manual_markers = {}
    for key, value in detail.items():
        if not key.endswith('_recorded_usage') or not isinstance(value, dict):
            continue
        if value.get('run_id') != run['id'] and value.get('session_id') != records[0]['session_id']:
            continue
        marker = key[:-6]  # remove _usage
        if detail.get(marker) != 1:
            raise Deferred('Partial or duplicated persisted final marker')
        if (isinstance(value.get('models'), list) or isinstance(value.get('model_markers'), list)) and 'model' not in value:
            # Aggregate manual markers are validated after the per-model rows.
            continue
        options = [record for record in records if _matches(value, record)]
        if len(options) != 1:
            raise Deferred('Persisted manual final usage disagrees or is ambiguous')
        identity = _identity(options[0])
        if not marker.startswith('hermes_run_' + run['id'] + '_model_'):
            if identity in manual_markers:
                raise Deferred('Several manual final credit markers identify the same model')
            manual_markers[identity] = marker
        credited[identity] = manual_markers.get(identity,marker)
    return credited


def _check_existing_totals(metrics, detail, records, snapshot, manual):
    """Refuse unallocated nonzero credits instead of assigning them twice.

    Existing final-marker provenance for any historical run can explain ticket
    totals. Several aliases for the same run/model are counted once. A current
    unmarked snapshot is counted only with its successful paired receipt. Old
    counters without this provenance are preserved and deferred for review.
    """
    known = {}
    for key,value in detail.items():
        if not key.endswith('_recorded_usage') or not isinstance(value,dict):
            continue
        if not value.get('model') or not value.get('run_id') or not value.get('session_id'):
            continue
        marker = key[:-6]
        if detail.get(marker) != 1:
            raise Deferred('Historical final usage lacks one persisted marker')
        if not value.get('provider') or value.get('tokens_in_including_caches') is None or value.get('tokens_out') is None:
            raise Deferred('Historical measured usage lacks model/token provenance')
        own = '_model_' in marker and marker.startswith('hermes_run_')
        if own:
            delta_in = _count(value.get('tokens_in_added'),'automatic credited input delta')
            delta_out = _count(value.get('tokens_out_added'),'automatic credited output delta')
            before_in = _count(value.get('successful_snapshot_tokens_in'),'automatic successful snapshot input')
            before_out = _count(value.get('successful_snapshot_tokens_out'),'automatic successful snapshot output')
            if (delta_in+before_in,delta_out+before_out) != (value['tokens_in_including_caches'],value['tokens_out']):
                raise Deferred('Automatic delta plus successful snapshot disagrees with final ledger')
            current = value['run_id'] == records[0]['run_id'] and value['session_id'] == records[0]['session_id']
            component = value['provider'],value['model'],value.get('task') or 'primary'
            if current and snapshot.get(component) != [before_in,before_out]:
                raise Deferred('Automatic credited snapshot differs from finalized transcript')
        incoming,outgoing = value['tokens_in_including_caches'],value['tokens_out']
        amounts = _count(incoming,'historical final input'),_count(outgoing,'historical final output')
        identity = (value['run_id'],value['session_id'],value['provider'],value['model'],value.get('task') or 'primary')
        if identity in known:
            previous,was_own = known[identity]
            if own and not was_own:
                continue  # automatic alias following a manual final credit
            if not own and was_own:
                known[identity] = amounts,False
                continue
            if amounts != previous:
                raise Deferred('Conflicting historical final credit amounts')
            continue
        known[identity] = amounts,own
    total_in = sum(amount[0] for amount,_ in known.values())
    total_out = sum(amount[1] for amount,_ in known.values())
    for record in records:
        identity = _identity(record)
        # A manual full final record includes the snapshot already. An
        # automatic record retains its delta and needs the successful snapshot.
        persisted_identity = (record['run_id'],record['session_id'],*identity)
        if persisted_identity in known:
            continue
        total_in += snapshot[identity][0]
        total_out += snapshot[identity][1]
    if (_count(metrics.get('tokens_in') or 0,'persisted tokens_in'),
        _count(metrics.get('tokens_out') or 0,'persisted tokens_out')) != (total_in,total_out):
        raise Deferred('Unattributed existing nonzero metric credits; leave totals unchanged')


def _plan(ticket, run, session, ledger, messages):
    records = _records(run, session, ledger)
    calls = _calls(messages)
    rid = _owners(calls, run, messages)
    if ticket.get('id') != rid:
        raise Deferred('Request identity mismatch')
    metrics = ticket.get('metrics')
    if not isinstance(metrics, dict):
        raise Deferred('Request metrics unavailable')
    detail = metrics.get('tokens_detail') or {}
    if not isinstance(detail, dict):
        raise Deferred('Invalid persisted token details')
    snapshot = _snapshots(calls, rid, records, run)
    manual = _manual_credits(detail, records, run)
    _check_existing_totals(metrics,detail,records,snapshot,manual)
    common = 'hermes_session_' + session['id'] + '_recorded'
    final = 'hermes_run_' + run['id'] + '_accounting_final_recorded'
    if detail.get(common) and (detail[common] != 1 or len(manual) != len(records)):
        raise Deferred('Another session accountant ran without complete model provenance')
    if detail.get(common) == 1 and len(manual) == len(records):
        return {'request_id':rid, 'run_id':run['id'], 'session_id':session['id'],
                'status':'already_recorded', 'tokens_in_added':0, 'tokens_out_added':0}
    if detail.get(final):
        if detail[final] != 1 or detail.get(common) != 1 or len(manual) != len(records):
            raise Deferred('Inconsistent aggregate accounting marker')
        return {'request_id':rid, 'run_id':run['id'], 'session_id':session['id'],
                'status':'already_recorded', 'tokens_in_added':0, 'tokens_out_added':0}
    additions = []
    for record in records:
        record = dict(record, request_id=rid)
        identity = _identity(record)
        marker = _marker(run, record)
        before_in, before_out = snapshot[identity]
        if before_in > record['tokens_in_including_caches'] or before_out > record['tokens_out']:
            raise Deferred('Successful snapshot exceeds exact final model usage')
        old = detail.get(marker + '_usage')
        if marker in detail and (detail[marker] != 1 or not isinstance(old, dict) or not _matches(old, record)):
            raise Deferred('Per-model accounting marker disagrees')
        if marker in detail:
            continue
        was_manual = identity in manual
        if was_manual:
            continue
        delta_in = 0 if was_manual else record['tokens_in_including_caches'] - before_in
        delta_out = 0 if was_manual else record['tokens_out'] - before_out
        record.update(final_marker=marker, tokens_in_added=delta_in, tokens_out_added=delta_out,
                      successful_snapshot_tokens_in=before_in, successful_snapshot_tokens_out=before_out,
                      prior_manual_marker=manual.get(identity))
        additions.append((marker, record))
    summary = {'run_id':run['id'], 'session_id':session['id'], 'request_id':rid,
               'availability':'measured_final', 'tokens_in':sum(r['tokens_in_including_caches'] for r in records),
               'tokens_out':sum(r['tokens_out'] for r in records),
               'api_calls':sum(r['api_call_count'] for r in records),
               'reasoning_tokens_included_in_output':sum(r['reasoning_tokens_included_in_output'] for r in records),
               'model_markers':[manual.get(_identity(r),_marker(run,r)) for r in records],
               'billed_credits':'unavailable', 'duration_credited':False,
               'tools_added':False, 'turns_added':0, 'old_unavailable_history_preserved':True}
    return {'request_id':rid, 'run_id':run['id'], 'session_id':session['id'], 'status':'reconciled',
            'additions':additions, 'common_marker':common, 'final_marker':final, 'summary':summary,
            'tokens_in_added':sum(r['tokens_in_added'] for _,r in additions),
            'tokens_out_added':sum(r['tokens_out_added'] for _,r in additions)}


def reconcile_run(store, run, session, ledger, messages):
    """Atomically credit one finalized, singly owned session; ambiguity defers.

    Passing data does not grant ownership: all mutation owner IDs, including
    attempted metrics, are checked. The caller must supply the complete message
    history and exact finalized model ledger, never a truncated UI summary.
    """
    try:
        rid = _owners(_calls(messages), run, messages)
        with store.lock:
            # Merge counters and markers in one SQLite transaction. A lost
            # process or SQL failure cannot leave token credits without markers.
            store.db.execute('BEGIN IMMEDIATE')
            try:
                row = store.db.execute("SELECT body FROM docs WHERE kind='request' AND id=?", (rid,)).fetchone()
                if not row:
                    raise Deferred('Owned inbox request is missing')
                ticket = json.loads(row[0])
                plan = _plan(ticket, run, session, ledger, messages)
                if plan['status'] == 'already_recorded':
                    store.db.rollback()
                    return plan
                new = copy.deepcopy(ticket)
                mt = new['metrics']
                mt['tokens_in'] = _count(mt.get('tokens_in') or 0, 'persisted tokens_in') + plan['tokens_in_added']
                mt['tokens_out'] = _count(mt.get('tokens_out') or 0, 'persisted tokens_out') + plan['tokens_out_added']
                detail = mt.setdefault('tokens_detail', {})
                solvers = mt.setdefault('usage_by_solver', [])
                if not isinstance(solvers, list):
                    raise Deferred('Invalid persisted model attribution')
                for marker, record in plan['additions']:
                    detail[marker], detail[marker+'_usage'] = 1, record
                    if not record['tokens_in_added'] and not record['tokens_out_added']:
                        continue
                    matches = [item for item in solvers if (item.get('provider'),item.get('model'),item.get('system')) ==
                               (record['provider'],record['model'],'Hermes')]
                    if len(matches) > 1:
                        raise Deferred('Ambiguous persisted solver totals')
                    entry = matches[0] if matches else {'provider':record['provider'],'model':record['model'],
                            'system':'Hermes','tokens_in':0,'tokens_out':0,'agent_seconds':0,'timed':False,
                            'token_count_unavailable':0}
                    if not matches:
                        solvers.append(entry)
                    entry['tokens_in'] = _count(entry.get('tokens_in') or 0, 'solver tokens_in') + record['tokens_in_added']
                    entry['tokens_out'] = _count(entry.get('tokens_out') or 0, 'solver tokens_out') + record['tokens_out_added']
                detail[plan['common_marker']] = detail[plan['final_marker']] = 1
                detail[plan['final_marker']+'_usage'] = plan['summary']
                store.db.execute("UPDATE docs SET body=? WHERE kind='request' AND id=?", (json.dumps(new),rid))
                receipt = {k:v for k,v in plan.items() if k != 'additions'}
                store.db.execute('INSERT INTO docs(kind,id,body) VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body',
                                 ('hermes_accounting',run['id'],json.dumps(receipt)))
                store.db.commit()
                return receipt
            except Exception:
                store.db.rollback()
                raise
    except (Deferred, ValueError, TypeError, KeyError) as exc:
        return {'run_id':run.get('id'), 'status':'deferred', 'reason':str(exc),
                'tokens_in_added':0, 'tokens_out_added':0}


def _fsync_directory(directory):
    if os.name != 'posix':
        return  # Windows does not support os.open/fsync on directory handles.
    try:
        fd = os.open(directory,os.O_RDONLY | getattr(os,'O_DIRECTORY',0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError as exc:
        unsupported = {errno.EINVAL,errno.ENOTSUP,getattr(errno,'EOPNOTSUPP',errno.ENOTSUP)}
        if exc.errno not in unsupported:
            raise


def _save_journal(path, value):
    temporary = path.with_suffix('.tmp')
    with temporary.open('wb') as stream:
        stream.write(json.dumps(value,sort_keys=True).encode('utf8'))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary,path)
    _fsync_directory(path.parent)


def _make_journal_directory(path):
    missing = []
    directory = path
    while not directory.exists():
        missing.append(directory)
        directory = directory.parent
    for directory in reversed(missing):
        directory.mkdir(exist_ok=True)
        _fsync_directory(directory.parent)
    if not path.is_dir():
        raise OSError('Accounting journal path is not a directory')
    # Also persist the leaf entry if another process created it during discovery.
    _fsync_directory(path.parent)


def _api_payload(plan):
    if plan['additions']:
        marker, record = plan['additions'][0]
        return {'provider':record['provider'], 'model':record['model'], 'system':'Hermes',
                'tokens_in':record['tokens_in_added'], 'tokens_out':record['tokens_out_added'],
                'tokens_detail':{marker:1,marker+'_usage':record}, 'tools':{}, 'turns':0}
    return {'tokens_in':0,'tokens_out':0,'tools':{},'turns':0,
            'tokens_detail':{plan['common_marker']:1,plan['final_marker']:1,
                             plan['final_marker']+'_usage':plan['summary']}}


def _verify_api_write(before, after, body):
    """A matching marker alone is insufficient if counters or history differ."""
    if not isinstance(after,dict) or after.get('id') != before.get('id'):
        raise Deferred('Accounting response request identity mismatch')
    mt, old = after.get('metrics') or {}, before.get('metrics') or {}
    if (mt.get('tokens_in') or 0,mt.get('tokens_out') or 0) != (
            (old.get('tokens_in') or 0)+body['tokens_in'],(old.get('tokens_out') or 0)+body['tokens_out']):
        raise Deferred('Concurrent or uncertain metric credits require review')
    if any(mt.get(k) != old.get(k) for k in ('tools','turns','agent_seconds','duration_s','files_changed')):
        raise Deferred('Non-token request metrics changed during reconciliation')
    if any(after.get(k) != before.get(k) for k in ('status','solved_by')):
        raise Deferred('Request acceptance changed during reconciliation')
    detail, old_detail = mt.get('tokens_detail') or {},old.get('tokens_detail') or {}
    if any(detail.get(k) != v for k,v in old_detail.items()):
        raise Deferred('Historical token details changed during reconciliation')
    if any(detail.get(k) != v for k,v in body['tokens_detail'].items()):
        raise Deferred('Accounting markers did not persist exactly')


def reconcile_run_api(api, run, session, ledger, messages, *, state_dir: Path | None = None):
    """Inject a GET/POST(path, optional_body) client, without retrying blind POSTs.

    A durable write intent precedes each token/marker POST. On response loss the
    ticket is re-read. If the exact receipt cannot be verified, the intent stays
    pending and future calls defer rather than replaying the write. The ordinary
    Hermes dispatch lock serializes this dedicated accounting lane.
    """
    from . import hermes_delivery
    try:
        records = _records(run,session,ledger)
        rid = _owners(_calls(messages),run,messages)
        directory = Path(state_dir) if state_dir is not None else hermes_delivery.state_dir()/'accounting'
        _make_journal_directory(directory)
        journal_path = directory/(run['id']+'.json')
        with hermes_delivery.locked('completed-accounting'):
            journal = json.loads(journal_path.read_text(encoding='utf8')) if journal_path.exists() else {}
            if journal and (journal.get('run_id'),journal.get('session_id'),journal.get('request_id')) != (run['id'],session['id'],rid):
                raise Deferred('Accounting journal identity mismatch')
            added_in = added_out = 0
            for _ in range(len(records)+2):
                ticket = api('/api/requests/'+rid)
                pending = journal.get('pending')
                if pending:
                    # Even after a process crash, never replay an unconfirmed
                    # write. A read can resolve it only with the exact counters.
                    _verify_api_write(pending['before'],ticket,pending['body'])
                    journal.pop('pending')
                    _save_journal(journal_path,journal)
                plan = _plan(ticket,run,session,ledger,messages)
                if plan['status'] == 'already_recorded':
                    return {'run_id':run['id'],'request_id':rid,'session_id':session['id'],
                            'status':'reconciled' if added_in or added_out else 'already_recorded',
                            'tokens_in_added':added_in,'tokens_out_added':added_out}
                body = _api_payload(plan)
                before = {k:ticket.get(k) for k in ('id','status','solved_by','metrics')}
                journal.update(run_id=run['id'],session_id=session['id'],request_id=rid,
                               pending={'before':before,'body':body})
                _save_journal(journal_path,journal)
                try:
                    after = api('/api/requests/'+rid+'/metrics',body)
                except Exception as exc:
                    status = getattr(exc,'code',None) or getattr(getattr(exc,'response',None),'status_code',None)
                    if isinstance(exc,urllib.error.HTTPError) or status is not None:
                        if isinstance(status,int) and 400 <= status < 500:
                            journal.pop('pending')
                            _save_journal(journal_path,journal)
                            raise Deferred('Metric POST explicitly rejected; no credit inferred') from exc
                    # Response timeout can follow a committed write. Resolve by
                    # GET exactly once; an unresolved intent forbids re-posting.
                    try:
                        after = api('/api/requests/'+rid)
                    except Exception as read_exc:
                        raise Deferred('Metric write outcome uncertain; durable intent retained') from read_exc
                _verify_api_write(ticket,after,body)
                journal.pop('pending')
                _save_journal(journal_path,journal)
                added_in += body['tokens_in']
                added_out += body['tokens_out']
            raise Deferred('Accounting did not reach its aggregate marker')
    except (Deferred,ValueError,TypeError,KeyError) as exc:
        return {'run_id':run.get('id'),'status':'deferred','reason':str(exc),
                'tokens_in_added':0,'tokens_out_added':0}


def reconcile_completed(store=None, home: Path | None = None, *, limit: int = 10, api=None,
                        state_dir: Path | None = None):
    """Explicit bounded scan of ended cron runs across all jobs, not one route.

    Hermes databases are opened read-only. Missing schemas, unfinished runs,
    ambiguous session matches or incomplete message histories are left alone.
    No inference, task dispatch or provider change runs here. An injected API
    client reads ticket evidence and writes only verified token metrics.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
        raise ValueError('limit must be an integer from1 to50')
    if (store is None) == (api is None):
        raise ValueError('Supply exactly one Store or injected API client')
    home = (Path(home) if home is not None else hermes_tasks._home()).resolve()
    paths = home/'cron/executions.db', home/'state.db'
    if not all(path.is_file() for path in paths):
        return []
    output = []
    try:
        with closing(sqlite3.connect(paths[0].as_uri()+'?mode=ro',uri=True)) as cron, \
             closing(sqlite3.connect(paths[1].as_uri()+'?mode=ro',uri=True)) as db:
            cron.row_factory = db.row_factory = sqlite3.Row
            cron.execute('PRAGMA query_only=ON')
            db.execute('PRAGMA query_only=ON')
            # Maintenance executions often outnumber inference by a wide margin.
            # They do not spend the inference-run budget, but discovery itself
            # remains bounded. Find the newest actual finalized model sessions.
            candidate_limit = min(500,max(100,limit*10))
            runs = [dict(row) for row in cron.execute("SELECT id,job_id,status,started_at,finished_at FROM executions "
                    "WHERE status IN ('completed','failed') AND finished_at IS NOT NULL ORDER BY started_at DESC LIMIT ?",(candidate_limit,))]
            inference_runs = 0
            for run in runs:
                try:
                    started = hermes_tasks._stamp(run['started_at'])
                    if started is None:
                        raise Deferred('Execution start unavailable')
                    matches = db.execute("SELECT * FROM sessions WHERE source='cron' AND id LIKE ? "
                                         'AND started_at>=? AND started_at<=?',
                                         ('cron_'+run['job_id']+'_%',started-120,started+120)).fetchall()
                    if not matches:
                        continue  # script/no-agent execution
                    if len(matches) != 1:
                        raise Deferred('No unique execution/session match')
                    session = dict(matches[0])
                    if not session.get('ended_at'):
                        continue
                    # Several scheduler executions near one conversation are
                    # not a one-to-one run match, even if only one session exists.
                    overlapping = cron.execute('SELECT id FROM executions WHERE job_id=? AND id!=? '
                        'AND ABS((julianday(started_at)-2440587.5)*86400-?)<120',
                        (run['job_id'],run['id'],session['started_at'])).fetchall()
                    if overlapping:
                        raise Deferred('Conversation ambiguously matches multiple executions')
                    messages = [dict(row) for row in db.execute('SELECT role,content,tool_calls,tool_call_id,tool_name FROM messages '
                                'WHERE session_id=? ORDER BY id LIMIT 4001',(session['id'],))]
                    if len(messages) > 4000:
                        raise Deferred('Message history exceeds bounded scan; no partial accounting')
                    ledger = [dict(row) for row in db.execute('SELECT * FROM session_model_usage WHERE session_id=?',(session['id'],))]
                    if not ledger:
                        continue
                    inference_runs += 1
                    normalized = dict(run, state=run['status'], session_id=session['id'])
                    output.append(reconcile_run_api(api,normalized,session,ledger,messages,state_dir=state_dir)
                                  if api is not None else reconcile_run(store,normalized,session,ledger,messages))
                    if inference_runs >= limit:
                        break
                except (Deferred, sqlite3.Error) as exc:
                    output.append({'run_id':run['id'],'status':'deferred','reason':str(exc),
                                   'tokens_in_added':0,'tokens_out_added':0})
    except sqlite3.Error:
        return [{'status':'deferred','reason':'Hermes accounting schema unavailable',
                 'tokens_in_added':0,'tokens_out_added':0}]
    return output
