from claude_science import make_env
from claude_science.benchmark import BenchmarkRunner, render_scorecard
from claude_science.harness import HeuristicAgent
from claude_science.harness.tools import ToolRegistry, ToolResult


def test_tool_registry_dispatch():
    reg = ToolRegistry()
    reg.add(
        "add",
        "add two numbers",
        {"type": "object", "properties": {"a": {"type": "number"},
                                           "b": {"type": "number"}},
         "required": ["a", "b"]},
        lambda a, b: a + b,
    )
    assert reg.dispatch("add", {"a": 2, "b": 3}).content == 5
    assert not reg.dispatch("add", {"a": 2}).ok           # missing required
    assert not reg.dispatch("nope", {}).ok                # unknown tool


def test_tool_error_is_captured():
    reg = ToolRegistry()
    reg.add("boom", "raises", {"type": "object", "properties": {}}, lambda: 1 / 0)
    res = reg.dispatch("boom", {})
    assert isinstance(res, ToolResult) and not res.ok and "ZeroDivision" in res.error


def test_transcript_records_calls():
    env = make_env("variant", seed=1, difficulty="low")
    tr = HeuristicAgent().run(env)
    assert tr.n_tool_calls() >= 1
    assert tr.final() is not None
    assert "task_id" in tr.to_dict()


def test_benchmark_runner_produces_report():
    runner = BenchmarkRunner(envs=["ic50", "pkpd"], seeds=[0, 1],
                             difficulties=["low"])
    report = runner.run(HeuristicAgent())
    assert len(report.results) == 4
    assert 0.0 <= report.overall() <= 1.0
    assert set(report.by_capability())  # non-empty
    assert "Scorecard" in render_scorecard(report)


def test_anthropic_schema_shape():
    env = make_env("admet", seed=0)
    schemas = env.tools().anthropic_schemas()
    for s in schemas:
        assert {"name", "description", "input_schema"} <= set(s)
