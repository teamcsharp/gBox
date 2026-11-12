"""Give the PiP toolbar PSO actions, and hide the Resident Evil ones when a PSO game is active.

The compact bar currently hardcodes RE actions - round replay, stage preferences, primary weapon, emergency flashbang, grenade ring - which is what the
operator saw while playing Phantasy Star Online and asked to be replaced by actions for the game at hand:

    "whenever I'm playing PSO, I want options in the top to change the equipment that I have, to adjust the stats of my mag, to teleport different
     areas, and bring up the live map viewer for controlling the bot on a 2d map"

This adds a PSO action group - **Equip**, **Mag**, **Warp**, **Map** - hidden by default and shown only when the active game is PSO
(`436e0bb84d5337d1`), and hides the RE-only buttons in that case. Each button calls the plane's own `pso_controls` RPC on the current session, so it
changes the real game rather than a mock:

  * **Equip**  - `equip` with a weapon code;
  * **Mag**    - `mag_set` with def/pow/dex/mind, iq and synchro;
  * **Warp**   - `floor_warp` with a floor number (string, which is what the request model accepts);
  * **Map**    - opens the live minimap at http://127.0.0.1:8802/ in a new window.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\index.html")
text = path.read_text(encoding="utf-8")

# 1. add the PSO action group to the toolbar, plus data attributes the painter can target
old_group = '<button type="button" data-round-replay aria-label="Replay stage next round"></button>'
new_group = ('<span data-pso-actions hidden>'
             '<button type="button" data-pso-equip title="PSO: change the equipped weapon">Equip</button>'
             '<button type="button" data-pso-mag title="PSO: adjust the mag\'s stats">Mag</button>'
             '<button type="button" data-pso-warp title="PSO: teleport to another area">Warp</button>'
             '<button type="button" data-pso-map title="PSO: open the live 2D map viewer">Map</button>'
             '</span>'
             '<button type="button" data-round-replay aria-label="Replay stage next round"></button>')
if text.count(old_group) != 1:
    raise SystemExit(f"toolbar anchor count {text.count(old_group)}")
text = text.replace(old_group, new_group, 1)

# 2. wire the buttons and the game-aware visibility, right after the toolbar is built
anchor = "      controls.querySelector('[data-full]').onclick = () => compactRestore().catch(error => toast(error.message)); document.body.append(controls);"
wiring = anchor + """
      // PSO actions (operator 2026-11-11): the bar must offer what the ACTIVE game needs. For PSO that is equipment, the mag's stats, an area
      // warp and the 2D map viewer; the RE-only controls are hidden instead of shown greyed, because they mean nothing here.
      const PSO_GAME = '436e0bb84d5337d1';
      const psoRpc = async (op, fields) => {
        const sid = COMPACT && COMPACT.sid;
        if (!sid) { toast('No game in the PiP.'); return null; }
        try {
          return await gbox.api(`/api/sessions/${encodeURIComponent(sid)}/rpc`, { op, ...fields });
        } catch (error) { toast(`${op} failed: ${error && error.message || error}`); return null; }
      };
      const psoNumber = (label, value) => {
        const said = prompt(label, String(value == null ? '' : value));
        if (said === null) return null;
        const n = Number(said);
        return Number.isFinite(n) ? n : null;
      };
      controls.querySelector('[data-pso-equip]').onclick = async () => {
        const code = prompt('Weapon code to equip (e.g. 000600 Handgun, 000700 Rifle, 000200 Sword):', '000700');
        if (!code) return;
        const out = await psoRpc('equip', { target: String(code).trim() });
        if (out) toast(`equipped ${code}`);
      };
      controls.querySelector('[data-pso-mag]').onclick = async () => {
        const def = psoNumber('Mag DEF', 5); if (def === null) return;
        const pow = psoNumber('Mag POW', 100); if (pow === null) return;
        const dex = psoNumber('Mag DEX', 50); if (dex === null) return;
        const mind = psoNumber('Mag MIND', 45); if (mind === null) return;
        const out = await psoRpc('mag_set', { properties: { def, pow, dex, mind, iq: 200, synchro: 120 } });
        if (out) toast(`mag set DEF ${def} POW ${pow} DEX ${dex} MIND ${mind}`);
      };
      controls.querySelector('[data-pso-warp]').onclick = async () => {
        const floor = prompt('Teleport to which floor? (0 city, 1 Forest 1, 2 Forest 2, 3 Cave 1 ... 11 Dragon)', '1');
        if (floor === null || floor === '') return;
        const out = await psoRpc('floor_warp', { target: String(floor).trim() });
        if (out && out.warped) toast(`warping to ${out.name || ('floor ' + out.floor)}`);
      };
      controls.querySelector('[data-pso-map]').onclick = () => {
        const win = root.open('http://127.0.0.1:8802/', 'gbox-pso-map', 'width=960,height=760');
        if (!win) toast('The map viewer could not open; is minimap_live.py running?');
      };
      const paintPso = gameId => {
        const pso = String(gameId || '') === PSO_GAME;
        const group = controls.querySelector('[data-pso-actions]');
        if (group) group.hidden = !pso;
        for (const selector of ['[data-round-replay]', '[data-stage-preferences]', '[data-primary-weapon]',
                                '[data-flash]', '[data-grenade-ring]', '[data-grenade-ring-kind]']) {
          const button = controls.querySelector(selector);
          if (button) button.hidden = pso;
        }
      };
      paintPso(COMPACT && COMPACT.gameId);
      controls.dataset.psoPaint = 'ready';"""
if text.count(anchor) != 1:
    raise SystemExit(f"wiring anchor count {text.count(anchor)}")
text = text.replace(anchor, wiring, 1)

# 3. keep the visibility right as the PiP's game changes
old_update = "compactCoach.update(state, controls?.querySelector('[data-compact-coach]'));"
new_update = ("compactCoach.update(state, controls?.querySelector('[data-compact-coach]'));\n"
              "    if (controls && controls.dataset.psoPaint === 'ready' && typeof paintPso === 'function') paintPso(COMPACT && COMPACT.gameId);")
if text.count(old_update) == 1:
    text = text.replace(old_update, new_update, 1)
    print("painted on every compact update too")

path.write_text(text, encoding="utf-8")
print("PSO actions added to the PiP toolbar; RE-only controls are hidden for PSO")
