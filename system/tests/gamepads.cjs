// Run with node system/tests/gamepads.cjs. Exercises the application's actual input loop.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '../clients/web/index.html'), 'utf8');
const source = html.slice(html.indexOf('const RETRO ='), html.indexOf('async function snap(sid)'));
const storage = new Map(), sent = [], nodes = new Map();
let devices = [];
const context = vm.createContext({
  navigator: {getGamepads: () => devices},
  localStorage: {getItem: k => storage.get(k), setItem: (k,v) => storage.set(k,v)},
  api: async (url, body) => sent.push({url, ...body}),
  requestAnimationFrame() {}, addEventListener() {}, setInterval() {},
  $: key => nodes.get(key), cur: 'Sessions', active: {sid: 'first'}, show() {},
  esc: value => String(value).replace(/[&<>"']/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char])),
});
vm.runInContext(source, context);
const run = code => vm.runInContext(code, context);
const pad = (id, index, mapping='standard') => ({id,index,mapping,connected:true,axes:[0,0],buttons:Array.from({length:17},()=>({pressed:false,value:0}))});
const flush = async () => { await run('Promise.all([...padQueues.values()])'); };
const choose = gp => run(`selectPrimaryPad(${JSON.stringify(JSON.stringify({id:gp.id,index:gp.index}))})`);
async function test() {
  const space = pad('SpaceMouse Compact (Vendor: 256f Product: c635)',0,''), xbox = pad('Xbox One Controller',2), other = pad('DualSense Wireless Controller',1);
  devices = [space,other,xbox];
  assert.equal(run('selectedPad().id'), xbox.id, 'Xbox wins even when SpaceMouse is slot zero');
  assert.equal(run('cfgFor(pads().find(p=>p.index===2)).player'),1);
  assert.equal(run('pads().length'),2);
  for (const id of ['Unknown (Vendor: 256f Product: c635)', '3Dconnexion KMJ Emulator', 'Unknown (Vendor: beef Product: 046d)', 'beef-046d', 'Unknown (Vendor: 046d Product: c626)', '046d-c626', 'Space Navigator'])
    assert.equal(run(`blockedPad({id:${JSON.stringify(id)}})`),true,id);
  run('padCfg[padKey(pads()[0])] = {player:0,map:{...XBOX_DEFAULT},stick:true}');
  assert.equal(run('cfgFor(pads()[0]).player'),1,'legacy slot assignment does not disable Xbox');
  space.buttons[0].pressed = true; xbox.buttons[0].pressed = true;
  run('padLoop()'); await flush();
  assert.equal(sent.length,1,'SpaceMouse sends no input');
  assert.equal(sent[0].events[0].player,1);
  assert.equal(sent[0].events[0].down,true);
  choose(other); run('padLoop()'); await flush();
  assert.equal(sent.at(-1).events[0].down,false,'switch releases original controller');
  assert.equal(JSON.parse(storage.get('gbox_primary_pad')).id,other.id,'manual choice is saved');
  other.buttons[1].pressed = true; run('padLoop()'); await flush();
  assert.equal(sent.at(-1).events[0].key,'a');
  context.active = {sid:'second'}; run('padLoop()'); await flush();
  assert.equal(sent.at(-2).url,'/api/sessions/first/input');
  assert.equal(sent.at(-2).events[0].down,false,'session switch releases in original game');
  assert.equal(sent.at(-1).url,'/api/sessions/second/input');
  assert.equal(sent.at(-1).events[0].down,true);
  devices = [space,xbox]; run('padLoop()'); await flush();
  assert.equal(run('selectedPad()'),null,'missing manual selection does not silently switch');
  assert.equal(sent.at(-1).events[0].down,false,'disconnect releases held buttons');
  other.index=3; devices.push(other); run('padLoop()'); await flush();
  assert.equal(run('selectedPad().index'),3,'saved device reconnects at a new slot');
  run('selectPrimaryPad("none"); padLoop()'); await flush();
  assert.equal(run('selectedPad()'),null);
  assert.equal(sent.at(-1).events[0].down,false,'off releases held buttons');
  run('selectPrimaryPad(""); padLoop()'); await flush();
  assert.equal(run('selectedPad().id'),xbox.id,'automatic restores Xbox preference');
  const button = {setAttribute(k,v){this[k]=v}}, picker = {hidden:true};
  nodes.set('#padstat',button); nodes.set('#padpicker',picker);
  run('padStatus(); togglePadPicker()');
  assert.equal(button['aria-expanded'],'true');
  assert.match(button.textContent,/Xbox One Controller/);
  assert.match(picker.innerHTML,/Player 1 controller/);
  assert.doesNotMatch(picker.innerHTML,/<option[^>]*>[^<]*SpaceMouse/);
  run('togglePadPicker()'); assert.equal(picker.hidden,true);
  const before = storage.get('gbox_primary_pad');
  choose(space); assert.equal(storage.get('gbox_primary_pad'),before,'blocked device cannot be selected');
  devices = [space]; run('padLoop()'); await flush();
  assert.equal(run('selectedPad()'),null,'SpaceMouse never becomes fallback');
  console.log('Gamepad regression checks passed');
}
test().catch(error => {console.error(error); process.exitCode=1;});
