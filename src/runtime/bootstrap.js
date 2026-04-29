import { mkdirSync, existsSync } from "fs";
import { join } from "path";
import { resolvePython } from "./python.js";

export function bootstrap({ os, python, paths, config }) {
  if (!python) {
    console.error("");
    console.error("  Error: Python 3.11+ not found.");
    console.error("  Logos CLI requires Python 3.11 or later.");
    console.error("");
    console.error("  Install: https://python.org/downloads");
    console.error("");
    return false;
  }

  ensureDir(paths.configDir);
  ensureDir(paths.sessionsDir);

  const engineExists = existsSync(join(paths.engineDir, "main.py"));
  if (!engineExists) {
    console.error("");
    console.error("  Error: Logos engine not found.");
    console.error("  Expected at: " + paths.engineDir);
    console.error("  Reinstall: npm install -g logos-cli");
    console.error("");
    return false;
  }

  return true;
}

function ensureDir(dir) {
  try {
    mkdirSync(dir, { recursive: true });
  } catch {}
}
