"""Claude playing the benchmark by hand — deciding only from tool observations.

Unlike HeuristicAgent (which replays a reference policy derived from hidden
ground truth), every choice below is made from what the tools return plus the
task prompt — a fair agent run. Prints the score obtained on each environment.

    python examples/claude_plays.py
"""

import re
from claude_science import make_env


def play_admet(env):
    reg = env.tools()
    best, best_q = None, -1.0
    for smi in env.candidates:                       # candidates are in the prompt
        d = reg.dispatch("analyze_molecule", {"smiles": smi}).content
        drug_like = d["lipinski_pass"] and d["veber_pass"] and not d["structural_alerts"]
        if drug_like and d["qed"] > best_q:
            best, best_q = smi, d["qed"]
    reg.dispatch("submit", {"smiles": best})


def play_screen(env):
    reg = env.tools()
    hits = reg.dispatch("screen_library", {"top_k": env.top_k}).content
    reg.dispatch("submit", {"hits": [h["smiles"] for h in hits]})


def play_ic50(env):
    reg = env.tools()
    concs, resps = [], []
    for c in [1, 10, 100, 1000, 10000, 100000]:      # log sweep within budget
        r = reg.dispatch("run_assay", {"concentration_nM": c})
        if not r.ok:
            break
        concs.append(c); resps.append(r.content["percent_inhibition"])
    fit = reg.dispatch("fit_curve", {"concentrations_nM": concs, "responses": resps})
    reg.dispatch("submit", {"ic50_nM": fit.content["ic50"]})


def play_pkpd(env):
    reg = env.tools()
    target = float(re.search(r"target of ([\d.]+) mg/L", env.task_prompt()).group(1))
    prof = reg.dispatch("simulate_dose", {"dose_mg": 100.0}).content
    nca = reg.dispatch("run_nca", {"times_h": prof["times_h"],
                                   "conc_mg_L": prof["conc_mg_L"], "dose_mg": 100.0}).content
    dose = 100.0 * target / nca["cmax"]              # Cmax linear in dose
    reg.dispatch("submit", {"dose_mg": round(dose, 2)})


def play_variant(env):
    reg = env.tools()
    ref = reg.dispatch("translate", {"dna": env.ref_cds}).content["protein"].rstrip("*")
    var = reg.dispatch("translate", {"dna": env.variant_cds}).content["protein"].rstrip("*")
    for i, (a, b) in enumerate(zip(ref, var), 1):
        if a != b:
            reg.dispatch("submit", {"variant": f"p.{a}{i}{b}"})
            return


def play_conformer(env):
    reg = env.tools()
    best = reg.dispatch("conformer_search", {"n_conformers": 40}).content["energy_min"]
    reg.dispatch("submit", {"energy_kcal_mol": best})


PLAYERS = {"admet": play_admet, "screen": play_screen, "ic50": play_ic50,
           "pkpd": play_pkpd, "variant": play_variant, "conformer": play_conformer}


def main():
    print("Claude playing (decisions from tool observations only)\n")
    total, n = 0.0, 0
    for key, play in PLAYERS.items():
        scores = []
        for seed in (0, 1, 2):
            env = make_env(key, seed=seed, difficulty="medium")
            play(env)
            sub = env.result()
            scores.append(sub.score if sub else 0.0)
        avg = sum(scores) / len(scores)
        total += avg; n += 1
        print(f"  {key:10} score={avg:.3f}   (seeds 0-2, medium)")
    print(f"\n  OVERALL = {total / n:.3f}")


if __name__ == "__main__":
    main()
