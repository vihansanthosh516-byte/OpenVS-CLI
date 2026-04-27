/**
 * OpenVS CLI Launcher — bridges Node.js CLI to Python runtime.
 *
 * The npm package provides the global `openvs` command.
 * The actual runtime is the Python package (openvs-cli on PyPI).
 * This launcher:
 * 1. Verifies Python is available
 * 2. Checks openvs-cli Python package is installed
 * 3. Delegates to the Python entry point
 */

import { spawn, execSync } from "child_process";
import { createRequire } from "module";

const VERSION = "1.0.0";

function findPython() {
  const candidates = ["python3", "python", "py"];
  for (const cmd of candidates) {
    try {
      const result = execSync(`${cmd} --version`, { encoding: "utf8", stdio: "pipe" });
      if (result.includes("Python")) {
        return cmd;
      }
    } catch {}
  }
  return null;
}

function checkOpenVSPackage(pythonCmd) {
  try {
    execSync(`${pythonCmd} -c "import openvs"`, { encoding: "utf8", stdio: "pipe" });
    return true;
  } catch {
    return false;
  }
}

export function launch() {
  const python = findPython();

  if (!python) {
    console.error("\n  Error: Python not found.");
    console.error("  OpenVS CLI requires Python 3.11+ to be installed.\n");
    console.error("  Install Python: https://python.org/downloads");
    console.error("  Then run: pip install openvs-cli\n");
    process.exit(1);
  }

  if (!checkOpenVSPackage(python)) {
    console.error("\n  OpenVS Python package not found.");
    console.error("  Install it with: pip install openvs-cli\n");
    process.exit(1);
  }

  // Launch the Textual TUI
  const proc = spawn(python, ["-m", "openvs", ...process.argv.slice(2)], {
    stdio: "inherit",
    env: { ...process.env },
  });

  proc.on("exit", (code) => {
    process.exit(code || 0);
  });

  // Graceful shutdown
  process.on("SIGINT", () => {
    proc.kill("SIGINT");
  });

  process.on("SIGTERM", () => {
    proc.kill("SIGTERM");
  });
}

export function runVersion() {
  console.log(`OpenVS CLI v${VERSION}`);
}

export function runDoctor() {
  const python = findPython();
  if (!python) {
    console.error("Error: Python not found. Cannot run doctor.");
    process.exit(1);
  }

  const proc = spawn(python, ["-m", "openvs", "--doctor"], {
    stdio: "inherit",
  });

  proc.on("exit", (code) => {
    process.exit(code || 0);
  });
}

export function runHelp() {
  console.log(`
OpenVS CLI v${VERSION} — Multi-agent AI Operating System

Usage:
  openvs                  Launch interactive terminal UI
  openvs --version        Show version
  openvs --doctor         Run system health checks
  openvs --doctor --export  Export diagnostic bundle
  openvs --demo           Run canned swarm demo
  openvs --help           Show this help

First run:
  openvs                  (guided setup on first launch)

Slash commands (inside UI):
  /model <name>           Switch AI model
  /swarm on|off           Toggle swarm orchestration
  /jobs                   List current jobs
  /trace <id>             Show execution trace
  /plugin list            List installed plugins
  /session load           Restore previous session
  /update check           Check for updates
  /doctor                 Run health checks
  /config                 View persistent config
  /help                   Show all commands

Keyboard:
  TAB                     Cycle mode (chat, diff, swarm, trace, jobs)
  CTRL+M                 Model selector
  CTRL+P                 Command palette
  CTRL+S                 Toggle swarm panel

More: https://github.com/openvs/openvs-cli
`);
}
