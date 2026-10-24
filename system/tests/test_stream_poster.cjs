const {test}=require('node:test');
const assert=require('node:assert/strict');
const {capture}=require('../clients/desktop/stream-poster.cjs');
function fixture(){
  const areas=[],frame={},image={isEmpty:()=>false,getSize:()=>({width:1920,height:1080}),
    resize:()=>({toJPEG:()=>Buffer.from('CURRENT')})};
  const sender={mainFrame:frame,capturePage:async rect=>{areas.push(rect);return image;}};
  return {win:{isDestroyed:()=>false,webContents:sender,getContentSize:()=>[1200,700]},
    event:{sender,senderFrame:frame},areas,image};
}
test('PiP poster reads only its own rendered content, including cross-origin video',async()=>{
  const x=fixture();assert.equal(await capture(x.win,x.event,{x:0,y:0,width:1200,height:700},true),
    'data:image/jpeg;base64,'+Buffer.from('CURRENT').toString('base64'));
  assert.deepEqual(x.areas,[{x:0,y:0,width:1200,height:700}]);
});
test('poster refuses another renderer, a guest frame, inactive PiP, and capture outside its content',async()=>{
  const x=fixture(),rect={x:0,y:0,width:1200,height:700};
  for(const [event,area,on] of [[{...x.event,sender:{}},rect,true],
    [{...x.event,senderFrame:{}},rect,true],[x.event,rect,false],
    [x.event,{...rect,x:-1},true],[x.event,{...rect,width:Infinity},true],
    [x.event,{...rect,height:900},true]])await assert.rejects(capture(x.win,event,area,on));
  assert.equal(x.areas.length,0);
});
