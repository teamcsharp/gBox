"""Receipt-bound extraction failures become offline local-engineering work.

No extractor, model, game, save or request status is changed here. Every accepted
occurrence is durable; repeated deliveries cannot create duplicate work.
"""
from __future__ import annotations

import json
import re
import time

from .models import new_id
from .store import append_audit, canon, sha256

KIND = 'extraction_engineering'
EVENT = 'extraction_engineering_job'
ID = re.compile(r'^[0-9a-f]{16}$')
HASH = re.compile(r'^[0-9a-f]{64}$')
CANCEL = re.compile(r'cancelled|canceled|stopped by the operator', re.I)
SELECTION = ('character', 'kind', 'session_id', 'x', 'y')


def failure(job):
    """A collection's partial *coverage* alone is not an extraction error."""
    inp = job.get('input') or {}
    if job.get('tool') != 'characters' or inp.get('op') not in ('collect', 'extract'):
        return None
    if job.get('state') not in ('failed', 'invalid', 'succeeded'):
        return None
    if job.get('cancel') or job.get('cancel_requested') or CANCEL.search(str(job.get('error') or '')):
        return None
    result = (job.get('output') or {}).get('result')
    result = result if isinstance(result, dict) else {}
    status = str(result.get('status') or '')
    rows = result.get('entries') or []
    bad = [r for r in rows if isinstance(r, dict) and (
        r.get('status') in ('failed', 'missing', 'unsupported') or r.get('error')
        or r.get('verified') is False or r.get('kind', 'character') == 'character'
        and r.get('retargetable') is False)] if isinstance(rows, list) else []
    if (job['state'] == 'succeeded' and not bad
            and status not in ('unsupported', 'missing', 'failed', 'error', 'blocked')
            and not result.get('error')):
        return None
    return {'state': job['state'], 'status': status, 'error': str(job.get('error') or result.get('error') or '')[:2000],
            'message': str(result.get('message') or '')[:2000], 'failed_entries': [
                {k: (r[k][:2000] if isinstance(r[k], str) else r[k]) for k in ('slug', 'name', 'kind', 'status', 'verified', 'retargetable', 'error', 'message')
                 if k in r} for r in bad[:40]], 'failed_entry_count': len(bad),
            'extractor': result.get('extractor'), 'reader_version': result.get('reader_version')}


def _identity(store, job):
    inp = job.get('input') or {}
    result = (job.get('output') or {}).get('result')
    result = result if isinstance(result, dict) else {}
    named_id = inp.get('game') if isinstance(inp.get('game'), str) and ID.fullmatch(inp['game']) else None
    gids = {str(g) for g in (inp.get('game_id'), result.get('game_id'), named_id) if g}
    if inp.get('session_id'):
        session = store.get('session', inp['session_id']) or {}
        if session.get('game_id'):
            gids.add(str(session['game_id']))
    if len(gids) != 1 or not ID.fullmatch(next(iter(gids))):
        raise ValueError('extraction handoff requires one unambiguous catalog game ID')
    gid = gids.pop()
    game = store.catalog_get(gid)
    if not game:
        raise ValueError('extraction handoff game is absent from the catalog')
    # Catalog paths identify the selection, not the bytes. Only carry a source
    # hash explicitly reported by this accepted result; never hash a later file.
    source = result.get('source') if isinstance(result.get('source'), dict) else {}
    source_hash = result.get('source_sha256') or source.get('sha256')
    source_hash = source_hash if isinstance(source_hash, str) and HASH.fullmatch(source_hash) else None
    snapshot = {k: game.get(k) for k in ('game_id', 'platform', 'library', 'source_paths', 'format', 'profile_id')}
    selected = {k: inp[k] for k in SELECTION if k in inp and inp[k] not in (None, '')}
    identity = {'game_id': gid, 'catalog': snapshot, 'reported_source_sha256': source_hash,
                'op': inp['op'], 'selection': selected}
    return game, identity


