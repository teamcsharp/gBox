const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const mapper = require('../clients/web/viz/cast-mapper.js');
const { withPage, findChrome } = require('../scripts/browser_lifecycle.cjs');
const script = fs.readFileSync(path.join(__dirname, '../clients/web/viz/cast-mapper.js'), 'utf8');
const skip = !findChrome() && 'No Chromium browser installed';
const fixture = {
  game: { game_id: 'target-game', title: 'Original title', platform: 'GameCube' },
  source: { key: 'source-game', label: 'Replacement title' },
  targets: Array.from({ length: 8 }, (_, i) => ({ id: `t${i}`, slot: i === 7 ? null : `fighter:${i}`,
    slug: `original-${i}`, name: `Original ${i}`, model_url: `/model/original-${i}.glb`, preview_url: i ? '' : '/missing.png' })),
  donors: Array.from({ length: 5 }, (_, i) => ({ id: `d${i}`, slug: `d${i}`, name: `Replacement ${i}`,
    ready: i !== 4, reason: i === 4 ? 'Requires re-extraction' : '', model_url: `/model/donor-${i}.glb` })),
  capability: { combined_writer: false, blocking_reasons: ['Native combined writer is not implemented.'] },
};
const setup = `document.body.innerHTML='<div id="host" style="max-width:1100px;margin:auto;padding:12px;background:#111722"></div>';
  document.body.style.cssText='margin:0;background:#0b1019';window.changes=[];window.inspections=[];
  window.data=${JSON.stringify(fixture)};
  window.panel=GBoxCastMapper.mount(document.querySelector('#host'),data,{onChange:r=>changes.push(r),inspect:(c,s)=>inspections.push({id:c.id,side:s}),img:u=>u});
  window.waitFrame=()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
  window.card=(s,id)=>document.querySelector('[data-cm-card="'+s+'"][data-key="'+id+'"]');
  window.click=(s,id,action)=>card(s,id).querySelector('[data-action="'+action+'"]').click();`;

test('seeded deals are stable, exhaustive per bag and safe for arbitrary target identifiers', () => {
  const ids = Array.from({ length: 12 }, (_, i) => `target-${i}`);
  const a = mapper.deal(ids, ['sonic', 'tails', 'knuckles', 'sonic'], 'seed');
  assert.deepEqual(a, mapper.deal(ids, ['sonic', 'tails', 'knuckles'], 'seed'));
  assert.notDeepEqual(a, mapper.deal(ids, ['sonic', 'tails', 'knuckles'], 'different'));
  for (let i = 0; i < ids.length; i += 3) assert.equal(new Set(ids.slice(i, i + 3).map(id => a[id])).size, 3);
  assert.deepEqual(Object.keys(mapper.deal(ids, [], 'seed')), []);
  assert.equal(mapper.deal(['__proto__'], ['donor'], 'seed').__proto__, 'donor');
});

test('roster normalization keeps real slots nullable and stable donor identities without inventing assets', () => {
  assert.deepEqual(mapper.roster([{ id: 'a', name: 'A' }, { id: 'a', name: 'duplicate' }, null], 'target'), [{ id: 'a', name: 'A', slot: null }]);
  assert.equal(mapper.roster([{ id: 'a', slot: 'native:a' }], 'target')[0].slot, 'native:a');
  assert.deepEqual(mapper.roster([{ id: 'old-id', slug: 'slug', name: 'A' }, { id: 'another-id', slug: 'slug' }], 'donor'), [{ id: 'slug', slug: 'slug', name: 'A' }]);
});

