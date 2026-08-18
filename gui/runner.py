"""Background test-run orchestration for the GUI.

Launches ``run_perf.py`` as a child process (exactly as a teammate would from the
CLI), captures its combined stdout/stderr line-by-line, and exposes the live log +
status to the Flask layer. Only ONE run is allowed at a time because a run drives a
single Playwright browser.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class RunJob:
    args: List[str]
    started_at: float = field(default_factory=time.time)
    lines: List[str] = field(default_factory=list)
    status: str = "running"  # running | finished | error | stopped
    returncode: Optional[int] = None
    _proc: Optional[subprocess.Popen] = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def append(self, line: str) -> None:
        with self._lock:
            self.lines.append(line)

    def snapshot(self, since: int = 0) -> dict:
        with self._lock:
            return {
                "status": self.status,
                "returncode": self.returncode,
                "started_at": self.started_at,
                "total_lines": len(self.lines),
                "lines": self.lines[since:],
            }


class TestRunner:
    """Holds the single active/last run job and manages its lifecycle."""

    def __init__(self) -> None:
        self._job: Optional[RunJob] = None
        self._lock = threading.Lock()

    @property
    def job(self) -> Optional[RunJob]:
        return self._job

    def is_running(self) -> bool:
        return self._job is not None and self._job.status == "running"

    def start(self, cli_args: List[str]) -> RunJob:
        with self._lock:
            if self.is_running():
                raise RuntimeError("A test run is already in progress.")

            cmd = [sys.executable, "-u", str(PROJECT_ROOT / "run_perf.py"), *cli_args]
            job = RunJob(args=cmd)

            creationflags = 0
            if os.name == "nt":
                # New process group so we can deliver CTRL_BREAK for a graceful stop
                # (mirrors the Ctrl+C flow run_perf.py uses to export reports).
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

            proc = subprocess.Popen(
                cmd,
                cwd=str(PROJECT_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=creationflags,
            )
            job._proc = proc
            self._job = job

        job.append(f"$ {' '.join(cli_args)}")
        threading.Thread(target=self._pump, args=(job,), daemon=True).start()
        return job

    def _pump(self, job: RunJob) -> None:
        proc = job._proc
        assert proc is not None and proc.stdout is not None
        try:
            for line in proc.stdout:
                job.append(line.rstrip("\n"))
        except Exception as exc:  # pragma: no cover - defensive
            job.append(f"[gui] error reading output: {exc}")
        finally:
            proc.wait()
            with job._lock:
                job.returncode = proc.returncode
                if job.status == "running":
                    job.status = "finished" if proc.returncode == 0 else "error"

    def stop(self) -> bool:
        """Request a graceful stop of the active run. Returns True if a run was stopped."""
        with self._lock:
            job = self._job
            if job is None or job.status != "running" or job._proc is None:
                return False
            proc = job._proc

        try:
            if os.name == "nt":
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                proc.send_signal(signal.SIGINT)
        except Exception:
            try:
                proc.terminate()
            except Exception:
                pass

        with job._lock:
            job.status = "stopped"
            job.append("[gui] stop requested")
        return True


def build_cli_args(payload: dict) -> List[str]:
    """Translate a GUI form payload into ``run_perf.py`` CLI arguments.

    Only known, whitelisted options are forwarded - nothing from the payload is passed
    through unchecked.
    """
    args: List[str] = []
    mode = payload.get("mode", "scenario")
    if mode not in ("passive", "scenario"):
        raise ValueError(f"Invalid mode: {mode!r}")
    args += ["--mode", mode]

    room = (payload.get("room") or "").strip()
    if room:
        args += ["--room", room]

    if mode == "scenario":
        scenario = (payload.get("scenario") or "").strip()
        if scenario:
            args += ["--scenario", scenario]
        iterations = payload.get("iterations")
        if iterations:
            args += ["--iterations", str(int(iterations))]
        if payload.get("headless"):
            args += ["--headless"]
    else:  # passive
        if payload.get("skip_login"):
            args += ["--skip-login"]
        duration = payload.get("duration")
        if duration:
            args += ["--duration", str(float(duration))]

    api_threshold = payload.get("api_threshold")
    if api_threshold:
        args += ["--api-threshold", str(int(api_threshold))]

    output_dir = (payload.get("output_dir") or "").strip()
    if output_dir:
        args += ["--output-dir", output_dir]

    return args
