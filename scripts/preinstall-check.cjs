#!/usr/bin/env node

// Preinstall check: verify Python 3.11+ exists before npm install completes
// This runs during `npm install -g logos-cli` before the package is extracted

const { execSync } = require("child_process");

const MIN_PYTHON = [3, 11, 0];
const candidates = process.platform === "win32"
  ? ["py", "python", "python3"]
  : ["python3", "python"];

let found = false;

for (const cmd of candidates) {
  try {
    const out = execSync(`${cmd} --version`, {
      encoding: "utf8",
      stdio: "pipe",
      timeout: 5000,
    }).trim();

    const match = out.match(/Python (\d+)\.(\d+)\.(\d+)/);
    if (!match) continue;

    const v = [parseInt(match[1]), parseInt(match[2]), parseInt(match[3])];
    let ok = true;
    for (let i = 0; i < 3; i++) {
      if (v[i] > MIN_PYTHON[i]) break;
      if (v[i] < MIN_PYTHON[i]) { ok = false; break; }
    }

    if (ok) {
      found = true;
      break;
    }
  } catch {
    continue;
  }
}

if (!found) {
  console.warn("");
  console.warn("  [warn] Python 3.11+ not found.");
  console.warn("  Logos CLI requires Python 3.11+ for the engine.");
  console.warn("  Install: https://python.org/downloads");
  console.warn("  The CLI will not work until Python is available.");
  console.warn("");
  // Don't fail install — just warn. Some users install node package first, python later.
}
