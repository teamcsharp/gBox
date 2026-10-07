"""Overlay swap tracker (Windows, PC venv: opencv-contrib-python-headless). Driven by the Electron main process (overlay.js)
over stdin/stdout, one JSON object per line, like winembed.py.

  {"op": "start", "pid": 1234, "point": [fx, fy]}   track the thing under that point of the game picture (0..1 fractions)
  {"op": "start", "pid": 1234, "box": [fx, fy, fw, fh]}
  {"op": "repick", "point": [fx, fy]}  ·  {"op": "stop"}  ·  {"op": "quit"}
Events: {"event": "box", "box": [fx, fy, fw, fh], "ok": true, "t": ..., "bg": [r, g, b]}
        {"event": "state", "state": "tracking|lost|waiting|stopped", ...}  ·  {"event": "stats", "fps", "cpu", "grab_ms", "track_ms"}

The frames come from PrintWindow(PW_RENDERFULLCONTENT) on the game window itself, so gBox's overlay (a separate window
above it) is never in them: the tracker always sees the original character, not the model drawn over it. If a window
answers PrintWindow with black, the screen pixels under it are used instead (overlay.js then excludes the overlay from
screen capture). Tracking: CSRT on a 240-line copy, checked against the character's look from the pick (template NCC);
when it drifts or loses it, a multi-scale template search over the whole frame finds it again.

  python overlay_track.py --bench video.mp4 --crop x,y,w,h --point fx,fy [--start N --frames M --out dir]
runs the same tracker over a recording (development / measurement).
"""
import ctypes
import json
import sys
import threading
import time

import cv2
import numpy as np

TRACK_H = 240                      # tracking resolution (lines)
DEBUG = __import__("os").environ.get("GBOX_OVERLAY_DEBUG", "")
FPS = 30

out_lock = threading.Lock()


def emit(obj):
    with out_lock:
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()