test('click connections, inspection, locks, pool selection and seeded review snapshots', { skip }, async () => {
  await withPage(async (evaluate, send) => {
    await send('Emulation.setDeviceMetricsOverride', { width: 1200, height: 850, deviceScaleFactor: 1, mobile: false });
    await evaluate(script); await evaluate(setup);
    assert.equal(await evaluate(`panel.getAssignments().length`), 8);
    assert.equal(await evaluate(`panel.getAssignments()[7].slot`), null);
    assert.match(await evaluate(`document.querySelector('.cm-capability').textContent`), /Native combined writer/);
    await evaluate(`click('target','t0','target');click('donor','d1','donor');waitFrame()`);
    assert.deepEqual(await evaluate(`panel.getAssignments()[0]`), { target_id: 't0', slot: 'fighter:0', character: 'd1' });
    assert.equal(await evaluate(`card('target','t0').querySelector('[data-action=lock]').checked`), true);
    assert.equal(await evaluate(`document.querySelectorAll('[data-lines] path').length`), 1);
    const points = await evaluate(`document.querySelector('[data-lines] path').getAttribute('d')`);
    assert.match(points, /^M[\d.]+,[\d.]+ C/);
    await evaluate(`click('target','t0','inspect');click('donor','d1','inspect');`);
    assert.deepEqual(await evaluate(`inspections`), [{ id: 't0', side: 'target' }, { id: 'd1', side: 'donor' }]);
    await evaluate(`document.querySelector('[data-action=pool-none]').click();card('donor','d0').querySelector('[data-action=pool]').click();card('donor','d2').querySelector('[data-action=pool]').click();panel.shuffle('locked-seed');`);
    assert.equal(await evaluate(`panel.getAssignments()[0].character`), 'd1');
    assert.equal(await evaluate(`panel.getAssignments().slice(1).every(r=>['d0','d2'].includes(r.character))`), true);
    const first = await evaluate(`panel.getAssignments()`);
    await evaluate(`panel.shuffle('locked-seed')`);
    assert.deepEqual(await evaluate(`panel.getAssignments()`), first);
    await evaluate(`click('target','t0','remove');`);
    assert.equal(await evaluate(`panel.getAssignments()[0].character`), '');
    assert.equal(await evaluate(`card('target','t0').querySelector('[data-action=lock]').checked`), false);
    await evaluate(`panel.setAssignments([{target_id:'t7',slot:'invented',character:'d4'},{target_id:'missing',character:'d0'},{target_id:'t0',character:'unknown'}]);`);
    assert.deepEqual(await evaluate(`panel.getAssignments()[7]`), { target_id: 't7', slot: null, character: 'd4' });
    assert.equal(await evaluate(`panel.getAssignments().filter(r=>r.character).length`), 1);
    await evaluate(`panel.clear();`);
    assert.equal(await evaluate(`panel.getAssignments().every(r=>r.character==='')`), true);
    assert.deepEqual(await evaluate(`changes.at(-1)`), await evaluate(`panel.getAssignments()`));
    // Keeping the original is also a deliberate choice that can stay locked across reopening.
    await evaluate(`card('target','t0').querySelector('[data-action=lock]').click();window.draft=panel.getDraft();panel.dispose();panel=GBoxCastMapper.mount(document.querySelector('#host'),data);panel.restoreDraft(draft);panel.shuffle('reopened');`);
    assert.equal(await evaluate(`card('target','t0').querySelector('[data-action=lock]').checked`), true);
    assert.equal(await evaluate(`panel.getAssignments()[0].character`), '');
    assert.equal(await evaluate(`panel.getAssignments().slice(1).every(r=>r.character)`), true);
  });
});

