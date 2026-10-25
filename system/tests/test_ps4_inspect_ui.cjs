const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(require.resolve('../clients/web/index.html'), 'utf8');

function inspector() {
  const calls = [], context = vm.createContext({
    D: {regs: {pc: 0x80000000}, prev: {}, addr: 0x80000000}, DEBUG_EMU: {},
    esc: s => String(s).replace(/[<>]/g, ''), tq: () => '',
    api: async (_url, body) => {
      calls.push(body.op);
      if (body.op === 'info') return {platform: 'ps4', title: 'Test game', rom: 'eboot.bin',
        capabilities: {query_memory_map: 'supported'}};
      return {scope: 'process_virtual', note: 'Includes host/emulator memory',
        regions: [{start: '0x900000000', end: '0x900010000', size: 65536, writable: true, executable: true, type: 'private'}]};
    }
  });
  vm.runInContext(html.slice(html.indexOf('const I = { src: "ram"'), html.indexOf('async function hexRefresh(sid)')), context);
  return {context, calls};
}

test('PS4 Inspect obtains actual process map and requires explicit region selection', async () => {
  const {context, calls} = inspector();
  const rendered = await vm.runInContext('inspectView("ps4-session")', context);
  assert.deepEqual(calls, ['info', 'query_memory_map']);
  assert.match(rendered, /Choose a process memory region/);
  assert.match(rendered, /0x900000000/);
  assert.match(rendered, /Includes host\/emulator memory/);
  assert.equal(vm.runInContext('I.addr', context), null);
  assert.equal(context.D.addr, null);
  vm.runInContext('I.addr = 0x900000000; I.base = I.addr;', context);
  await vm.runInContext('inspectView("ps4-next-session")', context);
  assert.equal(vm.runInContext('I.addr', context), null);
});

test('Inspect search-result navigation does not truncate x64 addresses', () => {
  const source = html.match(/\$\("#sres"\)\.onclick = e => \{([^\n]+)\};/)[1];
  const context = vm.createContext({I: {}, e: {target: {dataset: {j: '38654705695'}}, preventDefault() {}},
    $: () => ({}), hex: n => n.toString(16), hexRefresh() {}, sid: 'ps4'});
  vm.runInContext(`(() => { ${source} })()`, context);
  assert.equal(context.I.addr, 0x900000010);
});
