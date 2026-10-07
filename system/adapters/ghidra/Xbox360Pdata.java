// gBox: seed functions in a raw Xbox 360 image (XEX basefile loaded at its base, e.g. 0x82000000) from the PE .pdata
// table (8-byte entries: u32 begin address, u32 {prolog:8, length-in-words:22, flags:2}), then let auto-analysis run.
// Args: none. Use as -preScript after a raw-binary import (-loader BinaryLoader -loader-baseAddr 0x82000000).
// @category gBox
import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.program.model.address.*;
import ghidra.program.model.mem.*;

public class Xbox360Pdata extends GhidraScript {
    private long u32(Address a) throws Exception {
        return currentProgram.getMemory().getInt(a) & 0xFFFFFFFFL;                  // big-endian program
    }
    private int le32(Address a) throws Exception {
        Memory m = currentProgram.getMemory();
        return (m.getByte(a) & 0xFF) | (m.getByte(a.add(1)) & 0xFF) << 8 | (m.getByte(a.add(2)) & 0xFF) << 16 | (m.getByte(a.add(3)) & 0xFF) << 24;
    }
    private int le16(Address a) throws Exception {
        Memory m = currentProgram.getMemory();
        return (m.getByte(a) & 0xFF) | (m.getByte(a.add(1)) & 0xFF) << 8;
    }
    @Override
    public void run() throws Exception {
        Address base = currentProgram.getMinAddress();
        int pe = le32(base.add(0x3C));
        int nsec = le16(base.add(pe + 6));
        int optSize = le16(base.add(pe + 20));
        long pdata = -1, psize = 0;
        for (int i = 0; i < nsec; i++) {
            Address s = base.add(pe + 24 + optSize + 40 * i);
            byte[] nm = new byte[8];
            currentProgram.getMemory().getBytes(s, nm);
            String name = new String(nm, "latin1").trim().replace("\0", "");
            int vsize = le32(s.add(8)), vaddr = le32(s.add(12)), flags = le32(s.add(36));
            Address start = base.add(vaddr & 0xFFFFFFFFL);
            if (name.equals(".pdata")) { pdata = vaddr & 0xFFFFFFFFL; psize = vsize & 0xFFFFFFFFL; }
            println(String.format("section %-8s %s +%x %s", name, start, vsize, (flags & 0x20000000) != 0 ? "code" : ""));
        }
        if (pdata < 0) { println("no .pdata"); return; }
        int made = 0;
        AddressSpace sp = base.getAddressSpace();
        for (long o = 0; o + 8 <= psize; o += 8) {
            Address e = base.add(pdata + o);
            long begin = u32(e), info = u32(e.add(4));
            if (begin == 0) break;
            long len = ((info >> 8) & 0x3FFFFF) * 4;
            Address f = sp.getAddress(begin);
            if (!currentProgram.getMemory().contains(f)) continue;
            new DisassembleCommand(f, null, true).applyTo(currentProgram, monitor);
            if (getFunctionAt(f) == null) {
                CreateFunctionCmd c = new CreateFunctionCmd(f);
                if (c.applyTo(currentProgram, monitor)) made++;
            }
            if (monitor.isCancelled()) break;
        }
        println("gBox Xbox360Pdata created " + made + " functions");
    }
}
