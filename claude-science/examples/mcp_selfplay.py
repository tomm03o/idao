"""Drive the Claude Science MCP server as a client — answer verifiable
questions and play benchmark episodes, seeing and doing everything over MCP.

Every answer below is produced by calling MCP tools (science functions, or the
sandboxed `run_python` terminal for anything without a direct tool) — never by
reading a hidden gold value. Questions are then graded by their verifier; the
benchmark episodes are graded by the environment.

    python examples/mcp_selfplay.py
"""

import json
import re
import subprocess
import sys

from claude_science.rl import build_dataset


class MCPClient:
    """Minimal MCP stdio client (newline-delimited JSON-RPC 2.0)."""

    def __init__(self):
        self.p = subprocess.Popen(
            [sys.executable, "-m", "claude_science.mcp_server"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
        self._id = 0
        self._rpc("initialize")

    def _rpc(self, method, params=None):
        self._id += 1
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self._id,
                                       "method": method, "params": params or {}}) + "\n")
        self.p.stdin.flush()
        return json.loads(self.p.stdout.readline())

    def call(self, tool, arguments=None):
        r = self._rpc("tools/call", {"name": tool, "arguments": arguments or {}})
        text = r["result"]["content"][0]["text"]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    def close(self):
        self.p.stdin.close()
        self.p.wait(timeout=5)


# --- answering verifiable questions, each via MCP tools -------------------- #
def answer(mcp, task):
    tid, m = task.task_id, task.meta
    if tid.startswith("qa-qed"):
        return mcp.call("chem_descriptors", {"smiles": m["smiles"]})["qed"]
    if tid.startswith("qa-logp"):
        return mcp.call("chem_descriptors", {"smiles": m["smiles"]})["clogp"]
    if tid.startswith("qa-mw"):
        return mcp.call("chem_descriptors", {"smiles": m["smiles"]})["mol_weight"]
    if tid.startswith("qa-tpsa"):
        return mcp.call("chem_descriptors", {"smiles": m["smiles"]})["tpsa"]
    if tid.startswith("qa-rings"):
        return mcp.call("chem_descriptors", {"smiles": m["smiles"]})["aromatic_rings"]
    if tid.startswith("qa-rotbonds"):
        return mcp.call("chem_descriptors", {"smiles": m["smiles"]})["rotatable_bonds"]
    if tid.startswith("qa-lipinski"):
        d = mcp.call("chem_descriptors", {"smiles": m["smiles"]})
        return "yes" if d["lipinski_pass"] else "no"
    if tid.startswith("qa-alert"):
        return "yes" if mcp.call("chem_alerts", {"smiles": m["smiles"]}) else "no"
    if tid.startswith("qa-tanimoto"):
        return mcp.call("chem_tanimoto", {"smiles_a": m["a"], "smiles_b": m["b"]})
    if tid.startswith("qa-translate"):
        return mcp.call("seq_translate", {"dna": m["dna"]})["protein"]
    if tid.startswith("qa-formula"):
        # no direct tool → use the sandboxed terminal over MCP
        code = (f"from rdkit import Chem\nfrom rdkit.Chem import rdMolDescriptors\n"
                f"print(rdMolDescriptors.CalcMolFormula(Chem.MolFromSmiles({m['smiles']!r})))")
        return mcp.call("run_python", {"code": code})["stdout"].strip()
    if tid.startswith("qa-revcomp"):
        code = (f"from claude_science.science import seq\n"
                f"print(seq.reverse_complement({m['dna']!r}))")
        return mcp.call("run_python", {"code": code})["stdout"].strip()
    if tid.startswith("qa-ic50"):
        fit = mcp.call("pk_fit_dose_response",
                       {"concentrations": m["x"], "responses": m["y"]})
        return fit["ic50"]
    return None


def run_questions(mcp, n=40):
    ds = build_dataset(n_static=n, seed=7, include_agentic=False)
    solved = graded = 0
    per = {}
    for t in ds:
        a = answer(mcp, t)
        if a is None:
            continue
        graded += 1
        v = t.grade(a)
        solved += v.reward
        kind = t.task_id.rsplit("-", 1)[0]
        per.setdefault(kind, [0, 0]); per[kind][0] += v.reward; per[kind][1] += 1
    print(f"Verifiable questions answered over MCP: {graded}")
    for kind, (s, c) in sorted(per.items()):
        print(f"  {kind:14} {s/c:.2f}  ({c} q)")
    print(f"  → mean reward {solved/graded:.3f}\n")


# --- playing the benchmark over MCP --------------------------------------- #
def play_episode(mcp, env_key, seed):
    ep = mcp.call("bench_start", {"env_key": env_key, "seed": seed, "difficulty": "medium"})
    task = ep["task"]

    def act(tool, args):
        return mcp.call("bench_act", {"tool": tool, "arguments": args})

    if env_key == "variant":
        cds = re.findall(r"[ACGT]{30,}", task)
        rp = act("translate", {"dna": cds[0]})["observation"]["protein"].rstrip("*")
        vp = act("translate", {"dna": cds[1]})["observation"]["protein"].rstrip("*")
        i = next(k for k, (a, b) in enumerate(zip(rp, vp), 1) if a != b)
        return act("submit", {"variant": f"p.{rp[i-1]}{i}{vp[i-1]}"}).get("score")
    if env_key == "ic50":
        cs, rs = [], []
        for c in (1, 10, 100, 1000, 10000, 100000):
            o = act("run_assay", {"concentration_nM": c})
            if not o["ok"]:
                break
            cs.append(c); rs.append(o["observation"]["percent_inhibition"])
        fit = act("fit_curve", {"concentrations_nM": cs, "responses": rs})
        return act("submit", {"ic50_nM": fit["observation"]["ic50"]}).get("score")
    if env_key == "admet":
        cands = re.findall(r"-\s+(\S+)", task)
        best, bq = None, -1
        for smi in cands:
            d = act("analyze_molecule", {"smiles": smi})["observation"]
            if (d["lipinski_pass"] and d["veber_pass"]
                    and not d["structural_alerts"] and d["qed"] > bq):
                best, bq = smi, d["qed"]
        return act("submit", {"smiles": best}).get("score")
    return None


def run_benchmark(mcp):
    print("Playing benchmark episodes over MCP (decisions from observations):")
    total = 0.0
    envs = ["variant", "ic50", "admet"]
    for key in envs:
        scores = [play_episode(mcp, key, s) or 0.0 for s in (0, 1, 2)]
        avg = sum(scores) / len(scores)
        total += avg
        print(f"  {key:10} {avg:.3f}")
    print(f"  → overall {total/len(envs):.3f}")


def main():
    mcp = MCPClient()
    try:
        tools = mcp._rpc("tools/list")["result"]["tools"]
        print(f"Connected to MCP server — {len(tools)} tools visible\n")
        run_questions(mcp)
        run_benchmark(mcp)
    finally:
        mcp.close()


if __name__ == "__main__":
    main()
