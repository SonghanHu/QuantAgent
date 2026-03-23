"""One-command dev launcher for the agent dashboard."""

from __future__ import annotations

import signal
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = REPO_ROOT / "frontend"


def main() -> int:
    backend = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server.app:app", "--host", "127.0.0.1", "--port", "8000", "--reload"],
        cwd=REPO_ROOT,
    )
    frontend = subprocess.Popen(
        ["npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", "5173"],
        cwd=FRONTEND_DIR,
    )

    def shutdown(*_: object) -> None:
        for proc in (backend, frontend):
            if proc.poll() is None:
                proc.terminate()
        for proc in (backend, frontend):
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print("Dashboard dev servers running:")
    print("  backend:  http://127.0.0.1:8000")
    print("  frontend: http://127.0.0.1:5173")
    print("Press Ctrl+C to stop both.")

    while True:
        backend_code = backend.poll()
        frontend_code = frontend.poll()
        if backend_code is not None or frontend_code is not None:
            print(f"backend exited={backend_code}, frontend exited={frontend_code}")
            shutdown()
        time.sleep(1)


if __name__ == "__main__":
    raise SystemExit(main())
