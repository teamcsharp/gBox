const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const MG=require('../clients/web/viz/mods-gallery.js');
const {withPage,findChrome}=require('./build_report_browser.cjs');
const items=[{key:'g/a',game_id:'g',name:'a',built:1,favorite:true,play_count:4,last_played:10},
  {key:'g/b',game_id:'g',name:'b',built:3,play_count:0,last_played:0},
  {key:'g/c',game_id:'g',name:'c',built:2,play_count:1,last_played:20}];
test('sorts and played filters use build times and player counts',()=>{
  const names=o=>MG.filterMods(items,o).map(m=>m.name);
  assert.deepEqual(names(),['b','c','a']);assert.deepEqual(names({sort:'favorites'}),['a','b','c']);
  assert.deepEqual(names({sort:'plays'}),['a','c','b']);assert.deepEqual(names({sort:'recent'}),['c','a','b']);
  assert.deepEqual(names({sort:'unplayed'}),['b','c','a']);assert.deepEqual(names({played:'unplayed'}),['b']);
  assert.deepEqual(names({played:'played'}),['c','a']);
  assert.match(MG.cardHTML(items[1]),/>0 plays<\/span> <span[^>]*>unplayed/);
  assert.doesNotMatch(MG.cardHTML(items[0]),/>unplayed</);
  assert.doesNotMatch(MG.cardHTML({name:'unknown'}),/>unplayed</);
});
test('browser: filter menu updates order; donor popup carries game/slot, exports, examines and disposes', {skip:!findChrome()&&'no Chromium'},async()=>{
  await withPage(async evaluate=>{
    const read=n=>fs.readFileSync(path.join(__dirname,'../clients/web/viz',n),'utf8');
    await evaluate(read('build-actions.js'));await evaluate(read('build-shot.js'));await evaluate(read('mods-gallery.js'));await evaluate(read('character-popup.js'));
    const result=await evaluate(`(async()=>{
      document.body.innerHTML='<div id="host"></div>';window.opened=[];
      const rows=${JSON.stringify(items)}.map(m=>({...m,title:'Game',writer:'test',changes:[{donor:'mario',slot:'fighter:AYA'}]}));
      const ctl=GBoxModsGallery.mount(document.querySelector('#host'),{api:async p=>p==='/api/mods/built'?{items:rows}:[],openCharacter:o=>opened.push(o)});
      await ctl.ready;const keys=()=>[...document.querySelectorAll('.mg-card')].map(c=>c.dataset.key);
      const initial=keys();const sort=document.querySelector('[data-mg-f=sort]');sort.value='plays';sort.dispatchEvent(new Event('change',{bubbles:true}));const sorted=keys();
      document.querySelector('[data-mg=character]').click();ctl.stop();
      window.exports=[];window.retargets=[];window.disposed=0;
      const popup=await GBoxCharacterPopup.open(opened[0],{api:async()=>({slug:'mario',name:'Mario',model:'mario.glb',source:{game_title:'Super Mario 64'}}),url:u=>u+'?token=test',
        blender:s=>exports.push(s),retarget:o=>retargets.push(o),loadViewer:async()=>({createCharacterViewer:async()=>({gltf:{scene:{traverse:f=>f({isMesh:true,geometry:{attributes:{position:{count:6}}},material:[]})}},dispose:()=>disposed++})})});
      document.querySelector('[data-cp=examine]').click();const info=document.querySelector('.cp-info').textContent;
      document.querySelector('[data-cp=blender]').click();await new Promise(r=>setTimeout(r,0));
      document.querySelector('[data-cp=retarget]').click();
      return {initial,sorted,opened,exports,retargets,info,disposed,closed:!document.querySelector('.cp-modal')};
    })()`);
    assert.deepEqual(result.initial,['g/b','g/c','g/a']);assert.deepEqual(result.sorted,['g/a','g/c','g/b']);
    assert.deepEqual(result.opened,[{slug:'mario',name:'mario',gid:'g',slot:'fighter:AYA'}]);
    assert.deepEqual(result.exports,['mario']);assert.equal(result.retargets[0].slot,'fighter:AYA');
    assert.match(result.info,/vertices: 6/);assert.equal(result.disposed,1);assert.equal(result.closed,true);
  });
});
