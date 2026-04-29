const RESET = "\x1b[0m";
const BOLD = "\x1b[1m";
const DIM = "\x1b[2m";
const RED = "\x1b[31m";
const GREEN = "\x1b[32m";
const YELLOW = "\x1b[33m";
const CYAN = "\x1b[36m";
const MAGENTA = "\x1b[35m";

export function print(text) {
  process.stdout.write(text + "\n");
}

export function printDim(text) {
  process.stdout.write(DIM + text + RESET + "\n");
}

export function printBold(text) {
  process.stdout.write(BOLD + text + RESET + "\n");
}

export function printSuccess(text) {
  process.stdout.write(GREEN + text + RESET + "\n");
}

export function printError(text) {
  process.stderr.write(RED + text + RESET + "\n");
}

export function printWarn(text) {
  process.stdout.write(YELLOW + text + RESET + "\n");
}

export function printInfo(text) {
  process.stdout.write(CYAN + text + RESET + "\n");
}

export function printModelPrefix(model, provider) {
  return `${MAGENTA}[${model}]${RESET}`;
}

export function printBox(title, lines, width = 50) {
  const top = "┌" + "─".repeat(width - 2) + "┐";
  const bot = "└" + "─".repeat(width - 2) + "┘";
  const pad = (s) => "│ " + s.padEnd(width - 4) + " │";
  const sep = "├" + "─".repeat(width - 2) + "┤";

  print(BOLD + top + RESET);
  if (title) print(BOLD + pad(title) + RESET);
  if (title && lines.length) print(sep);
  for (const line of lines) {
    print(pad(line));
  }
  print(bot);
}

export function formatModelResponse(model, text, provider) {
  const prefix = `${MAGENTA}[${model}]${RESET} `;
  const lines = text.split("\n");
  return lines.map((l, i) => i === 0 ? prefix + l : " ".repeat(model.length + 3) + l).join("\n");
}

export function formatError(error, fix) {
  let out = RED + "ERROR: " + RESET + BOLD + error + RESET;
  if (fix) {
    out += "\n" + DIM + "  Fix: " + fix + RESET;
  }
  return out;
}

export function formatApiKeyStatus(provider, hasKey) {
  const icon = hasKey ? GREEN + "+" + RESET : RED + "X" + RESET;
  return `  [${icon}] ${provider}`;
}
