import asyncio
import concurrent.futures
from contextlib import contextmanager
import hashlib
import hmac
import importlib.util
import json
from pathlib import Path
import re
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest

import httpx
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import media_gateway as M

PLAYLIST = b"#EXTM3U\n#EXTINF:1,\nseg_00001.ts\n"


class Content(httpx.AsyncByteStream):
    def __init__(self, *parts):
        self.parts = parts

    async def __aiter__(self):
        for part in self.parts:
            yield part


def token(key, *, epoch=1, tag="viewer", expires=2000, scope="listen"):
    signed = hmac.new(key.encode(), f"{scope}:{expires}:{tag}:{epoch}".encode(), hashlib.sha256).hexdigest()[:24]
    return f"{expires}.{tag}.{signed}" + (".full" if scope == "full" else "")


class Hub:
    tile_view = staticmethod(lambda row, *_: dict(row))

    def __init__(self):
        self.allowed = {"program"}
        self.gw = SimpleNamespace(base="http://gbox:8765", url=lambda p: "http://gbox:8765"+p,
                                  headers=lambda: {"Authorization": "Bearer gbox-secret"})

    def pictures(self):
        return {"program": "/api/broadcast/program.mjpg", "private": "/api/broadcast/session/private.mjpg"}

    def allowed_keys(self):
        return self.allowed

    def seen(self, _):
        pass


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)
        self.shares = self.path / "shares.json"
        self.shares.write_text('{"epoch":1,"revoked":[]}')
        self.cfg = M.Config(self.path, "pine-secret", lock_reads=True)
        self.live = token(self.cfg.api_key, expires=int(time.time())+600)
        self.hub = Hub()
        self.stream = SimpleNamespace(HUB=self.hub, Hub=Hub, PREVIEW_KEY="gbox-preview",
                                      KEY_RE=re.compile(r"^[A-Za-z0-9_-]{1,96}$"))

    def tearDown(self):
        self.tmp.cleanup()

    def apps(self, *, fetch=None, transport=None, cfg=None):
        return M.applications(cfg or self.cfg, stream=self.stream,
                              relay=M.gbox_hls.BoundedRelay(fetch or
                                  (lambda url, *_: PLAYLIST if url.endswith("m3u8") else b"segment")),
                              proxy_transport=transport)

    def test_public_hls_bypasses_backend_and_never_exposes_gbox_credential(self):
        calls = []
        def backend(request):
            calls.append(request)
            raise AssertionError("HLS must never hit the station backend")
        public, _ = self.apps(transport=httpx.MockTransport(backend))
        with TestClient(public) as client:
            r = client.get("/api/gbox/hls", params={"k":"program", "t":self.live},
                           headers={"authorization":"Bearer pine-secret", "x-pinebox-public":"0"})
            self.assertEqual(r.status_code, 200)
            self.assertIn("name=seg_00001.ts", r.text)
            self.assertNotIn("secret", r.text)
            self.assertEqual(client.get("/api/gbox/hls?k=program",
                headers={"authorization":"Bearer pine-secret", "x-pinebox-public":"0"}).status_code, 403)
            self.assertEqual(client.get("/api/gbox/hls", params={"k":"private", "t":self.live}).status_code, 404)
        self.assertEqual(calls, [])

    def test_revocation_epoch_and_missing_or_corrupt_files_cut_off_cached_media(self):
        public, _ = self.apps()
        with TestClient(public) as client:
            url = "/api/gbox/hls?k=program&name=seg_00001.ts&t="+self.live
            self.assertEqual(client.get(url).status_code, 200)
            for state in ('{"epoch":2}', '{"epoch":1,"revoked":["viewer"]}', '[]', '{'):
                self.shares.write_text(state)
                self.assertEqual(client.get(url).status_code, 403)
            self.shares.unlink()
            self.assertEqual(client.get(url).status_code, 403)

    def test_revocation_or_stage_change_during_download_refuses_the_response(self):
        def revoke(*_):
            self.shares.write_text('{"revoked":["viewer"]}')
            return PLAYLIST
        public, _ = self.apps(fetch=revoke)
        with TestClient(public) as client:
            self.assertEqual(client.get("/api/gbox/hls", params={"k":"program","t":self.live}).status_code, 403)
        self.shares.write_text('{"epoch":1}')
        def remove_stage(*_):
            self.hub.allowed.clear()
            return PLAYLIST
        public, _ = self.apps(fetch=remove_stage)
        with TestClient(public) as client:
            self.assertEqual(client.get("/api/gbox/hls", params={"k":"program","t":self.live}).status_code, 404)

    def test_private_policy_full_bearer_preview_and_no_studio_routes(self):
        public, private = self.apps()
        with TestClient(public), TestClient(private) as client:
            self.assertEqual(client.get("/api/gbox/hls?k=program").status_code, 401)
            self.assertEqual(client.get("/api/gbox/hls?k=program",headers={"Authorization":"Bearer pine-secret"}).status_code,200)
            full=token("pine-secret",scope="full",expires=int(time.time())+600)
            self.assertEqual(client.get("/api/gbox/hls?k=program",headers={"Authorization":"Bearer "+full}).status_code,200)
            preview=M.Authorization(self.cfg).media_sign("gbox-preview")
            self.assertEqual(client.get("/api/gbox/hls?k=private&s="+preview).status_code,200)
            self.assertEqual(client.get("/api/gbox/config").status_code,404)
            self.assertEqual(client.get("/").status_code,404)

    def test_private_open_read_policy_matches_existing_station(self):
        cfg=M.Config(self.path,"pine-secret",lock_reads=False)
        public, private=self.apps(cfg=cfg)
        with TestClient(public), TestClient(private) as client:
            self.assertEqual(client.get('/api/gbox/hls?k=program').status_code,200)

    def test_private_cors_exact_same_hostname_port8096_and_forbidden_preflight(self):
        public, private=self.apps()
        with TestClient(public), TestClient(private,base_url="http://spark.local:18098") as client:
            headers={"Origin":"http://spark.local:8096","Access-Control-Request-Method":"GET",
                     "Access-Control-Request-Headers":"authorization,range"}
            r=client.options('/api/gbox/hls',headers=headers)
            self.assertEqual(r.status_code,204)
            self.assertEqual(r.headers['access-control-allow-origin'],headers['Origin'])
            for origin in ("http://elsewhere:8096","http://spark.local:8097","https://spark.local:8096","null"):
                self.assertEqual(client.options('/api/gbox/hls',headers={**headers,"Origin":origin}).status_code,403)
            self.assertEqual(client.options('/api/gbox/hls',headers={**headers,"Access-Control-Request-Method":"POST"}).status_code,403)
            r=client.get('/api/gbox/hls?k=program',headers={"Origin":headers['Origin'],"Authorization":"Bearer pine-secret"})
            self.assertEqual(r.status_code,200)
            self.assertEqual(r.headers['access-control-allow-origin'],headers['Origin'])

    def test_public_proxy_preserves_method_raw_query_range_status_and_strips_spoofs(self):
        calls=[]
        async def backend(request):
            calls.append((request,await request.aread()))
            return httpx.Response(206,headers={"Content-Range":"bytes 2-4/8","Content-Type":"video/mp2t","Connection":"keep-alive"},stream=Content(b"c",b"de"))
        public, _=self.apps(transport=httpx.MockTransport(backend))
        with TestClient(public) as client:
            r=client.post('/tune/name?x=%2F%26&x=two&t=opaque',content=b"body",headers={
                "Host":"pine.example:8097","Range":"bytes=2-4","Authorization":"Bearer secret",
                "X-Pinebox-Public":"0","X-Forwarded-For":"malicious","Connection":"X-Evil","X-Evil":"discard"})
            self.assertEqual(r.status_code,206)
            self.assertEqual(r.content,b"cde")
            self.assertEqual(r.headers['Content-Range'],'bytes 2-4/8')
            self.assertNotIn('connection',r.headers)
        req,body=calls[0]
        self.assertEqual(req.url.host,'127.0.0.1')
        self.assertEqual(req.url.port,18097)
        self.assertEqual(req.url.query,b'x=%2F%26&x=two&t=opaque')
        self.assertEqual(body,b'body')
        self.assertEqual(req.headers['host'],'pine.example:8097')
        self.assertEqual(req.headers['range'],'bytes=2-4')
        for name in ('authorization','x-pinebox-public','x-evil'):
            self.assertNotIn(name,req.headers)
        self.assertNotEqual(req.headers.get('x-forwarded-for'),'malicious')

    def test_proxy_does_not_follow_redirects_or_switch_destination(self):
        calls=[]
        def backend(request):
            calls.append(request)
            return httpx.Response(302,headers={'location':'http://forbidden.example/private'},stream=Content(b''))
        public,_=self.apps(transport=httpx.MockTransport(backend))
        with TestClient(public,follow_redirects=False) as client:
            r=client.get('/tune/x?url=http://forbidden.example/')
            self.assertEqual(r.status_code,302)
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0].url.host,'127.0.0.1')

    def test_public_backend_failure_is_generic_but_hls_remains_usable(self):
        def backend(request):
            raise httpx.ConnectError('Bearer do-not-leak',request=request)
        public,_=self.apps(transport=httpx.MockTransport(backend))
        with TestClient(public) as client:
            r=client.get('/tune/x')
            self.assertEqual(r.status_code,502)
            self.assertNotIn('do-not-leak',r.text)
            self.assertEqual(client.get('/api/gbox/hls',params={'k':'program','t':self.live}).status_code,200)

    def test_json_state_size_and_changed_file_fail_closed(self):
        f=M.JsonFile(self.shares,64)
        self.assertEqual(f.read()['epoch'],1)
        self.shares.write_text('{"epoch":2}')
        self.assertEqual(f.read()['epoch'],2)
        self.shares.write_text('{"oversize":"'+'x'*100+'"}')
        self.assertIsNone(f.read())
        self.shares.write_text('{}')
        self.assertEqual(f.read(),{})

    def test_token_scope_expiry_scope_and_key_are_not_interchangeable(self):
        auth=M.Authorization(self.cfg,clock=lambda:1000)
        self.assertEqual(auth.token_scope(token('pine-secret')),'listen')
        self.assertEqual(auth.token_scope(token('pine-secret',scope='full')),'full')
        for value in (token('wrong'),token('pine-secret',expires=999),token('pine-secret')+'.full',
                      'https://external.example/', '1.bad.signature'):
            self.assertEqual(auth.token_scope(value),'')

    def test_configuration_refuses_remote_backend_ambiguous_ports_and_missing_data_env(self):
        for kwargs in ({'backend':'http://external:18097'},{'backend':'http://127.0.0.1:8096'},
                       {'public_port':18098},{'gbox_url':'http://user:secret@host:8765'}):
            with self.assertRaises(ValueError):M.Config(self.path,'key',**kwargs)
        self.assertNotIn('pine-secret',repr(self.cfg))

    def test_no_app_import_or_station_lifecycle_is_required(self):
        source=(ROOT/'media_gateway.py').read_text()
        import ast
        tree=ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):self.assertNotIn('app',[n.name for n in node.names])
            if isinstance(node,ast.ImportFrom):self.assertNotEqual(node.module,'app')

    def test_real_stream_wrapper_refuses_missing_corrupt_or_stale_stage_and_feed_state(self):
        class NativeGateway:
            def __init__(self,*_):
                self.clock=time.time
                self.held={'at':time.time(),'ok':True,'feeds':[{'session_id':'real'}]}
            def snapshot(self):return dict(self.held)
        class NativeHub:
            def __init__(self,path,gw,**_):self.gw=gw
        class NativeToken:
            def __init__(self,*_):pass
            def kind(self):return 'broadcast'
        native=SimpleNamespace(Gateway=NativeGateway,Hub=NativeHub,TokenFile=NativeToken,
                               PREVIEW_KEY='gbox-preview',KEY_RE=re.compile('.*'),
                               clamp_settings=lambda raw: {'on':bool(raw.get('on'))})
        stream=M.make_stream(self.cfg,native)
        stage=self.path/'gbox-stream.json'
        self.assertFalse(stream.HUB.settings()['on'])
        stage.write_text('{"on":true}')
        self.assertTrue(stream.HUB.settings()['on'])
        stage.write_text('[')
        self.assertFalse(stream.HUB.settings()['on'])
        stage.write_text('{"on":true}')
        self.assertTrue(stream.HUB.settings()['on'])
        stage.unlink()
        self.assertFalse(stream.HUB.settings()['on'])
        self.assertTrue(stream.HUB.gw.snapshot()['feeds'])
        for at in (time.time()-16,time.time()+30,float('nan')):
            stream.HUB.gw.held['at']=at
            self.assertEqual(stream.HUB.gw.snapshot()['feeds'],[])
        stream.HUB.gw.held.update(at=time.time(),ok=False)
        self.assertEqual(stream.HUB.gw.snapshot()['feeds'],[])

    def test_first_manifest_resolves_the_real_feed_after_a_short_async_cache_refresh(self):
        class ColdGateway:
            def __init__(self,*_):
                self.clock=time.time;self.refreshing=False;self.held={'at':0,'ok':False}
            def snapshot(self):
                if not self.refreshing and not self.held['ok']:
                    self.refreshing=True
                    def refresh():
                        time.sleep(.025)
                        self.held={'at':time.time(),'ok':True,'feeds':[{'session_id':'native-source'}]}
                        self.refreshing=False
                    threading.Thread(target=refresh,daemon=True).start()
                return dict(self.held)
        class Hub:
            def __init__(self,_path,gw,**_):self.gw=gw
        native=SimpleNamespace(Gateway=ColdGateway,Hub=Hub,TokenFile=lambda _:lambda:'view',
            PREVIEW_KEY='gbox-preview',KEY_RE=re.compile('.*'),clamp_settings=lambda raw:raw)
        native.TokenFile=lambda _:SimpleNamespace(kind=lambda:'broadcast')
        stream=M.make_stream(self.cfg,native)
        before=time.monotonic();snapshot=stream.HUB.gw.snapshot()
        self.assertEqual(snapshot['feeds'],[{'session_id':'native-source'}])
        self.assertLess(time.monotonic()-before,.5)

    def test_slow_public_backend_does_not_hold_hls_or_its_cache_pool(self):
        entered=threading.Event()
        async def backend(_request):
            entered.set()
            await asyncio.sleep(.5)
            return httpx.Response(200,stream=Content(b'listener'))
        public,_=self.apps(transport=httpx.MockTransport(backend))
        with TestClient(public) as client, concurrent.futures.ThreadPoolExecutor() as pool:
            pending=pool.submit(client.get,'/tune/viewer')
            self.assertTrue(entered.wait(1))
            start=time.monotonic()
            self.assertEqual(client.get('/api/gbox/hls',params={'k':'program','t':self.live}).status_code,200)
            self.assertLess(time.monotonic()-start,.3)
            self.assertFalse(pending.done())
            self.assertEqual(pending.result().content,b'listener')


if __name__=='__main__':
    unittest.main()
