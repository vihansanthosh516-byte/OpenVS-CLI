const SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

export class Spinner {
  constructor() {
    this._interval = null;
    this._frame = 0;
    this._prefix = "";
    this._stream = process.stderr;
  }

  start(prefix = "thinking") {
    this._prefix = prefix;
    this._frame = 0;
    this._stream.write(`  ${SPINNER_FRAMES[0]} ${prefix}...\r`);
    this._interval = setInterval(() => {
      this._frame = (this._frame + 1) % SPINNER_FRAMES.length;
      this._stream.write(`  ${SPINNER_FRAMES[this._frame]} ${this._prefix}...\r`);
    }, 80);
    return this;
  }

  update(prefix) {
    this._prefix = prefix;
  }

  stop(finalMessage) {
    if (this._interval) {
      clearInterval(this._interval);
      this._interval = null;
    }
    this._stream.write("\r" + " ".repeat(40) + "\r");
    if (finalMessage) {
      this._stream.write(`  ${finalMessage}\n`);
    }
    return this;
  }

  succeed(message) {
    return this.stop(message || `${this._prefix} done`);
  }

  fail(message) {
    return this.stop(message || `${this._prefix} failed`);
  }
}

export function createSpinner() {
  return new Spinner();
}
