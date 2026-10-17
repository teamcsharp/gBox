const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const picker=require('../clients/web/viz/cover-picker.js');
const {withPage}=require('../scripts/browser_lifecycle.cjs');
const source=fs.readFileSync(path.join(__dirname,'../clients/web/viz/cover-picker.js'),'utf8');
const wait=`window.waitFor=async f=>{for(let n=0;n<300;n++){if(f())return;await new Promise(r=>setTimeout(r,10));}throw Error('cover picker UI timeout')};`;
const fixture=`window.calls=[];window.previews=[];window.saved=[];window.gif='data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7';
window.makeItems=(prefix,count=9)=>Array.from({length:count},(_,i)=>({url:'https://images.example/'+prefix+i+'.jpg',thumbnail:'https://thumbs.example/'+prefix+i+'.jpg',title:prefix+' cover '+i,source_url:'https://site.example/'+prefix+i,source:'Image archive'}));
window.media=u=>{previews.push(u);return gif;};`;

test('search result normalization rejects unsafe source URLs and caps pages at nine',()=>{
  assert.equal(picker.PAGE_SIZE,9);
  assert.equal(picker.remoteURL('javascript:alert(1)'), '');
  assert.equal(picker.remoteURL('https://name:secret@example.com/image.jpg'),'');
  const items=picker.results([{url:'javascript:alert(1)'},...Array.from({length:14},(_,n)=>({url:`https://img.example/${n}.jpg`,source_url:'javascript:bad()',title:'<img>'}))]);
  assert.equal(items.length,9);
  assert.equal(items[0].source_url,'https://img.example/0.jpg');
  assert.equal(items[0].title,'<img>');
  assert.equal(picker.defaultQuery('Dead or Alive 3 (USA) (Rev A)'),'Dead or Alive 3 cover');
  assert.equal(picker.defaultQuery('A Game (Special Edition) (Japan)'),'A Game (Special Edition) cover');
});

test('nine-image pages use authenticated proxy previews and explicitly save the chosen original',async()=>{
  await withPage(async evaluate=>{
    await evaluate(source);
    await evaluate(wait+fixture+`window.api=async(p,b)=>{calls.push({p,b});if(b)return {ok:true,kind:'boxart'};
      const u=new URL(p,'https://gbox.example');const page=+u.searchParams.get('page');return {items:makeItems('page'+page+'-'),page,has_next:page===1};};
      document.body.innerHTML='<button id="origin">Change cover</button>';document.querySelector('#origin').focus();
      window.panel=GBoxCoverPicker.open({gid:'disc/with space',title:'Dead or Alive 3',api,media,onSaved:(result,item)=>saved.push({result,item})});
      waitFor(()=>document.querySelectorAll('[data-cover-index]').length===9);`);
    assert.match(await evaluate(`calls[0].p`),/cover\/search\?q=Dead%20or%20Alive%203%20cover&source=web&page=1&page_size=9$/);
    assert.match(await evaluate(`previews[0]`),/^\/api\/catalog\/disc%2Fwith%20space\/cover\/preview\?url=https%3A%2F%2Fthumbs.example%2Fpage1-0.jpg$/);
    assert.equal(await evaluate(`document.querySelector('[data-cover-prev]').disabled`),true);
    assert.equal(await evaluate(`document.querySelector('[data-cover-save]').disabled`),true);
    await evaluate(`document.querySelector('[data-cover-next]').click();waitFor(()=>document.querySelector('[data-cover-page]').textContent==='Page 2'&&document.querySelectorAll('[data-cover-index]').length===9);`);
    assert.equal(await evaluate(`document.querySelector('[data-cover-next]').disabled`),true);
    assert.equal(await evaluate(`document.querySelector('[data-cover-prev]').disabled`),false);
    await evaluate(`document.querySelector('[data-cover-index="4"]').click();`);
    assert.equal(await evaluate(`calls.filter(c=>c.b).length`),0,'selection alone never writes cover art');
    assert.equal(await evaluate(`document.querySelector('[data-cover-index="4"]').getAttribute('aria-pressed')`),'true');
    await evaluate(`document.querySelector('[data-cover-save]').click();waitFor(()=>saved.length===1&&!document.querySelector('dialog'));`);
    assert.deepEqual(await evaluate(`calls.find(c=>c.b)`),{p:'/api/catalog/disc%2Fwith%20space/cover',b:{url:'https://images.example/page2-4.jpg',kind:'boxart'}});
    assert.equal(await evaluate(`document.activeElement.id`),'origin');
  });
});

