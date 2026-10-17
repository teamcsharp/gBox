'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../clients/web/index.html'),'utf8');

test('generic image slides retain their game and original source without leaking the previous game association',()=>{
  const title={textContent:''},context={LB:{list:[
    {src:'/small.jpg',original_url:'/api/artifacts/original',game_id:'game-one',name:'Screenshot'},
    {src:'/unassociated.jpg',name:'Another image'}],img:{dataset:{},complete:false},el:{querySelectorAll:()=>[]}},
    $:()=>title,lbFit:()=>{}};
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('function lbShow('),source.indexOf('function lbOpen(')),context);
  context.lbShow(0);
  assert.equal(context.LB.img.dataset.assetGame,'game-one');
  assert.equal(context.LB.img.dataset.assetOriginalUrl,'/api/artifacts/original');
  context.lbShow(1);
  assert.equal(context.LB.img.dataset.assetGame,undefined);
  assert.equal(context.LB.img.dataset.assetOriginalUrl,'/unassociated.jpg');
});

test('setting a gallery cover sends only its source path and refreshes the correct game',async()=>{
  const calls=[],changed=[],context={URL,location:{href:'https://gbox.example/',origin:'https://gbox.example'},
    api:async(path,body)=>calls.push({path,body}),coverArtworkChanged:async gid=>changed.push(gid)};
  vm.createContext(context);
  const start=source.indexOf('async function setImageAsCover('),end=source.indexOf('// move a running game',start);
  vm.runInContext(source.slice(start,end),context);
  await context.setImageAsCover({game_id:'game-one',url:'https://gbox.example/api/media/game-one/snap?token=secret&w=90',image:{must:'not serialize'}});
  assert.equal(JSON.stringify(calls),JSON.stringify([{path:'/api/catalog/game-one/cover',body:{url:'/api/media/game-one/snap',kind:'boxart'}}]));
  assert.deepEqual(changed,['game-one']);
});
