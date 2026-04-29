#!/usr/bin/env node

// Postinstall: run a quick doctor check after npm install completes
// This validates the install is usable

const { execSync } = require("child_process");
const path = require("path");

console.log("");
console.log("  Logos CLI installed successfully.");
console.log("");

// Quick Python check
const candidates = process.platform === "win32"
  ? ["py", "python", "python3"]
  : ["python3", "python"];

let pythonOk = false;
let pythonVer = "";

for (const cmd of candidates) {
  try {
    const out = execSync(`${cmd} --version`, {
      encoding: "utf8",
      stdio: "pipe",
      timeout: 5000,
    }).trim();
    const match = out.match(/Python (\d+\.\d+\.\d+)/);
    if (match) {
      pythonVer = match[1];
      const major = parseInt(match[1].split(".")[0]);
      const minor = parseInt(match[1].split(".")[1]);
      if (major > 3 || (major === 3 && minor >= 11)) {
        pythonOk = true;
      }
      break;
    }
  } catch {
    continue;
  }
}

if (pythonOk) {
  console.log(`  [+] Python ${pythonVer} found`);
} else if (pythonVer) {
  console.log(`  [!] Python ${pythonVer} found (need 3.11+)`);
  console.log("      Upgrade: https://python.org/downloads");
} else {
  console.log("  [!] Python not found");
  console.log("      Install: https://python.org/downloads");
}

// Engine check
const engineDir = path.resolve(__dirname, "..", "engine");
const fs = require("fs");
const mainPy = path.join(engineDir, "main.py");
if (fs.existsSync(mainPy)) {
  console.log("  [+] Engine bundled");
} else {
  console.log("  [!] Engine not found at " + engineDir);
}

console.log("");
console.log("  Get started:");
console.log("    1. Get an API key: https://build.nvidia.com");
console.log("    2. Run: logos");
console.log("    3. Inside CLI: /config set-key nvidia <your-key>");
console.log("");
console.log("  Or run health check: logos --doctor");
console.log("");
