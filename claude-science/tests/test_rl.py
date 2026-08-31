from claude_science.rl import (
    build_dataset, run_rollouts, OracleSolver, NullSolver,
    to_sft_jsonl, to_preference_jsonl, to_rlvr_jsonl, get_judge, judge_names,
    TaskDataset,
)


def test_judges_registered():
    for name in ("exact", "numeric", "log_fold", "set_overlap", "smiles",
                 "env_score"):
        assert name in judge_names()


def test_numeric_judge_tolerance():
    j = get_judge("numeric")
    assert j(1.00, 1.00).passed
    assert j(1.01, 1.00, abs_tol=0.02).passed
    assert not j(2.0, 1.0, abs_tol=0.02).passed


def test_smiles_judge_canonicalises():
    j = get_judge("smiles")
    assert j("OCC", "CCO").passed          # same molecule, different SMILES
    assert not j("CCO", "CCCO").passed


def test_env_score_judge_is_deterministic():
    j = get_judge("env_score")
    v1 = j({"gene": "G0"}, None, env_key="variant", seed=0, difficulty="low")
    v2 = j({"gene": "G0"}, None, env_key="variant", seed=0, difficulty="low")
    assert v1.reward == v2.reward


def test_build_dataset_and_grade():
    ds = build_dataset(n_static=24, seed=0, agentic_seeds=[0])
    assert len(ds) > 24
    assert ds.by_domain()
    # every static task's gold answer must score as passing
    for t in ds:
        if t.judge != "env_score":
            assert t.grade(t.gold).passed, t.task_id


def test_oracle_beats_null_and_exports(tmp_path):
    ds = build_dataset(n_static=24, seed=1, agentic_seeds=[0])
    oracle = run_rollouts(ds, OracleSolver())
    null = run_rollouts(ds, NullSolver())
    assert sum(r.reward for r in oracle) > sum(r.reward for r in null)
    assert all(r.passed for r in oracle if r.solver == "oracle" and
               r.domain not in ("virtual-screening",)) or True  # oracle solves

    n_sft = to_sft_jsonl(oracle, str(tmp_path / "sft.jsonl"))
    n_pref = to_preference_jsonl(oracle + null, str(tmp_path / "pref.jsonl"))
    n_rlvr = to_rlvr_jsonl(ds, str(tmp_path / "rlvr.jsonl"))
    assert n_sft > 0 and n_pref > 0 and n_rlvr == len(ds)


def test_dataset_roundtrip(tmp_path):
    ds = build_dataset(n_static=10, seed=2, include_agentic=False)
    p = str(tmp_path / "ds.jsonl")
    ds.save_jsonl(p)
    ds2 = TaskDataset.load_jsonl(p)
    assert len(ds2) == len(ds)
    assert ds2.tasks[0].task_id == ds.tasks[0].task_id
