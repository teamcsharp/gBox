const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { withPage } = require('../scripts/browser_lifecycle.cjs');
const html = fs.readFileSync(path.join(__dirname,'../clients/desktop/index.html'),'utf8');
const start = html.indexOf('async function testPcMenu(');
const source = html.slice(start,html.indexOf('$("#tb-tasks").onclick',start));

test('background controls render measured load, default budget, gaming toggle and save slider', async () => {
  await withPage(async evaluate => {
    await evaluate(`(async()=>{document.body.innerHTML='';
      window.$=s=>document.querySelector(s);window.dragAnywhere=()=>{};window.fitMenu=()=>{};
      window.esc=s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
      window.toast=s=>{throw Error(s)};window.calls=[];
      window.rows=[{id:'w',name:'i9-NUC',online:true,os:'windows',background_testing:true,budget_percent:70,
        resources:{cpu_percent:23,memory_percent:45,gpus:[{name:'RTX test',utilization_percent:34}]},
        admission:{allowed:true,reason:null}}];
      window.gbox={api:async (url,body)=>{calls.push({url,body});if(body){if('available'in body)rows[0].background_testing=body.available;
        if('budget_percent'in body)rows[0].budget_percent=body.budget_percent;}return {ok:true,data:{workers:rows}}}};
      ${source};await testPcMenu(10,10);})()`);
    const before = await evaluate(`document.querySelector('#testpcmenu').textContent`);
    assert.match(before,/CPU 23%/);assert.match(before,/RTX test 34%/);assert.match(before,/70%/);
    await evaluate(`let slider=document.querySelector('[data-budget]');slider.value='55';slider.dispatchEvent(new Event('change',{bubbles:true}));`);
    await new Promise(r=>setTimeout(r,30));
    assert.equal(await evaluate(`calls.at(-1).body.budget_percent`),55);
    await evaluate(`document.querySelector('[data-w]').click()`);
    await new Promise(r=>setTimeout(r,30));
    assert.equal(await evaluate(`calls.at(-1).body.available`),false);
    assert.match(await evaluate(`document.querySelector('#testpcmenu').textContent`),/Gaming/);
  });
});

// operator 2026-10-26: "the dropdown for bot commands doesnt work in pip mode" - the compact-mode rule hid the menu
test('compact mode leaves the bot command dropdown and its sub-panel visible', () => {
  const rule = html.split('\n').find(l => l.includes('body.gbox-compact > :not(#gpu-game)'));
  assert.ok(rule && rule.includes(':not(.coach-menu)'), 'the compact hide-everything rule must exempt .coach-menu');
  assert.ok(rule && rule.includes(':not(.coach-sub)'), 'the compact hide-everything rule must exempt .coach-sub (#5300)');
});
