import sys
import json

from engine.errors import BridgeError

PROTOCOL_VERSION = 1


class Bridge:
    def __init__(self, stdin, stdout):
        self.stdin = stdin
        self.stdout = stdout

    def read_request(self):
        line = self.stdin.readline()
        if not line:
            return None
        line = line.strip()
        if not line:
            return None
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            raise BridgeError("invalid JSON in request", direction="in")

        if "protocol_version" not in request:
            self.log("warning: request missing protocol_version, assuming v1")
            request["protocol_version"] = 1

        if request["protocol_version"] != PROTOCOL_VERSION:
            self.log(
                f"warning: protocol version mismatch: got {request['protocol_version']}, expected {PROTOCOL_VERSION}"
            )

        return request

    def write_response(self, response, request=None):
        envelope = {
            "protocol_version": PROTOCOL_VERSION,
            "payload": response,
        }

        if request:
            if "request_id" in request:
                envelope["request_id"] = request["request_id"]
            elif "_request_id" in request:
                envelope["request_id"] = request["_request_id"]

        data = json.dumps(envelope)
        self.stdout.write(data + "\n")
        self.stdout.flush()

    def log(self, message):
        print(f"[ENGINE] {message}", file=sys.stderr, flush=True)

    def close(self):
        pass
