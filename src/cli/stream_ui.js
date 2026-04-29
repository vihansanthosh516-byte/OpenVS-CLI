import { print, printDim, printSuccess } from "./prompt_renderer.js";
import { Spinner } from "./spinner.js";

export async function executeWithSpinner(bridge, payload, model) {
  const spinner = new Spinner();
  spinner.start(`${model} reasoning`);

  try {
    const resp = await bridge.request(payload);
    spinner.succeed(`${model} complete`);
    return resp;
  } catch (err) {
    spinner.fail(`${model} error`);
    throw err;
  }
}

export function streamTokenToOutput(token) {
  process.stdout.write(token);
}

export function streamEnd(summary) {
  print("");
  printDim(`  ${summary.total_tokens || 0} tokens generated`);
}
