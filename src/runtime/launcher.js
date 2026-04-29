import { spawn } from "child_process";
import { join } from "path";
import { createBridge } from "../bridge/bridge.js";
import {
  print, printDim, printSuccess, printError, printBox,
  formatModelResponse, formatError, formatApiKeyStatus,
} from "../cli/prompt_renderer.js";
import { createPromptLabel, formatBootScreen, formatShutdown } from "../cli/status_ui.js";
import { handleBridgeError } from "../cli/error_ui.js";
import { executeWithSpinner } from "../cli/stream_ui.js";
import { Spinner } from "../cli/spinner.js";

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
          printDim(`  ${line}`);
        }
      }
    }
  });

  proc.on("exit", (code) => {
    if (code !== 0 && code !== null) {
      printError(`Engine exited with code ${code}`);
    }
    process.exit(code || 0);
  });

  process.on("SIGINT", () => {
    proc.kill("SIGINT");
  });

  process.on("SIGTERM", () => {
    proc.kill("SIGTERM");
  });

  await startREPL(bridge, config, paths);
}

async function startREPL(bridge, config, paths) {
  const { createInterface } = await import("readline");

  const spinner = new Spinner();
  spinner.start("connecting to engine");

  const initResp = await bridge.request({ type: "init", config });

  spinner.stop();

  if (initResp.status !== "ok") {
    printError("Engine init failed: " + (initResp.error || "unknown"));
    process.exit(1);
  }

  const engineVer = initResp.version || "0.5.0";
  const model = config.default_model || "qwen";
  const provider = config.provider || "nvidia";
  const workers = initResp.workers || 3;
  const hasKey = !!(config.api_keys?.[provider] || process.env[`${provider.toUpperCase()}_API_KEY`]);

  const boot = formatBootScreen(engineVer, model, provider, workers, hasKey);
  printBox(boot.title, boot.lines);

  if (!hasKey) {
    print("");
    printDim("  No NVIDIA API key configured.");
    printDim("  Get a key at: https://build.nvidia.com");
    printDim("  Then run: /config set-key nvidia YOUR_KEY");
    print("");
  }

  printDim("  Type /help for commands");
  print("");

  const rl = createInterface({
    input: process.stdin,
    output: process.stdout,
    prompt: createPromptLabel(model, provider),
  });

  let currentModel = model;

  rl.prompt();

  rl.on("line", async (line) => {
    const input = line.trim();
    if (!input) {
      rl.prompt();
      return;
    }

    if (input === "/exit" || input === "/quit") {
      await bridge.request({ type: "shutdown" });
      print("");
      const shutdownLines = formatShutdown();
      for (const l of shutdownLines) {
        if (l) printDim(`  ${l}`);
      }
      rl.close();
      return;
    }

    if (input.startsWith("/")) {
      const parts = input.split(/\s+/);
      const cmd = parts[0].toLowerCase();

      if (cmd === "/model" && parts.length > 1) {
        currentModel = parts[1].toLowerCase();
      }

      const resp = await bridge.request({ type: "command", command: input });
      if (resp.output) {
        print(resp.output);
      } else if (handleBridgeError(resp)) {
        // handled
      } else {
        print(JSON.stringify(resp));
      }
    } else {
      const resp = await executeWithSpinner(bridge, { type: "prompt", text: input }, currentModel);

      if (handleBridgeError(resp)) {
        // handled
      } else if (resp.output) {
        print(formatModelResponse(currentModel, resp.output, provider));
        if (resp.trace) {
          printDim(`  [job ${resp.trace.job_id}] ${resp.trace.status} (${resp.trace.mode})`);
        }
      } else {
        print(resp.error || "No response");
      }
    }

    rl.setPrompt(createPromptLabel(currentModel, provider));
    rl.prompt();
  });

  rl.on("close", () => {
    bridge.close();
    process.exit(0);
  });
}
