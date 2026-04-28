import { join } from "path";
import { homedir } from "os";
import { dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));

export function getPaths() {
  const configDir = join(homedir(), ".openvs");
  const engineDir = join(__dirname, "..", "..", "engine");

  return {
    configDir,
    engineDir,
    sessionsDir: join(configDir, "sessions"),
    configPath: join(configDir, "config.json"),
  };
}
