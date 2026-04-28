import { detectOS } from "./runtime/detect.js";
import { resolvePython } from "./runtime/python.js";
import { bootstrap } from "./runtime/bootstrap.js";
import { loadConfig } from "./system/config.js";
import { getPaths } from "./system/paths.js";
import { launchEngine } from "./runtime/launcher.js";

const VERSION = "0.5.0";

export async function run() {
  const args = process.argv.slice(2);

  if (args.includes("--version") || args.includes("-v")) {
    console.log(`OpenVS v${VERSION}`);
    return;
  }

  if (args.includes("--help") || args.includes("-h")) {
    printHelp();
    return;
  }

  if (args.includes("--doctor")) {
    const { runDoctor } = await import("./system/health.js");
    await runDoctor();
    return;
  }

  await startEngine();
}

async function startEngine() {
  const os = detectOS();
  const python = resolvePython(os);
  const paths = getPaths();
  const config = loadConfig(paths);

  const ready = bootstrap({ os, python, paths, config });
  if (!ready) {
    process.exit(1);
  }

  await launchEngine({ python, paths, config });
}

function printHelp() {
  console.log(`
OpenVS v${VERSION} — AI Operating System for CLI

Usage:
  openvs              Start interactive session
  openvs --version    Show version
  openvs --doctor     Run health checks
  openvs --help       Show this help

Slash commands (inside session):
  /status             Show engine status
  /help               Show available commands
  /model <name>       Switch AI model
  /config             View config
  /exit               Exit session

Keyboard:
  CTRL+C              Exit
`);
}
