# Claude Science (open harness & benchmark)

**An agent harness, a validated scientific tool library, and a capability
benchmark for AI agents doing drug-discovery-style computation.**

> Context. Anthropic ships a commercial product called **Claude Science** — a
> workbench for drug discovery with 60+ built-in functions across genomics,
> single-cell, proteomics, structural biology and cheminformatics, MCP
> connectors (Benchling, 10x Genomics, PubMed, …) and Agent Skills
> ([announcement](https://www.anthropic.com/news/claude-for-life-sciences),
> [STAT](https://www.statnews.com/2026/06/30/anthropic-release-claude-science-ceo-dario-amodei/)).
> This repository is **not** that product. It is an open, self-hostable
> *harness + benchmark* in the same spirit: give an agent real scientific
> instruments in a sandbox, let it work autonomously, and **measure** how well
> it does the science. It is designed to be embedded in, or evaluated against,
> a pharma/bioinformatics team's own stack.

The distinguishing feature versus a demo: **every instrument is a real,
literature-standard computation**, not a toy surrogate. Cheminformatics runs on
**RDKit**, pharmacokinetics and curve-fitting on **SciPy**, sequence analysis on
validated dynamic-programming alignment, and 3D energetics on the **MMFF94**
force field. The numbers an agent sees — a QED score, an IC50 from a 4PL fit, a
half-life from non-compartmental analysis, a conformer energy in kcal/mol — are
the same numbers a computational chemist or pharmacometrician would compute.

---

## What's in the platform (v0.3)

| layer | package | what it gives you |
|-------|---------|-------------------|
| validated science | `science` | RDKit/SciPy/NumPy computations (below) |
| database access | `data_sources` | live cached connectors to PubChem, ChEMBL, UniProt, RCSB PDB |
| benchmark | `envs` + `benchmark` | six self-grading environments + scorecard |
| RL / training data | `rl` | verifiable tasks, judges, and SFT/DPO/RLVR export |
| agent workspace | `workspace` | sandboxed files + terminal (`run_python`/`run_bash`) |
| composed toolkit | `toolkits.lab_bench` | science + databases + workspace as one agent tool surface |
| research | `research` | a novel algorithm, formulated and empirically validated |

**1. A scientific tool library** (`claude_science.science`) — usable on its own,
independent of any agent:

| module   | backend | what it does |
|----------|---------|--------------|
| `chem`   | RDKit   | descriptors (Crippen logP, TPSA, …), Lipinski/Veber rules, Bickerton **QED**, Ertl **SA score**, ECFP4 fingerprints + Tanimoto virtual screening, structural-alert (PAINS-style) filtering |
| `pk`     | SciPy   | 1-/2-compartment PK models, **non-compartmental analysis** (Cmax, AUC linear-up/log-down, terminal t½, CL/F, Vz/F), **4-parameter-logistic** dose-response fitting → IC50 ± SE |
| `seq`    | NumPy   | **Needleman–Wunsch** / **Smith–Waterman** alignment, translation, reverse complement, GC content, ORF finding |
| `struct` | RDKit   | **ETKDGv3** conformer embedding, **MMFF94** energy & minimisation, multi-start conformer search |

```python
from claude_science.science import chem, pk
chem.descriptors("CC(=O)Oc1ccccc1C(=O)O")["qed"]      # aspirin QED ≈ 0.55
pk.fit_dose_response(concs, responses)["ic50"]        # IC50 with standard error
```

**2. An agent harness + benchmark** that wraps those tools into closed-loop
tasks and scores an agent's decisions.

## The benchmark: six environments across the real domains

| key         | capability                | the task (all graded on a real computation) |
|-------------|---------------------------|---------------------------------------------|
| `admet`     | cheminformatics           | Pick the best oral candidate from real drug SMILES: Lipinski + Veber, no structural alerts, best QED / SA. |
| `screen`    | virtual screening         | Return the top-k library compounds most similar to a query by ECFP4 Tanimoto. |
| `ic50`      | pharmacology assay        | Design a dose-response experiment under a read budget, fit a 4PL curve, report IC50. |
| `pkpd`      | quantitative pharmacology | Choose an oral dose to hit a target Cmax in the therapeutic window, using NCA on simulated profiles. |
| `variant`   | bioinformatics            | Call a coding mutation (`p.E12K`) from a reference vs variant CDS via alignment + translation. |
| `conformer` | computational chemistry   | Find a molecule's global-minimum MMFF94 conformer energy by seeded multi-start search. |

Each task supports `--difficulty low|medium|high` (more noise, tighter budgets)
and any integer `--seed` (a fresh randomised instance). Scores are normalised so
**0 ≈ random floor** and **1 ≈ expert reference policy**, so an agent's number is
immediately interpretable. On the built-in suite the random baseline scores
**~0.07** and the expert baseline **1.00** — the gap the benchmark measures.

## Agents

| agent       | what it is | needs |
|-------------|-----------|-------|
| `heuristic` | replays each environment's expert reference policy (the ceiling) | nothing |
| `random`    | random valid tool calls (the floor) | nothing |
| `claude`    | a real tool-use loop against the Claude Messages API | `anthropic` + `ANTHROPIC_API_KEY` |

## Database access

Live, disk-cached connectors to the public databases a discovery workflow needs,
exposed both as a Python API and as agent tools:

```bash
python -m claude_science data query pubchem_compound name=imatinib
python -m claude_science data query uniprot_protein accession=P00533
python -m claude_science data query chembl_target_activities target_chembl_id=CHEMBL203
```

```python
from claude_science.data_sources import pubchem, chembl, uniprot
uniprot.sequence("P00533")                       # EGFR, 1210 aa
chembl.activities_for_target("CHEMBL203")        # measured IC50s → QSAR data
```

Responses are cached under `~/.cache/claude_science` so agent loops are free to
re-query and runs reproduce offline.

## Training data & cheap RL with verifiable rewards

The `rl` package turns tasks into **self-grading** training data. Every item
carries a *judge* — a deterministic verifier (numeric tolerance, canonical
SMILES match, IC50 log-fold, set overlap, or a reconstructed environment score)
— so there is no human labeller and no learned reward model. That is what makes
the RL loop cheap.

```bash
# build a mixed dataset (static QA + agentic) and export every training format
python -m claude_science rl build --n-static 200 --rollouts --out-prefix run1
#   → run1.tasks.jsonl  run1.rlvr.jsonl  run1.sft.jsonl  run1.pref.jsonl
```

- **`.sft.jsonl`** — `{"messages":[…]}` from high-reward rollouts (supervised FT)
- **`.pref.jsonl`** — `{"prompt","chosen","rejected"}` DPO pairs
- **`.rlvr.jsonl`** — `{"prompt","verifier":{…}}` for online RL; the verifier
  regenerates the reward on the fly

The reference `OracleSolver`/`NullSolver` make the whole pipeline runnable and
testable with no API key (oracle mean reward 1.00 vs null 0.02); swap in
`AgentSolver(AnthropicAgent(...))` for genuine model rollouts.

## Sandboxed agent workspace (the "IDE")

`workspace.Workspace` gives an agent the Claude-Code surface — files + a terminal
— confined to a scratch dir with timeouts and path-escape protection:

```python
from claude_science.workspace import workspace_tools
tools = workspace_tools()   # write_file / read_file / list_files / run_python / run_bash
```

`toolkits.lab_bench()` composes this with the science library and the database
connectors into **one 18-tool registry** — the full "simulated laboratory" an
autonomous agent drives to plan and run experiments end to end:

```bash
python -m claude_science lab tools     # list the composed bench
```

## Visualization & experiment console

A self-contained, theme-aware HTML dashboard renders the live benchmark
scorecard, the RL-dataset composition, the adaptive-design result, and an
interactive **experiment planner** that composes the exact CLI command to run:

```bash
python -m claude_science.viz --out dashboard.html   # standalone, no assets
```

The layout is information-design first (KPI row → capability meters → detail),
with semantic colour for score bands and `tabular-nums` throughout.

## A novel algorithm, validated in-repo

`research/adaptive_design.py` contributes a **sequential D-optimal experimental
design for IC50 estimation**. For the Hill model, information about log(IC50) is
maximal at the inflection point, so the method locates the active decade from a
few anchor points then spends the remaining budget around the current estimate.

It is validated honestly — the win is real but *conditional*, and the repo says
where:

```bash
python -m claude_science research validate-design
```

| range | n | fixed (median \|log-fold\|) | adaptive | reduction |
|-------|---|------|----------|-----------|
| 4 decades | 6 | 0.10 | 0.15 | −41% |
| 7 decades | 6 | 0.16 | 0.16 | ~0% |
| 10 decades | 6 | 0.28 | 0.22 | **+24%** |
| 10 decades | 8 | 0.15 | 0.11 | **+30%** |

Adaptivity pays off in the wide-range / small-budget primary-screening regime;
a fixed grid is already near-optimal when the range is narrow. This is the kind
of formulate-implement-benchmark loop the harness is meant to accelerate.

## Install

```bash
cd claude-science
pip install -e .            # core: numpy, scipy, rdkit
pip install -e ".[claude]"  # + anthropic SDK for the real agent
pip install -e ".[dev]"     # + pytest
```

## Use

```bash
python -m claude_science env list

# watch the expert baseline solve one lab
python -m claude_science agent run --env admet --agent heuristic

# score the whole suite, no API key needed
python -m claude_science bench run --agent heuristic --seeds 0,1,2

# score a real Claude model and keep every transcript
export ANTHROPIC_API_KEY=sk-...
python -m claude_science bench run --agent claude --model claude-fable-5 \
    --difficulties low,medium --out report.json
```

## Architecture

```
claude_science/
├── science/          # validated scientific computing (usable standalone)
│   ├── chem.py  pk.py  seq.py  struct.py
├── data_sources/     # live cached DB connectors: pubchem, chembl, uniprot, pdb
├── harness/          # domain-agnostic engine
│   ├── tools.py        Tool/ToolRegistry (Claude Messages API schemas)
│   ├── agent.py        tool-use loop: AnthropicAgent + heuristic/random baselines
│   └── transcript.py   auditable, replayable episode record
├── envs/             # the six benchmark environments + curated real data
├── benchmark/        # runner → per-capability scorecard + JSON report
├── rl/               # verifiable tasks, judges, SFT/DPO/RLVR export
├── workspace/        # sandboxed agent files + terminal
├── research/         # novel algorithms, formulated + validated in-repo
├── toolkits.py       # lab_bench(): science + databases + workspace, composed
└── cli.py
```

The extension contract is small. An **Environment** samples a hidden ground
truth, registers domain **tools** (always including `submit`), scores a
submission to `[0,1]`, and exposes an expert **reference policy** — which both
provides the `heuristic` baseline and self-tests that the task is solvable
(`test_reference_policy_solves`). Add a subclass, register it in
`envs/__init__.py`, and it appears in the CLI and benchmark automatically.

## Autonomy

The harness *is* the autonomy layer: an agent runs a full episode — designs its
own experiments, spends a bounded tool budget (`--max-steps`), and commits to an
answer with no human in the loop. `BenchmarkRunner` then drives an agent across
dozens of independent tasks unattended and emits a signed-off report
(`--out report.json` embeds every transcript for audit). Wire `bench run --out`
into CI/cron for nightly regression of a model against the suite.

## Tests

```bash
python -m pytest -q   # 65 tests (science, harness, envs, rl, workspace, research)
```

Includes `tests/test_science.py`, which checks the tool library against
**known reference values** (aspirin MW 180.16 and Crippen logP; NCA half-life vs
analytic ln2/kₑ; 4PL fit recovering a known IC50; the textbook GATTACA/GCATGCU
Needleman–Wunsch score of −1). If a simulator or scorer drifts, these fail.

## Scope & honesty

- This is a **research and evaluation framework**, not a regulated or clinical
  system, and not Anthropic's Claude Science product.
- The *computations* are real and validated; the benchmark *scenarios* are
  abstract instances (sampled parameters, curated public SMILES, a synthetic
  reference CDS) chosen to isolate a capability — they are not tied to a specific
  program or proprietary target.
- No wet-lab protocols, no hazardous synthesis or biological-agent information —
  the goal is to measure and enable *computational reasoning*, and to plug real
  algorithms into an agent loop you control.

Licensable/extensible for internal evaluation: swap in your own descriptors,
QSAR/ADMET models, target structures, or assay simulators by adding a `science`
function and an `Environment`, and the whole harness, baseline set and scorecard
apply unchanged.
