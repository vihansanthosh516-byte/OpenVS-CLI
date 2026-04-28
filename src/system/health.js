import { detectOS } from "../runtime/detect.js";
import { resolvePython } from "../runtime/python.js";
import { getPaths } from "./paths.js";
import { existsSync } from "fs";
import { join } from "path";

export async function runDoctor() {
  console.log("");
  console.log("  OpenVS Doctor");
  console.log("  " + "=".repeat(40));
  console.log("");

  let passed = 0;
  let failed = 0;
  let warned = 0;

  const os = detectOS();
  const osResult = check("OS", `${os.platform} (${os.arch})`, true);
  osResult === "ok" ? passed++ : warned++;

  const python = resolvePython(os);
  if (python) {
    const v = python.version.join(".");
    check("Python", `v${v} at ${python.path}`, true);
    passed++;
  } else {
    check("Python", "3.11+ not found", false);
    failed++;
  }

  const paths = getPaths();
  const engineExists = existsSync(join(paths.engineDir, "main.py"));
  if (engineExists) {
    check("Engine", paths.engineDir, true);
    passed++;
  } else {
    check("Engine", "not found at " + paths.engineDir, false);
    failed++;
  }

  const configExists = existsSync(paths.configPath);
  check("Config", configExists ? paths.configPath : "not yet created", configExists);
  configExists ? passed++ : warned++;

  console.log("");
  console.log("  " + "=".repeat(40));
  if (failed === 0) {
    console.log(`  All checks passed (${passed} ok, ${warned} warnings)`);
  } else {
    console.log(`  ${passed} ok, ${failed} failed, ${warned} warnings`);
  }
  console.log("");
}

function check(label, message, ok) {
  const icon = ok ? "+" : "X";
  console.log(`  [${icon}] ${label.padEnd(12)} — ${message}`);
  return ok ? "ok" : "fail";
}
