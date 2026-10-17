"""A stand-in for audio.cpp's audiocpp_server in tests (tests/test_audio_cpp.py): same CLI shape and HTTP routes.

audiocpp_server [--fake-delay S] [--fake-busy] --config server.json
Every request is appended to requests.jsonl next to server.json so a test can see what gBox sent.
"""
import argparse
import json
import struct
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def wav(n=1600, rate=16000):
    pcm = b"\0\0" * n
    return b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16) + \
        b"data" + struct.pack("<I", len(pcm)) + pcm


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--fake-delay", type=float, default=0.0)
    ap.add_argument("--fake-busy", action="store_true")
    a = ap.parse_args()
    conf_path = Path(a.config)
    conf = json.loads(conf_path.read_text(encoding="utf-8"))
    log = conf_path.with_name("requests.jsonl")
    models = {m["id"]: m for m in conf["models"]}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code, body, ctype="application/json"):
            data = json.dumps(body).encode() if not isinstance(body, bytes) else body
            self.send_response(code)
            self.send_header("content-type", ctype)
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _note(self, entry):
            with open(log, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")

        def do_GET(self):
            if self.path == "/health":
                return self._send(200, {"status": "ok", "models": len(models), "backend": conf["backend"]})
            if self.path.startswith("/v1/audio/voices"):
                return self._send(200, {"voices": ["af_heart", "bm_george"]})
            if self.path == "/v1/models":
                return self._send(200, {"data": [{"id": k} for k in models]})
            self._send(404, {"error": "not found"})

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("content-length") or 0))
            if a.fake_delay:
                time.sleep(a.fake_delay)
            if a.fake_busy:
                return self._send(503, {"error": {"code": "server_busy"}})
            if self.path == "/v1/audio/speech":
                req = json.loads(body)
                self._note({"route": "speech", **req})
                if req.get("model") not in models:
                    return self._send(400, {"error": f"unknown model {req.get('model')}"})
                return self._send(200, wav(), "audio/wav")
            if self.path == "/v1/audio/transcriptions":
                is_wav = b"RIFF" in body and b"WAVE" in body
                model = next((m for m in models if f'name="model"\r\n\r\n{m}\r\n'.encode() in body), None)
                lang = b'name="language"' in body
                self._note({"route": "transcriptions", "wav": is_wav, "model": model, "language": lang})
                if not (is_wav and model):
                    return self._send(400, {"error": "need a WAV file and a known model"})
                return self._send(200, {"text": " hello from audio.cpp ", "timing": {}})
            self._send(404, {"error": "not found"})

    srv = ThreadingHTTPServer((conf["host"], conf["port"]), H)
    print(f"fake audiocpp_server on {conf['host']}:{conf['port']} ({len(models)} models)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
