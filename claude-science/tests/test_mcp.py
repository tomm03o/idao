"""Tests for the dependency-free MCP server (direct JSON-RPC dispatch)."""

import json

import pytest

from claude_science.mcp_server import MCPServer


@pytest.fixture
def server():
    s = MCPServer()
    yield s
    s.cleanup()


def _call(server, name, arguments=None, mid=1):
    resp = server.handle({"jsonrpc": "2.0", "id": mid, "method": "tools/call",
                          "params": {"name": name, "arguments": arguments or {}}})
    return json.loads(resp["result"]["content"][0]["text"])


def test_initialize(server):
    resp = server.handle({"jsonrpc": "2.0", "id": 0, "method": "initialize"})
    assert resp["result"]["serverInfo"]["name"] == "claude-science"
    assert "protocolVersion" in resp["result"]


def test_tools_list_includes_science_db_and_bench(server):
    resp = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = {t["name"] for t in resp["result"]["tools"]}
    for expected in ("chem_descriptors", "pubchem_compound", "run_python",
                     "rag_search", "bench_start", "bench_act", "bench_score"):
        assert expected in names
    # schemas must not leak the internal handler
    assert all("_handler" not in t for t in resp["result"]["tools"])


def test_science_tool_over_mcp(server):
    out = _call(server, "chem_descriptors", {"smiles": "CC(=O)Oc1ccccc1C(=O)O"})
    # tool returns a JSON string of the descriptor dict
    assert "180.16" in out or "mol_weight" in out


def test_play_full_episode_over_mcp(server):
    ep = _call(server, "bench_start", {"env_key": "admet", "seed": 0,
                                       "difficulty": "low"})
    assert "task_id" in ep and "instruments" in ep
    # a trivial (wrong) submit still returns a numeric score and ends the episode
    import re
    smi = re.search(r"- (\S+)", ep["task"]).group(1)
    res = _call(server, "bench_act", {"tool": "submit", "arguments": {"smiles": smi}})
    assert res["episode_done"] is True
    assert 0.0 <= res["score"] <= 1.0


def test_unknown_tool_is_rpc_error(server):
    resp = server.handle({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                          "params": {"name": "nope", "arguments": {}}})
    assert "error" in resp
