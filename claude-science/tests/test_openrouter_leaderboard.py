"""Tests for the OpenRouter backend and the multi-agent leaderboard.

Network is not exercised here (no API key in CI); we test schema conversion,
message shaping, spec parsing, and the baseline leaderboard path.
"""

import pytest

from claude_science import make_env
from claude_science.benchmark import (BenchmarkRunner, make_agent,
                                      run_leaderboard, render_leaderboard)
from claude_science.harness import HeuristicAgent, OpenRouterAgent, RandomAgent
from claude_science.harness.openrouter import _clean_assistant


def test_openai_tool_schema_conversion():
    env = make_env("admet", seed=0)
    tools = OpenRouterAgent._to_openai_tools(env.tools())
    assert tools and all(t["type"] == "function" for t in tools)
    for t in tools:
        assert {"name", "description", "parameters"} <= set(t["function"])
    assert any(t["function"]["name"] == "submit" for t in tools)


def test_clean_assistant_keeps_tool_calls():
    msg = {"role": "assistant", "content": "ok", "extra": "drop",
           "tool_calls": [{"id": "c1", "type": "function",
                           "function": {"name": "submit",
                                        "arguments": '{"x":1}'}}]}
    out = _clean_assistant(msg)
    assert out["role"] == "assistant" and "extra" not in out
    assert out["tool_calls"][0]["function"]["name"] == "submit"


def test_openrouter_requires_key():
    agent = OpenRouterAgent(model="tencent/hy3:free", api_key=None)
    agent._api_key = None
    with pytest.raises(RuntimeError):
        agent._post({"model": "x", "messages": []})


def test_make_agent_specs():
    assert isinstance(make_agent("heuristic"), HeuristicAgent)
    assert isinstance(make_agent("random"), RandomAgent)
    a = make_agent("openrouter:tencent/hy3:free")
    assert isinstance(a, OpenRouterAgent) and a.model == "tencent/hy3:free"
    with pytest.raises(ValueError):
        make_agent("bogus")


def test_leaderboard_ranks_baselines():
    runner = BenchmarkRunner(envs=["variant", "ic50"], seeds=[0],
                             difficulties=["low"])
    lb = run_leaderboard(["heuristic", "random"], runner, progress=False)
    ranked = lb.ranked()
    assert ranked[0][0] == "heuristic"          # expert wins
    assert ranked[0][1].overall() >= ranked[-1][1].overall()
    assert "LEADERBOARD" in render_leaderboard(lb)
