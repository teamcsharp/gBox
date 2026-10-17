"""Exit evidence shared by recovery UI and automatic failure reports.

A process exit value can come from ExitProcess/TerminateProcess as well as an
unhandled exception. In particular Windows termination commonly yields 1; that
number alone cannot establish that a game crashed.
"""


def crash_code(info):
    code = (info or {}).get('returncode')
    if not isinstance(code, int) or isinstance(code, bool):
        return False
    # POSIX fatal signals, plus signed/unsigned Windows exception statuses.
    if code in (-4, -6, -7, -8, -11):
        return True
    status = code & 0xffffffff
    return status in {
        0x80000003,  # breakpoint / unhandled trap
        0xc0000005,  # access violation
        0xc000001d,  # illegal instruction
        0xc000008c,  # array bounds
        0xc000008d, 0xc000008e, 0xc000008f, 0xc0000090,
        0xc0000091, 0xc0000092, 0xc0000093, 0xc0000094, 0xc0000095,
        0xc0000096,  # privileged instruction
        0xc00000fd,  # stack overflow
        0xc0000374,  # heap corruption
        0xc0000409,  # fail fast
    }


def intentional(info):
    return bool(isinstance(info, dict) and (info.get('via') or 'timings' in info))


def merge(previous, incoming):
    """A late process watcher must not erase an acknowledged stop or saved moment."""
    previous = previous if isinstance(previous, dict) else {}
    incoming = incoming if isinstance(incoming, dict) else {}
    result = previous | incoming
    if previous.get('via') and not incoming.get('via'):
        result['via'] = previous['via']
    return result
