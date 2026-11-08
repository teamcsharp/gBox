"""Make the MercMode sidebar's swap section title-aware, and give RE4 a section of its own.

The panel's four operations (swap clothes / plain / character->zombie / zombies->cast) are wired to RE5's `.arc` archives through
`/api/decrypt-lab/model-swap`, `strip-clothes` and `zombie-cast`. `labTitleFor` already resolves RE4 to `re4_switch`, but the SWAP map
holds RE5 paths only - so on RE4 those buttons offer archives that do not exist in that title and can only fail.

RE4's equivalent operations are pack-based (measured in rounds 100-119): the drawn player mesh is `pl08`, the village enemy is `em16`, and
`/api/decrypt-lab/replace` transfers proportions from a collection model or another pack with `auto_blend`. This patch renders that section
when the current title is RE4 and wires it to the route; every other title keeps the RE5 section untouched.
"""
import pathlib

target = pathlib.Path("system/clients/web/viz/mercmode.js")
source = target.read_text(encoding="utf-8")

re4_html = '''  // RE4 (Switch) swaps are pack-based, not archive-based: the drawn player mesh is pl08 (measured rounds 112-113), the village enemy is
  // em16, and /api/decrypt-lab/replace transfers proportions from a collection model or another pack. Offering RE5's .arc slots here
  // would only fail, so the section changes with the title.
  const RE4_PACKS = {player: 'pl08.udas', ganado: 'em16.udas', ganado2: 'em10.udas'};
  function re4SwapHTML(){
    return `<div class="pip-mm-swaps"><small>Characters · RE4 (Switch) · applies at the next boot</small>`+
      `<label>Pack <select data-mm-r4-pack>`+
      `<option value="player" selected>player body (pl08)</option>`+
      `<option value="ganado">village enemy (em16)</option>`+
      `<option value="ganado2">village enemy (em10)</option>`+
      `</select></label>`+
      `<span class="pip-mm-swap-buttons">`+
      `<button type="button" data-mm-r4="sonic">Sonic proportions</button>`+
      `<button type="button" data-mm-r4="ganado">Ganado proportions</button>`+
      `<button type="button" data-mm-r4="plain">Remove clothes (materials)</button>`+
      `</span><label class="pip-mm-retag"><input type="checkbox" data-mm-r4-blend>Full strength (off = auto from the pack's bands)</label>`+
      `<small>Proportions come from the collection's model; the mesh keeps its own topology (this engine draws nothing else).</small></div>`;
  }
'''
anchor = "  function swapHTML(){\n"
assert anchor in source, "swapHTML not found in the expected shape"
source = source.replace(anchor, re4_html + "  function swapHTML(title){\n", 1)

old_body = '''    return `<div class="pip-mm-swaps"><small>Characters &amp; zombies · applies at the next boot</small>`+'''
new_body = '''    if (title === 're4_switch') return re4SwapHTML();
    return `<div class="pip-mm-swaps"><small>Characters &amp; zombies · applies at the next boot</small>`+'''
assert old_body in source
source = source.replace(old_body, new_body, 1)

# the call site inside menuHTML: pass the lab title so the section can choose
old_call = "}${queueHTML(host,catalog)}${swapHTML()}${objectsHTML()}</div></div>`;"
new_call = "}${queueHTML(host,catalog)}${swapHTML(host.current_run?.lab_title||'')}${objectsHTML()}</div></div>`;"
if old_call in source:
    source = source.replace(old_call, new_call, 1)
    print("menuHTML passes the title")
else:
    print("WARNING: the swapHTML() call site was not found; it still renders the RE5 section")

# wireSwaps: an RE4 branch before the RE5 handlers
old_wire = '''    const APPLY = 'mercmode-swap';            // every panel swap writes this build; apply_live boots it in place'''
new_wire = '''    const APPLY = 'mercmode-swap';            // every panel swap writes this build; apply_live boots it in place
    if (title === 're4_switch') { wireRe4Swaps(root, {api, title, done, fail}); return; }'''
assert old_wire in source
source = source.replace(old_wire, new_wire, 1)

re4_wire = '''
  // RE4's four operations, each one call to /api/decrypt-lab/replace. The donor is the collection's Sonic model for the two "proportions"
  // buttons and the other pack for the third; "remove clothes" is the material-hide path, which on this title leaves the surface itself
  // untouched (measured round 113) and is offered with that meaning rather than as a promise.
  const RE4_DONOR_GLB = '/home/ehm_eckx/agent-work/re4chars/sonic_src.glb';
  function wireRe4Swaps(root,{api,title,done,fail}){
    const packKey = () => root.querySelector('[data-mm-r4-pack]')?.value || 'player';
    const pack = () => RE4_PACKS[packKey()] || RE4_PACKS.player;
    const blend = () => (root.querySelector('[data-mm-r4-blend]')?.checked ? 1.0 : null);
    const run = async(button) => {
      button.disabled = true;
      try {
        const kind = button.dataset.mmR4;
        let body = {title, pack: pack(), build: 'mercmode-swap', write: true};
        if (kind === 'sonic') body = {...body, donor_glb: RE4_DONOR_GLB, blend: blend()};
        else if (kind === 'ganado') body = {...body, donor_pack: RE4_PACKS.ganado, donor_slot: 0, blend: blend()};
        else body = {...body, hide: Array.from({length: 24}, (_, i) => i + 1), hide_mode: 'vanish'};
        const r = await api('/api/decrypt-lab/replace', body);
        const report = r?.report || {};
        done(kind === 'plain'
          ? `Materials hidden in ${report.pack || body.pack} (${report.skipped?.length || 0} step(s)); the surface itself is unchanged on this title.`
          : `${report.pack || body.pack}: ${report.touched || 0} slot(s), blend ${report.blend ?? 'auto'}, ${report.vertices_changed || 0} vertices — applies at the next boot.`);
      } catch (error) { fail(error); }
      finally { button.disabled = false; }
    };
    root.querySelectorAll('[data-mm-r4]').forEach(b => b.addEventListener('click', e => { e.stopPropagation(); run(b); }));
  }
'''
anchor2 = "  function wireSwaps(root,{api,title,sessionId,done,fail}){"
assert anchor2 in source
source = source.replace(anchor2, re4_wire + anchor2, 1)

target.write_text(source, encoding="utf-8")
print("mercmode.js: RE4 section added")
