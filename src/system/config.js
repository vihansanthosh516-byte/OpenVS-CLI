import { readFileSync, writeFileSync, mkdirSync, existsSync } from "fs";
import { join } from "path";

const DEFAULT_CONFIG = {
  provider: "nvidia",
  api_keys: {},
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
      const parsed = JSON.parse(data);
      return { ...DEFAULT_CONFIG, ...parsed };
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

export function setApiKey(paths, provider, key) {
  const config = loadConfig(paths);
  if (!config.api_keys) {
    config.api_keys = {};
  }
  config.api_keys[provider] = key;
  if (!config.provider) {
    config.provider = provider;
  }
  saveConfig(paths, config);
  return config;
}

export function getApiKey(paths, provider) {
  const config = loadConfig(paths);
  const fromConfig = config.api_keys?.[provider] || "";
  const fromEnv = process.env[`${provider.toUpperCase()}_API_KEY`] || "";
  return fromEnv || fromConfig;
}

export function hasApiKey(paths, provider) {
  return !!getApiKey(paths, provider);
}
