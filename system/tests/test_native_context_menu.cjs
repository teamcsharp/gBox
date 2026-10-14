const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const web = fs.readFileSync(path.join(__dirname, '../clients/web/index.html'), 'utf8');
const nativeCode = web.slice(web.indexOf('const PW_GAME_VIEW ='), web.indexOf('</script>', web.indexOf('const PW_GAME_VIEW =')));
const genericCode = web.slice(web.indexOf('document.addEventListener("contextmenu", e => {'), web.indexOf('document.addEventListener("mousedown"', web.indexOf('document.addEventListener("contextmenu", e => {')));

function event(view, prevented = false) {
  return { defaultPrevented: prevented, stopped: false, clientX: 210, clientY: 240,
    target: { closest: selector => selector.includes(view.id === 'nativeslot' ? '#nativeslot' : 'img.screen') ? view : null },
    preventDefault() { this.defaultPrevented = true; }, stopPropagation() { this.stopped = true; } };
}

test('empty native surface opens the desktop game menu without filing a report', () => {
  const handlers = [], messages = [], picks = [];
  const context = { document: { addEventListener: (name, handler) => handlers.push(handler) },
    console: { log: message => messages.push(JSON.parse(message.slice(5))) },
    PWW: { menuAt: (...args) => picks.push(args) } };
  vm.runInNewContext(nativeCode, context);
  const e = event({ id: 'nativeslot' });
  handlers[0](e);
  assert.deepEqual(messages, [{ ev: 'gamecontext', x: 210, y: 240 }]);
  assert.equal(picks.length, 0);
  assert.ok(e.defaultPrevented && e.stopped);
});

test('stream images still use the web character menu', () => {
  let handler, picked;
  vm.runInNewContext(nativeCode, { document: { addEventListener: (_, fn) => { handler = fn; } },
    PWW: { menuAt: (...args) => { picked = args; } } });
  const view = { id: 'scr', classList: { contains: () => false } };
  handler(event(view));
  assert.deepEqual(picked, [210, 240, view]);
});

test('generic report listener leaves native surfaces and handled events alone', () => {
  let handler;
  // The listener body is executed, with no UI dependencies supplied: opening a report would throw.
  vm.runInNewContext(genericCode, { document: { addEventListener: (_, fn) => { handler = fn; } } });
  handler(event({ id: 'nativeslot' }));
  handler(event({ id: 'other' }, true));
});
