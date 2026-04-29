#!/usr/bin/env node

const MIN_NODE = 18;

const nodeVersion = parseInt(process.version.slice(1).split(".")[0], 10);
if (nodeVersion < MIN_NODE) {
  console.error(`Logos CLI requires Node.js >= ${MIN_NODE}. You have ${process.version}.`);
  console.error(`Upgrade: https://nodejs.org`);
  process.exit(1);
}

import("../src/index.js").then((mod) => {
  mod.run().catch((err) => {
    console.error("Logos CLI crashed:", err.message);
    process.exit(1);
  });
}).catch((err) => {
  if (err.code === "ERR_MODULE_NOT_FOUND") {
    console.error("Logos CLI: module not found. Reinstall with: npm install -g logos-cli");
  } else {
    console.error("Logos CLI: startup error:", err.message);
  }
  process.exit(1);
});
