#!/bin/bash
set -euo pipefail

cp /app/solution/fixed/network-fabric.js /app/cdk-vpc/lib/network-fabric.js
chmod 0755 /app/cdk-vpc/bin/synth.js
mkdir -p /app/cdk.out
node /app/cdk-vpc/bin/synth.js --config /app/config/payments-network.json --out /app/cdk.out
