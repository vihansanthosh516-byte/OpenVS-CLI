import { print, printError, formatError } from "./prompt_renderer.js";

export function handleBridgeError(resp) {
  if (!resp || resp.status !== "error") return false;

  const error = resp.error || resp.output || "unknown error";
  let fix = null;

  if (error.includes("no API key") || error.includes("API key missing")) {
    fix = "/config set-key nvidia <your-key>";
  } else if (error.includes("network") || error.includes("URLError")) {
    fix = "check your internet connection";
  } else if (error.includes("HTTP 401") || error.includes("Unauthorized")) {
    fix = "API key is invalid — /config set-key nvidia <new-key>";
  } else if (error.includes("HTTP 429")) {
    fix = "rate limited — wait a moment and try again";
  } else if (error.includes("unknown model")) {
    fix = "type /models to list available models";
  }

  printError(formatError(error, fix));
  return true;
}
