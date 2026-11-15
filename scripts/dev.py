"""Start Cross Post for development.

    py scripts/dev.py                 tunnel + backend + frontend
    py scripts/dev.py backend         just one
    py scripts/dev.py backend frontend
    py scripts/dev.py --no-tunnel     everything except the tunnel

The tunnel is first and the backend waits for it, because a Cloudflare quick
tunnel gets a new random hostname every run and the backend reads
PUBLIC_BASE_URL once at import. Starting them the other way round leaves the
backend pointing at the previous, dead hostname — which is what produces
Cloudflare's 1033 page in the middle of an OAuth redirect.

Stdlib only, so there is nothing to install before you can start the thing
that installs everything else.
"""

import argparse
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / "backend" / ".env"
BACKEND_PYTHON = ROOT / "backend" / ".venv" / "Scripts" / "python.exe"
BACKEND_PYTHON_POSIX = ROOT / "backend" / ".venv" / "bin" / "python"

TUNNEL_URL = re.compile(rb"https://[a-z0-9-]+\.trycloudflare\.com")
TUNNEL_TIMEOUT_S = 60

# Printed after the tunnel comes up: every redirect URI that has to match a
# console entry. The hostname changes each run, so this list is the thing you
# paste, not something you remember.
REDIRECT_PATHS = [
    ("Google  ", "/api/auth/youtube/callback"),
    ("Google  ", "/api/login/google/callback"),
    ("Meta    ", "/api/auth/meta/callback"),
    ("Meta    ", "/api/login/meta/callback"),
]

COLOURS = {"tunnel": "\033[35m", "backend": "\033[36m", "frontend": "\033[32m"}
RESET = "\033[0m"


def say(name: str, line: str) -> None:
    colour = COLOURS.get(name)
    tag = f"{colour}[{name}]{RESET}" if colour else f"[{name}]"
    print(f"{tag} {line}".rstrip(), flush=True)


