export function createPromptLabel(model, provider) {
  if (!model) return "logos> ";
  return `logos (${model})> `;
}

export function formatBootScreen(version, model, provider, workers, hasKey) {
  const lines = [
    `Model: ${model} (${provider})`,
    `API Key: ${hasKey ? "configured" : "NOT SET"}`,
    `Workers: ${workers}`,
    `Event Bus: active`,
  ];
  return { title: `LOGOS CLI v${version}`, lines };
}

export function formatShutdown() {
  return [
    "event bus flushed",
    "workers stopped",
    "session saved",
    "",
    "Goodbye.",
  ];
}