test('custom search and source reset pagination; stale responses and unsafe labels cannot replace current results',async()=>{
  await withPage(async evaluate=>{
    await evaluate(source);
    await evaluate(wait+fixture+`window.pending=null;window.api=async(p,b)=>{calls.push({p,b});const u=new URL(p,'https://gbox.example');
      const query=u.searchParams.get('q');if(query==='delayed')return new Promise(resolve=>pending=resolve);
      if(query==='empty')return {items:[],page:1,has_next:false};
      return {items:makeItems(u.searchParams.get('source')+'-'+query),page:+u.searchParams.get('page'),has_next:true};};
      window.panel=GBoxCoverPicker.open({gid:'game',title:'A game',api,media});waitFor(()=>document.querySelectorAll('[data-cover-index]').length===9);`);
    await evaluate(`document.querySelector('[data-cover-next]').click();waitFor(()=>document.querySelector('[data-cover-page]').textContent==='Page 2'&&document.querySelector('[data-cover-results]').getAttribute('aria-busy')==='false');
      document.querySelector('[name=query]').value='<b>collector edition</b>';document.querySelector('[name=source]').value='vimm';document.querySelector('[name=source]').dispatchEvent(new Event('change'));
      waitFor(()=>document.querySelector('[data-cover-page]').textContent==='Page 1'&&document.querySelector('[data-cover-results]').getAttribute('aria-busy')==='false');`);
    assert.match(await evaluate(`calls.at(-1).p`),/q=%3Cb%3Ecollector%20edition%3C%2Fb%3E&source=vimm&page=1&page_size=9$/);
    assert.equal(await evaluate(`document.querySelectorAll('.gbox-cover-picker-results strong b').length`),0);
    await evaluate(`panel.search(1,'delayed','web');panel.search(1,'current','vimm');waitFor(()=>document.querySelector('.gbox-cover-picker-results strong')?.textContent.includes('current'));`);
    await evaluate(`pending({items:makeItems('stale'),page:3,has_next:false});Promise.resolve();`);
    assert.match(await evaluate(`document.querySelector('.gbox-cover-picker-results strong').textContent`),/current/);
    await evaluate(`panel.search(1,'empty','web');waitFor(()=>document.querySelector('[data-cover-status]').textContent.includes('No images found'));`);
    assert.equal(await evaluate(`document.querySelector('[data-cover-next]').disabled`),true);
    await evaluate(`document.querySelector('dialog').dispatchEvent(new Event('cancel',{cancelable:true}));waitFor(()=>!document.querySelector('dialog'));`);
  });
});

test('search and save errors remain actionable, while closing never revives a pending response',async()=>{
  await withPage(async evaluate=>{
    await evaluate(source);
    await evaluate(wait+fixture+`window.failSearch=true;window.pending=null;window.api=async(p,b)=>{calls.push({p,b});if(b)throw Error('Image download failed');
      if(failSearch)throw Error('Search unavailable');return {items:makeItems('ready'),page:1,has_next:false};};
      window.panel=GBoxCoverPicker.open({gid:'game',title:'A game',api,media});waitFor(()=>document.querySelector('[data-cover-status]').textContent.includes('Search unavailable'));`);
    await evaluate(`failSearch=false;document.querySelector('form').requestSubmit();waitFor(()=>document.querySelectorAll('[data-cover-index]').length===9);`);
    await evaluate(`document.querySelector('[data-cover-index="0"]').click();document.querySelector('[data-cover-save]').click();waitFor(()=>document.querySelector('[data-cover-status]').textContent.includes('Image download failed'));`);
    assert.equal(await evaluate(`document.querySelector('[data-cover-save]').disabled`),false);
    await evaluate(`panel.close();window.lateApi=()=>new Promise(resolve=>pending=resolve);panel=GBoxCoverPicker.open({gid:'other',title:'Other',api:lateApi,media});panel.close();pending({items:makeItems('late'),page:1,has_next:false});Promise.resolve();`);
    assert.equal(await evaluate(`document.querySelectorAll('dialog').length`),0);
  });
});

