// Offline execution of the owned checksum routine; no emulator/session attachment.
import ghidra.app.script.GhidraScript;
import ghidra.app.emulator.EmulatorHelper;
import java.io.*;
import java.security.MessageDigest;
import java.util.HexFormat;
public class RE2GCSaveChecksum extends GhidraScript {
 public void run() throws Exception {
  String[] a=getScriptArgs();
  long entry=Long.parseLong(a[1],16);
  byte[] code=getBytes(toAddr(entry),80);
  String hash=HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(code));
  if(!hash.equals(a[2])) throw new IllegalArgumentException("checksum code hash differs");
  try(Writer out=new FileWriter(a[0])) {
   out.write("{\"code_sha256\":\""+hash+"\",\"entry\":\""+a[1]+"\",\"vectors\":[");
   boolean first=true;
   for(int n:new int[]{0,1,255,8188}) for(int pattern=0;pattern<3;pattern++) {
    byte[] data=new byte[n]; long expected=0;
    for(int i=0;i<n;i++){data[i]=(byte)(pattern==0?0:pattern==1?255:(i*73+19)&255);expected+=data[i]&255;}
    EmulatorHelper emu=new EmulatorHelper(currentProgram);
    try {
     emu.writeMemory(toAddr(0x81700000L),data);
     emu.writeMemory(toAddr(0x817fe000L),new byte[4096]);
     emu.writeRegister("r1",0x817ff000L); emu.writeRegister("r3",0x81700000L);emu.writeRegister("r4",n);
     String lr=currentProgram.getRegister("LR")!=null?"LR":"lr";
     emu.writeRegister(lr,0x80003100L);emu.writeRegister(emu.getPCRegister(),entry);
     int steps=0;
     while(!emu.getExecutionAddress().equals(toAddr(0x80003100L))) {
      if(++steps>100000) throw new IllegalStateException("instruction bound exceeded");
      if(!emu.step(monitor)) throw new IllegalStateException(emu.getLastError());
     }
     long actual=emu.readRegister("r3").longValue()&0xffffffffL;
     if(actual!=expected || emu.readRegister("r1").longValue()!=0x817ff000L) throw new IllegalStateException("checksum/stack mismatch");
     if(!first)out.write(",");first=false;
     out.write("{\"length\":"+n+",\"pattern\":"+pattern+",\"expected\":"+expected+",\"actual\":"+actual+",\"steps\":"+steps+"}");
    } finally {emu.dispose();}
   }
   out.write("],\"native_gameplay_verified\":false}\n");
  }
 }
}