class Proc:
    """A child process whose output is prefixed and merged into this one."""

    def __init__(self, name: str, args: list[str], cwd: Path | None = None) -> None:
        self.name = name
        self.popen = subprocess.Popen(
            args,
            cwd=str(cwd or ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            # Keeps Ctrl+C from reaching children directly on Windows, so this
            # script decides the shutdown order instead of racing them.
            creationflags=(
                subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
            ),
        )
        self.lines: list[bytes] = []
        self._pump = threading.Thread(target=self._read, daemon=True)
        self._pump.start()

    def _read(self) -> None:
        assert self.popen.stdout is not None
        for raw in self.popen.stdout:
            self.lines.append(raw)
            say(self.name, raw.decode(errors="replace").rstrip())

    def stop(self) -> None:
        if self.popen.poll() is not None:
            return
        self.popen.terminate()
        try:
            self.popen.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.popen.kill()


# name on PATH -> winget package, for the two things no language package
# manager can install for us.
WINGET_PACKAGES = {
    "npm": ("OpenJS.NodeJS.LTS", "Node.js"),
    "cloudflared": ("Cloudflare.cloudflared", "cloudflared"),
}


def run(args, cwd=None) -> int:
    """Run something to completion, with its output inline."""
    say("setup", "$ " + " ".join(str(a) for a in args))
    return subprocess.call([str(a) for a in args], cwd=str(cwd or ROOT))


def _find_after_install(name: str):
    """winget only updates PATH for new processes, so this one cannot see what
    it just installed. Look where these two actually land."""
    program_files = Path(os.environ.get("ProgramFiles", "C:/Program Files"))
    program_files_x86 = Path(
        os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")
    )
    for folder in (
        program_files / "nodejs",
        program_files_x86 / "cloudflared",
        program_files / "cloudflared",
    ):
        for suffix in (".exe", ".cmd", ""):
            candidate = folder / (name + suffix)
            if candidate.exists():
                os.environ["PATH"] = str(folder) + os.pathsep + os.environ["PATH"]
                return str(candidate)
    return None


def ensure_tool(name: str) -> str:
    """Path to `name`, installed with winget first if it is missing."""
    found = shutil.which(name)
    if found:
        return found

    package, label = WINGET_PACKAGES[name]
    if os.name != "nt" or shutil.which("winget") is None:
        sys.exit(f"{label} is not installed, and there is no winget to install it.")

    say("setup", f"{label} is missing - installing it with winget")
    run([
        "winget", "install", "--id", package,
        "--accept-source-agreements", "--accept-package-agreements",
        "--disable-interactivity",
    ])

    found = shutil.which(name) or _find_after_install(name)
    if not found:
        sys.exit(
            f"{label} installed, but {name} is still not on PATH in this shell. "
            "Open a new terminal and run this again."
        )
    return found


def _install_requirements(python: str) -> None:
    run([python, "-m", "pip", "install", "--upgrade", "pip", "--quiet"])
    if run([python, "-m", "pip", "install", "-r", "backend/requirements.txt"]) != 0:
        sys.exit("pip install failed.")


def ensure_backend() -> str:
    """The virtualenv and its requirements, created on first run."""
    python = next(
        (str(p) for p in (BACKEND_PYTHON, BACKEND_PYTHON_POSIX) if p.exists()), None
    )
    if python is None:
        say("setup", "creating backend/.venv")
        if run([sys.executable, "-m", "venv", str(ROOT / "backend" / ".venv")]) != 0:
            sys.exit("Could not create the virtualenv.")
        python = next(
            str(p) for p in (BACKEND_PYTHON, BACKEND_PYTHON_POSIX) if p.exists()
        )
        _install_requirements(python)
        return python

    # The cheapest honest check that the requirements are really in there.
    probe = subprocess.call(
        [python, "-c", "import fastapi, uvicorn, httpx, cryptography, googleapiclient"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if probe != 0:
        say("setup", "backend requirements are missing or incomplete")
        _install_requirements(python)
    return python


def ensure_frontend(npm: str) -> None:
    if (ROOT / "frontend" / "node_modules").is_dir():
        return
    say("setup", "installing frontend dependencies")
    if run([npm, "--prefix", "frontend", "install"]) != 0:
        sys.exit("npm install failed.")


def ensure_env_file() -> None:
    """A .env with a usable key, so a clean clone starts without hand-editing."""
    if ENV_FILE.exists():
        return
    example = ROOT / "backend" / ".env.example"
    if not example.exists():
        sys.exit(f"Neither {ENV_FILE} nor {example} exists.")

    from base64 import urlsafe_b64encode
    from secrets import token_bytes

    key = urlsafe_b64encode(token_bytes(32)).decode()
    text = re.sub(
        r"^TOKEN_ENCRYPTION_KEY=.*$",
        "TOKEN_ENCRYPTION_KEY=" + key,
        example.read_text(encoding="utf-8"),
        1,
        re.M,
    )
    ENV_FILE.write_text(text, encoding="utf-8")
    say("setup", "created backend/.env from the example, with a fresh key")
    say("setup", "fill in GOOGLE_* and META_* before connecting anything")


def port_is_free(port: int) -> bool:
    import socket

    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def set_public_base_url(url: str) -> bool:
    """Point the backend at the tunnel. Returns True if the file changed."""
    if not ENV_FILE.exists():
        sys.exit(f"{ENV_FILE} does not exist. Copy backend/.env.example to it first.")

    text = ENV_FILE.read_text(encoding="utf-8")
    current = re.search(r"^PUBLIC_BASE_URL=(.*)$", text, re.M)
    if current and current.group(1).strip() == url:
        return False

    if current:
        text = re.sub(r"^PUBLIC_BASE_URL=.*$", f"PUBLIC_BASE_URL={url}", text, 1, re.M)
    else:
        text += f"\nPUBLIC_BASE_URL={url}\n"
    ENV_FILE.write_text(text, encoding="utf-8")
    return True


def start_tunnel(port: int) -> tuple[Proc, str]:
    cloudflared = ensure_tool("cloudflared")
    proc = Proc("tunnel", [cloudflared, "tunnel", "--url", f"http://localhost:{port}"])

    deadline = time.monotonic() + TUNNEL_TIMEOUT_S
    while time.monotonic() < deadline:
        for line in list(proc.lines):
            found = TUNNEL_URL.search(line)
            if found:
                return proc, found.group().decode()
        if proc.popen.poll() is not None:
            sys.exit("cloudflared exited before printing a URL. See [tunnel] above.")
        time.sleep(0.2)

    proc.stop()
    sys.exit(f"No tunnel URL after {TUNNEL_TIMEOUT_S}s. See [tunnel] above.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    # No `choices` here: argparse validates the empty default against it, so
    # the no-argument form — the whole point of this script — would fail.
    parser.add_argument(
        "targets",
        nargs="*",
        metavar="{tunnel,backend,frontend,setup}",
        help="what to start (default: all three)",
    )
    parser.add_argument("--no-tunnel", action="store_true")
    parser.add_argument("--port", type=int, default=8000, help="backend port")
    args = parser.parse_args()

    known = {"tunnel", "backend", "frontend", "setup"}
    unknown = set(args.targets) - known
    if unknown:
        parser.error(f"unknown target(s): {', '.join(sorted(unknown))}")

    wanted = set(args.targets) or {"tunnel", "backend", "frontend"}

    # Setup runs for whatever is about to start, so the first run on a clean
    # clone needs no separate install step.
    setup_only = wanted == {"setup"}
    wanted.discard("setup")

    ensure_env_file()
    npm = ensure_tool("npm") if ("frontend" in wanted or setup_only) else None
    if "backend" in wanted or setup_only:
        ensure_backend()
    if npm is not None:
        ensure_frontend(npm)
    if setup_only:
        ensure_tool("cloudflared")
        say("setup", "everything is installed")
        return 0
    if args.no_tunnel:
        wanted.discard("tunnel")

    if "backend" in wanted and not port_is_free(args.port):
        sys.exit(
            f"Port {args.port} is already in use, so the backend cannot start there.\n"
            "Find it with:  netstat -ano | findstr :%d\n"
            "Then stop that process, or pass --port to use another one — but note\n"
            "the Vite proxy and the tunnel both point at %d."
            % (args.port, args.port)
        )

    running: list[Proc] = []
    try:
        if "tunnel" in wanted:
            tunnel, url = start_tunnel(args.port)
            running.append(tunnel)
            changed = set_public_base_url(url)
            say("tunnel", f"public URL: {url}")
            say("tunnel", "PUBLIC_BASE_URL " + ("updated" if changed else "unchanged"))
            if changed:
                say("tunnel", "Register these redirect URIs before signing in:")
                for provider, path in REDIRECT_PATHS:
                    say("tunnel", f"  {provider} {url}{path}")

        if "backend" in wanted:
            running.append(
                Proc(
                    "backend",
                    [
                        ensure_backend(),
                        "-m",
                        "uvicorn",
                        "app.main:app",
                        "--app-dir",
                        "backend",
                        "--port",
                        str(args.port),
                        "--reload",
                    ],
                )
            )

        if "frontend" in wanted:
            assert npm is not None
            running.append(Proc("frontend", [npm, "--prefix", "frontend", "run", "dev"]))

        say("dev", "Ctrl+C to stop everything")
        while True:
            for proc in running:
                code = proc.popen.poll()
                if code is not None:
                    say("dev", f"{proc.name} exited ({code}) — stopping the rest")
                    return code or 1
            time.sleep(0.4)

    except KeyboardInterrupt:
        say("dev", "stopping")
        return 0
    finally:
        # Reverse order: the tunnel started first and should outlive the thing
        # it points at, so its last log lines are not about a refused port.
        for proc in reversed(running):
            proc.stop()


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal.default_int_handler)
    sys.exit(main())
