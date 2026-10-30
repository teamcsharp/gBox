'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),http=require('node:http');
const {withPage}=require('../scripts/browser_lifecycle.cjs');
const {sortedWeapons}=require('../clients/web/viz/stream-interventions.js');

test('damage order is numeric, keeps unknowns last, and never changes the advertised catalogue',()=>{
  const rows=[{item:1,weapon:'Low',damage:9},{item:2,weapon:'Unknown',damage:null},
    {item:3,weapon:'High',damage:10000},{item:4,weapon:'Zero',damage:0},{item:5,weapon:'Invalid',damage:Infinity}];
  assert.deepEqual(sortedWeapons(rows).map(r=>r.item),[3,1,4,5,2]);
  assert.deepEqual(rows.map(r=>r.item),[1,2,3,4,5]);
});

test('PiP weapon menu stays visible, labels inventory, sends an immediate single selection and follows title changes',async()=>{
  const desktop=fs.readFileSync(path.join(__dirname,'../clients/desktop/index.html'),'utf8');
  const compactHide=desktop.match(/body\.gbox-compact >[^\n]+?\{[^}]+\}/)[0];
  const html=desktop.match(/controls\.innerHTML = ('<span class="compact-title"[^\n]+?');/)[1];
  const server=http.createServer((req,res)=>{
    if(req.url==='/controls.js'){res.setHeader('Content-Type','application/javascript');res.end(fs.readFileSync(path.join(__dirname,'../clients/web/viz/stream-interventions.js')));return;}
    res.end(`<style>${compactHide}#compact-controls{display:flex;position:fixed;right:0;top:0;height:28px}</style><body class="gbox-compact"><img id="compact-stream" src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw=="><div id="compact-controls"></div><script src="/controls.js"></script></body>`);
  });
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  try{await withPage(async(evaluate,send)=>{
    await send('Page.navigate',{url:`http://127.0.0.1:${server.address().port}`});
    await evaluate(`new Promise(r=>{const wait=()=>window.GBoxStreamInterventions?r():setTimeout(wait,10);wait();})`);
    await evaluate(`document.querySelector('#compact-controls').innerHTML=${html};
      window.current='re5';window.posts=[];window.reads=[];window.delayed=true;window.release=null;
      window.stream=document.querySelector('#compact-stream');window.source=stream.src;window.changes=0;
      new MutationObserver(r=>changes+=r.length).observe(stream,{attributes:true});
      window.alert=window.confirm=window.prompt=()=>{throw Error('Selection must not open a confirmation')};
      window.state={available:true,capabilities:['equip_primary'],options:{weapons:[
        {item:2,weapon:'M92F',damage:1500,in_inventory:true},
        {item:25,weapon:'Hydra',damage:5500,in_inventory:true,equipped:true},
        {item:27,weapon:'S&W M500',damage:50000,in_inventory:false},
        {item:54,weapon:'rotten egg',damage:null,in_inventory:false}
      ]}};
      window.api=async(p,b)=>{if(b){posts.push({p,b});return {request:{id:b.request_id,state:'queued'}};}
        reads.push(p);if(delayed)await new Promise(r=>release=r);return state;};
      window.client=GBoxStreamInterventions.create({api,notify:(text,row)=>picker.receipt(text,row)});
      window.gun=document.querySelector('[data-primary-weapon]');
      window.picker=GBoxStreamInterventions.bindWeapon(gun,{api,equipPrimary:client.equipPrimary,sid:()=>current});gun.click();`);
    assert.equal(await evaluate(`getComputedStyle(document.querySelector('.merc-weapon-menu')).display`),'flex','actual compact CSS permits the menu');
    assert.match(await evaluate(`document.querySelector('.merc-weapon-menu').textContent`),/Loading weapons/);
    assert.equal(await evaluate(`gun.nextElementSibling.hasAttribute('data-flash')`),true);
    await evaluate(`delayed=false;release();new Promise(r=>setTimeout(r,10))`);
    assert.deepEqual(await evaluate(`[...document.querySelectorAll('[data-weapon-item]')].map(e=>Number(e.dataset.weaponItem))`),[27,25,2,54]);
    assert.match(await evaluate(`document.querySelector('[data-weapon-item="27"]').textContent`),/Not in inventory/);
    assert.match(await evaluate(`document.querySelector('[data-weapon-item="2"]').textContent`),/In inventory/);
    assert.equal(await evaluate(`document.querySelector('[data-weapon-item="25"]').getAttribute('aria-pressed')`),'true');
    await evaluate(`window.option=document.querySelector('[data-weapon-item="27"]');option.click();option.click();new Promise(r=>setTimeout(r,10))`);
    assert.equal(await evaluate('posts.length'),1,'even a detached button cannot submit twice');
    assert.deepEqual(await evaluate('posts[0].b.args'),{item:27});
    assert.equal(await evaluate(`document.querySelector('.merc-weapon-menu')`),null);
    await evaluate(`picker.receipt('S&W M500 equipped. Locked for three minutes.',{op:'equip_primary',sid:'re5',state:'confirmed'});gun.click();new Promise(r=>setTimeout(r,10))`);
    assert.match(await evaluate('gun.title'),/three minutes/);
    await evaluate(`window.old=document.querySelector('[data-weapon-item="2"]');current='re6';old.click();`);
    assert.equal(await evaluate('posts.length'),1,'an old title menu never equips in a new title');
    assert.equal(await evaluate(`document.querySelector('.merc-weapon-menu')`),null);
    await evaluate(`delayed=true;gun.click();gun.click();release();new Promise(r=>setTimeout(r,10))`);
    assert.equal(await evaluate(`document.querySelector('.merc-weapon-menu')`),null,'closing while loading never resurrects it');
    await evaluate(`delayed=false;state={available:false,capabilities:[],reason:'No active player'};gun.click();new Promise(r=>setTimeout(r,10))`);
    assert.match(await evaluate(`document.querySelector('.merc-weapon-menu').textContent`),/No active player/);
    await evaluate(`document.activeElement.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));`);
    assert.equal(await evaluate(`document.querySelector('.merc-weapon-menu')`),null);
    assert.equal(await evaluate('stream===document.querySelector("#compact-stream") && source===stream.src && changes===0'),true);
    await evaluate('picker.dispose();client.dispose()');
  },{timeoutMs:30000});}finally{server.closeAllConnections();await new Promise(r=>server.close(r));}
});
