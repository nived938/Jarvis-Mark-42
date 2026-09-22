"""
JARVIS process and lifecycle manager.

Keeps process-level restart/shutdown separate from JarvisLive so the assistant
can restart itself without duplicating OS-specific process code in main.py.
Sleep/wake remain application-session state and are delegated by main.py.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


class JarvisManager:
    def __init__(self, logger=None):
        self._logger = logger or (lambda _msg: None)
        self._busy = False

    @property
    def busy(self) -> bool:
        return self._busy

    def _log(self, message: str) -> None:
        try:
            self._logger(str(message))
        except Exception:
            pass

    def _command(self) -> list[str]:
        if getattr(sys, "frozen", False):
            return [sys.executable, *sys.argv[1:]]
        script = Path(__file__).resolve().with_name("main.py")
        return [sys.executable, str(script), *sys.argv[1:]]

    def start_new_instance(self) -> bool:
        """Start a fresh JARVIS process using the same launch mode."""
        try:
            env = os.environ.copy()
            env["JARVIS_RESTARTED"] = "1"
            kwargs = {
                "cwd": str(Path(__file__).resolve().parent),
                "env": env,
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
            }

            if os.name == "nt":
                flags = 0
                flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
                if flags:
                    kwargs["creationflags"] = flags
            else:
                kwargs["start_new_session"] = True

            subprocess.Popen(self._command(), **kwargs)
            self._log("SYS: New JARVIS process started.")
            return True
        except Exception as exc:
            self._log(f"ERR: Could not start JARVIS: {exc}")
            return False

    def restart(self) -> bool:
        """Start a new instance, then terminate this process."""
        if self._busy:
            return False
        self._busy = True
        if not self.start_new_instance():
            self._busy = False
            return False
        self._log("SYS: Restarting JARVIS.")
        return True

    def shutdown(self) -> None:
        """Terminate the current JARVIS process immediately."""
        self._busy = True
        self._log("SYS: Shutting down JARVIS.")
        os._exit(0)