# ---------------- capture ----------------
class Grabber:
    """Client area of a process's game window (docked as a child of the gBox app or top-level), as BGR."""

    def __init__(self, pid: int):
        from ctypes import wintypes as W
        self.W, self.pid, self.hwnd, self.size, self.mode = W, pid, None, None, "printwindow"
        u, g = ctypes.windll.user32, ctypes.windll.gdi32
        VP = ctypes.c_void_p
        for f, rt, at in ((u.GetDC, VP, [VP]), (u.ReleaseDC, ctypes.c_int, [VP, VP]), (g.CreateCompatibleDC, VP, [VP]),
                          (g.CreateCompatibleBitmap, VP, [VP, ctypes.c_int, ctypes.c_int]), (g.SelectObject, VP, [VP, VP]),
                          (g.BitBlt, W.BOOL, [VP] + [ctypes.c_int] * 4 + [VP, ctypes.c_int, ctypes.c_int, W.DWORD]),
                          (g.GetDIBits, ctypes.c_int, [VP, VP, W.UINT, W.UINT, VP, VP, W.UINT]), (g.DeleteObject, W.BOOL, [VP]),
                          (g.StretchBlt, W.BOOL, [VP] + [ctypes.c_int] * 4 + [VP] + [ctypes.c_int] * 4 + [W.DWORD]),
                          (g.SetStretchBltMode, ctypes.c_int, [VP, ctypes.c_int]),
                          (g.DeleteDC, W.BOOL, [VP]), (u.PrintWindow, W.BOOL, [VP, VP, W.UINT]),
                          (u.GetClientRect, W.BOOL, [VP, VP]), (u.ClientToScreen, W.BOOL, [VP, VP]),
                          (u.IsWindow, W.BOOL, [VP]), (u.IsWindowVisible, W.BOOL, [VP]), (u.IsIconic, W.BOOL, [VP])):
            f.restype, f.argtypes = rt, at
        self.u, self.g, self.dc = u, g, None

    def _pids(self) -> set:
        """pid + its child processes (launchers start the real emulator); same walk as winembed.descendants."""
        W, k = self.W, ctypes.windll.kernel32

        class PE(ctypes.Structure):
            _fields_ = [("dwSize", W.DWORD), ("cntUsage", W.DWORD), ("pid", W.DWORD), ("heap", ctypes.c_void_p),
                        ("mod", W.DWORD), ("threads", W.DWORD), ("ppid", W.DWORD), ("pri", ctypes.c_long),
                        ("flags", W.DWORD), ("exe", ctypes.c_wchar * 260)]
        k.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
        k.Process32FirstW.argtypes = k.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        k.CloseHandle.argtypes = [ctypes.c_void_p]
        snap, pe, kids = k.CreateToolhelp32Snapshot(2, 0), PE(), {}
        pe.dwSize = ctypes.sizeof(PE)
        ok = k.Process32FirstW(snap, ctypes.byref(pe))
        while ok:
            kids.setdefault(pe.ppid, []).append(pe.pid)
            ok = k.Process32NextW(snap, ctypes.byref(pe))
        k.CloseHandle(snap)
        out, todo = set(), [self.pid]
        while todo:
            p = todo.pop()
            if p not in out:
                out.add(p)
                todo += kids.get(p, [])
        return out

    def find(self):
        W, u, pids, best = self.W, self.u, self._pids(), [None, 0]

        @ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
        def cb(h, _):
            p = W.DWORD()
            u.GetWindowThreadProcessId(h, ctypes.byref(p))
            if p.value in pids and u.IsWindowVisible(h):
                r = W.RECT()
                u.GetClientRect(h, ctypes.byref(r))
                if r.right * r.bottom > best[1]:
                    best[0], best[1] = h, r.right * r.bottom
            return True
        u.EnumChildWindows(u.GetDesktopWindow(), cb, 0)      # docked game windows are children of the gBox window
        self.hwnd = best[0]
        return self.hwnd

    def grab(self, out_h: int = TRACK_H):
        """-> (small BGR frame out_h lines tall, (full w, full h)) or None. The game window prints into a full-size
        memory DC; GDI shrinks it (nearest pixel, ~0.5 ms) so only the small copy ever reaches Python."""
        u, g, W = self.u, self.g, self.W
        h = self.hwnd
        if not (h and u.IsWindow(h)):
            h = self.find()
            if not h:
                return None
        if not u.IsWindowVisible(h) or u.IsIconic(h):
            return None
        r = W.RECT()
        u.GetClientRect(h, ctypes.byref(r))
        w, hh = r.right, r.bottom
        if w < 16 or hh < 16:
            return None
        oh = min(out_h, hh)
        ow = max(1, round(w * oh / hh))
        sh, sw = min(hh, oh * 2), min(w, ow * 2)               # GDI shrinks to 2x (nearest), OpenCV area-filters the rest
        if self.size != (w, hh, sw, sh):                        # (re)allocate on resize: docking, PiP, full screen
            self.close()
            self.sdc = u.GetDC(None)
            self.dc = g.CreateCompatibleDC(self.sdc)
            self.bmp = g.CreateCompatibleBitmap(self.sdc, w, hh)
            g.SelectObject(self.dc, self.bmp)
            self.sdc2 = g.CreateCompatibleDC(self.sdc)
            self.bmp2 = g.CreateCompatibleBitmap(self.sdc, sw, sh)
            g.SelectObject(self.sdc2, self.bmp2)
            g.SetStretchBltMode(self.sdc2, 3)                  # COLORONCOLOR: plain nearest-pixel, cheap
            self.buf = np.empty((sh, sw, 4), np.uint8)

            class BIH(ctypes.Structure):
                _fields_ = [("biSize", W.DWORD), ("biWidth", W.LONG), ("biHeight", W.LONG), ("biPlanes", W.WORD),
                            ("biBitCount", W.WORD), ("biCompression", W.DWORD), ("biSizeImage", W.DWORD),
                            ("a", W.LONG), ("b", W.LONG), ("c", W.DWORD), ("d", W.DWORD)]
            self.bi = BIH(ctypes.sizeof(BIH), sw, -sh, 1, 32, 0, 0, 0, 0, 0, 0)
            self.size = (w, hh, sw, sh)
        if self.mode == "printwindow":
            u.PrintWindow(h, self.dc, 3)                       # PW_CLIENTONLY | PW_RENDERFULLCONTENT: GPU windows too
            g.StretchBlt(self.sdc2, 0, 0, sw, sh, self.dc, 0, 0, w, hh, 0x00CC0020)
        else:                                                  # screen pixels under the window (overlay excluded by overlay.js)
            o = W.POINT(0, 0)
            u.ClientToScreen(h, ctypes.byref(o))
            g.StretchBlt(self.sdc2, 0, 0, sw, sh, self.sdc, o.x, o.y, w, hh, 0x00CC0020)
        g.GetDIBits(self.sdc2, self.bmp2, 0, sh, self.buf.ctypes.data, ctypes.byref(self.bi), 0)
        small = cv2.resize(self.buf, (ow, oh), interpolation=cv2.INTER_AREA) if (sw, sh) != (ow, oh) else self.buf
        return cv2.cvtColor(small, cv2.COLOR_BGRA2BGR), (w, hh)

    def close(self):
        if self.dc:
            for o in (self.bmp, self.bmp2):
                self.g.DeleteObject(o)
            for d in (self.dc, self.sdc2):
                self.g.DeleteDC(d)
            self.u.ReleaseDC(None, self.sdc)
            self.dc, self.size = None, None


