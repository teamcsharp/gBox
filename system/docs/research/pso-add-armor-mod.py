"""Four random armor pieces, equipped - the operator's request, as one click.

*"When changing my equipment, make sure that the frame you give me have four armor slots and those four slots are filled with things at random from the game
as well."*

PSO's armor is three code families, documented in `psoitems.py`:

    frame    01 01 ii
    barrier  01 02 ii
    unit     01 03 ii

where `ii` is the item index in the catalog. A four-piece set is therefore one frame, one barrier and two units, each with a random index - and the plane's
`give` op takes `{code, count, equip}`, so equipping is part of the same call.

Two pieces are needed:

1. **the handler must support `run`** - a mod that performs several RPCs, not one;
2. **the manifest gains the armor entry**, which builds four codes and gives each one equipped.
"""
import pathlib

# 1. handler: support a mod that runs its own sequence of RPCs
page = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\index.html")
text = page.read_text(encoding="utf-8")

anchor = "            const out = await window.gboxPsoRpc(mod.op, fields || {});"
if anchor in text and "mod.run" not in text:
    replacement = """            if (typeof mod.run === 'function') {
              const out = await mod.run(window.gboxPsoRpc);
              toast(mod.id + ': ' + (out ? 'done' : 'no answer'));
            } else {
            const out = await window.gboxPsoRpc(mod.op, fields || {});"""
    text = text.replace(anchor, replacement, 1)
    # close the else
    old_tail = "            toast(out ? `${mod.id}: sent` : `${mod.id}: no answer`);"
    new_tail = "            toast(out ? `${mod.id}: sent` : `${mod.id}: no answer`);\n            }"
    if text.count(old_tail) == 1:
        text = text.replace(old_tail, new_tail, 1)
    page.write_text(text, encoding="utf-8")
    print("handler supports mod.run")
else:
    print("handler already supports run, or anchor missing")

# 2. the armor mod
mods = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\game-mods.js")
mtext = mods.read_text(encoding="utf-8")

entry = """    {id: 'armor4', label: 'Four random armor pieces, equipped', icon: ICONS.armor || ICONS.mag,
     // frame 01 01 ii, barrier 01 02 ii, unit 01 03 ii - one frame, one barrier, two units, each a random index
     run: async (rpc) => {
       const families = [0x0101, 0x0102, 0x0103, 0x0103];
       const codes = families.map(family => {
         const index = Math.floor(Math.random() * 0x60);
         return ((family << 8) | index).toString(16).padStart(6, '0');
       });
       for (const code of codes) {
         await rpc('give', { code, count: 1, equip: true });
       }
       window.__gboxArmorCodes = codes;
       return codes;
     }},
"""
if "id: 'armor4'" not in mtext:
    marker = "    {id: 'area',"
    if mtext.count(marker) == 1:
        mtext = mtext.replace(marker, entry + marker, 1)
        mods.write_text(mtext, encoding="utf-8")
        print("armor4 mod added")
    else:
        print("manifest anchor count", mtext.count(marker))
else:
    print("armor4 already present")
