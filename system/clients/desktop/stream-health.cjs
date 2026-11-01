'use strict';
// The image may belong to the remote authority while the library is local.
// Never borrow the selected library's credential or trust a token in its URL.
async function read(src, {origins, token, fetch, timeoutMs=4000}) {
  const url = new URL(src);
  if (!/^https?:$/.test(url.protocol) || url.username || url.password || !origins.includes(url.origin))
    throw Error('The stream belongs to an unpaired gBox authority.');
  const match = /^\/api\/sessions\/([^/]+)\/mjpeg$/.exec(url.pathname);
  if (!match || !/^[a-zA-Z0-9_-]+$/.test(match[1])) throw Error('Unknown stream session.');
  const credential = await token(url.origin);
  if (!credential) throw Error('Waiting for the stream authority credential.');
  const result = await fetch(url.origin + '/api/sessions/' + match[1] + '/stream/health', {
    headers: {authorization: `Bearer ${credential}`}, signal: AbortSignal.timeout(timeoutMs), redirect: 'error'
  });
  if (!result.ok) throw Error(`Stream health returned ${result.status}.`);
  const data = await result.json();
  if (data.session_id !== match[1]) throw Error('Stream health returned a different session.');
  return data;
}
module.exports = {read};
