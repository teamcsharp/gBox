const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { withPage } = require('../scripts/browser_lifecycle.cjs');

test('task close buttons work while running or collapsed and late updates stay dismissed', async () => {
  await withPage(async (evaluate, send) => {
    await evaluate(fs.readFileSync(require.resolve('../clients/web/viz/pick-whip.js'), 'utf8'));
    await evaluate(`window.con=GBoxPickWhip.createConsole(document);con.anchor(40,60);
      window.first=con.open('naming','Naming with local model').update({state:'running'});
      window.second=con.open('finished','Naming with local model').done(true,'Named').collapse();`);
    async function click(selector) {
      const r = await evaluate(`(()=>{const el=document.querySelector(${JSON.stringify(selector)}),r=el.getBoundingClientRect();
        return {x:r.x+r.width/2,y:r.y+r.height/2,w:r.width,h:r.height,hit:document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===el};})()`);
      assert.ok(r.hit, 'the close control is the pointer target');
      assert.ok(r.w >= 24 && r.h >= 24, 'usable button hit area');
      await send('Input.dispatchMouseEvent', { type:'mousePressed', x:r.x, y:r.y, button:'left', clickCount:1 });
      await send('Input.dispatchMouseEvent', { type:'mouseReleased', x:r.x, y:r.y, button:'left', clickCount:1 });
    }
    await click('[data-id="naming"] [data-c="x"]');
    assert.equal(await evaluate(`con.size`), 1);
    await evaluate(`first.update({state:'succeeded'}).done(true,'Late result').log('Still finished').collapse();`);
    assert.equal(await evaluate(`document.querySelector('[data-id="naming"]')===null`), true);
    assert.equal(await evaluate(`!!document.querySelector('[data-id="finished"].min')`), true);
    await click('[data-id="finished"] [data-c="x"]');
    assert.equal(await evaluate(`con.size`), 0);
    // Delegation also handles an icon nested inside the button, without triggering a parent game click.
    await evaluate(`window.bubbled=0;document.body.addEventListener('click',()=>bubbled++);
      con.open('nested','Nested icon').el;document.querySelector('[data-c="x"]').innerHTML='<span>×</span>';
      document.querySelector('[data-c="x"] span').click();`);
    assert.equal(await evaluate(`con.size`), 0);
    assert.equal(await evaluate(`bubbled`), 0);
  });
});
