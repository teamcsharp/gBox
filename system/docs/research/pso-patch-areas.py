"""Give every area its own picker: one button, a dropdown of all Episode I destinations.

The operator wants all areas available by default in every session. The game's own area list is gated by quest progress held in the save, and there is no
verified way to rewrite that here: `pso_ragol_unlock` is a research gate for a different build and states it contains no write targets, and the memory
card payload is encrypted with no recovered key. What *is* available - and is how this session already moved between Forest, Caves and the Dragon - is
the plane's `floor_warp`, which reaches any floor directly.

So the tool makes that a single click:

  * the dialog gains a **select** field type (a real `<select>`), because a list of thirteen areas must not be typed from memory;
  * the manifest gains an **Area** entry whose values are the floor identifiers `floor_warp` expects, labelled with the area names;
  * the existing **Boss arena** entry covers De Rol Le, Vol Opt and Dark Falz through `boss_warp`.

That makes every area reachable in one click in every session, without pretending the save's progress flags were changed.
"""
import pathlib

# 1. the dialog learns <select>
page = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\index.html")
text = page.read_text(encoding="utf-8")

old_rows = """  const rows = (fields || []).map((field, index) => `
    <label style="display:block;margin:6px 0">
      <span style="display:block;font-size:11px;color:#9aa4b2;margin-bottom:2px">${field.label}</span>
      <input data-field="${index}" type="${field.type === 'number' ? 'number' : 'text'}"
             value="${String(field.value == null ? '' : field.value).replace(/"/g, '&quot;')}"
             style="width:100%;padding:5px 6px;background:#0d1117;color:#e6edf3;border:1px solid #30363d;border-radius:4px">
    </label>`).join('');"""

new_rows = """  const inputStyle = "width:100%;padding:5px 6px;background:#0d1117;color:#e6edf3;border:1px solid #30363d;border-radius:4px";
  const rows = (fields || []).map((field, index) => {
    const label = `<span style="display:block;font-size:11px;color:#9aa4b2;margin-bottom:2px">${field.label}</span>`;
    if (field.type === 'select') {
      const options = (field.options || []).map(option => {
        const value = String(option.value).replace(/"/g, '&quot;');
        const text = String(option.label).replace(/</g, '&lt;');
        return `<option value="${value}"${String(option.value) === String(field.value) ? ' selected' : ''}>${text}</option>`;
      }).join('');
      return `<label style="display:block;margin:6px 0">${label}<select data-field="${index}" style="${inputStyle}">${options}</select></label>`;
    }
    return `<label style="display:block;margin:6px 0">${label}<input data-field="${index}" type="${field.type === 'number' ? 'number' : 'text'}"
             value="${String(field.value == null ? '' : field.value).replace(/"/g, '&quot;')}" style="${inputStyle}"></label>`;
  }).join('');"""

if text.count(old_rows) != 1:
    raise SystemExit(f"dialog rows pattern count {text.count(old_rows)}")
text = text.replace(old_rows, new_rows, 1)

# the collector must read selects too
old_inputs = "  const inputs = [...box.querySelectorAll('input[data-field]')];"
new_inputs = "  const inputs = [...box.querySelectorAll('input[data-field], select[data-field]')];"
if text.count(old_inputs) == 1:
    text = text.replace(old_inputs, new_inputs, 1)

page.write_text(text, encoding="utf-8")
print("dialog supports a select field")

# 2. the manifest gains the Area entry
mods = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\game-mods.js")
mtext = mods.read_text(encoding="utf-8")

entry = """    {id: 'area', label: 'Go to any area of Episode I', icon: ICONS.warp, op: 'floor_warp',
     ask: [{key: 'target', label: 'Area', type: 'select', value: '1', options: [
       {value: '0', label: 'Pioneer 2 (city)'},
       {value: '1', label: 'Forest 1'},
       {value: '2', label: 'Forest 2'},
       {value: '3', label: 'Cave 1'},
       {value: '4', label: 'Cave 2'},
       {value: '5', label: 'Cave 3'},
       {value: '6', label: 'Mine 1'},
       {value: '7', label: 'Mine 2'},
       {value: '8', label: 'Ruins 1'},
       {value: '9', label: 'Ruins 2'},
       {value: '10', label: 'Ruins 3'},
       {value: '11', label: 'Dragon arena'},
       {value: '12', label: 'De Rol Le arena'},
       {value: '13', label: 'Vol Opt arena'},
       {value: '14', label: 'Dark Falz arena'}
     ]}]},
"""
anchor = "    {id: 'warp', label: 'Teleport to a floor'"
if "id: 'area'" not in mtext:
    if mtext.count(anchor) != 1:
        raise SystemExit("manifest anchor not found")
    mtext = mtext.replace(anchor, entry + anchor, 1)
    mods.write_text(mtext, encoding="utf-8")
    print("manifest gained the Area entry with every Episode I destination")
