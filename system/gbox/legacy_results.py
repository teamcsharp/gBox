"""Verify pre-durable result receipts without replaying acceptance callbacks."""
import base64
import json
import re
import math

from .store import canon, sha256


def verify_legacy_success(store, job, receipt, result, worker_id):
    """Verify an independently persisted old success before binding its digest.

    Missing or ambiguous evidence stays held. No callback or tool is rerun.
    """
    def require(condition):
        if not condition:
            raise ValueError('Legacy completion evidence does not verify this result')

    require(isinstance(receipt, dict) and job.get('state') == 'succeeded'
            and not job.get('cancel') and not job.get('result_sha256')
            and not job.get('result_acceptance') and result.get('ok') is True)
    require(all(isinstance(receipt.get(key), str) and receipt[key]
                for key in ('id', 'job_id', 'worker_id', 'tool', 'tool_version')))
    require(all(type(receipt.get(key)) in (int, float) and math.isfinite(receipt[key])
                and receipt[key] > 0 for key in ('started', 'finished'))
            and receipt['finished'] >= receipt['started'])
    require(all(type(job.get(key)) in (int, float) and math.isfinite(job[key])
                and job[key] > 0 for key in ('started', 'finished'))
            and job['finished'] >= job['started'])
    require(job.get('id') == result.get('job_id') == receipt.get('job_id')
            and job.get('worker_id') == worker_id == receipt.get('worker_id')
            and job.get('tool') == receipt.get('tool')
            and job.get('receipt_id') == receipt.get('id')
            and receipt.get('validation_ok') is True
            and receipt.get('validation_problems') == [])
    require(receipt.get('input_sha256') == sha256(canon(job.get('input')))
            and canon(job.get('output')) == canon(result.get('output'))
            and receipt.get('output_sha256') == sha256(canon(result.get('output')))
            and job.get('error') is None and result.get('error') is None
            and job.get('started') == receipt.get('started')
            and job.get('finished') == receipt.get('finished'))
    if job['tool'] == 'launch_game':
        output = result['output']
        session = store.get('session', output.get('session_id'))
        detail = output.get('detail') or {}
        pid = detail.get('pid')
        require(isinstance(session, dict) and session.get('session_id') == output.get('session_id')
                and isinstance(output.get('session_id'), str) and output['session_id'].startswith(worker_id + '-')
                and isinstance(output.get('adapter'), str) and output['adapter']
                and canon(session.get('adapter')) == canon(output['adapter'])
                and canon(session.get('game_id')) == canon((detail.get('_game') or {}).get('game_id'))
                and type(pid) is int and pid > 0
                and type((session.get('detail') or {}).get('pid')) is int
                and (session.get('detail') or {}).get('pid') == pid)
        for checkpoint in detail.get('previous_checkpoints') or []:
            prior = store.get('session', checkpoint['session_id'])
            artifact = checkpoint.get('artifact')
            require(isinstance(artifact, str) and re.fullmatch('[0-9a-f]{64}', artifact)
                    and type(checkpoint.get('bytes')) is int and checkpoint['bytes'] > 0)
            saved = store.read_artifact(artifact)
            require(isinstance(prior, dict) and prior.get('state') == 'ended'
                    and prior.get('checkpoint') == artifact and isinstance(saved, bytes)
                    and len(saved) == checkpoint['bytes'] and sha256(saved) == artifact)
    log = result.get('log') or []
    require(isinstance(log, list) and all(isinstance(line, str) for line in log))
    log_bytes = '\n'.join(log).encode()
    if log:
        require(job.get('log_sha') == sha256(log_bytes)
                and store.read_artifact(job['log_sha']) == log_bytes)
    else:
        require(not job.get('log_sha'))
    artifacts = result.get('artifacts') or []
    refs = receipt.get('artifacts')
    require(isinstance(artifacts, list) and isinstance(refs, list) and len(artifacts) == len(refs))
    for artifact, ref in zip(artifacts, refs):
        require(isinstance(artifact, dict) and isinstance(ref, dict))
        data = base64.b64decode(artifact['b64'], validate=True)
        provenance = artifact.get('provenance') or {}
        require(isinstance(provenance, dict))
        reserved = {'tool': receipt['tool'], 'tool_version': receipt['tool_version'],
                    'job': job['id'], 'worker': worker_id}
        require(all(key not in provenance or provenance[key] == value for key, value in reserved.items()))
        require(ref.get('sha256') == sha256(data) and type(ref.get('size')) is int and ref['size'] == len(data)
                and ref.get('name') == artifact.get('name')
                and ref.get('media_type') == artifact.get('media_type')
                and canon(ref.get('provenance')) == canon(provenance | reserved)
                and store.read_artifact(ref['sha256']) == data)
    seq = receipt.get('audit_seq')
    require(type(seq) is int and seq > 0)
    row = store.db.execute('SELECT ts,actor,action,subject,data,prev,hash FROM audit WHERE seq=?', (seq,)).fetchone()
    require(row is not None)
    ts, actor, action, subject, encoded, prev, digest = row
    event = json.loads(encoded)
    require(action == 'job.succeeded' and subject == job['id']
            and isinstance(event, dict) and event.get('receipt') == receipt['id']
            and event.get('artifacts') == [ref['sha256'] for ref in refs]
            and event.get('problems') == [] and event.get('error') is None)
    previous = store.db.execute('SELECT hash FROM audit WHERE seq<? ORDER BY seq DESC LIMIT 1', (seq,)).fetchone()
    require(prev == (previous[0] if previous else '0' * 64)
            and digest == sha256(prev.encode() + canon({'ts': ts, 'actor': actor,
                'action': action, 'subject': subject, 'data': event})))
    return True
