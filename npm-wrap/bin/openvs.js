#!/usr/bin/env node
/**
 * OpenVS CLI — Global entry point.
 *
 * Routes to:
 *  - openvs             → launch Textual TUI
 *  - openvs --version   → show version
 *  - openvs --doctor    → run health checks
 *  - openvs --doctor --export → export diagnostic bundle
 *  - openvs --demo      → run canned swarm demo
 *  - openvs --help      → show help
 */
import { launch, runDoctor, runVersion, runHelp } from "../src/launcher.js";
import { spawn } from "child_process";

const args = process.argv.slice(2);

if (args.includes("--version") || args.includes("-v")) {
  runVersion();
} else if (args.includes("--doctor")) {
  if (args.includes("--export")) {
    const proc = spawn("python", ["-m", "openvs", "--doctor", "--export"], { stdio: "inherit" });
    proc.on("exit", (code) => process.exit(code || 0));
  } else {
    runDoctor();
  }
} else if (args.includes("--demo")) {
  const proc = spawn("python", ["-m", "openvs", "--demo"], { stdio: "inherit" });
  proc.on("exit", (code) => process.exit(code || 0));
} else if (args.includes("--help") || args.includes("-h")) {
  runHelp();
} else {
  launch();
}
