"""A sandboxed workspace: a filesystem + terminal an agent can drive.

This gives agents the "IDE" surface of Claude Code -- write files, read them
back, list a tree, run Python, run a shell command -- but confined to a scratch
directory with wall-clock timeouts and output caps. It is the substrate for a
lab agent that builds its own analysis scripts and iterates.

Security note: commands execute in a subprocess with ``cwd`` pinned to the
workspace and a timeout, but this is *not* a hardened jail. For untrusted models
run the whole process inside a container/VM; the confinement here is
convenience + accident-avoidance, not a security boundary.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Dict, List

from ..harness.tools import ToolRegistry

_MAX_OUTPUT = 20_000  # chars returned to the agent


class Workspace:
    def __init__(self, root: str | None = None, timeout: int = 20):
        self.root = os.path.realpath(root or tempfile.mkdtemp(prefix="cs_ws_"))
        os.makedirs(self.root, exist_ok=True)
        self.timeout = timeout

    # -- path safety ----------------------------------------------------- #
    def _resolve(self, path: str) -> str:
        full = os.path.realpath(os.path.join(self.root, path))
        if not (full == self.root or full.startswith(self.root + os.sep)):
            raise ValueError(f"path escapes workspace: {path!r}")
        return full

    # -- file ops -------------------------------------------------------- #
    def write_file(self, path: str, content: str) -> str:
        full = self._resolve(path)
        os.makedirs(os.path.dirname(full) or self.root, exist_ok=True)
        with open(full, "w") as fh:
            fh.write(content)
        return f"wrote {len(content)} bytes to {path}"

    def read_file(self, path: str) -> str:
        with open(self._resolve(path)) as fh:
            return fh.read()[:_MAX_OUTPUT]

    def list_files(self, path: str = ".") -> List[str]:
        base = self._resolve(path)
        out: List[str] = []
        for dirpath, _dirs, files in os.walk(base):
            rel = os.path.relpath(dirpath, self.root)
            for f in files:
                out.append(os.path.normpath(os.path.join(rel, f)))
        return sorted(out)

    def delete(self, path: str) -> str:
        full = self._resolve(path)
        if os.path.isdir(full):
            shutil.rmtree(full)
        elif os.path.exists(full):
            os.remove(full)
        return f"removed {path}"

    # -- execution ------------------------------------------------------- #
    def run_python(self, code: str) -> Dict[str, Any]:
        script = os.path.join(self.root, "_cell.py")
        with open(script, "w") as fh:
            fh.write(code)
        return self._exec([sys.executable, "-I", script])

    def run_bash(self, command: str) -> Dict[str, Any]:
        return self._exec(["bash", "-lc", command])

    def _exec(self, argv: List[str]) -> Dict[str, Any]:
        try:
            proc = subprocess.run(
                argv, cwd=self.root, capture_output=True, text=True,
                timeout=self.timeout,
            )
            return {
                "exit_code": proc.returncode,
                "stdout": proc.stdout[:_MAX_OUTPUT],
                "stderr": proc.stderr[:_MAX_OUTPUT],
            }
        except subprocess.TimeoutExpired:
            return {"exit_code": 124, "stdout": "",
                    "stderr": f"timed out after {self.timeout}s"}

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


def workspace_tools(ws: Workspace | None = None) -> ToolRegistry:
    """Expose a Workspace as harness tools an agent can call."""
    ws = ws or Workspace()
    reg = ToolRegistry()
    reg.add("write_file", "Create or overwrite a file in the workspace.",
            {"type": "object", "properties": {"path": {"type": "string"},
             "content": {"type": "string"}}, "required": ["path", "content"]},
            ws.write_file)
    reg.add("read_file", "Read a file from the workspace.",
            {"type": "object", "properties": {"path": {"type": "string"}},
             "required": ["path"]}, ws.read_file)
    reg.add("list_files", "List all files in the workspace (recursive).",
            {"type": "object", "properties": {"path": {"type": "string"}},
             "required": []}, ws.list_files)
    reg.add("run_python", "Execute a Python snippet in the workspace and return "
            "stdout/stderr/exit code.",
            {"type": "object", "properties": {"code": {"type": "string"}},
             "required": ["code"]}, ws.run_python)
    reg.add("run_bash", "Run a shell command in the workspace (timeout-bounded).",
            {"type": "object", "properties": {"command": {"type": "string"}},
             "required": ["command"]}, ws.run_bash)
    reg._workspace = ws  # keep a handle
    return reg