test('empty search warnings retain a direct image URL fallback with validation and retry',async()=>{
  await withPage(async evaluate=>{
    await evaluate(source);
    await evaluate(wait+fixture+`window.failSave=true;window.api=async(p,b)=>{calls.push({p,b});if(b){if(failSave)throw Error('That image could not be downloaded');return {ok:true};}
      return {items:[],page:1,has_next:false,warnings:['SearX image search is temporarily unavailable.']};};
      window.panel=GBoxCoverPicker.open({gid:'game',title:'Dead or Alive 3 (USA) (Rev 1)',api,media,onSaved:(result,item)=>saved.push({result,item})});
      waitFor(()=>document.querySelector('[data-cover-status]').textContent.includes('SearX'));`);
    assert.equal(await evaluate(`document.querySelector('[name=query]').value`),'Dead or Alive 3 cover');
    assert.match(await evaluate(`document.querySelector('[data-cover-status]').textContent`),/temporarily unavailable/);
    await evaluate(`document.querySelector('details').open=true;document.querySelector('[name=image_url]').value='ftp://example.com/cover.jpg';document.querySelector('[data-cover-url-form]').requestSubmit();`);
    assert.match(await evaluate(`document.querySelector('[data-cover-status]').textContent`),/HTTP or HTTPS/);
    assert.equal(await evaluate(`calls.filter(call=>call.b).length`),0);
    await evaluate(`document.querySelector('[name=image_url]').value='https://images.example/direct.jpg';document.querySelector('[data-cover-url-form]').requestSubmit();waitFor(()=>document.querySelector('[data-cover-status]').textContent.includes('could not be downloaded'));`);
    assert.equal(await evaluate(`document.querySelector('[data-cover-url-save]').disabled`),false);
    await evaluate(`failSave=false;document.querySelector('[data-cover-url-form]').requestSubmit();waitFor(()=>saved.length===1&&!document.querySelector('dialog'));`);
    assert.deepEqual(await evaluate(`calls.filter(call=>call.b).at(-1).b`),{url:'https://images.example/direct.jpg',kind:'boxart'});
    assert.equal(await evaluate(`saved[0].item.source`),'Direct image URL');
  });
});

test('thumbnail failures try the proxied original once, then show an unavailable label',async()=>{
  await withPage(async evaluate=>{
    await evaluate(source);
    await evaluate(wait+fixture+`window.api=async()=>({items:makeItems('preview',1),page:1,has_next:false});
      window.panel=GBoxCoverPicker.open({gid:'game',title:'A game',api,media});waitFor(()=>document.querySelectorAll('[data-cover-index]').length===1);`);
    await evaluate(`document.querySelector('.gbox-cover-picker-results img').dispatchEvent(new Event('error'));`);
    assert.match(await evaluate(`previews.at(-1)`),/preview\?url=https%3A%2F%2Fimages.example%2Fpreview0.jpg$/);
    await evaluate(`document.querySelector('.gbox-cover-picker-results img').dispatchEvent(new Event('error'));`);
    assert.equal(await evaluate(`document.querySelector('[data-cover-preview-error]').hidden`),false);
    assert.equal(await evaluate(`document.querySelector('.gbox-cover-picker-results img').hidden`),true);
    await evaluate(`panel.close();`);
  });
});

test('small windows scroll the nine results while keeping search and paging actions visible',async()=>{
  await withPage(async(evaluate,send)=>{
    await send('Emulation.setDeviceMetricsOverride',{width:800,height:600,deviceScaleFactor:1,mobile:false});
    await evaluate(source);
    await evaluate(wait+fixture+`window.api=async()=>({items:makeItems('small'),page:1,has_next:true});
      window.panel=GBoxCoverPicker.open({gid:'game',title:'A game',api,media});waitFor(()=>document.querySelectorAll('[data-cover-index]').length===9);`);
    assert.equal(await evaluate(`(()=>{const dialog=document.querySelector('dialog').getBoundingClientRect(),footer=document.querySelector('.gbox-cover-picker-footer').getBoundingClientRect();return footer.bottom<=dialog.bottom&&footer.top>=dialog.top;})()`),true);
    await evaluate(`document.querySelector('[data-cover-index="8"]').scrollIntoView({block:'nearest'});`);
    assert.equal(await evaluate(`(()=>{const grid=document.querySelector('[data-cover-results]').getBoundingClientRect(),last=document.querySelector('[data-cover-index="8"]').getBoundingClientRect(),footer=document.querySelector('.gbox-cover-picker-footer').getBoundingClientRect();return last.top>=grid.top&&last.bottom<=grid.bottom&&footer.bottom<=innerHeight;})()`),true);
    await evaluate('panel.close()');
  });
});
