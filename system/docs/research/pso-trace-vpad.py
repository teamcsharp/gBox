"""Instrument the vpad path with explicit, verifiable strings - no templating.

The previous attempt raised before writing, so adapters.py is untouched; this one builds each insertion as a literal so there is nothing to mis-expand, and compiles
before and after.
"""
import pathlib
import py_compile

path = pathlib.Path(r"C:\_tools\gBox\system\gbox\adapters.py")
before = path.read_text(encoding="utf-8")
py_compile.compile(str(path), doraise=True)
print("adapters.py compiles BEFORE the patch")

if "vpad_trace.log" in before:
    print("already instrumented - nothing to do")
    raise SystemExit(0)

text = before
changes = 0

ENTRY = """        self.vpad = self.vpad2 = self.vpad3 = None
        try:
            with open(r'D:\\gBox\\pso-ds\\vpad_trace.log', 'a', encoding='utf-8') as _t:
                _t.write(time.strftime('%H:%M:%S') + ' setup_vpad entered gecko=' + repr(getattr(self, 'gecko_id', None))
                         + ' capture=' + repr(getattr(self, 'capture_backend', None))
                         + ' flag=' + repr(os.environ.get('GBOX_DOLPHIN_VPAD', '<unset>')) + '\\n')
        except Exception:
            pass
        if not self._want_vpad():
            try:
                with open(r'D:\\gBox\\pso-ds\\vpad_trace.log', 'a', encoding='utf-8') as _t:
                    _t.write(time.strftime('%H:%M:%S') + ' _want_vpad() is False - keyboard ini used\\n')
            except Exception:
                pass
            return None"""

old_entry = """        self.vpad = self.vpad2 = self.vpad3 = None
        if not self._want_vpad():
            return None"""
if old_entry in text:
    text = text.replace(old_entry, ENTRY, 1)
    changes += 1
    print("traced: entry and the want gate")

GIVE_UP = """            try:
                with open(r'D:\\gBox\\pso-ds\\vpad_trace.log', 'a', encoding='utf-8') as _t:
                    _t.write(time.strftime('%H:%M:%S') + ' make() failed after 3 tries: ' + str(last) + '\\n')
            except Exception:
                pass
            self._p(50, f"virtual pad unavailable after 3 tries, keyboard input used: {last}")
            return None"""
old_give_up = """            self._p(50, f"virtual pad unavailable after 3 tries, keyboard input used: {last}")
            return None"""
if old_give_up in text:
    text = text.replace(old_give_up, GIVE_UP, 1)
    changes += 1
    print("traced: make() gave up")

SLOT = """        vp1 = make()
        try:
            with open(r'D:\\gBox\\pso-ds\\vpad_trace.log', 'a', encoding='utf-8') as _t:
                _t.write(time.strftime('%H:%M:%S') + ' make() -> ' + ('slot ' + str(getattr(vp1, 'slot', None)) if vp1 is not None else 'None') + '\\n')
        except Exception:
            pass
        if vp1 is None:
            return None
        self.vpad = vp1"""
old_slot = """        vp1 = make()
        if vp1 is None:
            return None
        self.vpad = vp1"""
if old_slot in text:
    text = text.replace(old_slot, SLOT, 1)
    changes += 1
    print("traced: the pad's slot")

print("changes:", changes)
path.write_text(text, encoding="utf-8")
py_compile.compile(str(path), doraise=True)
print("adapters.py compiles AFTER the patch")
print("trace writes:", path.read_text(encoding='utf-8').count("vpad_trace.log"))
