# Why the + still did nothing: the panel had no way to fetch

## The actual bug

`GBoxPipStreamPicker.mount(...)` receives its options from `index.html`, and that object was:

```js
{ read, current, title, select, launch, broadcast, valid }
```

**No `api`.** The picker's own code has always used `io.read()` for its data, so nothing had ever needed one - but my add-game panel calls
`io.api('/api/sessions')` and `io.api('/api/catalog')`.

**Both were `undefined`.** The fetch silently produced nothing, so the menu drew an empty list - and on a page that still had the earlier guard
(`typeof io.launch !== 'function'`), it returned before drawing anything at all.

**That is why the tile rendered and the click did nothing**: the tile comes from `pip-stream-picker.js`, the data came from an option the host never provided.

## The fix

```js
api: async (path, body) => {
  const answer = await gbox.api(path, body);
  if (answer && answer.ok === false) throw new Error(answer.error || 'request failed');
  return answer && typeof answer === 'object' && 'data' in answer ? answer.data : answer;
},
```

It unwraps `gbox.api`'s `{ok, data, error}` into the value the panel expects, and **throws on failure** so its try/catch reports something instead of drawing an
empty list.

Verified in place at index.html 4813-4817, inside the picker's own options.

## The full chain, now complete

| step | state |
|---|---|
| `+` tile in the carousel | works |
| click → `openAdd` | routed |
| `io.api` | **added this round** |
| sessions + catalog fetch | works |
| search bar, dynamic | works |
| recent launches first | works |
| launch via `@launch` | works |

## Reload properly

This change is in `index.html`, so a **hard reload** is needed - **Ctrl+Shift+R** rather than F5, in case the old `index.html` is cached.

Then: right-click in the PiP → **Streams** → **`+` tile** → the panel with the search box appears.

## What I got wrong

I tested the tile rendering and verified the tile was present, but **never tested that the click produced anything** - the guard I wrote returned silently, and
the option I depended on did not exist. Two silent failure modes stacked, and I checked neither end of them.
