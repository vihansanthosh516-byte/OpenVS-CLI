/**
 * OpenVS CLI — Post-install doctor check.
 *
 * Runs after `npm install -g openvs-cli` to verify:
 * - Python is available
 * - openvs-cli Python package is installed
 * - Dependencies are present
 */

import { execSync } from "child_process";

function check(label, cmd) {
  try {
    execSync(cmd, { encoding: "utf8", stdio: "pipe" });
    console.log(`  [+] ${label}`);
    return true;
  } catch {
    console.log(`  [!] ${label} — not found`);
    return false;
  }
}

console.log("\n  OpenVS CLI — Post-install check\n");

const python = check("Python runtime", "python --version");
check("OpenVS package", "python -c \"import openvs\"");

if (python) {
  console.log("\n  Running full doctor...\n");
  try {
    execSync("python -m openvs --doctor", { encoding: "utf8", stdio: "inherit" });
  } catch {}
} else {
  console.log("\n  Install Python 3.11+ and run: pip install openvs-cli");
}

console.log("\n  Then run: openvs\n");
