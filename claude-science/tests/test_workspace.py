from claude_science.workspace import Workspace, workspace_tools


def test_file_roundtrip_and_list():
    ws = Workspace()
    try:
        ws.write_file("a/b.txt", "hello")
        assert ws.read_file("a/b.txt") == "hello"
        assert "a/b.txt" in ws.list_files()
    finally:
        ws.cleanup()


def test_path_escape_blocked():
    ws = Workspace()
    try:
        for bad in ("../escape.txt", "/etc/passwd", "a/../../x"):
            try:
                ws.write_file(bad, "x")
                assert False, f"escape not blocked: {bad}"
            except ValueError:
                pass
    finally:
        ws.cleanup()


def test_run_python_captures_output():
    ws = Workspace()
    try:
        r = ws.run_python("print(6 * 7)")
        assert r["exit_code"] == 0
        assert r["stdout"].strip() == "42"
    finally:
        ws.cleanup()


def test_run_python_timeout():
    ws = Workspace(timeout=1)
    try:
        r = ws.run_python("import time; time.sleep(5)")
        assert r["exit_code"] == 124
    finally:
        ws.cleanup()


def test_workspace_tools_registry():
    reg = workspace_tools()
    try:
        assert {"write_file", "read_file", "list_files", "run_python",
                "run_bash"} <= set(reg.names())
        assert reg.dispatch("write_file", {"path": "x.txt", "content": "y"}).ok
    finally:
        reg._workspace.cleanup()
