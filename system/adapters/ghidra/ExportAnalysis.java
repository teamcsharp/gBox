// G-Box headless post-script: exports functions and defined strings to JSON.
// Usage: analyzeHeadless <proj> gbox -import <bin> -postScript ExportAnalysis.java <out.json>
// Status: written against the Ghidra 11.x API; not yet run (Ghidra not installed on the build host).
// @category G-Box
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import ghidra.program.model.data.StringDataInstance;
import java.io.FileWriter;

public class ExportAnalysis extends GhidraScript {
    private static String q(String s) {
        return "\"" + s.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n").replace("\r", "\\r") + "\"";
    }

    @Override
    public void run() throws Exception {
        StringBuilder sb = new StringBuilder("{\"program\":{");
        sb.append("\"name\":").append(q(currentProgram.getName()))
          .append(",\"language\":").append(q(currentProgram.getLanguageID().toString()))
          .append(",\"image_base\":").append(q(currentProgram.getImageBase().toString()))
          .append(",\"sha256\":").append(q(String.valueOf(currentProgram.getExecutableSHA256())))
          .append("},\"functions\":[");
        boolean first = true;
        for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
            if (!first) sb.append(",");
            first = false;
            sb.append("{\"name\":").append(q(f.getName()))
              .append(",\"entry\":").append(q(f.getEntryPoint().toString()))
              .append(",\"size\":").append(f.getBody().getNumAddresses())
              .append(",\"source\":").append(q(f.getSymbol().getSource().toString())).append("}");
        }
        sb.append("],\"strings\":[");
        first = true;
        for (Data d : currentProgram.getListing().getDefinedData(true)) {
            if (!d.hasStringValue()) continue;
            if (!first) sb.append(",");
            first = false;
            sb.append("{\"addr\":").append(q(d.getAddress().toString()))
              .append(",\"value\":").append(q(StringDataInstance.getStringDataInstance(d).getStringValue() + "")).append("}");
        }
        sb.append("]}");
        try (FileWriter w = new FileWriter(getScriptArgs()[0])) { w.write(sb.toString()); }
    }
}
