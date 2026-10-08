#!/bin/bash
set -euo pipefail

echo "=== Terminus 3 Oracle Solution: Fleet Routing JNI Solver Recovery ==="

JAVA_SRC="/app/java_gateway/src/main/java/com/fleet/DispatchGateway.java"

# Step 1: Fix JNI buffer byte order endianness alignment (Set ByteOrder.LITTLE_ENDIAN)
python3 -c "
path = '$JAVA_SRC'
with open(path, 'r') as f:
    content = f.read()

# Enable ByteOrder.LITTLE_ENDIAN
content = content.replace('// buffer.order(ByteOrder.LITTLE_ENDIAN);', 'buffer.order(ByteOrder.LITTLE_ENDIAN);')

# Enable Locale.US formatting
content = content.replace('String latStr = String.format(\"%.6f\", lat);', 'String latStr = String.format(Locale.US, \"%.6f\", lat);')
content = content.replace('String lonStr = String.format(\"%.6f\", lon);', 'String lonStr = String.format(Locale.US, \"%.6f\", lon);')

# Enable releaseVrpPlanNative cleanup
content = content.replace('// releaseVrpPlanNative(planHandle);', 'releaseVrpPlanNative(planHandle);')

with open(path, 'w') as f:
    f.write(content)
"

# Step 2: Rebuild all components
chmod +x /app/build_all.sh
/app/build_all.sh

# Step 3: Run dispatch gateway to produce /app/output.json
chmod +x /app/run_solution.sh
/app/run_solution.sh

echo "=== Oracle Solution Completed Successfully ==="
