import { spawn } from "child_process";

const PROTOCOL_VERSION = 1;

export function createBridge(proc) {
  let requestId = 0;
  const pending = new Map();
  let buffer = "";

  proc.stdout.on("data", (data) => {
    buffer += data.toString();
    const lines = buffer.split("\n");
    buffer = lines.pop();

    for (const line of lines) {
      if (!line.trim()) continue;
      try {
        const envelope = JSON.parse(line);

        if (envelope.protocol_version && envelope.protocol_version !== PROTOCOL_VERSION) {
          process.stderr.write(`[bridge] protocol version mismatch: got v${envelope.protocol_version}, expected v${PROTOCOL_VERSION}\n`);
        }

        const response = envelope.payload || envelope;
        const id = envelope.request_id || response._request_id || response.request_id;
        if (id && pending.has(id)) {
          const { resolve } = pending.get(id);
          pending.delete(id);
          resolve({ ...response, _meta: { protocol_version: envelope.protocol_version } });
        }
      } catch {}
    }
  });

  return {
    async request(payload) {
      const id = ++requestId;
      return new Promise((resolve, reject) => {
        const timeout = setTimeout(() => {
          pending.delete(id);
          resolve({ status: "error", error: "request timed out" });
        }, 30000);

        pending.set(id, {
          resolve: (resp) => {
            clearTimeout(timeout);
            resolve(resp);
          },
        });

        const envelope = {
          protocol_version: PROTOCOL_VERSION,
          request_id: id,
          type: payload.type,
          payload: payload,
        };

        const msg = JSON.stringify(envelope);
        proc.stdin.write(msg + "\n");
      });
    },

    close() {
      try {
        proc.stdin.end();
      } catch {}
    },
  };
}
