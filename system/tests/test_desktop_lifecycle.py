"""Test regression coverage for request #1074:
Desktop embedded view lifecycle, authentication startup, Chromium rendering, and Windows native embedding.
"""
from pathlib import Path


def test_desktop_main_chromium_webview_rendering():
    main_js = (Path(__file__).parent.parent / "clients" / "desktop" / "main.js").read_text("utf-8")
    assert 'wc.getType() === "webview"' in main_js
    assert 'wc.setBackgroundColor("#16161a")' in main_js
    assert 'render-process-gone' in main_js


def test_winembed_ws_clipchildren():
    winembed_py = (Path(__file__).parent.parent / "clients" / "desktop" / "winembed.py").read_text("utf-8")
    assert "WS_CLIPCHILDREN" in winembed_py
    assert "WS_CLIPSIBLINGS" in winembed_py
    assert "p_style & WS_CLIPCHILDREN" in winembed_py


def test_desktop_index_lifecycle_and_auth():
    desktop_html = (Path(__file__).parent.parent / "clients" / "desktop" / "index.html").read_text("utf-8")
    # Dark backgrounds on container and webview
    assert "#play { padding:0; position:relative; background:#16161a; color-scheme:dark; }" in desktop_html
    assert "#play webview { width:100%; height:100vh; border:0; background:#16161a; }" in desktop_html
    assert '#play webview[data-ready="false"] { opacity:0; pointer-events:none; }' in desktop_html
    # Status retry panel
    assert 'id="playhost"' in desktop_html
    assert 'id="playretry"' in desktop_html
    # Auth before navigation
    assert "url.hash = new URLSearchParams({ token: tok, worker: S.workerName }).toString();" in desktop_html
    # Lifecycle event handlers
    assert 'wv.addEventListener("did-start-loading"' in desktop_html
    assert 'wv.addEventListener("did-fail-load"' in desktop_html
    assert 'wv.addEventListener("render-process-gone"' in desktop_html


def test_web_index_startup_auth():
    web_html = (Path(__file__).parent.parent / "clients" / "web" / "index.html").read_text("utf-8")
    assert 'if (HASH.get("token")) { tok = HASH.get("token"); try { localStorage.setItem("gbox_tok", tok); } catch {} }' in web_html
    assert 'window.GBOX_LOCAL = { worker: HASH.get("worker"), incidentCapture: true };' in web_html
