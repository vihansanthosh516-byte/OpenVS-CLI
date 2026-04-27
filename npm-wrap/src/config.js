/**
 * OpenVS CLI — Node-side config management.
 *
 * Reads/writes ~/.openvs/config.json from the Node side.
 * Used by launcher.js and doctor.js to check user preferences.
 */

import { readFileSync, writeFileSync, mkdirSync } from "fs";
import { join } from "path";
import { homedir } from "os";

const CONFIG_DIR = join(homedir(), ".openvs");
const CONFIG_PATH = join(CONFIG_DIR, "config.json");

const DEFAULT_CONFIG = {
  provider: "nvidia",
  default_model: "qwen",
  update_channel: "stable",
  auto_check_updates: true,
  swarm_enabled: true,
  swarm_mode: "parallel",
  worker_count: 3,
  profile: "fullstack",
  telemetry_enabled: false,
  session_restore: true,
};

export function loadConfig() {
  try {
    const data = readFileSync(CONFIG_PATH, "utf8");
    return { ...DEFAULT_CONFIG, ...JSON.parse(data) };
  } catch {
    return { ...DEFAULT_CONFIG };
  }
}

export function saveConfig(config) {
  mkdirSync(CONFIG_DIR, { recursive: true });
  writeFileSync(CONFIG_PATH, JSON.stringify(config, null, 2));
}

export function getConfig(key) {
  const config = loadConfig();
  return config[key] ?? null;
}

export function setConfig(key, value) {
  const config = loadConfig();
  config[key] = value;
  saveConfig(config);
}