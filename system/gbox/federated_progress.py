"""Bounded rebuild console snapshots; absolute source sequences survive retries and tail trimming."""
from __future__ import annotations

import math
import re

from .node_rebuild import redact

MAX_LINES = 200
MAX_LINE = 1024
MAX_TEXT = 32768
MAX_SEQ = 2 ** 53 - 1
_QUOTED = re.compile(
    r'''(?i)((?:token|secret|password|passwd|api[_-]?key|authorization)["']?\s*[=:]\s*)(["'])(.*?)\2''')


def _text(value, secrets=()):
    # Redact before truncation: cutting through a credential must not expose its prefix.
    for secret in secrets:
        if isinstance(secret, str) and secret:
            value = value.replace(secret, '***')
    value = _QUOTED.sub(lambda match: match[1] + match[2] + '***' + match[2], value)
    return redact(value).replace('\r', ' ').replace('\n', ' ')[:MAX_LINE]


def validate(value, secrets=()):
    """Only console evidence is accepted; no arbitrary job fields cross this channel."""
    if not isinstance(value, dict) or set(value) != {'seq', 'lines', 'progress'}:
        raise ValueError('Invalid rebuild progress snapshot')
    seq, lines, progress = value['seq'], value['lines'], value['progress']
    if type(seq) is not int or not 0 <= seq <= MAX_SEQ or not isinstance(lines, list) \
            or len(lines) > min(seq, MAX_LINES) or any(not isinstance(line, str) or len(line) > MAX_LINE for line in lines) \
            or sum(map(len, lines)) > MAX_TEXT:
        raise ValueError('Invalid rebuild console sequence or tail')
    if not isinstance(progress, dict) or set(progress) != {'pct', 'msg', 'ts'} \
            or not isinstance(progress['msg'], str) or len(progress['msg']) > MAX_LINE:
        raise ValueError('Invalid rebuild progress fields')
    pct, ts = progress['pct'], progress['ts']
    try:
        valid = type(pct) in (int, float) and 0 <= pct <= 100 and math.isfinite(pct) \
            and type(ts) in (int, float) and ts >= 0 and math.isfinite(ts)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError('Invalid rebuild progress values')
    return {'seq': seq, 'lines': [_text(line, secrets) for line in lines],
            'progress': {'pct': pct, 'msg': _text(progress['msg'], secrets), 'ts': ts}}


def snapshot(job, secrets=()):
    """Send a contiguous newest tail; omitted older lines retain their absolute source count."""
    if job.get('tool') != 'rebuild_node':
        return None
    progress, console = job.get('progress'), job.get('console') or []
    if not isinstance(progress, dict) or not isinstance(progress.get('msg'), str) or not isinstance(console, list):
        raise ValueError('Invalid local rebuild progress')
    lines, used = [], 0
    for line in reversed(console[-MAX_LINES:]):
        if not isinstance(line, str):
            raise ValueError('Invalid local rebuild console line')
        clean = _text(line, secrets)
        if used + len(clean) > MAX_TEXT:
            break
        lines.append(clean)
        used += len(clean)
    return validate({'seq': job.get('console_seq'), 'lines': list(reversed(lines)), 'progress': {
        'pct': progress.get('pct'), 'msg': _text(progress['msg'], secrets),
        'ts': progress.get('ts')}}, secrets)


def merge(job, value):
    """Called under the store lock after authority/job binding, before terminal result acceptance."""
    previous = max(job.get('federation_progress_seq', -1), job.get('console_seq', -1))
    if value['seq'] <= previous:
        return False
    pct = (job.get('progress') or {}).get('pct', 0)
    if type(pct) not in (int, float) or not 0 <= pct <= 100:
        pct = 0
    job.update(progress=value['progress'] | {'pct': max(pct, value['progress']['pct'])},
               progress_log=value['lines'][-50:], console=value['lines'],
               console_seq=value['seq'], federation_progress_seq=value['seq'])
    return True
