// gBox headless post-script: exports functions and defined strings to JSON.
// Usage: analyzeHeadless <proj> gbox -import <bin> -postScript ExportAnalysis.java <out.json>
// @category gBox
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import ghidra.program.model.data.StringDataInstance;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

public class ExportAnalysis extends GhidraScript {
    private static String q(String s) {
        StringBuilder out = new StringBuilder("\"");
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (c == '"' || c == '\\') out.append('\\').append(c);
            else if (c < 0x20) out.append(String.format("\\u%04x", (int)c));
            else out.append(c);
        }
        return out.append('"').toString();
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
        try (java.io.Writer w = Files.newBufferedWriter(Path.of(getScriptArgs()[0]), StandardCharsets.UTF_8)) {
            w.write(sb.toString());
        }
    }
}
