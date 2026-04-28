import { platform, release } from "os";
import { execSync } from "child_process";

export function detectOS() {
  const plat = platform();
  const rel = release();

  if (plat === "win32") {
    const isWsl = isWslEnvironment();
    if (isWsl) {
      return { platform: "wsl", arch: process.arch, release: rel };
    }
    return { platform: "windows", arch: process.arch, release: rel };
  }

  if (plat === "darwin") {
    return { platform: "macos", arch: process.arch, release: rel };
  }

  if (plat === "linux") {
    if (isWslEnvironment()) {
      return { platform: "wsl", arch: process.arch, release: rel };
    }
    return { platform: "linux", arch: process.arch, release: rel };
  }

  return { platform: plat, arch: process.arch, release: rel };
}

function isWslEnvironment() {
  try {
    const uname = execSync("uname -r", { encoding: "utf8", stdio: "pipe" }).trim();
    return /microsoft|wsl/i.test(uname);
  } catch {
    return false;
  }
}
