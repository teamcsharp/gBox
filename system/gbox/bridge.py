"""Static/runtime correlation (plan §7, Phase 4): "what code writes this value?" end to end.

1. runtime: write-watchpoint on the address, trigger the event (press a button / wait), capture PC, LR and registers
2. static:  snapshot the code region of live RAM into an ELF, run Ghidra ExplainAddresses on it with the live
            small-data registers -> containing function, decompiled C, callers
3. validate: exec breakpoint at the function entry, trigger again, check it fires and the watched value changes
4. record:  evidence artifacts + knowledge edges (validated only if step 3 passed)

Works on any session whose emulator has a GDB stub (Dolphin, DuckStation, mGBA, MAME). Ghidra runs on a worker that
has the native decompiler (x86_64) and reads the ELF from the shared data folder.
"""
import json
import time

import httpx

from .gcdisc import ram_to_elf

# per-CPU: (Ghidra language, ELF machine, big endian, small-data registers worth pinning)
CPU = {"ppc": ("PowerPC:BE:32:default", 20, True, ["r13", "r2"]),
       "mips_le": ("MIPS:LE:32:default", 8, False, ["r28"]),
       "arm": ("ARM:LE:32:v4t", 40, False, []),
       "m68k": ("68000:BE:32:default", 4, True, [])}


class Bridge:
    def __init__(self, server: str, token: str, sid: str, log=print):
        self.api = httpx.Client(base_url=server, headers={"authorization": f"Bearer {token}", "x-gbox-actor": "ghidra-bridge"},
                                timeout=120)
        self.sid, self.log = sid, log

    def rpc(self, op, **args):
        r = self.api.post(f"/api/sessions/{self.sid}/rpc", json={"op": op, "args": args})
        r.raise_for_status()
        return r.json()

    def job(self, tool, inp, os_=None, wait=3600):
        body = {"tool": tool, "input": inp, **({"require_os": os_} if os_ else {})}
        j = self.api.post("/api/jobs", json=body).json()
        t = time.time()
        while j.get("state") in ("queued", "running") and time.time() - t < wait:
            time.sleep(3)
            j = self.api.get(f"/api/jobs/{j['id']}").json()
        return j

    def _wait_halt(self, trigger, secs=20):
        trigger()
        t = time.time()
        while time.time() - t < secs:
            if self.rpc("debug_info", regs=False).get("halted"):
                return self.rpc("debug_regs")
            time.sleep(0.25)
        return None

    def trace_writer(self, address: int, length: int, trigger, game_id: str, label: str,
                     code_range=(0x80000000, 0x80600000), analysis_dir_local=None, analysis_dir_worker=None,
                     ghidra_os="windows", read_value=None) -> dict:
        info = self.rpc("debug_info", regs=False)
        cpu = info["cpu"]
        lang, machine, be, sda = CPU[cpu]
        # 1. runtime
        self.rpc("debug_break", address=address, kind="write", length=length)
        regs = self._wait_halt(trigger)
        self.rpc("debug_unbreak", address=address, kind="write", length=length)
        if not regs:
            self.rpc("debug_resume")
            return {"ok": False, "reason": "watchpoint never fired (trigger did not write the value)"}
        pc, lr = regs["pc"], regs.get("lr")
        self.log(f"write caught at pc {pc:#x} (lr {lr:#x})" if lr else f"write caught at pc {pc:#x}")
        # 2. static: live-RAM ELF -> Ghidra
        lo, hi = code_range
        ram = bytearray()
        for a in range(lo, hi, 0x100000):
            ram += bytes.fromhex(self.rpc("read_memory", address=a, length=min(0x100000, hi - a)))
        self.rpc("debug_resume")
        name = f"ram_{game_id}_{lo:x}.elf"
        (analysis_dir_local / name).write_bytes(ram_to_elf(bytes(ram), lo, lo, machine, be))
        out = f"{analysis_dir_worker}/explain_{int(time.time())}.json"
        args = [out] + [f"{r}:{regs[r]:x}" for r in sda if r in regs] + [f"{pc:x}"] + ([f"{lr - 4:x}"] if lr else [])
        j = self.job("ghidra_script", {"binary_path": f"{analysis_dir_worker}/{name}", "script": "ExplainAddresses.java",
                                       "args": args, "processor": lang}, ghidra_os)
        if j["state"] != "succeeded":
            return {"ok": False, "reason": f"ghidra: {j.get('error')}"}
        static = json.loads((analysis_dir_local / out.rsplit("/", 1)[1]).read_text())
        fn = static["addresses"][0]
        entry = int(fn["entry"], 16)
        # 3. validate: the function entry must be hit by the same event, with the value changing afterwards
        before = read_value() if read_value else None
        self.rpc("debug_break", address=entry, kind="exec")
        vregs = self._wait_halt(trigger)
        self.rpc("debug_unbreak", address=entry, kind="exec")
        self.rpc("debug_resume")
        time.sleep(1.0)
        after = read_value() if read_value else None
        validated = vregs is not None and vregs["pc"] == entry and (read_value is None or after != before)
        # 4. record
        def up(obj, nm):
            return self.api.post("/api/artifacts", content=json.dumps(obj).encode(), params={
                "name": nm, "media_type": "application/json", "provenance": json.dumps({"session": self.sid, "game": game_id})}).json()["sha256"]
        ev = [up({"address": address, "length": length, "pc": pc, "lr": lr, "regs": regs}, "runtime_watch.json"),
              up(static, "ghidra_explain.json"),
              up({"entry": entry, "hit": vregs is not None, "regs": vregs, "value_before": before, "value_after": after}, "validation.json")]
        edge = {"game_id": game_id, "src": label, "rel": "written_by",
                "dst": f"{fn['function']} @ {entry:#x}: {fn['decompiled'].strip().splitlines()[0][:160] if fn.get('decompiled') else ''}",
                "confidence": 0.9 if validated else 0.5, "status": "validated" if validated else "hypothesis",
                "evidence": ev, "source": "gbox.bridge"}
        e = self.api.post("/api/knowledge", json=edge).json()
        return {"ok": True, "validated": validated, "pc": pc, "function": fn.get("function"), "entry": entry,
                "callers": fn.get("callers", []), "decompiled": fn.get("decompiled"), "edge": e.get("id"), "evidence": ev}
