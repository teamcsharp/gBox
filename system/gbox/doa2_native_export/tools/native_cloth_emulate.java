// Read-only native SH4 cloth initializer execution in Ghidra's p-code emulator.
import ghidra.app.script.GhidraScript;
import ghidra.app.emulator.EmulatorHelper;
import ghidra.program.model.address.Address;
import ghidra.pcode.emulate.BreakCallBack;
import ghidra.pcode.pcoderaw.PcodeOpRaw;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.HashMap;
import java.util.Map;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.Arrays;

public class native_cloth_emulate extends GhidraScript {
    long source=0x8c600000L, state=0x8c500000L, cells=0x8c700000L, sentinel=0x8c000040L;
    Address addr(long value) {return currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(value);}
    int u32(byte[] data,int offset) {return ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN).getInt(offset);}
    void put(byte[] data,int offset,int value) {ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN).putInt(offset,value);}
    int lastFR=0;
    boolean warnedNaN=false;
    float regFloat(EmulatorHelper emu,String name) {return Float.intBitsToFloat(emu.readRegister(name).intValue());}
    void floatReg(EmulatorHelper emu,String name,float value) {emu.writeRegister(name,Float.floatToRawIntBits(value)&0xffffffffL);}
    void syncFloatingControl(EmulatorHelper emu) {
        // Ghidra SuperH4.sinc explicitly omits floating register bank switching;
        // its FSCHG also toggles FPSCR without updating the separate SZ varnode.
        // Supply architectural banking/control bookkeeping, never game physics.
        long fpscr=emu.readRegister("FPSCR").longValue();
        int fr=(int)((fpscr>>>21)&1);
        if(fr!=lastFR) {
            for(int i=0;i<16;i++) {
                long a=emu.readRegister("fr"+i).longValue(),b=emu.readRegister("xf"+i).longValue();
                emu.writeRegister("fr"+i,b);emu.writeRegister("xf"+i,a);
            }
            lastFR=fr;
        }
        emu.writeRegister("FPSCR_PR",(fpscr>>>19)&1);
        emu.writeRegister("FPSCR_SZ",(fpscr>>>20)&1);
        emu.writeRegister("FPSCR_FR",fr);
    }
    long execute(EmulatorHelper emu,long pc) throws Exception {
        return execute(emu,pc,sentinel);
    }
    long execute(EmulatorHelper emu,long pc,long stop) throws Exception {
        emu.writeRegister("r15",0x8cfe0000L);emu.writeRegister("PR",sentinel);
        emu.writeRegister("pc",pc);long count=0;
        while(emu.getExecutionAddress().getOffset()!=stop) {
            if(++count>2000000)throw new Exception("Native routine instruction budget exceeded");
            syncFloatingControl(emu);
            long previous=emu.getExecutionAddress().getOffset();
            byte[] instruction=emu.readMemory(addr(previous),2);
            int opcode=(instruction[0]&255)|((instruction[1]&255)<<8);
            long transferAddress=0;String transferBank=null;int transferRegister=0;byte[] transferData=null;
            if((opcode&0xf000)==0xf000 && emu.readRegister("FPSCR_SZ").intValue()!=0) {
                // Flycast's authoritative SH4 interpreter keeps DR/XD raw words
                // in logical fr[n],fr[n+1] order. Ghidra's little-endian DR
                // register definition reverses the pair for numeric doubles,
                // so supply the architectural FMOV transport order explicitly.
                int kind=opcode&15,n=(opcode>>>8)&15,m=(opcode>>>4)&15;
                if(kind==6||kind==8||kind==9) {
                    transferAddress=emu.readRegister("r"+m).longValue();
                    if(kind==6)transferAddress+=emu.readRegister("r0").longValue();
                    transferData=emu.readMemory(addr(transferAddress&0xffffffffL),8);
                    transferBank=(n&1)==0?"fr":"xf";transferRegister=n&14;
                } else if(kind==7||kind==10||kind==11||kind==12) {
                    String sourceBank=(m&1)==0?"fr":"xf";int sourceRegister=m&14;
                    transferData=new byte[8];
                    put(transferData,0,emu.readRegister(sourceBank+sourceRegister).intValue());
                    put(transferData,4,emu.readRegister(sourceBank+(sourceRegister+1)).intValue());
                    if(kind==12) {transferBank=(n&1)==0?"fr":"xf";transferRegister=n&14;}
                    else {
                        transferAddress=emu.readRegister("r"+n).longValue();
                        if(kind==7)transferAddress+=emu.readRegister("r0").longValue();
                        if(kind==11)transferAddress-=8;
                    }
                }
            }
            float[] vector=null;int vectorBase=0;
            if((opcode&0xf0ff)==0xf0ed || (opcode&0xf3ff)==0xf1fd) {
                // Ghidra's little-endian frN pairs have reversed offsets, whereas
                // FIPR/FTRV Sleigh assumes monotonically increasing FR offsets.
                // Replay only these two architectural vector operations by name.
                vectorBase=((opcode>>>10)&3)*4;vector=new float[4];
                for(int i=0;i<4;i++)vector[i]=regFloat(emu,"fr"+(vectorBase+i));
                if((opcode&0xf0ff)==0xf0ed) {
                    int other=((opcode>>>8)&3)*4;float total=0;
                    for(int i=0;i<4;i++)total+=(float)(vector[i]*regFloat(emu,"fr"+(other+i)));
                    vector[3]=total;
                } else {
                    float[] transformed=new float[4];
                    for(int row=0;row<4;row++)for(int col=0;col<4;col++)
                        transformed[row]+=(float)(regFloat(emu,"xf"+(col*4+row))*vector[col]);
                    vector=transformed;
                }
            }
            if(!emu.step(monitor))throw new Exception("SH4 emulation failure at "+emu.getExecutionAddress()+": "+emu.getLastError());
            if(transferData!=null) {
                if(transferBank!=null) {
                    emu.writeRegister(transferBank+transferRegister,u32(transferData,0)&0xffffffffL);
                    emu.writeRegister(transferBank+(transferRegister+1),u32(transferData,4)&0xffffffffL);
                } else emu.writeMemory(addr(transferAddress&0xffffffffL),transferData);
            }
            if(vector!=null)for(int i=0;i<4;i++)floatReg(emu,"fr"+(vectorBase+i),vector[i]);
        }
        return count;
    }
    public void run() throws Exception {
        String[] args=getScriptArgs();
        Path inputs=Path.of(args[0].equals("--manifest")?args[1]:args[0]).toAbsolutePath().getParent();
        byte[] owned=Files.readAllBytes(inputs.resolve("1ST_READ.BIN"));
        String hash=HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(owned));
        if(!hash.equals("27a014aeda35983df749f7d575bbddbea3f1ffd1f7776194ef503108c20c97e1"))
            throw new Exception("Native cloth cache executable is not the verified DOA2 LE JP build");
        byte[] loaded=new byte[owned.length];
        currentProgram.getMemory().getBytes(addr(0x8c010000L),loaded);
        if(!Arrays.equals(owned,loaded))throw new Exception("Ghidra program bytes differ from owned cache executable");
        println("NATIVE EXECUTABLE VERIFIED SHA256="+hash);
        if(args[0].equals("--manifest")) {
            int ok=0,failed=0;Map<String,byte[]> workingChr=new HashMap<>();
            for(String line:Files.readAllLines(Path.of(args[1]))) {
                if(line.isBlank())continue;
                String[] fields=line.split("\\t");
                try {
                    byte[] result=runOne(fields,workingChr.get(fields[0]));
                    if(result!=null)workingChr.put(fields[0],result);
                    ok++;
                }
                catch(Exception error) {failed++;println("NATIVE GRID FAILED "+line+" : "+error);}
            }
            println("NATIVE GRID BATCH completed="+ok+" failed="+failed);
        } else runOne(args,null);
    }
    byte[] runOne(String[] args,byte[] initialChr) throws Exception {
        lastFR=0;warnedNaN=false;
        byte[] generatedChr=null;
        byte[] data=Files.readAllBytes(Path.of(args[0]));
        int descriptor=Integer.decode(args[1]);
        for(int offset=0xe0;offset<0xfc;offset+=4) {
            int value=u32(data,descriptor+offset);
            if(value!=0)put(data,descriptor+offset,(int)source+value);
        }
        EmulatorHelper emu=new EmulatorHelper(currentProgram);
        try {
            // Execute the Sleigh FSCA semantics; only implement its two explicit
            // mathematical userops. The game routine and all state writes run natively.
            for(String name:new String[]{"sin","cos"}) {
                final boolean sine=name.equals("sin");
                emu.registerCallOtherCallback(name,new BreakCallBack() {
                    public boolean pcodeCallback(PcodeOpRaw op) {
                        float angle=Float.intBitsToFloat((int)emulate.getMemoryState().getValue(op.getInput(1)));
                        float result=(float)(sine?Math.sin(angle):Math.cos(angle));
                        emulate.getMemoryState().setValue(op.getOutput(),Float.floatToRawIntBits(result)&0xffffffffL);
                        return true;
                    }
                });
            }
            emu.writeMemory(addr(source),data);
            emu.writeMemory(addr(state),new byte[8192]);
            emu.writeMemory(addr(cells),new byte[32768]);
            emu.writeMemory(addr(0x8cfc0000L),new byte[0x30000]);
            for(int i=0;i<16;i++) {
                emu.writeRegister("r"+i,0);emu.writeRegister("fr"+i,0);emu.writeRegister("xf"+i,0);
            }
            emu.writeRegister("FPSCR_SZ",0);emu.writeRegister("FPSCR_PR",0);emu.writeRegister("FPSCR_FR",0);
            emu.writeRegister("r4",state);emu.writeRegister("r5",source+descriptor);emu.writeRegister("r6",cells);
            emu.writeRegister("FPSCR",0);
            long count=execute(emu,0x8c0d63caL);
            println("NATIVE CLOTH INITIALIZED descriptor="+descriptor+" instructions="+count+" r0="+emu.readRegister("r0"));
            if(args.length>3) {
                String prefix=args[3];
                emu.writeMemory(addr(0x8c230000L),new byte[0x90000]);
                emu.writeMemory(addr(0x8c410000L),Files.readAllBytes(Path.of(prefix+".world")));
                emu.writeMemory(addr(0x8c420000L),Files.readAllBytes(Path.of(prefix+".inverse")));
                emu.writeMemory(addr(0x8c400000L),Files.readAllBytes(Path.of(prefix+".models")));
                byte[] chr=initialChr==null?Files.readAllBytes(Path.of(prefix+".CHR")):initialChr;
                Files.write(Path.of(args[2]+".input.CHR"),chr);
                emu.writeMemory(addr(0x8c800000L),chr);
                emu.writeMemoryValue(addr(0x8c2a723cL),4,0x8c410000L);
                emu.writeMemoryValue(addr(0x8c2a7240L),4,0x8c420000L);
                emu.writeMemoryValue(addr(0x8c2a7238L),4,0x8c400000L);
                Path root=Path.of(prefix+".base");
                if((data[descriptor+1]&255)==15&&!Files.exists(root))throw new Exception("Actor-root grid requires explicit base pose");
                if(Files.exists(root))emu.writeMemory(addr(0x8c2a73c8L),Files.readAllBytes(root));
                Path effect=Path.of(prefix+".effect");
                if((data[descriptor+1]&255)==15&&Files.exists(effect)) {
                    int controller=u32(Files.readAllBytes(effect),0);
                    long controllerState=0x8c510000L;
                    emu.writeMemory(addr(controllerState),new byte[8192]);
                    emu.writeRegister("r5",controllerState);emu.writeRegister("r6",source+controller);
                    execute(emu,0x8c0d9370L);
                    emu.writeRegister("r4",0);emu.writeRegister("r5",controllerState);
                    execute(emu,0x8c0d93e0L,0x8c0d9a00L); // stop before native rendering
                    byte[] actual=emu.readMemory(addr(0x8c2a73c8L),64),expected=Files.readAllBytes(root);
                    Files.write(Path.of(args[2]+".native-base"),actual);
                    float max=0;
                    for(int i=0;i<64;i+=4)max=Math.max(max,Math.abs(Float.intBitsToFloat(u32(actual,i))-Float.intBitsToFloat(u32(expected,i))));
                    if(!Float.isFinite(max)||max>0.00001f)throw new Exception("Native controller root differs from source transform: "+max);
                    println("NATIVE ACTOR ROOT controller="+controller+" maximum_error="+max);
                }
                // Rendering is suppressed after preserving original configuration;
                // no game renderer/GPU calls are invoked by this offline bake.
                emu.writeMemory(addr(state+2),new byte[]{0});
                emu.writeRegister("r4",state);
                count=execute(emu,0x8c0d664cL);
                println("NATIVE CLOTH GENERATED instructions="+count);
                generatedChr=emu.readMemory(addr(0x8c800000L),chr.length);
                Files.write(Path.of(args[2]+".CHR"),generatedChr);
            }
            Files.write(Path.of(args[2]),emu.readMemory(addr(state),8192));
            Files.write(Path.of(args[2]+".cells"),emu.readMemory(addr(cells),32768));
        } finally {emu.dispose();}
        return generatedChr;
    }
}
