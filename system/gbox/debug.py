"""CPU-level debugging for live sessions: registers, disassembly, breakpoints/watchpoints, stepping, video memory.

Two back ends behind one interface (`Debugger`):
- GdbDebugger: the GDB remote serial protocol, spoken by emulators' built-in stubs (Dolphin, DuckStation, mGBA, MAME).
- MemoryDebugger: any session that can only read memory (RetroArch cores): disassembly + memory, no registers/breakpoints.
Disassembly is Capstone for every CPU it knows (PPC, MIPS, ARM/Thumb, SH4/SH2, 68k, 6502/65C02/65816, x86).
"""
import socket
import struct
import threading
import time
import xml.etree.ElementTree as ET

# platform -> (cpu, capstone arch, mode flags, big endian)
CPUS = {
    "gamecube": "ppc", "wii": "ppc",
    "dreamcast": "sh4", "naomi": "sh4", "atomiswave": "sh4", "saturn": "sh2",
    "psx": "mips_le", "psp": "mips_le", "ps2": "mips_le", "n64": "mips_be", "n64dd": "mips_be",
    "gba": "arm", "nds": "arm", "3do": "arm", "3ds": "arm",
    "genesis": "m68k", "megadrive": "m68k", "segacd": "m68k", "neogeo": "m68k", "neocd": "m68k", "amiga": "m68k",
    "atarist": "m68k", "jaguar": "m68k", "x68000": "m68k", "sega32x": "sh2",
    "nes": "6502", "fds": "6502", "atari2600": "6502", "atari7800": "6502", "atari8": "6502", "c64": "6502",
    "apple2": "6502", "bbcmicro": "6502", "lynx": "65c02", "pce": "65c02", "pcecd": "65c02",
    "snes": "65816", "satellaview": "65816", "sufami": "65816",
    "dos": "x86_16", "pc": "x86_32",
    "xbox360": "ppc",                                         # Xenon: 64-bit PPC, 32-bit addresses (VMX128 ops undecoded)
    # Z80 / LR35902 / others: Capstone has no decoder (memory + raw bytes only)
}


def _cs(cpu: str):
    import capstone as c
    table = {
        "ppc": (c.CS_ARCH_PPC, c.CS_MODE_32 | c.CS_MODE_BIG_ENDIAN),
        "sh4": (c.CS_ARCH_SH, c.CS_MODE_SH4 | c.CS_MODE_LITTLE_ENDIAN),
        "sh2": (c.CS_ARCH_SH, c.CS_MODE_SH2 | c.CS_MODE_BIG_ENDIAN),
        "mips_le": (c.CS_ARCH_MIPS, c.CS_MODE_MIPS32 | c.CS_MODE_LITTLE_ENDIAN),
        "mips_be": (c.CS_ARCH_MIPS, c.CS_MODE_MIPS64 | c.CS_MODE_BIG_ENDIAN),
        "arm": (c.CS_ARCH_ARM, c.CS_MODE_ARM),
        "thumb": (c.CS_ARCH_ARM, c.CS_MODE_THUMB),
        "m68k": (c.CS_ARCH_M68K, c.CS_MODE_M68K_000),
        "6502": (c.CS_ARCH_MOS65XX, c.CS_MODE_MOS65XX_6502),
        "65c02": (c.CS_ARCH_MOS65XX, c.CS_MODE_MOS65XX_65C02),
        "65816": (c.CS_ARCH_MOS65XX, c.CS_MODE_MOS65XX_65816_LONG_MX),
        "x86_16": (c.CS_ARCH_X86, c.CS_MODE_16),
        "x86_32": (c.CS_ARCH_X86, c.CS_MODE_32),
    }
    if cpu not in table:
        raise ValueError(f"no disassembler for {cpu}")
    md = c.Cs(*table[cpu])
    md.skipdata = True                                        # keep going over data/undefined opcodes
    return md


def disassemble(cpu: str, data: bytes, address: int, count: int = 64) -> list[dict]:
    out = []
    for ins in _cs(cpu).disasm(data, address):
        out.append({"addr": ins.address, "bytes": ins.bytes.hex(), "mnemonic": ins.mnemonic, "operands": ins.op_str})
        if len(out) >= count:
            break
    return out


