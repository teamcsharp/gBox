// Run with node system/tests/test_pad_map_dialog.cjs (needs Edge/Chrome; scripts/browser_lifecycle.cjs).
// The controller picture's "Map … to…" dialog in a real browser: the N64 picture's parts, picking a control, pressing
// one ("Press a control to bind", buttons and sticks), whole-stick binding, reset, closing; and the picture lighting the
// C buttons from the right stick.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path');
const { withPage } = require('../scripts/browser_lifecycle.cjs');
const glyph = fs.readFileSync(path.join(__dirname, '../clients/web/padglyph.js'), 'utf8');
const padmap = fs.readFileSync(path.join(__dirname, '../clients/web/viz/pad-map.js'), 'utf8');

async function setup(evaluate, send) {
  await send('Emulation.setDeviceMetricsOverride', { width: 1000, height: 800, deviceScaleFactor: 1, mobile: false });
  await evaluate(`document.body.style='margin:12px;background:#16171c;color:#eee';document.body.innerHTML='<div id="pg" style="width:260px"></div><div id="snes" style="width:260px"></div>';`);
  await evaluate(glyph); await evaluate(padmap);
  await evaluate(`var fake={buttons:Array.from({length:17},()=>({pressed:false,value:0})),axes:[0,0,0,0]},saves=[],caps=[];
    var press=(i,on)=>{fake.buttons[i]={pressed:on,value:on?1:0}};
    PadGlyph.mount(document.querySelector('#pg'),'n64',{});
    var part=sel=>{const g=document.querySelector(sel);return {keys:g.dataset.k.split(' '),label:g.dataset.btn,stick:g.classList.contains('pg-stk')}};
    var open=(sel,x,y,platform)=>GBoxPadMap.dialog({x:x||300,y:y||40,platform:platform||'n64',part:part(sel),map:window.current||{},
      save:m=>{saves.push(m);window.current=m;return Promise.resolve(m)},read:()=>({gp:fake,map:null}),capturing:v=>caps.push(v),
      note:'Streamed game: a change works at once.'});`);
}
const settle = evaluate => evaluate('new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(()=>setTimeout(r,20))))');
const text = evaluate => evaluate(`document.querySelector('#padmapdlg')?.innerText||''`);

// right-clicked N64 C-up maps to a picked control, a pressed control, and resets
async function pickPressReset(evaluate, send) {
    await setup(evaluate, send);
    await evaluate(`open('#pg [data-btn="cup"]')`); await settle(evaluate);
    assert.equal(await evaluate(`document.querySelector('#padmapdlg').getAttribute('role')`), 'dialog', 'cut out of a docked game window by the desktop shell');
    assert.match(await text(evaluate), /Map N64 C-up to…/);
    assert.match(await text(evaluate), /Now: Right stick up/, 'the default: C-up is the right stick');
    assert.equal(await evaluate(`document.querySelector('[data-src="rup"]').getAttribute('aria-pressed')`), 'true');
    assert.equal(await evaluate(`document.querySelectorAll('#padmapdlg [data-src]').length`), 24, 'every face button, bumper, trigger, d-pad and stick direction');
    // pick RB from the list: RB drives C-up too (the right stick keeps it), R is left without a control and says so
    await evaluate(`document.querySelector('[data-src="r"]').click()`); await settle(evaluate);
    assert.deepEqual(await evaluate('saves.at(-1)'), { r: 'rup' });
    assert.match(await text(evaluate), /Now: RB, Right stick up/);
    assert.match(await text(evaluate), /RB → C-up \(Right stick up too\) · saved/);
    assert.match(await text(evaluate), /No control: R\. Right-click it on the picture/);
    assert.match(await evaluate(`document.querySelector('[data-src="r"]').innerText`), /C-up$/, 'the list says what each control does now');
    // Reset C-up
    await evaluate(`document.querySelector('[data-reset]').click()`); await settle(evaluate);
    assert.deepEqual(await evaluate('saves.at(-1)'), {});
    assert.doesNotMatch(await text(evaluate), /No control/);
    // Press a control: a control held when listening starts is ignored until let go, then RB binds
    await evaluate(`press(5,true);document.querySelector('[data-cap]').click()`); await settle(evaluate);
    assert.deepEqual(await evaluate('caps'), [true], 'forwarding to the game pauses while listening');
    assert.equal(await evaluate('saves.length'), 2, 'RB held from before does not bind');
    await evaluate('press(5,false)'); await settle(evaluate);
    await evaluate('press(5,true)'); await settle(evaluate);
    assert.deepEqual(await evaluate('saves.at(-1)'), { r: 'rup' }, 'pressed RB is bound');
    assert.deepEqual(await evaluate('caps'), [true, false]);
    await evaluate('press(5,false)');
    // a stick direction binds too: left stick up drives C-up, RB (a button) takes its Stick up
    await evaluate(`document.querySelector('[data-cap]').click()`); await settle(evaluate);
    await evaluate('fake.axes[1]=-0.95'); await settle(evaluate);
    assert.deepEqual(await evaluate('saves.at(-1)'), { r: 'lup', lup: 'rup' });
    assert.doesNotMatch(await text(evaluate), /RetroArch window/, 'a streamed game has no half-axis limit');
    await evaluate('fake.axes[1]=0');
    // Escape closes, and with it any listening
    await evaluate(`document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}))`);
    assert.equal(await evaluate(`!!document.querySelector('#padmapdlg')`), false);
}