# ---------------- detection + tracking ----------------
def detect(frame, pt):
    """Box (x, y, w, h) of the thing under pt (pixels) on a small BGR frame. GrabCut seeded around the point first;
    if that cuts out only a part (a shield, a hand), the character's colours against its surroundings grow the box;
    last resort, a character-sized box around the point (the operator can nudge it)."""
    H, W = frame.shape[:2]
    px, py = int(pt[0]), int(pt[1])
    fh = int(H * 0.3)
    fallback = Tracker._clamp((px - fh * 0.25, py - fh * 0.45, fh * 0.5, fh), W, H)
    b = _grabcut(frame, px, py)
    if not (b and b[3] >= H * 0.12):
        b = _colour_grow(frame, px, py, b or fallback) or b or fallback
    x, y, w, h = b
    if h < H * 0.1:                                     # a sliver (a hand, a highlight): a character-sized box there instead
        return fallback
    if w > h * 0.95:                                    # wider than tall: it leaked into a neighbour / the ground; keep the
        nw = int(h * 0.75)                              # part around the point
        x = max(x, min(px - nw // 2, x + w - nw))
        w = nw
    if h < w * 1.35:                                    # a squat cut-out is usually the upper body (a shield, a torso):
        h = min(H - y, int(w * 1.35))                   # the feet are below it, and the model stands on the box bottom
    return Tracker._clamp((x, y, w, h), W, H)


def _grabcut(frame, px, py):
    H, W = frame.shape[:2]
    rw, rh = int(W * 0.34), int(H * 0.62)
    x0, y0 = max(0, px - rw // 2), max(0, py - int(rh * 0.45))
    x1, y1 = min(W - 1, x0 + rw), min(H - 1, y0 + rh)
    if x1 - x0 < 12 or y1 - y0 < 12:
        return None
    mask = np.zeros((H, W), np.uint8)
    bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    try:
        cv2.grabCut(frame, mask, (x0, y0, x1 - x0, y1 - y0), bgd, fgd, 3, cv2.GC_INIT_WITH_RECT)
        mask[max(0, py - 2):py + 3, max(0, px - 2):px + 3] = cv2.GC_FGD            # the operator's point is the thing
        cv2.grabCut(frame, mask, None, bgd, fgd, 2, cv2.GC_INIT_WITH_MASK)
    except cv2.error:
        return None
    fg = ((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD)).astype(np.uint8)
    return _blob_at(cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)), px, py)


def _blob_at(fg, px, py):
    """Bounding box of the blob at (or nearest to) the point, plus sizeable blobs touching it."""
    H, W = fg.shape
    n, lab, st, _ = cv2.connectedComponentsWithStats(fg, 8)
    if n <= 1:
        return None
    ys, xs = np.nonzero(lab)
    d = (xs - px) ** 2 + (ys - py) ** 2
    if d.min() > (H * 0.05) ** 2:
        return None
    i = int(lab[ys[d.argmin()], xs[d.argmin()]])
    x, y, w, h = st[i, :4]
    for j in range(1, n):
        if j != i and st[j, 4] > st[i, 4] * 0.15:
            a, b, c, e = st[j, :4]
            if a < x + w + 4 and a + c > x - 4 and b < y + h + 4 and b + e > y - 4:
                x, y, w, h = min(x, a), min(y, b), max(x + w, a + c) - min(x, a), max(y + h, b + e) - min(y, b)
    if w * h < (H * 0.04) ** 2 or w * h > W * H * 0.5:
        return None
    return int(x), int(y), int(w), int(h)


def _colour_grow(frame, px, py, box):
    """Twice: colours of the box vs its surroundings -> pixels that look like it -> the blob at the point."""
    H, W = frame.shape[:2]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    t = Tracker()
    for _ in range(2):
        box = Tracker._clamp(box, W, H)
        t.obj, t.bg = t._hist(hsv, box)
        t.ratio = t._model()
        bp = t._bp(hsv)
        x, y, w, h = box
        reg = np.zeros_like(bp)
        reg[max(0, y - h // 2):y + h + h // 2, max(0, x - w):x + 2 * w] = 1
        fg = ((bp > 60) & (reg > 0)).astype(np.uint8)
        k = max(3, h // 8) | 1
        fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
        nb = _blob_at(fg, px, py)
        if not nb or nb[3] < H * 0.08 or nb[2] * nb[3] > 3 * w * h or nb[3] > H * 0.7:
            return None
        box = (nb[0] - nb[2] * 0.05, nb[1] - nb[3] * 0.03, nb[2] * 1.1, nb[3] * 1.06)
    return Tracker._clamp(box, W, H)


class Tracker:
    """CSRT for frame-to-frame motion + a colour model of the character (hue/saturation histogram of the box divided by
    the one around it, so only colours that set it apart from its surroundings count) for checking and finding it again:
    the colour model doesn't care which way a 3D character is turned."""
    BINS, RANGES = [24, 12], [0, 180, 0, 256]

    def __init__(self, kind: str = "csrt"):
        self.kind, self.t, self.box, self.n, self.bad, self.lost, self.score = kind, None, None, 0, 0, False, 1.0

    def _new(self):
        if self.kind == "kcf":
            return cv2.TrackerKCF_create()
        p = cv2.TrackerCSRT_Params()
        p.use_segmentation = False                              # faster; the colour model does the verification
        if self.kind == "csrt":                                 # light settings: ~2x cheaper than the defaults
            p.template_size, p.number_of_scales, p.admm_iterations = 96, 9, 3
            p.use_color_names, p.use_gray = False, True
        return cv2.TrackerCSRT_create(p)

    @staticmethod
    def _clamp(box, W, H):
        x, y, w, h = [int(round(v)) for v in box]
        w, h = max(8, min(w, W)), max(8, min(h, H))
        return max(0, min(x, W - w)), max(0, min(y, H - h)), w, h

    def _hist(self, hsv, box):
        x, y, w, h = box
        m = np.zeros(hsv.shape[:2], np.uint8)
        m[y:y + h, x:x + w] = 1
        sat = cv2.inRange(hsv, (0, 30, 25), (180, 256, 256))
        obj = cv2.calcHist([hsv], [0, 1], m & sat, self.BINS, self.RANGES)
        H, W = hsv.shape[:2]
        rx, ry = int(w * 0.8), int(h * 0.5)
        r = np.zeros_like(m)
        r[max(0, y - ry):min(H, y + h + ry), max(0, x - rx):min(W, x + w + rx)] = 1
        r[y:y + h, x:x + w] = 0
        bg = cv2.calcHist([hsv], [0, 1], r & sat, self.BINS, self.RANGES)
        obj /= max(1.0, float(obj.sum()))
        bg /= max(1.0, float(bg.sum()))
        return obj, bg

    def _model(self):
        ratio = self.obj / (self.obj + self.bg + 1e-4)          # 1 = only on the character, 0 = only around it
        ratio[self.obj < 0.002] = 0
        return np.clip((ratio - 0.5) * 2, 0, 1).astype(np.float32)   # only colours more likely on it than around it

    def _bp(self, hsv):
        return cv2.calcBackProject([hsv], [0, 1], self.ratio, self.RANGES, 255)

    def _score(self, bp, box):
        x, y, w, h = box
        a = bp[y:y + h, x:x + w]
        return float(a.mean()) if a.size else 0.0

    def init(self, frame, box, keep_model=False):
        H, W = frame.shape[:2]
        box = self._clamp(box, W, H)
        self.t = self._new()
        self.t.init(frame, box)
        self.box, self.good, self.size, self.n, self.bad, self.lost = box, box, box[2:], 0, 0, False
        if not keep_model:
            self.size0 = box[2:]
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            self.obj, self.bg = self._hist(hsv, box)
            self.ratio = self._model()
            self.s0 = max(1e-3, self._score(self._bp(hsv), box))
        self.score = 1.0

    def redetect(self, frame, hsv=None, near=None):
        """Where does the colour model fire hardest, in a box of the character's size? (prefers places near `near`)"""
        H, W = frame.shape[:2]
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV) if hsv is None else hsv
        w, h = [int(v) for v in self.size]
        dens = cv2.boxFilter(self._bp(hsv).astype(np.float32), -1, (max(3, w), max(3, h)))
        st = self._static(hsv.shape)
        if st is not None:                                      # never the HUD: drop places that are mostly still pixels
            dens *= 1 - cv2.boxFilter(st, -1, (max(3, w), max(3, h)))
        g = self.good if near is None else (near[0] - w / 2, near[1] - h / 2, w, h)
        cx, cy = g[0] + g[2] / 2, g[1] + g[3] / 2
        gx = np.exp(-((np.arange(W) - cx) / (0.3 * W)) ** 2)
        gy = np.exp(-((np.arange(H) - cy) / (0.3 * H)) ** 2)
        m = dens * np.outer(gy, gx)
        m[:h // 2, :] = m[H - h // 2:, :] = 0                    # the whole box on the picture
        m[:, :w // 2] = m[:, W - w // 2:] = 0
        y, x = np.unravel_index(int(m.argmax()), m.shape)
        if dens[y, x] < 0.55 * self.s0:
            return False
        self.init(frame, (x - w / 2, y - h / 2, w, h), keep_model=True)
        return True

    def _motion(self, frame):
        """Running per-pixel change (quarter size): HUD, minimap and score digits stay still while the scene moves, so
        the re-search never jumps onto them."""
        g = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA).astype(np.float32)
        if getattr(self, "prev", None) is None or self.prev.shape != g.shape:
            self.prev, self.mot, self.nmot = g, np.full_like(g, 8.0), 0
            return
        self.mot += (np.abs(g - self.prev) - self.mot) * 0.05
        self.prev, self.nmot = g, self.nmot + 1

    def _static(self, shape):
        if getattr(self, "nmot", 0) < 30:
            return None
        return cv2.resize((self.mot < 1.5).astype(np.float32), (shape[1], shape[0]), interpolation=cv2.INTER_NEAREST)

    def update(self, frame):
        """-> (box, ok). Not ok = lost (box = last known position)."""
        self.n += 1
        H, W = frame.shape[:2]
        self._motion(frame)
        if self.lost:
            if self.n % 6 == 0 and self.redetect(frame):
                return self.box, True
            return self.box, False
        ok, b = self.t.update(frame)
        if ok:
            b = self._clamp(b, W, H)
            ok = b[2] < W * 0.9 and b[3] < H * 0.95
        if ok:                                                  # CSRT's scale wanders (it grows into the ground):
            w0, h0 = self.size0                                 # characters keep about the size they had when picked
            w = min(max(b[2], w0 * 0.65), w0 * 1.5)
            h = min(max(b[3], h0 * 0.65), h0 * 1.5)
            if (w, h) != (b[2], b[3]):
                cx, cy = b[0] + b[2] / 2, b[1] + b[3] / 2
                b = self._clamp((cx - w / 2, cy - h / 2, w, h), W, H)
                self.t = self._new()
                self.t.init(frame, b)
        if not ok:                                              # the tracker gave up: look for its colours
            if self.redetect(frame):
                return self.box, True
            self.lost = True
            return self.box, False
        if self.n % 5 == 0:                                     # check: are we still on the character's colours?
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            self.score = s = self._score(self._bp(hsv), b) / self.s0
            if s > 0.75:
                self.bad, self.good = 0, b
                if b[2] * b[3] > 0.5 * self.size[0] * self.size[1]:
                    self.size = (0.9 * self.size[0] + 0.1 * b[2], 0.9 * self.size[1] + 0.1 * b[3])
            elif s < 0.45:
                self.bad += 1
            if self.bad >= 2:                                   # drifted onto something else: look for its colours near
                g = self.good                                   # where it was last seen; hold there until found
                if self.redetect(frame, hsv, near=(g[0] + g[2] / 2, g[1] + g[3] / 2)):
                    self.bad, self.good = 0, self.box
                    return self.box, True
        if self.bad >= 2:
            return self.good, False
        self.box = b
        return b, True


def ring_color(frame, box):
    """Mean colour just around the box (RGB): the optional soft backdrop's fill."""
    H, W = frame.shape[:2]
    x, y, w, h = box
    m = max(3, int(h * 0.12))
    a = frame[max(0, y - m):min(H, y + h + m), max(0, x - m):min(W, x + w + m)]
    if not a.size:
        return [0, 0, 0]
    c = np.concatenate([a[:m].reshape(-1, 3), a[:, :m].reshape(-1, 3), a[:, -m:].reshape(-1, 3)])
    return [int(v) for v in c.mean(0)[::-1]]


# ---------------- live loop ----------------
class Live:
    """Two threads: capture (PrintWindow + downscale, the slow part, mostly waiting on the GPU) and tracking on the newest
    frame. They overlap, so the rate is set by the slower one, not their sum."""

    def __init__(self):
        self.lock = threading.Lock()
        self.cmds = []
        self.grab = None
        self.frame = None                                       # (small BGR, full size, seq)
        self.seq = 0
        self.gms = 0.0

    def capture(self):
        cur = None
        while True:
            g = self.grab
            if g is not cur:                                    # started / stopped: free the old window's GDI objects here,
                if cur:                                         # in the thread that uses them
                    cur.close()
                cur = g
            if not g:
                time.sleep(0.05)
                continue
            t0 = time.perf_counter()
            try:
                got = g.grab()
            except OSError:
                got = None
            if got is None:
                with self.lock:
                    self.frame = None
                time.sleep(0.2)
                continue
            sm, (W, H) = got
            if g.mode == "printwindow" and sm.max() < 6:
                g.black = getattr(g, "black", 0) + 1
                if g.black > 15:                                # black for half a second: can this window be printed at all?
                    g.black, g.mode = 0, "screen"
                    if (g.grab() or (np.zeros(1),))[0].max() > 20:   # the screen shows a picture there: read the screen from now on
                        emit({"event": "state", "state": "capture", "mode": "screen"})
                    else:
                        g.mode = "printwindow"                  # really a black frame (a fade, loading)
            else:
                g.black = 0
            with self.lock:
                self.seq += 1
                self.frame = (sm, (W, H), self.seq)
                self.gms += time.perf_counter() - t0
            spare = 1 / FPS - (time.perf_counter() - t0)
            if spare > 0:
                time.sleep(spare)

    def loop(self):
        threading.Thread(target=self.capture, daemon=True).start()
        trk, pending, state, last_seq = None, None, "stopped", 0
        nf, tsum, last_stat, cpu0 = 0, 0.0, time.time(), time.process_time()
        while True:
            with self.lock:
                cmd = self.cmds.pop(0) if self.cmds else None
            if cmd:
                op = cmd.get("op")
                if op == "quit":
                    return
                if op == "stop":
                    self.grab, trk, pending = None, None, None
                    state = "stopped"
                    emit({"event": "state", "state": state})
                elif op == "start":
                    self.grab, trk, pending = Grabber(int(cmd["pid"])), None, cmd
                elif op == "repick" and self.grab:
                    trk, pending = None, cmd
            with self.lock:
                f = self.frame
            if not self.grab or not f or f[2] == last_seq:
                if self.grab and not f and state != "waiting":
                    state = "waiting"
                    emit({"event": "state", "state": state, "why": "the game window isn't visible"})
                time.sleep(0.005)
                continue
            sm, (W, H), last_seq = f
            sh, sw = sm.shape[:2]
            t1 = time.perf_counter()
            if pending:
                if "box" in pending:
                    fx, fy, fw, fh = pending["box"]
                    b = (fx * sw, fy * sh, fw * sw, fh * sh)
                else:
                    b = detect(sm, (pending["point"][0] * sw, pending["point"][1] * sh))
                trk = Tracker(pending.get("tracker", "csrt"))
                trk.init(sm, b)
                pending, box, ok = None, trk.box, True
                state = "tracking"
                emit({"event": "state", "state": state, "box": [box[0] / sw, box[1] / sh, box[2] / sw, box[3] / sh]})
            elif trk:
                box, ok = trk.update(sm)
            else:
                continue
            t2 = time.perf_counter()
            if ok != (state == "tracking"):
                state = "tracking" if ok else "lost"
                emit({"event": "state", "state": state})
            x, y, w, h = box
            if DEBUG and nf % 15 == 0:                          # GBOX_OVERLAY_DEBUG=<dir>: what the tracker sees
                d = sm.copy()
                cv2.rectangle(d, (int(x), int(y)), (int(x + w), int(y + h)), (0, 255, 0) if ok else (0, 0, 255), 1)
                cv2.imwrite(f"{DEBUG}/trk_{int(time.time() * 1000)}.png", d)
            emit({"event": "box", "box": [round(x / sw, 4), round(y / sh, 4), round(w / sw, 4), round(h / sh, 4)], "ok": ok,
                  "t": round(time.time(), 3), "bg": ring_color(sm, box) if nf % 10 == 0 else None})
            nf += 1
            tsum += t2 - t1
            now = time.time()
            if now - last_stat >= 2:
                with self.lock:
                    gms, self.gms, seqs = self.gms, 0.0, self.seq
                cpu = (time.process_time() - cpu0) / (now - last_stat) * 100     # % of one core, whole helper
                emit({"event": "stats", "fps": round(nf / (now - last_stat), 1), "cpu": round(cpu, 1),
                      "grab_ms": round(gms * 1000 / max(1, seqs - getattr(self, "_seq0", 0)), 1),
                      "track_ms": round(tsum / nf * 1000, 1), "size": [W, H], "mode": self.grab.mode if self.grab else ""})
                self._seq0 = seqs
                last_stat, nf, tsum, cpu0 = now, 0, 0.0, time.process_time()

    def reader(self):
        for line in sys.stdin:
            try:
                m = json.loads(line)
            except ValueError:
                continue
            with self.lock:
                self.cmds.append(m)
            if m.get("op") == "quit":
                return
        with self.lock:
            self.cmds.append({"op": "quit"})


def bench(argv):
    """Offline run over a recording: per-frame track time, CPU, how often it was lost; annotated frames for checking."""
    import argparse
    import os
    a = argparse.ArgumentParser()
    a.add_argument("--bench")
    a.add_argument("--crop", default="")
    a.add_argument("--point")
    a.add_argument("--box", default="")
    a.add_argument("--start", type=int, default=0)
    a.add_argument("--frames", type=int, default=300)
    a.add_argument("--every", type=int, default=30)
    a.add_argument("--step", type=float, default=1.0)                # >1: skip frames like the live loop does
    a.add_argument("--tracker", default="csrt")
    a.add_argument("--out", default=".")
    o = a.parse_args(argv)
    cap = cv2.VideoCapture(o.bench)
    cap.set(cv2.CAP_PROP_POS_FRAMES, o.start)
    cx, cy, cw, ch = [int(v) for v in o.crop.split(",")] if o.crop else (0, 0, 0, 0)
    pt = [float(v) for v in (o.point or "0.5,0.5").split(",")]
    cv2.setNumThreads(2)
    trk, times, lost, cpu0, n = None, [], 0, time.process_time(), 0
    os.makedirs(o.out, exist_ok=True)
    pos = float(o.start)
    for i in range(o.frames):
        ok, fr = cap.read()
        if not ok:
            break
        pos += o.step
        while cap.get(cv2.CAP_PROP_POS_FRAMES) < int(pos):
            cap.grab()
        if cw:
            fr = fr[cy:cy + ch, cx:cx + cw]
        H, W = fr.shape[:2]
        k = TRACK_H / H
        t0 = time.perf_counter()
        sm = cv2.resize(fr, (round(W * k), round(H * k)), interpolation=cv2.INTER_AREA)
        if trk is None:
            if o.box:
                bx = [float(v) for v in o.box.split(",")]
                b = (bx[0] * sm.shape[1], bx[1] * sm.shape[0], bx[2] * sm.shape[1], bx[3] * sm.shape[0])
            else:
                b = detect(sm, (pt[0] * sm.shape[1], pt[1] * sm.shape[0]))
            trk = Tracker(o.tracker)
            trk.init(sm, b)
            box, good = trk.box, True
            print("init box", b, "detect ms %.1f" % ((time.perf_counter() - t0) * 1000))
        else:
            box, good = trk.update(sm)
            times.append(time.perf_counter() - t0)
        lost += not good
        n += 1
        if i % o.every == 0:
            x, y, w, h = [int(v / k) for v in box]
            cv2.rectangle(fr, (x, y), (x + w, y + h), (0, 255, 0) if good else (0, 0, 255), 3)
            cv2.putText(fr, f"{int(pos)} ncc {trk.score:.2f}", (10, 30), 0, 1, (0, 255, 255), 2)
            cv2.imwrite(os.path.join(o.out, f"bench_{int(pos):05d}.jpg"), cv2.resize(fr, None, fx=0.5, fy=0.5))
    t = np.array(times) * 1000
    print(json.dumps({"frames": n, "tracker": o.tracker, "track_ms_mean": round(float(t.mean()), 2), "track_ms_p95": round(float(np.percentile(t, 95)), 2),
                      "lost_frames": lost, "cpu_s_per_frame_ms": round((time.process_time() - cpu0) / n * 1000, 2),
                      "max_fps_tracking_only": round(1000 / float(t.mean()), 1)}))


if __name__ == "__main__":
    if "--bench" in sys.argv:
        bench(sys.argv[1:])
        sys.exit(0)
    cv2.setNumThreads(1)                                        # low CPU: no worker-pool spinning; the game owns the machine
    live = Live()
    threading.Thread(target=live.reader, daemon=True).start()
    live.loop()