# GDB register layouts for stubs that don't send target.xml: (name, size in bytes) in 'g'-packet order,
# plus registers only reachable with 'p' (regnum, name, size).
LAYOUTS = {
    "ppc": ([(f"r{i}", 4) for i in range(32)],
            [(64, "pc", 4), (65, "msr", 4), (66, "cr", 4), (67, "lr", 4), (68, "ctr", 4), (69, "xer", 4)]),
    "mips_le": ([(f"r{i}", 4) for i in range(32)] + [("sr", 4), ("lo", 4), ("hi", 4), ("bad", 4), ("cause", 4), ("pc", 4)], []),
    "arm": ([(f"r{i}", 4) for i in range(13)] + [("sp", 4), ("lr", 4), ("pc", 4)], [(25, "cpsr", 4)]),
    "m68k": ([(f"d{i}", 4) for i in range(8)] + [(f"a{i}", 4) for i in range(8)] + [("sr", 4), ("pc", 4)], []),
    "sh4": ([(f"r{i}", 4) for i in range(16)] + [("pc", 4), ("pr", 4), ("gbr", 4), ("vbr", 4), ("mach", 4), ("macl", 4), ("sr", 4)], []),
}
BIG_ENDIAN = {"ppc", "m68k", "sh2", "mips_be"}


class Unavailable(RuntimeError):
    pass


class Debugger:
    """Interface. Addresses are the CPU's native addresses."""
    cpu = "?"
    features: set[str] = set()                # regs, step, break, watch, halt, vram

    def info(self) -> dict:
        return {"cpu": self.cpu, "features": sorted(self.features), "halted": False}

    def regs(self) -> dict:
        raise Unavailable("registers are not exposed by this emulator")

    def read(self, address: int, length: int) -> bytes:
        raise NotImplementedError

    def disasm(self, address: int | None, count: int = 48) -> list[dict]:
        if address is None:
            address = self.regs()["pc"]
        cpu = self.cpu
        if cpu == "arm" and self.features & {"regs"} and (self.regs().get("cpsr", 0) >> 5) & 1:
            cpu = "thumb"                                     # CPSR T bit
        width = {"6502": 3, "65c02": 3, "65816": 4}.get(cpu, 8)
        return disassemble(cpu, self.read(address, count * width), address, count)

    def halt(self):
        raise Unavailable("this emulator can't be halted from gBox")

    resume = step = halt

    def set_breakpoint(self, address: int, kind: str = "exec", length: int = 4):
        raise Unavailable("breakpoints need an emulator with a debug server (e.g. Dolphin, DuckStation, mGBA, MAME)")

    remove_breakpoint = set_breakpoint

    def close(self):
        pass


class MemoryDebugger(Debugger):
    """Read-only debugging over an adapter's memory reads (RetroArch cores)."""
    features = {"disasm", "memory"}

    def __init__(self, adapter, cpu: str):
        self.ad, self.cpu = adapter, cpu

    def read(self, address, length):
        return self.ad.read_memory(address, length)

    def disasm(self, address, count=48):
        if address is None:
            raise Unavailable("no program counter from this emulator: give an address to disassemble")
        return super().disasm(address, count)


