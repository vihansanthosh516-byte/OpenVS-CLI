import { spawn } from "child_process";
import { join } from "path";
import { createBridge } from "../bridge/bridge.js";

export async function launchEngine({ python, paths, config }) {
  const engineScript = join(paths.engineDir, "main.py");

  const proc = spawn(python.command, [engineScript], {
    stdio: ["pipe", "pipe", "pipe"],
    env: {
      ...process.env,
      OPENVS_CONFIG_DIR: paths.configDir,
      OPENVS_ENGINE_DIR: paths.engineDir,
    },
  });

  const bridge = createBridge(proc);

  proc.stderr.on("data", (data) => {
    const msg = data.toString().trim();
    if (msg) {
      for (const line of msg.split("\n")) {
        if (line.startsWith("[ENGINE]")) {
          console.error(line);
        } else {
          console.error(`  [engine] ${line}`);
        }
      }
    }
  });

  proc.on("exit", (code) => {
    if (code !== 0 && code !== null) {
      console.error(`  Engine exited with code ${code}`);
    }
    process.exit(code || 0);
  });

  process.on("SIGINT", () => {
    proc.kill("SIGINT");
  });

  process.on("SIGTERM", () => {
    proc.kill("SIGTERM");
  });

  await startREPL(bridge, config);
}

async function startREPL(bridge, config) {
  const { createInterface } = await import("readline");
  const rl = createInterface({
    input: process.stdin,
    output: process.stdout,
    prompt: "openvs> ",
  });

  const initResp = await bridge.request({ type: "init", config });
  if (initResp.status === "ok") {
    const protoVer = initResp._meta?.protocol_version || 1;
    const engineVer = initResp.version || "0.3.0";
    const lifecycle = initResp.lifecycle || "ready";
    const plugins = initResp.plugins || 0;
    console.log(`  OpenVS v${engineVer} — engine ready (lifecycle: ${lifecycle}, plugins: ${plugins})`);
    console.log(`  Model: ${config.default_model} | Type /help for commands`);
    console.log("");
  } else {
    console.error("  Engine init failed:", initResp.error || "unknown");
    process.exit(1);
  }

  rl.prompt();

  rl.on("line", async (line) => {
    const input = line.trim();
    if (!input) {
      rl.prompt();
      return;
    }

    if (input === "/exit" || input === "/quit") {
      await bridge.request({ type: "shutdown" });
      rl.close();
      return;
    }

    if (input.startsWith("/")) {
      const resp = await bridge.request({ type: "command", command: input });
      console.log(resp.output || resp.error || "");
    } else {
      const resp = await bridge.request({ type: "prompt", text: input });
      console.log(resp.output || resp.error || "No response");
    }

    rl.prompt();
  });

  rl.on("close", () => {
    bridge.close();
    process.exit(0);
  });
}
