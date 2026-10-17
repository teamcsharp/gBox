"""A stand-in for ffmpeg in the ring recording tests (#1084): run as `python fake_ffmpeg.py <ffmpeg args>`.

Every call is appended to $FAKE_LOG (one JSON argv per line). Modes, picked from the arguments like ffmpeg would:
  -encoders              prints $FAKE_ENCODERS (default "h264_nvenc libx264")
  -h demuxer=gdigrab     prints a help text that names hwnd= when $FAKE_HWND=1
  lavfi color= ... null  the NVENC test encode: fails when $FAKE_NVENC_BROKEN=1 and the encoder is NVENC
  -f segment             the ring: a segment every segment_time * $FAKE_TIME_SCALE s ($FAKE_SEG_BYTES each), wrapped,
                         one csv line per finished segment; 'q' on stdin closes the current one; $FAKE_DIE_AFTER=n exits
                         with an error after n segments
  -f concat              the export: checks the list, writes an MP4-looking file of bitrate * -t bytes
                         (x $FAKE_OVERSHOOT); fails for NVENC when $FAKE_NVENC_EXPORT_FAIL=1
"""
import json
import os
import sys
import threading
import time
from pathlib import Path


def arg(argv, name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default


def kbps_of(v: str) -> float:
    return float(v.rstrip("k")) if v.endswith("k") else float(v) / 1000


def main(argv):
    if os.environ.get("FAKE_LOG"):
        with open(os.environ["FAKE_LOG"], "a", encoding="utf-8") as f:
            f.write(json.dumps(argv) + "\n")
    enc = arg(argv, "-c:v", "")
    if "-encoders" in argv:
        for e in os.environ.get("FAKE_ENCODERS", "h264_nvenc libx264").split():
            print(f" V....D {e:<20} fake {e}")
        return 0
    if "-h" in argv:
        print("gdigrab indev AVOptions:\n  -draw_mouse\n" + ("  input: desktop | title=<t> | hwnd=<handle>\n" if os.environ.get("FAKE_HWND") == "1" else ""))
        return 0
    if any(str(a).startswith("color=") for a in argv) and "null" in argv:
        if "nvenc" in enc and os.environ.get("FAKE_NVENC_BROKEN") == "1":
            print("[h264_nvenc] OpenEncodeSessionEx failed: no capable devices found", file=sys.stderr)
            return 1
        return 0
    if arg(argv, "-f") == "segment" or "segment" in argv:
        return ring(argv)
    if "concat" in argv:
        return export(argv, enc)
    print("fake ffmpeg: unknown call", file=sys.stderr)
    return 2


def stdin_q() -> bool:
    """'q' (or a closed pipe) waiting on stdin, checked without blocking."""
    if os.name == "nt":
        import ctypes
        import msvcrt
        avail = ctypes.c_ulong(0)
        h = msvcrt.get_osfhandle(sys.stdin.fileno())
        if not ctypes.windll.kernel32.PeekNamedPipe(ctypes.c_void_p(h), None, 0, None, ctypes.byref(avail), None):
            return True                                             # the parent closed the pipe
        return avail.value > 0 and os.read(sys.stdin.fileno(), 1) in (b"q", b"")
    import select
    if select.select([sys.stdin], [], [], 0)[0]:
        return os.read(sys.stdin.fileno(), 1) in (b"q", b"")
    return False


def ring(argv):
    seg_t = float(arg(argv, "-segment_time", "5"))
    wrap = int(arg(argv, "-segment_wrap", "0") or 0)
    lst, pattern = Path(arg(argv, "-segment_list")), argv[-1]
    step = seg_t * float(os.environ.get("FAKE_TIME_SCALE", "1"))
    size = int(os.environ.get("FAKE_SEG_BYTES", str(188 * 100)))
    die_after = int(os.environ.get("FAKE_DIE_AFTER", "0") or 0)
    quit_ = threading.Event()

    def wait(step):
        """Sleep `step`, watching stdin for 'q' without a blocking read (a thread blocked in ReadFile on a Windows
        pipe stalls this interpreter)."""
        end = time.time() + step
        while time.time() < end and not quit_.is_set():
            if stdin_q():
                quit_.set()
            time.sleep(0.01)
    n, t = 0, 0.0
    while True:
        idx = n % wrap if wrap else n
        path = Path(pattern % idx)
        path.write_bytes(b"\x47" * (size // 2))                    # opened (truncated) at once, half written
        began = time.time()
        wait(step)
        dur = seg_t if not quit_.is_set() else max(0.1, seg_t * min(1.0, (time.time() - began) / step))
        path.write_bytes(b"\x47" * size)
        with open(lst, "a", encoding="utf-8") as f:
            f.write(f"{path.name},{t:.6f},{t + dur:.6f}\n")
        n, t = n + 1, t + dur
        if quit_.is_set():
            return 0
        if die_after and n >= die_after:
            print("fake ffmpeg: capture lost", file=sys.stderr)
            return 1


def export(argv, enc):
    lst = Path(arg(argv, "-i"))
    for line in lst.read_text(encoding="utf-8").splitlines():
        name = line.split("'")[1]
        if not (lst.parent / name).is_file():
            print(f"missing {name}", file=sys.stderr)
            return 1
    if "nvenc" in enc and os.environ.get("FAKE_NVENC_EXPORT_FAIL") == "1":
        print("[h264_nvenc] InitializeEncoder failed: out of memory", file=sys.stderr)
        return 1
    seconds = float(arg(argv, "-t", "1"))
    kbps = kbps_of(arg(argv, "-b:v", "1000k"))
    n = int(kbps * 1000 / 8 * seconds * float(os.environ.get("FAKE_OVERSHOOT", "1")))
    Path(argv[-1]).write_bytes((b"\0\0\0\x18ftypisom" + b"\0" * max(0, n - 12))[:max(n, 12)])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