test('search, keyboard activation, drag links and scroll geometry remain within responsive panels', { skip }, async () => {
  await withPage(async (evaluate, send) => {
    await send('Emulation.setDeviceMetricsOverride', { width: 660, height: 800, deviceScaleFactor: 1, mobile: false });
    await evaluate(script); await evaluate(setup);
    await evaluate(`const search=document.querySelector('[data-search=donor]');search.value='Replacement 3';search.dispatchEvent(new Event('input',{bubbles:true}));`);
    assert.equal(await evaluate(`[...document.querySelectorAll('[data-cm-card=donor]')].filter(el=>!el.hidden).length`), 1);
    await evaluate(`document.querySelector('[data-search=donor]').value='';document.querySelector('[data-search=donor]').dispatchEvent(new Event('input',{bubbles:true}));card('target','t0').querySelector('.cm-main').focus();`);
    await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'ArrowDown', code: 'ArrowDown' });
    await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'ArrowDown', code: 'ArrowDown' });
    assert.equal(await evaluate(`document.activeElement.closest('[data-cm-card]').dataset.key`), 't1');
    await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13 });
    await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13 });
    await evaluate(`card('donor','d3').querySelector('.cm-main').focus()`);
    await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13 });
    await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13 });
    assert.equal(await evaluate(`panel.getAssignments()[1].character`), 'd3');
    await evaluate(`const dt=new DataTransfer();card('donor','d0').querySelector('.cm-main').dispatchEvent(new DragEvent('dragstart',{bubbles:true,dataTransfer:dt}));card('target','t2').dispatchEvent(new DragEvent('dragover',{bubbles:true,cancelable:true,dataTransfer:dt}));card('target','t2').dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:dt}));waitFrame();`);
    assert.equal(await evaluate(`panel.getAssignments()[2].character`), 'd0');
    assert.equal(await evaluate(`document.querySelectorAll('[data-drop]').length`), 0);
    // The line follows scroll rather than continuing to point to the previous row position.
    await evaluate(`document.querySelector('[data-list=target]').scrollTop=300;waitFrame()`);
    assert.equal(await evaluate(`!!document.querySelector('[data-lines] path[data-target-id=t1]')`), false);
    assert.equal(await evaluate(`document.documentElement.scrollWidth<=innerWidth`), true);
    assert.equal(await evaluate(`document.querySelector('[data-list=target]').scrollHeight>document.querySelector('[data-list=target]').clientHeight`), true);
    await send('Emulation.setDeviceMetricsOverride', { width: 600, height: 800, deviceScaleFactor: 1, mobile: false });
    await evaluate(`waitFrame()`);
    assert.equal(await evaluate(`document.documentElement.scrollWidth<=innerWidth`), true);
    await send('Emulation.setDeviceMetricsOverride', { width: 660, height: 800, deviceScaleFactor: 1, mobile: false });
    await evaluate(`document.querySelector('[data-list=target]').scrollTop=0;document.querySelector('[data-list=donor]').scrollTop=0;waitFrame()`);
    const evidence = process.env.GBOX_CAST_MAPPER_SCREENSHOT;
    if (evidence) {
      const screenshot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
      fs.mkdirSync(path.dirname(evidence), { recursive: true }); fs.writeFileSync(evidence, Buffer.from(screenshot.result.data, 'base64'));
    }
  });
});

test('untrusted labels stay text, broken images have name fallbacks, and disposal cancels late work', { skip }, async () => {
  await withPage(async evaluate => {
    await evaluate(script); await evaluate(setup + `panel.dispose();data.targets[0].name='<img src=x onerror="window.injected=true">';data.donors[0].preview_url='javascript:alert(1)';
      window.rejectInspection=null;window.count=0;panel=GBoxCastMapper.mount(document.querySelector('#host'),data,{img:u=>u,onChange:()=>count++,inspect:()=>new Promise((r,no)=>rejectInspection=no)});`);
    assert.equal(await evaluate(`window.injected===true`), false);
    assert.equal(await evaluate(`card('donor','d0').querySelectorAll('img').length`), 0);
    await evaluate(`card('target','t0').querySelector('img').dispatchEvent(new Event('error'));`);
    assert.equal(await evaluate(`card('target','t0').querySelector('.cm-fallback').hidden`), false);
    assert.equal(await evaluate(`card('target','t0').querySelector('img').hidden`), true);
    await evaluate(`click('target','t0','inspect');panel.dispose();rejectInspection(new Error('late inspection'));panel.shuffle('after-dispose');panel.setAssignments([{target_id:'t0',character:'d0'}]);panel.clear();window.dispatchEvent(new Event('resize'));Promise.resolve();`);
    assert.equal(await evaluate(`document.querySelectorAll('.gbox-cast-mapper').length`), 0);
    assert.equal(await evaluate(`count`), 0);
    await evaluate(`panel.dispose();panel=GBoxCastMapper.mount(document.querySelector('#host'),{targets:[{id:'missing-model',name:'Not extracted',slug:'pending'}],donors:[]});`);
    assert.equal(await evaluate(`document.querySelector('[data-action=shuffle]').disabled`), true);
    assert.equal(await evaluate(`document.querySelector('[data-action=inspect]').disabled`), true);
    assert.match(await evaluate(`document.querySelector('.cm-status').textContent`), /No replacement characters/);
    await evaluate(`panel.dispose();panel=GBoxCastMapper.mount(document.querySelector('#host'),{targets:[],donors:[]});`);
    assert.match(await evaluate(`document.querySelector('.cm-status').textContent`), /No original character roster/);
  });
});
