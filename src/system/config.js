import { readFileSync, writeFileSync, mkdirSync, existsSync } from "fs";
import { join } from "path";

const DEFAULT_CONFIG = {
  provider: "nvidia",
  default_model: "qwen",
  update_channel: "stable",
  auto_check_updates: true,
  swarm_enabled: false,
  swarm_mode: "parallel",
  worker_count: 3,
  telemetry_enabled: false,
};

export function loadConfig(paths) {
  const configPath = join(paths.configDir, "config.json");

  if (existsSync(configPath)) {
    try {
      const data = readFileSync(configPath, "utf8");
      return { ...DEFAULT_CONFIG, ...JSON.parse(data) };
    } catch {
      return { ...DEFAULT_CONFIG };
    }
  }

  saveConfig(paths, DEFAULT_CONFIG);
  return { ...DEFAULT_CONFIG };
}

export function saveConfig(paths, config) {
  const configPath = join(paths.configDir, "config.json");
  mkdirSync(paths.configDir, { recursive: true });
  writeFileSync(configPath, JSON.stringify(config, null, 2));
}