class DolphinProcMem(Debugger):
    """Windows Dolphin: emulated RAM read/written in the Dolphin process (like Dolphin Memory Engine). A GDB client left
    attached slows Dolphin on Windows ~70x (measured: RE4 intro 0.3 vs 25 frames/s), and the stub won't take a second
    connection after a detach, so after boot gBox works on the shared memory mapping instead: no halts, full speed.
    ponytail: code writes land in RAM but Dolphin's JIT keeps already-compiled blocks until they're recompiled, so a
    patch of hot code can lag or need a state reload; data (ammo, health, items, stats) applies at once."""
    cpu = "ppc"
    features = {"memory", "disasm"}

    def __init__(self, pid: int):
        import ctypes
        self.lock = threading.RLock()
        self.k = ctypes.WinDLL("kernel32", use_last_error=True)
        self.k.OpenProcess.restype = ctypes.c_void_p
        self.h = self.k.OpenProcess(0x0010 | 0x0020 | 0x0008 | 0x0400, False, pid)   # VM_READ | VM_WRITE | VM_OPERATION | QUERY
        if not self.h:
            raise Unavailable(f"can't open the Dolphin process {pid} (error {ctypes.get_last_error()})")
        self.pid, self.mem1, self.mem2 = pid, None, None

    def _raw(self, addr: int, n: int) -> bytes:
        import ctypes
        buf, got = ctypes.create_string_buffer(n), ctypes.c_size_t()
        if not self.k.ReadProcessMemory(ctypes.c_void_p(self.h), ctypes.c_void_p(addr), buf, n, ctypes.byref(got)) or got.value != n:
            raise Unavailable(f"Dolphin memory read failed at host {addr:#x}")
        return buf.raw

    def _find(self):
        """MEM1 = the 32 MiB MEM_MAPPED view that starts with the game id; MEM2 (Wii) = the next 64 MiB mapped view."""
        import ctypes, ctypes.wintypes as w

        class MBI(ctypes.Structure):
            _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p), ("AllocationProtect", w.DWORD),
                        ("PartitionId", w.WORD), ("RegionSize", ctypes.c_size_t), ("State", w.DWORD), ("Protect", w.DWORD), ("Type", w.DWORD)]
        mbi, addr, views = MBI(), 0, []
        while addr < 0x7FFFFFFF0000 and self.k.VirtualQueryEx(ctypes.c_void_p(self.h), ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
            if mbi.Type == 0x40000 and mbi.State == 0x1000 and mbi.RegionSize in (0x2000000, 0x4000000):   # MEM_MAPPED, MEM_COMMIT
                views.append((mbi.BaseAddress, mbi.RegionSize))
            addr = (mbi.BaseAddress or 0) + mbi.RegionSize
        for base, size in views:
            if size == 0x2000000:
                try:
                    gid = self._raw(base, 6)
                except Unavailable:
                    continue
                if gid[:4].isalnum() and gid[:1].isalpha():
                    self.mem1 = base
                    self.mem2 = next((b for b, sz in views if sz == 0x4000000 and b > base), None)
                    return
        raise Unavailable("the game's RAM isn't mapped yet (still booting?): try again in a moment")

    def _host(self, address: int, length: int) -> int:
        if self.mem1 is None:
            self._find()
        a = address & 0xFFFFFFFF
        if 0x80000000 <= a < 0x82000000 or 0xC0000000 <= a < 0xC2000000 or a < 0x2000000:
            off, base, size = a & 0x1FFFFFF, self.mem1, 0x2000000
        elif (0x90000000 <= a < 0x94000000 or 0xD0000000 <= a < 0xD4000000) and self.mem2:
            off, base, size = a & 0x3FFFFFF, self.mem2, 0x4000000
        else:
            raise Unavailable(f"{address:#x} is outside GameCube/Wii RAM")
        if off + length > size:
            raise Unavailable(f"{address:#x}+{length} runs past the end of RAM")
        return base + off

    def read(self, address, length):
        with self.lock:
            return self._raw(self._host(address, length), length)

    def write(self, address, data: bytes):
        with self.lock:
            import ctypes
            host, n = self._host(address, len(data)), ctypes.c_size_t()
            if not self.k.WriteProcessMemory(ctypes.c_void_p(self.h), ctypes.c_void_p(host), data, len(data), ctypes.byref(n)) or n.value != len(data):
                raise Unavailable(f"Dolphin memory write failed at {address:#x}")
            return {"written": len(data), "via": "process memory"}

    def paused(self):
        import contextlib
        return contextlib.nullcontext()                      # nothing to halt: reads/writes don't stop the game

    def halt(self):
        raise Unavailable("on this PC Dolphin runs at full speed without the CPU debugger; for halts/breakpoints/stepping "
                          "launch the game with debug=true (Spark)")

    resume = step = set_breakpoint = remove_breakpoint = halt

    def close(self):
        with self.lock:
            if self.h:
                self.k.CloseHandle(__import__("ctypes").c_void_p(self.h))
                self.h = None


class XeniaProcMem(Debugger):
    """Windows Xenia (Xbox 360): guest memory read/written in the Xenia process (gbox.xenia.XeniaAdapter maps a guest
    virtual address A to host virtual_membase + A, +0x1000 for A >= 0xE0000000). Guest physical addresses
    (< 0x20000000) are reached through their 0xA0000000 alias (Xenia maps physical memory there too).
    Big-endian PowerPC data. No halts/breakpoints: the JIT runs at full speed; code patches reach already-compiled
    blocks only when Xenia recompiles them, data (ammo, items, health) applies at once."""
    cpu = "ppc"
    features = {"memory", "disasm"}

    def __init__(self, adapter):
        self.ad = adapter

    @staticmethod
    def guest(address: int) -> int:
        a = address & 0xFFFFFFFF
        return 0xA0000000 | a if a < 0x20000000 else a

    def read(self, address, length):
        try:
            return self.ad.read_memory(self.guest(address), length)
        except (ValueError, RuntimeError) as e:
            raise Unavailable(str(e))

    def write(self, address, data: bytes):
        try:
            self.ad.write_memory(self.guest(address), bytes(data))
        except (ValueError, RuntimeError) as e:
            raise Unavailable(str(e))
        return {"written": len(data), "via": "process memory"}

    def paused(self):
        import contextlib
        return contextlib.nullcontext()

    def halt(self):
        raise Unavailable("Xenia runs without a CPU debugger here: memory, memory_search and disassembly only")

    resume = step = set_breakpoint = remove_breakpoint = halt


class GdbDebugger(Debugger):
    """GDB Remote Serial Protocol client. The stub halts the CPU while we hold it; reads while running
    briefly halt and resume (a few ms), so it is safe to poll during play."""
    features = {"regs", "disasm", "memory", "halt", "step", "break", "watch"}
    Z_KIND = {"exec": 0, "hw": 1, "write": 2, "read": 3, "access": 4}

    def __init__(self, host: str, port: int, cpu: str, connect_timeout: float = 30):
        self.addr, self.cpu, self.lock = (host, port), cpu, threading.RLock()
        self.sock, self.running, self.last_stop, self.breakpoints = None, True, None, {}
        self.layout, self.extra = LAYOUTS.get(cpu, ([], []))
        end = time.time() + connect_timeout
        while True:
            try:
                self.sock = socket.create_connection(self.addr, timeout=5)
                break
            except OSError:
                if time.time() > end:
                    raise Unavailable(f"debug stub not reachable on {host}:{port}")
                time.sleep(0.5)
        self.sock.settimeout(5)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)   # tiny packets + acks: Nagle cost ~90 ms each
        self.buf = b""
        sup = self._cmd("qSupported:swbreak+;hwbreak+;xmlRegisters=i386")
        self.supported = sup
        if "qXfer:features:read+" in sup:
            try:
                self._load_target_xml()
            except Exception:
                pass
        self.last_stop = self._cmd("?")                       # stubs halt on attach
        self.running = False
        self.resume()                                         # attaching must not freeze the game

    # --- packet layer ---
    def _send(self, body: str):
        data = body.encode("latin-1")
        self.sock.sendall(b"$" + data + b"#" + f"{sum(data) & 0xFF:02x}".encode())

    def _recv_packet(self, timeout: float | None = 5) -> str | None:
        self.sock.settimeout(timeout)
        while True:
            i = self.buf.find(b"$")
            j = self.buf.find(b"#", i + 1) if i >= 0 else -1
            if i >= 0 and j >= 0 and len(self.buf) >= j + 3:
                body = self.buf[i + 1:j]
                self.buf = self.buf[j + 3:]
                self.sock.sendall(b"+")
                return self._unrle(body.decode("latin-1"))
            try:
                if hasattr(socket, "TCP_QUICKACK"):                # ack at once, or the stub's Nagle waits ~40 ms per reply
                    self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_QUICKACK, 1)
                chunk = self.sock.recv(65536)
            except (TimeoutError, socket.timeout, BlockingIOError):
                return None
            if not chunk:
                raise Unavailable("debug stub closed the connection (emulator exited?)")
            self.buf += chunk

    @staticmethod
    def _unrle(s: str) -> str:
        if "*" not in s:
            return s
        out, i = [], 0
        while i < len(s):
            if s[i] == "*" and out:
                out.append(out[-1] * (ord(s[i + 1]) - 29))
                i += 2
            else:
                out.append(s[i])
                i += 1
        return "".join(out)

    def _drain(self):
        """Stubs may repeat stop replies / send empty packets after an interrupt (Dolphin does): discard them."""
        while self._recv_packet(0.05) is not None:
            pass

    def _cmd(self, body: str, timeout: float = 5) -> str:
        with self.lock:
            self._send(body)
            while True:
                r = self._recv_packet(timeout)
                if r is None:
                    raise Unavailable(f"debug stub did not answer {body[:12]}")
                if body not in ("?", "s", "c") and (r == "" and body[0] not in "Zzq" or r[:1] in "ST" and len(r) >= 3 and
                                                     all(ch in "0123456789abcdefABCDEF:;" for ch in r[1:])):
                    continue                                  # stray stop/empty packet, not the answer to this command
                return r

    # --- execution control ---
    def poll_stop(self) -> str | None:
        """Non-blocking: did the target stop by itself (breakpoint/watchpoint hit)?"""
        with self.lock:
            if not self.running:
                return None
            r = self._recv_packet(0.01)
            if r and r[:1] in "ST":
                self.running, self.last_stop = False, r
            return r

    def halt(self):
        with self.lock:
            if self.running:
                self.sock.sendall(b"\x03")
                for _ in range(20):
                    r = self._recv_packet(0.5)
                    if r and r[:1] in "ST":
                        self.last_stop = r
                        break
                self._drain()
                self.running = False
            return self.info()

    def resume(self):
        with self.lock:
            if not self.running:
                self._send("c")
                self.running = True
            return self.info()

    def step(self):
        with self.lock:
            self.halt()
            self._send("s")
            r = self._recv_packet(5)
            self.last_stop = r
            self._drain()
            return self.info()

    class _Paused:
        def __init__(self, d):
            self.d, self.was = d, False

        def __enter__(self):
            self.d.lock.acquire()
            self.was = self.d.running
            if self.was:
                self.d.halt()

        def __exit__(self, *exc):
            if self.was:
                self.d.resume()
            self.d.lock.release()

    def paused(self):
        return self._Paused(self)

    # --- state ---
    def _load_target_xml(self):
        def fetch(name):
            data, off = "", 0
            while True:
                r = self._cmd(f"qXfer:features:read:{name}:{off:x},800")
                data += r[1:]
                off += len(r) - 1
                if r[:1] == "l":
                    return data
        root = ET.fromstring(fetch("target.xml"))
        arch = next((el.text or "" for el in root.iter() if el.tag.endswith("architecture")), "").lower()
        for key, cpu in (("m68k", "m68k"), ("68", "m68k"), ("i386", "x86_32"), ("x86", "x86_32"), ("arm", "arm"),
                         ("powerpc", "ppc"), ("mips", "mips_le"), ("sh", "sh2"), ("z80", "z80")):
            if key in arch:
                self.cpu = cpu                                # MAME machines: the stub says which CPU this is
                break
        regs = []
        for el in root.iter():
            if el.tag.endswith("include"):
                for r in ET.fromstring(fetch(el.get("href"))).iter():
                    if r.tag.endswith("reg"):
                        regs.append(r)
            elif el.tag.endswith("reg"):
                regs.append(el)
        self.layout = [(r.get("name"), int(r.get("bitsize")) // 8) for r in regs]
        self.extra = []

    def regs(self) -> dict:
        with self.paused():
            g = self._cmd("g")
            out, pos = {}, 0
            order = ">" if self.cpu in BIG_ENDIAN else "<"
            for name, size in self.layout:
                h = g[pos:pos + size * 2]
                pos += size * 2
                if len(h) < size * 2 or "x" in h:
                    continue
                out[name] = int.from_bytes(bytes.fromhex(h), "big" if order == ">" else "little")
            for regnum, name, size in self.extra:
                h = self._cmd(f"p{regnum:x}")
                if h and not (len(h) == 3 and h[0] == "E") and "x" not in h:
                    out[name] = int.from_bytes(bytes.fromhex(h[:size * 2]), "big" if order == ">" else "little")
            if "pc" not in out:
                m = __import__("re").search(r"([0-9a-f]+):([0-9a-f]+);", self.last_stop or "")
                if m:                                         # some stubs only report pc in the stop packet
                    out["pc"] = int.from_bytes(bytes.fromhex(m.group(2)), "big" if order == ">" else "little")
            return out

    def read(self, address, length):
        out = bytearray()
        with self.paused():
            for off in range(0, length, 0x800):
                n = min(0x800, length - off)
                r = self._cmd(f"m{address + off:x},{n:x}")
                if (len(r) == 3 and r[0] == "E") or len(r) != 2 * n:      # "Exx" = error (data may start with E too)
                    raise Unavailable(f"stub refused read at {address + off:#x}: {r}")
                out += bytes.fromhex(r)
        return bytes(out)

    def write(self, address, data: bytes):
        with self.paused():
            r = self._cmd(f"M{address:x},{len(data):x}:{data.hex()}")
            if r != "OK":
                raise Unavailable(f"stub refused write at {address:#x}: {r}")
        return {"written": len(data), "via": "gdb"}

    def set_breakpoint(self, address, kind="exec", length=4):
        with self.paused():
            r = self._cmd(f"Z{self.Z_KIND[kind]},{address:x},{length:x}")
        if r != "OK":
            raise Unavailable(f"stub refused {kind} breakpoint at {address:#x}: {r or 'unsupported'}")
        self.breakpoints[f"{kind}:{address:x}"] = {"address": address, "kind": kind, "length": length}
        return self.info()

    def remove_breakpoint(self, address, kind="exec", length=4):
        with self.paused():
            self._cmd(f"z{self.Z_KIND[kind]},{address:x},{length:x}")
        self.breakpoints.pop(f"{kind}:{address:x}", None)
        return self.info()

    def info(self):
        self.poll_stop()
        return {"cpu": self.cpu, "features": sorted(self.features), "halted": not self.running, "stop": self.last_stop,
                "breakpoints": list(self.breakpoints.values())}

    def close(self):
        try:
            for b in list(self.breakpoints.values()):
                self.remove_breakpoint(b["address"], b["kind"], b["length"])
            self.resume()
            self._send("D")
            self.sock.close()
        except Exception:
            pass


# Video memory regions per platform: (label, address, size, view hint). Hints: tiles format for the tile viewer,
# or "fb:<fmt>:<width>" for a linear framebuffer. Only regions in the CPU's address space are listed.
VRAM = {
    "gba": [("VRAM (BG+OBJ tiles)", 0x06000000, 0x18000, "tiles:gba4"), ("Palette RAM", 0x05000000, 0x400, "pal:bgr555"),
            ("OAM", 0x07000000, 0x400, "raw")],
    "nds": [("VRAM bank A (LCDC)", 0x06800000, 0x20000, "fb:bgr555:256")],
    "psp": [("VRAM framebuffer", 0x04000000, 512 * 272 * 4, "fb:rgba8888:512"), ("VRAM (all)", 0x04000000, 0x200000, "raw")],
    "dreamcast": [("VRAM (64-bit)", 0xA5000000, 0x800000, "fb:rgb565:640")],
    "naomi": [("VRAM (64-bit)", 0xA5000000, 0x800000, "fb:rgb565:640")],
    "gamecube": [("XFB (main RAM, YUV)", None, 640 * 480 * 2, "xfb")],
    "wii": [("XFB (main RAM, YUV)", None, 640 * 480 * 2, "xfb")],
    "n64": [("RDRAM framebuffer (VI origin)", None, 320 * 240 * 2, "fb:rgba5551:320")],
}


def _selftest():
    # x86: mov eax, 1 ; ret  -- every table entry must build a working decoder
    assert disassemble("x86_32", bytes.fromhex("b801000000c3"), 0x1000)[0]["mnemonic"] == "mov"
    assert disassemble("ppc", bytes.fromhex("38600001"), 0x80000000)[0]["mnemonic"] == "li"
    assert disassemble("sh4", bytes.fromhex("0900"), 0x8C010000)[0]["mnemonic"] == "nop"
    assert disassemble("6502", bytes.fromhex("a9 01".replace(" ", "")), 0x8000)[0]["mnemonic"] == "lda"
    assert GdbDebugger._unrle("0* ") == "0000"
    for cpu in ("sh2", "mips_le", "mips_be", "arm", "thumb", "m68k", "65c02", "65816", "x86_16"):
        _cs(cpu)
    print("debug selftest ok")


if __name__ == "__main__":
    _selftest()
