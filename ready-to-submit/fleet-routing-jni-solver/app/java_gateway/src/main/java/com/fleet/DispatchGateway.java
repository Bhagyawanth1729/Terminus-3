package com.fleet;

import java.io.File;
import java.io.FileReader;
import java.io.FileWriter;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.Locale;

public class DispatchGateway {

    static {
        System.loadLibrary("solver_rust");
    }

    public static native long solveVrpNative(ByteBuffer buffer, int capacity);
    public static native int releaseVrpPlanNative(long handle);
    public static native int getActivePlanCountNative();
    public static native long getPlanDepartureTimeNative(long handle);

    public static void main(String[] args) {
        try {
            System.out.println("Starting Fleet Dispatch Gateway...");
            String inputPath = args.length > 0 ? args[0] : "/app/data/fleet_orders.json";
            String outputPath = args.length > 1 ? args[1] : "/app/output.json";

            // Parse dummy orders or execute benchmark batch
            long timestamp = 1700000000L;
            long weight = 4500L;
            double lat = 48.8566;
            double lon = 2.3522;
            int orderId = 101;

            ByteBuffer buffer = ByteBuffer.allocateDirect(36);

            // BUG 1: Missing buffer.order(ByteOrder.LITTLE_ENDIAN);
            // Default Java ByteBuffer order is BIG_ENDIAN, but Rust solver expects LITTLE_ENDIAN.
            // UNCOMMENT TO FIX:
            // buffer.order(ByteOrder.LITTLE_ENDIAN);

            buffer.putInt(orderId);
            buffer.putLong(timestamp);
            buffer.putLong(weight);
            buffer.putLong(Double.doubleToLongBits(lat));
            buffer.putLong(Double.doubleToLongBits(lon));

            long planHandle = solveVrpNative(buffer, 36);

            long solvedDepartureTime = getPlanDepartureTimeNative(planHandle);
            int activeHandles = getActivePlanCountNative();

            System.out.println("Native VRP Plan Handle: " + planHandle);
            System.out.println("Solved Departure Time: " + solvedDepartureTime);
            System.out.println("Active Native Plan Handles: " + activeHandles);

            // BUG 3: Locale formatting - String.format without Locale.US produces comma decimals in some JVM locales
            // UNCOMMENT TO FIX:
            // String latStr = String.format(Locale.US, "%.6f", lat);
            // String lonStr = String.format(Locale.US, "%.6f", lon);
            String latStr = String.format("%.6f", lat);
            String lonStr = String.format("%.6f", lon);

            String jsonOutput = String.format(
                "{\n" +
                "  \"status\": \"DISPATCHED\",\n" +
                "  \"order_id\": %d,\n" +
                "  \"departure_time\": %d,\n" +
                "  \"weight\": %d,\n" +
                "  \"latitude\": \"%s\",\n" +
                "  \"longitude\": \"%s\",\n" +
                "  \"plan_handle\": %d,\n" +
                "  \"active_native_handles\": %d\n" +
                "}\n",
                orderId, solvedDepartureTime, weight, latStr, lonStr, planHandle, activeHandles
            );

            // BUG 2: Missing native handle release!
            // Solver plan handle is never released via releaseVrpPlanNative(planHandle).
            // UNCOMMENT TO FIX:
            // releaseVrpPlanNative(planHandle);

            File outFile = new File(outputPath);
            if (outFile.getParentFile() != null) {
                outFile.getParentFile().mkdirs();
            }
            try (FileWriter writer = new FileWriter(outFile)) {
                writer.write(jsonOutput);
            }

            System.out.println("Dispatch completed. Results written to " + outputPath);

        } catch (Exception e) {
            e.printStackTrace();
            System.exit(1);
        }
    }

    public static void runBatchSolverTest(int count) {
        for (int i = 0; i < count; i++) {
            ByteBuffer buffer = ByteBuffer.allocateDirect(36);
            // BUG 1: Missing buffer.order(ByteOrder.LITTLE_ENDIAN);
            buffer.putInt(200 + i);
            buffer.putLong(1700000000L + i * 100);
            buffer.putLong(5000L);
            buffer.putLong(Double.doubleToLongBits(48.8566));
            buffer.putLong(Double.doubleToLongBits(2.3522));

            long handle = solveVrpNative(buffer, 36);
            
            // BUG 2: missing releaseVrpPlanNative(handle);
        }
    }
}
