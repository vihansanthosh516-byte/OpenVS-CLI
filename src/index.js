import { detectOS } from "./runtime/detect.js";
import { resolvePython } from "./runtime/python.js";
import { bootstrap } from "./runtime/bootstrap.js";
import { loadConfig } from "./system/config.js";
import { getPaths } from "./system/paths.js";
import { launchEngine } from "./runtime/launcher.js";
import { printBox, printError, printDim } from "./cli/prompt_renderer.js";

const VERSION = "0.1.0-beta.1";

export async function run() {
  const args = process.argv.slice(2);

  if (args.includes("--version") || args.includes("-v")) {
    console.log(`Logos CLI v${VERSION}`);
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
Logos CLI v${VERSION} — AI Operating System for Agents & Swarms

Usage:
  logos                Start interactive session
  logos --version      Show version
  logos --doctor       Run health checks
  logos --help         Show this help

First time?
  1. Get an API key from NVIDIA (https://build.nvidia.com)
  2. Run: /config set-key nvidia <your-key>
  3. Start chatting

Slash commands (inside session):
  /model <name>       Switch model
  /models             List available models
  /config             Show config
  /status             Engine status
  /help               Show all commands
  /exit               Exit session
`);
}
