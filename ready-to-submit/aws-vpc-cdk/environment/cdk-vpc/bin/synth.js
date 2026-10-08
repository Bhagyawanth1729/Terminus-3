#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const cdk = require("aws-cdk-lib");
const { NetworkFabric } = require("../lib/network-fabric");

function parseArgs(argv) {
  const out = {};
  for (let i = 2; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--config") {
      out.config = argv[++i];
    } else if (arg === "--out") {
      out.out = argv[++i];
    } else {
      throw new Error(`unknown argument: ${arg}`);
    }
  }
  if (!out.config || !out.out) {
    throw new Error("usage: node bin/synth.js --config <file> --out <dir>");
  }
  return out;
}

function main() {
  const args = parseArgs(process.argv);
  const config = JSON.parse(fs.readFileSync(args.config, "utf8"));
  fs.mkdirSync(args.out, { recursive: true });
  const app = new cdk.App({ outdir: args.out });
  const stack = new cdk.Stack(app, "FleetVpc", {
    env: {
      account: config.account || "111122223333",
      region: config.region || "us-east-1"
    }
  });
  new NetworkFabric(stack, "Network", config);
  app.synth();
  const manifest = path.join(args.out, "manifest.json");
  if (!fs.existsSync(manifest)) {
    throw new Error("CDK synth did not write manifest.json");
  }
}

try {
  main();
} catch (err) {
  console.error(err && err.stack ? err.stack : String(err));
  process.exit(1);
}
