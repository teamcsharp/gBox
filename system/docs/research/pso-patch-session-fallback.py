"""Make session.py fall back to the worker's own port automatically.

The desktop service (18765) has been answering 504 for this session while the worker mirror (8765) answers correctly. Rather than export an
environment variable for every script, `_call` now retries the other port when the first one reports a gateway timeout, and remembers the
winner for the rest of the process.
"""
import pathlib

PATH = pathlib.Path(r"C:\_tools\gBox\.tmp\session.py")
text = PATH.read_text(encoding="utf-8")

if "FALLBACK_API" not in text:
    text = text.replace(
        'API = os.environ.get("GBOX_API") or "http://127.0.0.1:18765"',
        'API = os.environ.get("GBOX_API") or "http://127.0.0.1:18765"\n'
        'FALLBACK_API = "http://127.0.0.1:8765"   # the worker mirror answers when the desktop service is stale')

old_call = 'def _call(path, method="GET", body=None, timeout=40):'
new_call = '''def _call(path, method="GET", body=None, timeout=40, _retry=True):
    global API
    try:
        return _call_once(API, path, method, body, timeout)
    except Exception as exc:                                     # noqa: BLE001
        code = getattr(exc, "code", 0)
        if _retry and code == 504 and API != FALLBACK_API:
            API = FALLBACK_API                                   # desktop service is stale: use the worker directly
            return _call(path, method, body, timeout, _retry=False)
        raise


def _call_once(base, path, method="GET", body=None, timeout=40):'''

assert text.count(old_call) == 1
text = text.replace(old_call, new_call)

# the original body used the module-level API through urlopen(f"{API}..."), which _call_once now owns via `base`
text = text.replace('f"{API}{path}"', 'f"{base}{path}"')
PATH.write_text(text, encoding="utf-8")
print("session.py now falls back to the worker port on 504")
