"""Admin web console — launch and inspect everything from a browser.

A real, dependency-free web app (stdlib ``http.server``) that runs jobs against
the platform: benchmark runs, multi-model leaderboards, verifiable-dataset
builds, and dataset inspection to audit the scoring. Jobs execute in background
threads; results are held in memory and written under ``--runs-dir``.

    python -m claude_science.admin --port 8765
    # open http://localhost:8765

Endpoints (JSON):
    GET  /api/envs                       list environments
    GET  /api/agents                     known agent specs
    POST /api/bench      {agent,seeds,difficulty,envs}      → job
    POST /api/leaderboard{agents,seeds,difficulty,envs}     → job
    POST /api/dataset    {n_static,seed}                    → job (writes files)
    GET  /api/dataset/sample?n=..        sample graded tasks (audit scoring)
    GET  /api/job/<id>                   job status + result
    GET  /api/jobs                       all jobs
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List
from urllib.parse import urlparse, parse_qs

_JOBS: Dict[str, Dict[str, Any]] = {}
_LOCK = threading.Lock()
RUNS_DIR = "runs"


# --------------------------------------------------------------------------- #
# Job runners (execute real platform work)
# --------------------------------------------------------------------------- #
def _new_job(kind: str, params: Dict[str, Any]) -> str:
    jid = uuid.uuid4().hex[:12]
    with _LOCK:
        _JOBS[jid] = {"id": jid, "kind": kind, "params": params,
                      "status": "running", "started": time.time(), "result": None,
                      "error": None}
    return jid


def _finish(jid: str, result: Any = None, error: str | None = None) -> None:
    status = "error" if error else "done"
    with _LOCK:
        job = _JOBS[jid]
        job.update(result=result, error=error, ended=time.time())
        payload = dict(job, status=status)
    # persist BEFORE publishing the terminal status, so a caller that observes
    # status != "running" can always then read the run file (no write race).
    os.makedirs(RUNS_DIR, exist_ok=True)
    with open(os.path.join(RUNS_DIR, f"{jid}.json"), "w") as fh:
        json.dump(payload, fh, indent=2, default=str)
    with _LOCK:
        _JOBS[jid]["status"] = status


def _run_bench(jid: str, p: Dict[str, Any]) -> None:
    try:
        from .benchmark import BenchmarkRunner, render_scorecard
        from .benchmark.leaderboard import make_agent
        runner = BenchmarkRunner(envs=p.get("envs") or None,
                                 seeds=p.get("seeds", [0]),
                                 difficulties=[p.get("difficulty", "low")])
        agent = make_agent(p.get("agent", "heuristic"), max_steps=p.get("max_steps", 10))
        report = runner.run(agent)
        _finish(jid, {"overall": report.overall(),
                      "by_capability": report.by_capability(),
                      "by_env": report.by_env(),
                      "scorecard": render_scorecard(report)})
    except Exception:
        _finish(jid, error=traceback.format_exc()[-1500:])


def _run_leaderboard(jid: str, p: Dict[str, Any]) -> None:
    try:
        from .benchmark import BenchmarkRunner, run_leaderboard, render_leaderboard
        runner = BenchmarkRunner(envs=p.get("envs") or None,
                                 seeds=p.get("seeds", [0]),
                                 difficulties=[p.get("difficulty", "low")])
        lb = run_leaderboard(p.get("agents", ["heuristic", "random"]), runner,
                             max_steps=p.get("max_steps", 10), progress=False)
        _finish(jid, {"ranking": [{"spec": s, "overall": r.overall(),
                                    "by_capability": r.by_capability(),
                                    "by_env": r.by_env()}
                                   for s, r in lb.ranked()],
                      "errors": lb.errors,
                      "transcripts": lb.transcripts(),
                      "table": render_leaderboard(lb)})
    except Exception:
        _finish(jid, error=traceback.format_exc()[-1500:])


def _run_dataset(jid: str, p: Dict[str, Any]) -> None:
    try:
        from .rl import (build_dataset, run_rollouts, OracleSolver, NullSolver,
                         to_sft_jsonl, to_preference_jsonl, to_rlvr_jsonl)
        ds = build_dataset(n_static=p.get("n_static", 120), seed=p.get("seed", 0),
                           agentic_seeds=p.get("agentic_seeds", [0, 1]))
        os.makedirs(RUNS_DIR, exist_ok=True)
        prefix = os.path.join(RUNS_DIR, f"dataset_{jid}")
        ds.save_jsonl(prefix + ".tasks.jsonl")
        to_rlvr_jsonl(ds, prefix + ".rlvr.jsonl")
        res = {"total": len(ds), "by_domain": ds.by_domain(),
               "files": [prefix + ".tasks.jsonl", prefix + ".rlvr.jsonl"]}
        if p.get("rollouts"):
            oracle = run_rollouts(ds, OracleSolver())
            null = run_rollouts(ds, NullSolver())
            res["sft"] = to_sft_jsonl(oracle, prefix + ".sft.jsonl")
            res["preference"] = to_preference_jsonl(oracle + null, prefix + ".pref.jsonl")
            res["oracle_mean_reward"] = round(
                sum(r.reward for r in oracle) / len(oracle), 3)
            res["null_mean_reward"] = round(
                sum(r.reward for r in null) / len(null), 3)
        _finish(jid, res)
    except Exception:
        _finish(jid, error=traceback.format_exc()[-1500:])


_RUNNERS = {"bench": _run_bench, "leaderboard": _run_leaderboard,
            "dataset": _run_dataset}


def start_job(kind: str, params: Dict[str, Any]) -> str:
    jid = _new_job(kind, params)
    threading.Thread(target=_RUNNERS[kind], args=(jid, params), daemon=True).start()
    return jid


def _list_runs() -> List[Dict[str, Any]]:
    """List persisted runs (survives restarts) with a one-line summary."""
    if not os.path.isdir(RUNS_DIR):
        return []
    out = []
    for fn in sorted(os.listdir(RUNS_DIR), reverse=True):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(RUNS_DIR, fn)) as fh:
                d = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        res = d.get("result") or {}
        summary = ""
        if d.get("kind") == "leaderboard" and res.get("ranking"):
            top = res["ranking"][0]
            summary = f"top: {top['spec']} ({top['overall']:.2f})"
        elif d.get("kind") == "bench":
            summary = f"overall {res.get('overall', '—')}"
        out.append({"id": d.get("id", fn[:-5]), "kind": d.get("kind"),
                    "status": d.get("status"), "started": d.get("started"),
                    "params": d.get("params"), "summary": summary})
    return out


def _load_run(jid: str) -> Dict[str, Any] | None:
    path = os.path.join(RUNS_DIR, f"{jid}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def dataset_sample(n: int = 10, seed: int = 0) -> List[Dict[str, Any]]:
    """Sample tasks WITH gold + a self-check that the gold scores as passing."""
    from .rl import build_dataset
    ds = build_dataset(n_static=max(n, 20), seed=seed, include_agentic=False)
    out = []
    for t in list(ds)[:n]:
        v = t.grade(t.gold)
        out.append({"task_id": t.task_id, "domain": t.domain,
                    "prompt": t.prompt[:220], "judge": t.judge,
                    "gold": t.gold, "gold_scores_pass": v.passed,
                    "reward": v.reward})
    return out


# --------------------------------------------------------------------------- #
# HTTP handler
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj: Any, code: int = 200) -> None:
        self._send(code, json.dumps(obj, default=str).encode(), "application/json")

    def do_GET(self) -> None:
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/":
            self._send(200, ADMIN_HTML.encode(), "text/html; charset=utf-8")
        elif u.path == "/api/envs":
            from .envs import ENVIRONMENTS
            self._json([{"key": c.key, "title": c.title, "capability": c.capability}
                        for c in ENVIRONMENTS.values()])
        elif u.path == "/api/agents":
            self._json(["heuristic", "random", "openrouter:tencent/hy3:free",
                        "openrouter:poolside/laguna-xs-2.1:free",
                        "claude:claude-fable-5"])
        elif u.path == "/api/jobs":
            with _LOCK:
                self._json([{k: v for k, v in j.items() if k != "result"}
                            for j in _JOBS.values()])
        elif u.path.startswith("/api/job/"):
            jid = u.path.rsplit("/", 1)[-1]
            with _LOCK:
                job = _JOBS.get(jid)
            self._json(job or {"error": "not found"}, 200 if job else 404)
        elif u.path == "/api/dataset/sample":
            n = int(q.get("n", ["10"])[0])
            self._json(dataset_sample(n))
        elif u.path == "/api/runs":
            self._json(_list_runs())
        elif u.path.startswith("/api/run/"):
            jid = u.path.rsplit("/", 1)[-1]
            self._json(_load_run(jid) or {"error": "not found"},
                       200 if _load_run(jid) else 404)
        elif u.path.startswith("/vendor/"):
            self._serve_vendor(u.path.rsplit("/", 1)[-1])
        elif u.path.startswith("/api/"):
            self._science_get(u.path, q)
        else:
            self._json({"error": "not found"}, 404)

    # -- Workbench science endpoints ------------------------------------- #
    def _serve_vendor(self, name: str) -> None:
        from . import workbench
        try:
            body = workbench.vendor_asset(name)
        except Exception:
            return self._json({"error": "not found"}, 404)
        ctype = "application/javascript" if name.endswith(".js") else "text/plain"
        self._send(200, body, ctype)

    def _science_get(self, path: str, q: Dict[str, Any]) -> None:
        from . import workbench
        one = lambda key, default="": q.get(key, [default])[0]
        try:
            if path == "/api/mol3d":
                self._send(200, workbench.mol3d_sdf(one("smiles")).encode(),
                           "chemical/x-mdl-sdfile")
            elif path == "/api/mol2d":
                self._send(200, workbench.mol2d_svg(one("smiles")).encode(),
                           "image/svg+xml")
            elif path == "/api/descriptors":
                self._json(workbench.descriptors(one("smiles")))
            elif path == "/api/perceive":
                self._json(workbench.perceive(one("obj"), one("kind", "auto")))
            elif path == "/api/crispr":
                self._json(workbench.crispr_guides(one("dna")))
            else:
                self._json({"error": "not found"}, 404)
        except Exception as exc:
            self._json({"error": f"{type(exc).__name__}: {exc}"}, 400)

    def do_POST(self) -> None:
        u = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)
        kind = {"/api/bench": "bench", "/api/leaderboard": "leaderboard",
                "/api/dataset": "dataset"}.get(u.path)
        if kind:
            jid = start_job(kind, body)
            return self._json({"job_id": jid, "status": "running"})
        # synchronous science endpoints
        from . import workbench
        try:
            if u.path == "/api/design":
                return self._json(workbench.design(
                    body["query_smiles"], body.get("seed_smiles"),
                    int(body.get("generations", 5))))
            if u.path == "/api/rag":
                return self._json(workbench.rag(
                    body.get("action", "search"), body.get("kind", "literature"),
                    body.get("query", ""), body.get("doc_id", ""),
                    body.get("content", ""), int(body.get("k", 5))))
        except Exception as exc:
            return self._json({"error": f"{type(exc).__name__}: {exc}"}, 400)
        self._json({"error": "not found"}, 404)


def serve(port: int = 8765, runs_dir: str = "runs") -> None:
    global RUNS_DIR
    RUNS_DIR = runs_dir
    httpd = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Claude Science admin → http://localhost:{port}  (Ctrl-C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="claude-science-admin", description=__doc__)
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--runs-dir", default="runs")
    args = p.parse_args(argv)
    serve(args.port, args.runs_dir)
    return 0


# HTML is defined in admin_ui.py to keep this module readable
from .admin_ui import ADMIN_HTML  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
