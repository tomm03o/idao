"""Sandboxed agent workspace (files + terminal).

    from claude_science.workspace import Workspace, workspace_tools
    ws = Workspace()
    tools = workspace_tools(ws)   # write_file / read_file / list_files / run_python / run_bash
"""

from .sandbox import Workspace, workspace_tools

__all__ = ["Workspace", "workspace_tools"]
