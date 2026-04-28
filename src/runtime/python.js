import { execSync } from "child_process";

const MIN_PYTHON_VERSION = [3, 11, 0];

export function resolvePython(os) {
  const candidates = getCandidates(os);

  for (const cmd of candidates) {
    const info = probePython(cmd);
    if (info && meetsMinVersion(info.version)) {
      return {
        command: cmd,
        version: info.version,
        path: info.path,
      };
    }
  }

  return null;
}

function getCandidates(os) {
  if (os.platform === "windows") {
    return ["py", "python", "python3"];
  }
  return ["python3", "python"];
}

function probePython(cmd) {
  try {
    const versionOut = execSync(`${cmd} --version`, {
      encoding: "utf8",
      stdio: "pipe",
      timeout: 5000,
    }).trim();

    const match = versionOut.match(/Python (\d+)\.(\d+)\.(\d+)/);
    if (!match) return null;

    const version = [parseInt(match[1]), parseInt(match[2]), parseInt(match[3])];

    const path = execSync(`${cmd} -c "import sys; print(sys.executable)"`, {
      encoding: "utf8",
      stdio: "pipe",
      timeout: 5000,
    }).trim();

    return { version, path };
  } catch {
    return null;
  }
}

function meetsMinVersion(version) {
  for (let i = 0; i < 3; i++) {
    if (version[i] > MIN_PYTHON_VERSION[i]) return true;
    if (version[i] < MIN_PYTHON_VERSION[i]) return false;
  }
  return true;
}
