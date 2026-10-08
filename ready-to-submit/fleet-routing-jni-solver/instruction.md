# Fleet Routing JNI Solver Service Recovery

The multi-language vehicle routing and dispatch engine under `/app/` consists of a Java enterprise gateway (`/app/java_gateway`), a native Rust branch-and-bound VRP solver (`/app/solver_rust`), and a Python telematics feasibility validator (`/app/telemetry_python`). Under production loads, the service produces invalid vehicle route schedules, leaks native solver heap memory, and fails telematics parsing.

Your task is to repair the dispatch engine to achieve complete operational correctness:

1. **JNI Serialization & Endianness Alignment:** Ensure fleet demand weights and time-window timestamps serialized into JNI DirectByteBuffers in `/app/java_gateway/src/main/java/com/fleet/DispatchGateway.java` are correctly decoded by `/app/solver_rust/src/lib.rs`. Departure timestamps must accurately reflect scheduled dispatch windows without byte-order corruption.
2. **Native Memory Management:** Ensure all native solver plan handles (`jlong`) allocated by Rust during optimization calls are cleanly released via native cleanup methods (`releaseVrpPlanNative`) after Java completes route dispatch. Active native handle counts must remain stable across rapid re-routing operations without leaking native heap memory.
3. **Locale-Independent Telemetry Formatting:** Ensure route GeoJSON coordinates emitted by the Java gateway format floating-point values using standard US locale formatting (`.` decimal separator) so `/app/telemetry_python/validate_telemetry.py` can parse and validate telemetry streams across all execution environments.

All components can be compiled and executed using `/app/build_all.sh` and `/app/run_solution.sh`. The final dispatch output must be written to `/app/output.json`.