// the N64 stick binds as a whole stick; the dialog stays on screen; other consoles map buttons only
async function wholeStick(evaluate, send) {
    await setup(evaluate, send);
    await evaluate(`open('#pg [data-btn="lstick"]', 990, 790)`); await settle(evaluate);
    assert.match(await text(evaluate), /Map N64 Stick to…/);
    assert.match(await text(evaluate), /Now: Left stick/);
    const r = await evaluate(`(()=>{const b=document.querySelector('#padmapdlg').getBoundingClientRect();return {l:b.left,t:b.top,r:b.right,b:b.bottom}})()`);
    assert.ok(r.l >= 0 && r.t >= 0 && r.r <= 1000 && r.b <= 800, JSON.stringify(r));
    await evaluate(`document.querySelector('[data-grp="rstick"]').click()`); await settle(evaluate);
    assert.deepEqual(await evaluate('saves.at(-1)'), { rup: 'lup', rdown: 'ldown', rleft: 'lleft', rright: 'lright', lup: 'rup', ldown: 'rdown', lleft: 'rleft', lright: 'rright' });
    assert.match(await text(evaluate), /Now: Right stick/);
    // pressing a button while binding a whole stick asks for a stick instead
    await evaluate(`document.querySelector('[data-cap]').click()`); await settle(evaluate);
    await evaluate('press(0,true)'); await settle(evaluate); await settle(evaluate);
    assert.match(await text(evaluate), /A is a button: move a stick or press the D-pad/);
    await evaluate('press(0,false)'); await settle(evaluate);
    await evaluate('fake.axes[0]=0.9'); await settle(evaluate);
    assert.deepEqual(await evaluate('saves.at(-1)'), {}, 'moving the left stick puts the N64 stick back on it');
    await evaluate('fake.axes[0]=0');
    // a click outside closes it
    await evaluate(`document.body.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true}))`);
    assert.equal(await evaluate(`!!document.querySelector('#padmapdlg')`), false);
    // SNES: buttons only, named by the picture
    await evaluate(`window.current={};PadGlyph.mount(document.querySelector('#snes'),'snes',{});`);
    await evaluate(`open('#snes [data-k="a"]',10,10,'snes')`); await settle(evaluate);
    assert.match(await text(evaluate), /Map A to…/);
    assert.equal(await evaluate(`document.querySelectorAll('#padmapdlg [data-src]').length`), 16, 'no stick directions for a buttons-only console');
    await evaluate(`document.querySelector('[data-src="b"]').click()`); await settle(evaluate);
    assert.deepEqual(await evaluate('saves.at(-1)'), { b: 'a', a: 'b' });
    assert.match(await evaluate(`document.querySelector('[data-src="a"]').innerText`), /B\s+B$/, 'Xbox B now presses SNES B');
    await evaluate('GBoxPadMap.close()');
    assert.equal(await evaluate(`!!document.querySelector('#padmapdlg')`), false);
}

// the N64 picture lights the C buttons from the right stick, and RetroPad X only with RT (C mode)
async function lighting(evaluate, send) {
    await setup(evaluate, send);
    const lit = () => evaluate(`document.querySelector('#pg [data-btn="cup"]').classList.contains('on')`);
    await evaluate(`PadGlyph.update({held:['rup'],source:'agent'})`); await settle(evaluate);
    assert.equal(await lit(), true, 'right stick up = C-up');
    await evaluate(`PadGlyph.update({held:['x'],source:'agent'})`); await settle(evaluate);
    assert.equal(await lit(), false, 'Xbox Y alone does nothing on N64');
    await evaluate(`PadGlyph.update({held:['x','r2'],source:'agent'})`); await settle(evaluate);
    assert.equal(await lit(), true, 'with RT held (the cores\' C mode) it is C-up');
    await evaluate(`PadGlyph.update(null)`);
}

// one browser for all three: the shared harness's process cleanup is the slow part on a busy PC
test('browser: N64 "Map C-up to…" (pick, press, reset), whole sticks, SNES buttons, and the picture lighting C from the right stick', async () => {
  await withPage(async (evaluate, send) => {
    for (const scenario of [pickPressReset, wholeStick, lighting]) {
      await send('Page.navigate', { url: 'about:blank' }); await settle(evaluate);
      await scenario(evaluate, send);
    }
  });
});
