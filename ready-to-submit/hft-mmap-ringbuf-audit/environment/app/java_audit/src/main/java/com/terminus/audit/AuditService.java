package com.terminus.audit;

import java.io.File;
import java.io.FileWriter;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class AuditService {

    public static void generateAuditReport(String intermediateJsonPath, String outputJsonPath) throws IOException {
        String content = new String(Files.readAllBytes(Paths.get(intermediateJsonPath)));

        long totalTrades = parseLong(content, "TotalTrades");
        long totalVolumeScaled = parseLong(content, "TotalVolumeScaled");
        double averagePrice = parseDouble(content, "AvgPrice");

        // DEFECT: String.format without Locale.US formats floating point numbers with system locale decimal separators
        // (e.g. "150,2500" under German/European locale settings), producing invalid JSON numeric representations.
        String jsonOutput = String.format(
            "{\n" +
            "  \"status\": \"SUCCESS\",\n" +
            "  \"total_trades\": %d,\n" +
            "  \"total_volume_scaled\": %d,\n" +
            "  \"average_price\": \"%.4f\"\n" +
            "}\n",
            totalTrades, totalVolumeScaled, averagePrice
        );

        File outputFile = new File(outputJsonPath);
        if (outputFile.getParentFile() != null) {
            outputFile.getParentFile().mkdirs();
        }

        try (FileWriter writer = new FileWriter(outputFile)) {
            writer.write(jsonOutput);
        }

        System.out.println("Audit Report generated successfully at: " + outputJsonPath);
    }

    private static long parseLong(String json, String key) {
        Pattern pattern = Pattern.compile("\"" + key + "\"\\s*:\\s*(-?\\d+)");
        Matcher matcher = pattern.matcher(json);
        if (matcher.find()) {
            return Long.parseLong(matcher.group(1));
        }
        return 0;
    }

    private static double parseDouble(String json, String key) {
        Pattern pattern = Pattern.compile("\"" + key + "\"\\s*:\\s*(-?\\d+(?:\\.\\d+)?)");
        Matcher matcher = pattern.matcher(json);
        if (matcher.find()) {
            return Double.parseDouble(matcher.group(1));
        }
        return 0.0;
    }
}
