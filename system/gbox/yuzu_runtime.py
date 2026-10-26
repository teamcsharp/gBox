"""Opt-in Switch debugger configuration for an operator's private local runtime."""
from __future__ import annotations

from pathlib import Path


def set_debug_config(path: Path, *, port: int, enabled: bool = True, dump_nso: bool = True) -> None:
    """Preserve unrelated Qt settings and the original file; only a local copy calls this."""
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError('Yuzu debugger port must be 1024..65535')
    original = path.read_bytes()
    text = original.decode('utf-8-sig')
    values = {'use_gdbstub': str(bool(enabled)).lower(), 'use_gdbstub\\default': 'false',
              'gdbstub_port': str(port), 'gdbstub_port\\default': 'false',
              'dump_nso': str(bool(dump_nso)).lower(), 'dump_nso\\default': 'false'}
    lines, section, pending = [], '', dict(values)
    for line in text.splitlines():
        if line.startswith('['):
            if section == 'Debugging':
                lines.extend(f'{key}={value}' for key, value in pending.items())
                pending.clear()
            section = line.strip('[]')
        key = line.partition('=')[0].strip()
        if section == 'Debugging' and key in values:
            if key in pending:
                lines.append(f'{key}={pending.pop(key)}')
            continue
        lines.append(line)
    if pending:
        if section != 'Debugging':
            lines.append('[Debugging]')
        lines.extend(f'{key}={value}' for key, value in pending.items())
    backup = path.with_name(path.name + '.gbox-debug-original')
    if not backup.exists():
        backup.write_bytes(original)
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def private_debug_config(exe: Path, config) -> Path:
    """Debugging must never rewrite a shared NAS emulator/user configuration."""
    path = exe.parent / 'user' / 'config' / 'qt-config.ini'
    roots = (Path(config.runtime).resolve(), Path(config.data_dir).resolve())
    target = path.resolve()
    if str(exe).startswith(('\\\\', '//')) or not any(target.is_relative_to(root) for root in roots):
        raise ValueError('Switch debug launch requires an explicit private local runtime under gBox runtime/data')
    if not path.is_file():
        raise ValueError('Private Switch runtime needs its existing user/config/qt-config.ini')
    return path


SWITCH_KEYS = {'a': 'c', 'b': 'x', 'x': 'v', 'y': 'z', 'l': 'q', 'r': 'e',
               'zl': 'r', 'zr': 't', 'l2': 'r', 'r2': 't', 'plus': 'm', 'start': 'm',
               'minus': 'n', 'select': 'n', 'lstick': 'f', 'rstick': 'g',
               'left': 'Left', 'right': 'Right', 'up': 'Up', 'down': 'Down',
               'dleft': 'Left', 'dright': 'Right', 'dup': 'Up', 'ddown': 'Down',
               'lleft': 'a', 'lright': 'd', 'lup': 'w', 'ldown': 's',
               'rleft': 'j', 'rright': 'l', 'rup': 'i', 'rdown': 'k'}


def input_events(events):
    out = []
    for event in events:
        key = str(event.get('key', '')).casefold()
        if key not in SWITCH_KEYS:
            raise ValueError(f'Unknown Switch control: {key}')
        out.append({**event, 'key': SWITCH_KEYS[key]})
    return out
