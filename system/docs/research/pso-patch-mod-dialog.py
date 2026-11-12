"""Give the mod buttons a real pop-up: Electron disables window.prompt, so asking through it does nothing.

The operator reported that clicking the toolbar buttons does not show the dialog that would let them choose the specifics. The cause is not the button
wiring: **Electron's renderer does not implement `window.prompt`** - it returns without showing anything - so every `askFor()` prompt silently vanished
and the op was either sent with nulls or not sent at all.

This replaces that with a real DOM dialog:

  * `window.gboxAsk(fields)` returns a Promise of the collected values, or null when cancelled;
  * the dialog is a fixed overlay with one labelled input per field (number fields validate), an OK and a Cancel button, Escape to cancel and Enter to
    accept;
  * it is added to the compact-mode allow-list, because everything outside that list is hidden in the PiP;
  * the GPU game surface is taken down while it is open, for the same reason the context menu needed it - a DOM overlay cannot out-stack a composite
    surface.

`askFor` now awaits it instead of calling `prompt`.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\index.html")
text = path.read_text(encoding="utf-8")

# 1. allow the dialog in compact mode
old_list = ":not(#gbox-mod-dialog)"
if old_list not in text:
    anchor = ":not(#gbox-toasts):not(script):not(style)"
    if text.count(anchor) != 1:
        raise SystemExit("compact allow-list anchor not found")
    text = text.replace(anchor, ":not(#gbox-mod-dialog)" + anchor, 1)
    print("dialog added to the compact allow-list")

# 2. the dialog itself, plus the promise-based asker
if "window.gboxAsk" not in text:
    anchor = "// The PiP's game is a GPU surface above the page"
    if text.count(anchor) != 1:
        raise SystemExit("helper anchor not found")
    dialog = r'''// A real dialog for asking values. Electron's renderer does not implement window.prompt - it returns without showing anything - which is why the
// toolbar buttons appeared to do nothing when they needed specifics. This builds a DOM overlay instead, and takes the game surface down while it is up
// for the same reason the context menu does: a DOM element cannot out-stack the composite game surface.
window.gboxAsk = (fields) => new Promise(resolve => {
  document.getElementById('gbox-mod-dialog')?.remove();
  const box = document.createElement('div');
  box.id = 'gbox-mod-dialog';
  const rows = (fields || []).map((field, index) => `
    <label style="display:block;margin:6px 0">
      <span style="display:block;font-size:11px;color:#9aa4b2;margin-bottom:2px">${field.label}</span>
      <input data-field="${index}" type="${field.type === 'number' ? 'number' : 'text'}"
             value="${String(field.value == null ? '' : field.value).replace(/"/g, '&quot;')}"
             style="width:100%;padding:5px 6px;background:#0d1117;color:#e6edf3;border:1px solid #30363d;border-radius:4px">
    </label>`).join('');
  box.innerHTML = `
    <div style="position:fixed;inset:0;background:#000a;z-index:100000" data-backdrop></div>
    <div style="position:fixed;left:50%;top:50%;transform:translate(-50%,-50%);z-index:100001;width:min(420px,90vw);
                background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px;color:#e6edf3;
                font:13px/1.4 system-ui,sans-serif;box-shadow:0 12px 40px #000b">
      <div style="font-weight:600;margin-bottom:8px">Choose the specifics</div>
      ${rows}
      <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px">
        <button type="button" data-cancel style="padding:5px 12px;background:#21262d;color:#e6edf3;border:1px solid #30363d;border-radius:4px">Cancel</button>
        <button type="button" data-ok style="padding:5px 12px;background:#238636;color:#fff;border:1px solid #2ea043;border-radius:4px">Send</button>
      </div>
    </div>`;
  document.body.append(box);
  window.gboxPipCover?.(true);
  const inputs = [...box.querySelectorAll('input[data-field]')];
  const finish = (value) => { box.remove(); window.gboxPipCover?.(false); document.removeEventListener('keydown', onKey, true); resolve(value); };
  const collect = () => {
    const values = {};
    for (let i = 0; i < inputs.length; i += 1) {
      const field = fields[i];
      const raw = inputs[i].value;
      if (field.type === 'number') {
        const n = Number(raw);
        if (!Number.isFinite(n)) { inputs[i].focus(); return null; }
        values[field.key] = n;
      } else {
        values[field.key] = String(raw).trim();
      }
    }
    return values;
  };
  const onKey = event => {
    if (event.key === 'Escape') { event.preventDefault(); finish(null); }
    else if (event.key === 'Enter') { event.preventDefault(); finish(collect()); }
  };
  box.querySelector('[data-ok]').onclick = () => finish(collect());
  box.querySelector('[data-cancel]').onclick = () => finish(null);
  box.querySelector('[data-backdrop]').onclick = () => finish(null);
  document.addEventListener('keydown', onKey, true);
  setTimeout(() => inputs[0]?.focus(), 30);
});

'''
    text = text.replace(anchor, dialog + anchor, 1)
    print("dialog and gboxAsk added")

# 3. askFor waits for the dialog instead of calling prompt
old_ask = """      const askFor = spec => {
        const values = {};
        for (const field of spec) {
          const said = prompt(field.label, String(field.value == null ? '' : field.value));
          if (said === null) return null;
          values[field.key] = field.type === 'number' ? Number(said) : said.trim();
          if (field.type === 'number' && !Number.isFinite(values[field.key])) {
            toast(`${field.key} must be a number`); return null;
          }
        }
        return values;
      };"""
new_ask = """      const askFor = async spec => {
        if (typeof window.gboxAsk !== 'function') { toast('The dialog is unavailable.'); return null; }
        return await window.gboxAsk(spec);
      };"""
if text.count(old_ask) == 1:
    text = text.replace(old_ask, new_ask, 1)
    print("askFor now uses the dialog")
else:
    print("askFor pattern not found - left as is")

# 4. the callers must await it
text = text.replace("""            if (mod.ask) { fields = askFor(mod.ask); if (!fields) return; }""",
                    """            if (mod.ask) { fields = await askFor(mod.ask); if (!fields) return; }""")

path.write_text(text, encoding="utf-8")
print("done")
