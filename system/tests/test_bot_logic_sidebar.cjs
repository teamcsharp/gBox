// The PiP's bot logic sidebar: grouped knobs, sliders and toggles; a change is an operator re5_mods job (op bot_logic).
const test = require('node:test');
const assert = require('node:assert');
const S = require('../clients/desktop/bot-logic-sidebar.js');
const VIEW = { title: 're6', knobs: [
  { name: 'FLASH', label: 'Flash and fight', group: 'Crowd control', kind: 'bool', value: true, set: false, min: 0, max: 1, step: 1 },
  { name: 'FLASH_GAP_S', label: 'Seconds between flashes', group: 'Crowd control', kind: 'float', value: 5, set: true, min: 0.5, max: 15, step: 0.5, help: 'fight window' }] };

test('the knobs render as a toggle and a slider, grouped', () => {
  const h = S.html(VIEW);
  assert.match(h, /<h4>Crowd control<\/h4>/);
  assert.match(h, /type="checkbox" data-bl="FLASH" checked/);
  assert.match(h, /type="range" data-bl="FLASH_GAP_S" min="0.5" max="15" step="0.5" value="5"/);
  assert.match(h, /bl-set/);
});

test('a change submits the bot_logic job to the session worker and reads the result back', async () => {
  const calls = [];
  const api = async (path, body) => { calls.push([path, body]); return { id: 'j1', state: 'succeeded', output: { result: VIEW } }; };
  const sb = S.create({ api, doc: null, delay: async () => {} });
  sb.update({ on: true, sid: 'w123-abc' });
  await sb.set('FLASH_GAP_S', 3);
  assert.equal(calls[0][0], '/api/jobs');
  assert.deepEqual(calls[0][1].input, { session_id: 'w123-abc', op: 'bot_logic', values: { FLASH_GAP_S: 3 } });
  assert.equal(calls[0][1].require_worker, 'w123') && assert.equal(calls[0][1].tool, 're5_mods');
  assert.equal(sb.state().view.title, 're6');
});
