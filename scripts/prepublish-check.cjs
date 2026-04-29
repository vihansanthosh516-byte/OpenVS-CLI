#!/usr/bin/env node

// Prepublish check: validate package is ready for npm publish
// Runs automatically on `npm publish` via prepublishOnly script

const fs = require("fs");
const path = require("path");
const pkg = require("../package.json");

let errors = 0;

// Check bin entry exists
const binPath = path.resolve(__dirname, "..", pkg.bin.logos);
if (!fs.existsSync(binPath)) {
  console.error(`  [X] bin entry not found: ${pkg.bin.logos}`);
  errors++;
} else {
  // Check shebang
  const content = fs.readFileSync(binPath, "utf8");
  if (!content.startsWith("#!/usr/bin/env node")) {
    console.error(`  [X] bin/logos.js missing shebang`);
    errors++;
  } else {
    console.log(`  [+] bin/logos.js has shebang`);
  }
}

// Check main entry
const mainPath = path.resolve(__dirname, "..", pkg.main);
if (!fs.existsSync(mainPath)) {
  console.error(`  [X] main entry not found: ${pkg.main}`);
  errors++;
} else {
  console.log(`  [+] main entry exists: ${pkg.main}`);
}

// Check engine bundled
const engineMain = path.resolve(__dirname, "..", "engine", "main.py");
if (!fs.existsSync(engineMain)) {
  console.error(`  [X] engine/main.py not found`);
  errors++;
} else {
  console.log(`  [+] engine/main.py exists`);
}

// Check version is set
if (!pkg.version || pkg.version === "0.0.0") {
  console.error(`  [X] version not set in package.json`);
  errors++;
} else {
  console.log(`  [+] version: ${pkg.version}`);
}

// Check name
if (!pkg.name) {
  console.error(`  [X] name not set in package.json`);
  errors++;
} else {
  console.log(`  [+] name: ${pkg.name}`);
}

// Check files field
if (!pkg.files || !Array.isArray(pkg.files) || pkg.files.length === 0) {
  console.error(`  [X] files field missing or empty`);
  errors++;
} else {
  console.log(`  [+] files: ${pkg.files.join(", ")}`);
}

// Check .npmignore exists
const npmignorePath = path.resolve(__dirname, "..", ".npmignore");
if (!fs.existsSync(npmignorePath)) {
  console.warn(`  [!] .npmignore not found (will ship everything)`);
} else {
  console.log(`  [+] .npmignore exists`);
}

// Check no __pycache__ in files list
for (const dir of pkg.files) {
  const pycachePath = path.resolve(__dirname, "..", dir, "__pycache__");
  if (fs.existsSync(pycachePath)) {
    console.warn(`  [!] ${dir}/__pycache__/ exists — ensure .npmignore excludes it`);
  }
}

console.log("");
if (errors > 0) {
  console.error(`  ${errors} error(s) found. Fix before publishing.`);
  process.exit(1);
} else {
  console.log("  Package ready for publish.");
}
