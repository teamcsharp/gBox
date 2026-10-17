"""One owner for a session's ordered RetroArch-native cheat table.

Only independent set rows are frozen by gBox. Once a native row needs the
emulator, all native rows transfer there in table order and remain there.
Core-code and user-added gBox cheats are outside this ownership boundary.
"""
from __future__ import annotations

import threading

from . import cheats

_RUNTIME_LOCK = threading.RLock()


def is_native(entry):
    value = entry.get('handler', 0)
    if isinstance(value, bool):
        return False
    try:
        raw = str(value).strip()
        return int(raw, 16 if raw.lower().startswith('0x') else 10) == 1
    except (TypeError, ValueError):
        return False


def display_code(entry):
    return entry.get('code') or f"addr {entry.get('address', '?')} = {entry.get('value', '?')}"


class NativeCheatRuntime:
    def __init__(self, adapter, platform, mine, start):
        self.adapter, self.platform = adapter, platform
        self.entries, self.mine, self.start = adapter.cheats, mine, start
        self.lock = threading.RLock()
        self.retired = False
        self.logical = {i: bool(e.get('enable')) for i, e in enumerate(self.entries) if is_native(e)}
        # Startup-enabled rows already belong to RetroArch; never create a
        # second writer or infer that logical shadow state means RA is off.
        self.actual = dict(self.logical)
        self.emulator_owned = any(self.actual.values())

    def enabled(self, index):
        return self.logical[index]

    def engine(self, index):
        return 'retired' if self.retired else 'emulator' if self.emulator_owned else 'gbox'

    def retire(self):
        # Adapter table replacement makes every old numeric index ambiguous.
        # Stop old freezes under their own write lock; never toggle those old
        # indices against the adapter's replacement table. Keep aliases inert
        # so indices belonging to custom cheats do not move.
        with self.lock:
            for code in self.mine:
                if code.get('native_runtime') is self:
                    code['on'].clear()
            self.logical = {index: False for index in self.logical}
            self.retired = True

    def _sync_emulator(self, desired):
        # ad.cheats is shared logical state. cheat_set's no-op guard must see
        # the tracked actual RA state, not an earlier gBox-owned shadow toggle.
        try:
            for index in sorted(desired):
                if self.actual[index] == desired[index]:
                    continue
                self.entries[index]['enable'] = self.actual[index]
                self.adapter.cheat_set(index, desired[index])
                self.actual[index] = desired[index]
        except Exception:
            # No gBox freeze is resumed after a partial migration. Report only
            # states whose adapter command completed, so retry remains possible.
            self.logical = dict(self.actual)
            raise
        else:
            self.logical = dict(desired)
        finally:
            for index, enabled in self.logical.items():
                self.entries[index]['enable'] = enabled

    def _transfer(self, desired):
        # The freeze loop holds this same lock around its on-check AND write.
        # Entering here waits for any in-flight write before RA can be enabled.
        for code in self.mine:
            if code.get('native_runtime') is self:
                code['on'].clear()
        self.emulator_owned = True
        self._sync_emulator(desired)

    def set(self, index, on, *, probe=None):
        with self.lock:
            if self.retired:
                raise ValueError('Native cheat table was replaced; select a current database row instead of its retired alias')
            before = self.logical[index]
            desired = self.logical | {index: bool(on)}
            if self.emulator_owned:
                self._sync_emulator(desired)
            else:
                code = next((c for c in self.mine if c.get('native_runtime') is self and
                             c.get('native_index') == index), None)
                ops, bad = cheats.decode_native(self.platform, self.entries[index]) if on else ([], [])
                overlap = any(a < b + len(y) and b < a + len(x)
                              for _kind, a, x in ops for other in self.mine
                              if other.get('native_runtime') is self and other is not code and other['on'].is_set()
                              for _other_kind, b, y in other['ops'])
                # Independent freeze threads cannot preserve table ordering for
                # overlapping writes, even when both rows are simple constants.
                if on and (not ops or bad or overlap):
                    self._transfer(desired)
                else:
                    if on and not before:
                        if probe is None:
                            raise ValueError("Native write verification is required before enabling")
                        # Verify one application before reporting enabled or starting
                        # a background loop which otherwise suppresses write errors.
                        probe(index, ops)
                        if code is None:
                            code = {'key': f'db{index}', 'native_index': index, 'native_runtime': self,
                                    'lock': self.lock, 'desc': self.entries[index].get('desc', ''),
                                    'lines': [display_code(self.entries[index])], 'unsupported': []}
                            self.mine.append(code)
                        # A fresh event lets a previous sleeping loop exit even
                        # when this row is disabled/re-enabled before it wakes.
                        code['ops'], code['on'] = ops, threading.Event()
                        code['on'].set()
                        self.start(code)
                    elif not on and code is not None:
                        code['on'].clear()
                    self.logical = desired
                    self.entries[index]['enable'] = bool(on)
            return {'index': index, 'enabled': bool(on), 'changed': before != bool(on),
                    'engine': self.engine(index), 'desc': self.entries[index].get('desc')}


def runtime(adapter, platform, mine, start):
    with _RUNTIME_LOCK:
        current = getattr(adapter, '_gbox_native_cheats', None)
        if current is None or current.entries is not adapter.cheats or current.mine is not mine:
            if current is not None:
                current.retire()
            current = adapter._gbox_native_cheats = NativeCheatRuntime(adapter, platform, mine, start)
        return current
