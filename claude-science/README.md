# Claude Science

**An agent harness and benchmark for biological & pharmaceutical simulation.**

Claude Science is to scientific discovery what Claude Code is to software: a
*harness* that gives an AI agent instruments, a workspace, and an auditable
record, plus a *benchmark* to measure how well the agent actually does the
science — and the plumbing to let it work autonomously across many tasks.

Instead of a shell and a filesystem, agents here get **in-silico laboratories**:
pharmacokinetic models, dose-response assays, docking/lead-optimisation, and
gene-knockout networks. Each lab exposes its instruments as *tools*, hides a
ground truth the agent must discover, and scores the agent's final answer.

It runs **out of the box with no API key** (deterministic baseline agents), and
plugs into the **Claude API** for a real LLM-driven agent.

---

## Why

Evaluating whether a model can *do science* needs more than a Q&A dataset. It
needs closed-loop tasks where the agent must **design experiments, spend a
limited budget, reason from noisy data, and commit to a decision** — then be
graded on the decision's quality. Claude Science provides that loop, packaged
as a benchmark so results are comparable across agents and models.

## Install

```bash
cd claude-science
pip install -e .            # core, zero dependencies
pip install -e ".[claude]"  # + anthropic SDK for the real agent
pip install -e ".[dev]"     # + pytest
```

## Quick start

```bash
# what labs exist
python -m claude_science env list

# run the expert baseline on one lab and watch the transcript
python -m claude_science agent run --env assay --agent heuristic

# score the full benchmark suite (no API key needed)
python -m claude_science bench run --agent heuristic --seeds 0,1,2

# score a real Claude agent (needs ANTHROPIC_API_KEY)
export ANTHROPIC_API_KEY=sk-...
python -m claude_science bench run --agent claude --model claude-fable-5 --out report.json
```

## The environments (labs)

| key        | capability probed              | the task |
|------------|--------------------------------|----------|
| `pkpd`     | quantitative pharmacology      | Pick an oral dose that hits a target plasma Cmax in the therapeutic window (one-compartment PK model, hidden parameters). |
| `assay`    | experiment design under budget | Estimate a compound's IC50 from a limited number of noisy dose-response reads (Hill curve). |
| `docking`  | multi-objective optimisation   | Optimise a ligand's descriptors for binding affinity while staying drug-like (Lipinski). |
| `knockout` | causal intervention            | Find the single gene knockout that most lowers a disease marker in a regulatory network. |

Each supports `--difficulty low|medium|high` (more noise, tighter budgets) and
any integer `--seed` (a fresh randomised instance), so a benchmark is many
independent tasks, not one lucky roll.

## Agents

| agent       | what it is | needs |
|-------------|-----------|-------|
| `heuristic` | replays each lab's expert reference policy — the "ceiling" baseline | nothing |
| `random`    | random valid tool calls — the "floor" baseline | nothing |
| `claude`    | a real tool-use loop against the Claude Messages API | `anthropic` + `ANTHROPIC_API_KEY` |

Scores are normalised so **0 ≈ random floor** and **1 ≈ expert policy**, which
makes an agent's number immediately interpretable.

## Architecture

```
claude_science/
├── harness/          # the domain-agnostic engine
│   ├── tools.py        Tool, ToolRegistry, ToolResult  (Claude-API-shaped schemas)
│   ├── agent.py        Agent loop: AnthropicAgent, HeuristicAgent, RandomAgent
│   └── transcript.py   auditable step-by-step episode record
├── envs/             # the science
│   ├── base.py         Environment ABC: ground truth + tools + scorer + reference policy
│   ├── pkpd.py assay.py docking.py knockout.py
├── benchmark/        # evaluation
│   ├── runner.py       BenchmarkRunner → BenchmarkReport (per-capability scorecard)
│   └── report.py       human-readable scorecard
└── cli.py            # `python -m claude_science ...`
```

The contract is small. An **Environment** samples a hidden ground truth,
registers domain **tools** (always including `submit`), scores a submission to
`[0,1]`, and exposes an expert **reference policy** (which both provides the
`heuristic` baseline and self-tests that the lab is solvable). An **Agent**
takes an environment and returns a **Transcript**. That's the whole extension
surface.

## Add a new lab

```python
from claude_science.envs.base import Environment

class MyEnv(Environment):
    key = "myenv"; title = "..."; capability = "..."
    def _build(self):          # sample hidden truth, register tools
        ...
    def submit_schema(self):   # JSON schema for the submit tool
        ...
    def task_prompt(self):     # what the agent is told
        ...
    def score(self, payload):  # -> float in [0, 1]
        ...
    def reference_policy(self): # -> list of {"tool", "args"} an expert would run
        ...
```

Register it in `envs/__init__.py` and it appears in the CLI and benchmark
automatically. The `test_reference_policy_solves` test will immediately verify
your scorer and simulator agree.

## Autonomy

The harness *is* the autonomy layer: an agent runs a full episode — many tool
calls, its own experiment design, a committed answer — with no human in the
loop, bounded by `--max-steps`. The `BenchmarkRunner` then drives an agent
across dozens of independent tasks unattended and produces a signed-off report
(`--out report.json` includes every transcript for review). To run continuously
(e.g. nightly regression of a model against the suite), wire `bench run --out`
into cron or CI.

## Tests

```bash
python -m pytest -q     # 29 tests: every lab is solvable, tools dispatch,
                        # expert beats random, reports aggregate correctly
```

## Safety note

All "laboratories" here are abstract mathematical simulators (PK equations, Hill
curves, toy descriptor scoring, small regulatory networks). They contain no
real chemical, biological, or synthesis information — they exist to measure
*reasoning and experiment-design* capability, not to provide laboratory
protocols.
