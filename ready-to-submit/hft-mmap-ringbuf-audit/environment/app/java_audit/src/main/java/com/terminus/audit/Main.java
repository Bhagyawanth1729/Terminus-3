package com.terminus.audit;

public class Main {
    public static void main(String[] args) {
        String intermediatePath = "/tmp/intermediate_batch.json";
        String outputPath = "/app/output.json";

        if (args.length > 0) {
            intermediatePath = args[0];
        }
        if (args.length > 1) {
            outputPath = args[1];
        }

        try {
            AuditService.generateAuditReport(intermediatePath, outputPath);
        } catch (Exception e) {
            System.err.println("Error generating audit report: " + e.getMessage());
            e.printStackTrace();
            System.exit(1);
        }
    }
}
