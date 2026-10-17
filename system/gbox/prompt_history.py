"""Export retained operator prompts, ordered by event time across all requests and chats."""
from datetime import datetime, timezone
from .inbox import automated


def markdown(requests, chats=(), redact=lambda text: text):
    events = []
    linked = {}
    for r in requests:
        rid = r.get('id', '')
        context = r.get('context') or {}
        cid = context.get('conversation') or context.get('chat_id')
        messages = r.get('messages') or []
        initial = r.get('body') or r.get('title') or ''
        operator = [m for m in messages if m.get('author') in ('operator', 'user')]
        is_auto = automated(r)
        if is_auto:
            operator = [m for m in operator if not (m.get('text') == initial and
                        abs((m.get('ts') or r.get('created', 0)) - r.get('created', 0)) < 1)]
            if cid:
                linked.setdefault((cid, initial), []).append(r.get('created') or 0)
        # Some old requests have only agent replies; their original body still matters.
        if not is_auto and initial and not any(m.get('text') == initial and
                abs((m.get('ts') or r.get('created', 0)) - r.get('created', 0)) < 1 for m in operator):
            operator.insert(0, {'text': initial, 'ts': r.get('created'), 'author': r.get('author', 'operator')})
        for i, m in enumerate(operator):
            text = m.get('text') or ''
            stamp = m.get('ts') or r.get('created') or 0
            events.append((stamp, f'request:{rid}:{i}', text, f"Request #{r.get('number', '?')} ({rid}); {r.get('source', 'unknown')}", m.get('attachments') or []))
            if cid:
                linked.setdefault((cid, text), []).append(stamp)
    for c in chats:
        for i, e in enumerate(c.get('events') or []):
            if e.get('type') != 'user':
                continue
            text = e.get('text') or ''
            stamp = e.get('ts') or c.get('created') or 0
            # Deduplicate only a recorded link to the same chat turn, never global repeated text.
            matches = linked.get((c.get('id'), text), [])
            same = next((s for s in matches if abs(s - stamp) < 30), None)
            if same is not None:
                matches.remove(same)
                continue
            events.append((stamp, f"chat:{c.get('id')}:{i}", text, f"Chat {c.get('id')}: {c.get('title') or ''}", []))
    out = ['# gBox prompt history', '', f'{len(events)} recorded prompts, oldest first (UTC).', '',
           'Includes retained request bodies, operator follow-ups, imported prompts and chat turns. '
           'Deleted or never-imported conversations cannot be reconstructed. Credentials are redacted.', '']
    for stamp, key, text, source, attachments in sorted(events, key=lambda e: (e[0], e[1])):
        when = datetime.fromtimestamp(stamp, timezone.utc).isoformat() if stamp else 'Time not recorded'
        out += [f'## {when}', '', source, f'Event: {key}', '', redact(text), '']
        for attachment in attachments:
            out += [f"Attachment: {attachment.get('name') or attachment.get('sha256') or 'recorded image'}", '']
    return '\n'.join(out).encode('utf-8', 'replace').decode('utf-8')