def observe(store, job_id, *, redact=lambda text: text):
    """Atomically create/update a request and its per-job occurrence marker.

    Called after terminal result acceptance; safe to retry explicitly after a
    crash. Uses stored jobs and receipts, never a caller-supplied result payload.
    """
    with store.lock:
        store.db.execute('BEGIN IMMEDIATE')
        try:
            prior = store.get(EVENT, job_id)
            if prior:
                store.db.rollback()
                return prior | {'existing': True}
            job = store.get('job', job_id) or {}
            issue = failure(job)
            if not issue:
                store.db.rollback()
                return None
            receipt = store.get('receipt', job.get('receipt_id') or '') or {}
            output_hash = sha256(canon(job['output'])) if job.get('output') is not None else None
            if (not receipt or receipt.get('job_id') != job_id or receipt.get('tool') != job.get('tool')
                    or receipt.get('worker_id') != job.get('worker_id')
                    or receipt.get('input_sha256') != sha256(canon(job.get('input') or {}))
                    or receipt.get('output_sha256') != output_hash):
                raise ValueError('extraction handoff receipt does not match the stored job')
            game, identity = _identity(store, job)
            key = sha256(canon(identity))
            index = store.get(KIND, key) or {}
            request = store.get('request', index.get('request_id') or '')
            # Single-model extract already files a request in its normal gap path.
            # Reuse only its exact job/game link; arbitrary output IDs are not authority.
            result = (job.get('output') or {}).get('result') or {}
            linked_id = (result.get('request') or {}).get('id') if isinstance(result, dict) and isinstance(result.get('request'), dict) else None
            linked = store.get('request', linked_id) if linked_id else None
            if not request and linked:
                context = linked.get('context') or {}
                if (linked.get('source') == 'characters' and context.get('job_id') == job_id
                        and context.get('game_id') == identity['game_id']):
                    request = linked
            # A new failure after a closed/blocked request gets a new task. Never
            # reopen an operator's closed/blocked request or silently mutate it.
            if request and request.get('status') not in ('open', 'in_progress'):
                request = None
            ts = time.time()
            evidence = {'job_id': job_id, 'receipt_id': receipt['id'], 'worker_id': receipt.get('worker_id'),
                        'input_sha256': receipt['input_sha256'], 'output_sha256': output_hash,
                        'started': receipt.get('started'), 'finished': receipt.get('finished'),
                        'parent_request_id': job.get('parent_request_id'), 'source': identity, 'issue': issue}
            text = redact('Extraction engineering occurrence: ' + job_id + '\n' + json.dumps(evidence, indent=2))
            created = request is None
            if created:
                rid = new_id()
                parent = job.get('parent_request_id')
                if parent and not store.get('request', parent):
                    parent = None
                body = redact(
                    'Extract the requested native models from ' + str(game.get('title') or identity['game_id'])
                    + '. Diagnose this exact extraction failure on the local Hermes/Spark engineering queue. '
                    'First verify source access and configuration; do not assume every error needs a new format reader. '
                    'When the reader is missing or wrong, use REA/Ghidra and the native-reader-writer playbook to '
                    'identify the native loader, develop or repair a bounded reusable reader in an isolated workspace, '
                    'and publish tested code with independently checked native assets. Preserve source files and '
                    'hash the exact owned build before analysis. Catalog paths are not content-hash evidence; '
                    'reported source hashes below are worker-reported, not independent verification. '
                    'Read all recorded occurrence receipts and failed entries. Rerun the same extraction after '
                    'integration and independently validate every requested asset before closing this task. '
                    'A queue item, analysis plan, PR merge or successful tool exit alone is not completion. '
                    'This is offline extraction work: do not launch, capture, pause or stop games, modify user '
                    'saves/memory, or perform a replacement. No writer or gameplay acceptance is requested here.\n\n' + text)
                request = {'id': rid, 'number': store.db.execute("SELECT count(*) FROM docs WHERE kind='request'").fetchone()[0] + 1,
                    'title': redact(('Extraction engineering: ' + str(game.get('title') or identity['game_id']))[:140]),
                    'body': body, 'source': 'characters', 'kind': 'text', 'image': None, 'element': None,
                    'status': 'open', 'created': ts, 'started': None, 'completed': None, 'author': 'system',
                    'parent_request_id': parent, 'automated': True,
                    'context': {'game_id': identity['game_id'], 'job_id': job_id, 'extraction_engineering': True,
                                'extraction_identity': identity, 'extraction_key': key, 'what': 'native model extraction',
                                'resolution_dispatch': 'hermes_queue'},
                    'messages': [{'author': 'system', 'text': body, 'ts': ts, 'attachments': []}],
                    'metrics': {'tokens_in': 0, 'tokens_out': 0, 'tools': {}, 'files_changed': [], 'duration_s': None, 'turns': 0}}
            else:
                request.setdefault('context', {}).update(extraction_engineering=True, extraction_key=key,
                    extraction_identity=identity, resolution_dispatch='hermes_queue')
                request.setdefault('messages', []).append({'author': 'system', 'text': text, 'ts': ts, 'attachments': []})
            event = {'job_id': job_id, 'receipt_id': receipt['id'], 'request_id': request['id'],
                     'key': key, 'at': ts, 'evidence': evidence}
            for kind, ident, value in [('request', request['id'], request), (EVENT, job_id, event),
                                       (KIND, key, {'request_id': request['id'], 'last_job_id': job_id, 'updated': ts})]:
                store.db.execute('INSERT OR REPLACE INTO docs(kind,id,body) VALUES(?,?,?)', (kind, ident, json.dumps(value)))
            append_audit(store.db, 'gbox-auto', 'extraction.engineering', request['id'],
                         {'job_id': job_id, 'receipt_id': receipt['id'], 'created': created, 'key': key}, ts=ts)
            store.db.commit()
            return event | {'created': created}
        except BaseException:
            store.db.rollback()
            raise
