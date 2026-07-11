"""Tests for retrieval (RAG), the admin job runners, and the console —
all provider-independent (no LLM/network calls)."""

import json

from claude_science.retrieval import Corpus, retrieval_tools


# --- RAG ------------------------------------------------------------------ #
def test_bm25_ranks_relevant_doc_first():
    c = Corpus()
    c.add_many([
        ("d1", "Imatinib inhibits BCR-ABL tyrosine kinase in leukemia"),
        ("d2", "Aspirin inhibits cyclooxygenase and reduces inflammation"),
        ("d3", "Gefitinib is an EGFR tyrosine kinase inhibitor in lung cancer"),
    ])
    hits = c.search("kinase inhibitor cancer", k=2)
    assert hits[0]["doc_id"] in ("d3", "d1")
    assert all(h["score"] > 0 for h in hits)


def test_retrieval_tools_add_and_search():
    reg = retrieval_tools()
    assert reg.dispatch("rag_add", {"doc_id": "x", "text": "hello world kinase"}).ok
    res = reg.dispatch("rag_search", {"query": "kinase", "k": 1})
    assert res.ok and res.content[0]["doc_id"] == "x"


def test_empty_corpus_returns_nothing():
    assert Corpus().search("anything") == []


# --- admin job runners ---------------------------------------------------- #
def test_admin_dataset_sample_all_golds_verify():
    from claude_science.admin import dataset_sample
    sample = dataset_sample(n=12)
    assert len(sample) == 12
    assert all(t["gold_scores_pass"] for t in sample)


def test_admin_bench_job_runs():
    from claude_science import admin
    jid = admin.start_job("bench", {"agent": "heuristic", "envs": ["variant"],
                                     "seeds": [0], "difficulty": "low"})
    _wait(admin, jid)
    job = admin._JOBS[jid]
    assert job["status"] == "done"
    assert job["result"]["overall"] == 1.0


def test_admin_dataset_job_writes_files(tmp_path):
    from claude_science import admin
    admin.RUNS_DIR = str(tmp_path)
    jid = admin.start_job("dataset", {"n_static": 20, "seed": 0,
                                      "agentic_seeds": [0], "rollouts": True})
    _wait(admin, jid)
    res = admin._JOBS[jid]["result"]
    assert res["total"] > 20 and res["oracle_mean_reward"] == 1.0
    assert res["null_mean_reward"] < res["oracle_mean_reward"]


# --- console -------------------------------------------------------------- #
def test_console_assembles_full_toolset_and_dispatches():
    from claude_science.console import ScienceConsole, build_session_tools
    tools = build_session_tools(with_databases=True)
    try:
        names = set(tools.names())
        for expected in ("chem_descriptors", "pubchem_compound", "run_python",
                         "literature_search", "rag_search", "seq_translate"):
            assert expected in names
        out = tools.dispatch("chem_descriptors", {"smiles": "CCO"})
        assert out.ok and "qed" in out.content
    finally:
        tools._workspace.cleanup()


def test_console_commands_handled():
    from claude_science.console import ScienceConsole, build_session_tools
    tools = build_session_tools(with_databases=False)
    try:
        logs = []
        c = ScienceConsole(agent=None, tools=tools, printer=logs.append)
        assert c.handle_command("/tools")
        assert c.handle_command("/reset")
        assert not c.handle_command("not a command")
    finally:
        tools._workspace.cleanup()


def _wait(admin, jid, timeout=60):
    import time
    for _ in range(timeout * 2):
        if admin._JOBS[jid]["status"] != "running":
            return
        time.sleep(0.5)
