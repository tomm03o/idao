"""Figures and Markdown report (Italian) for a pipeline run."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from .physics import atmosphere as atm  # noqa: E402
from .physics import habitable_zone as hz  # noqa: E402

# reference palette (light mode), see dataviz skill references/palette.md
C1, C2, C3 = "#257de0", "#f47230", "#00b894"
INK, INK2, GRID = "#191919", "#666666", "#e4e4e4"
SEQ = ["#cce3fd", "#9dc8f7", "#6aabf1", "#338ced", "#2370cd", "#1757ac", "#0e3d7e"]

plt.rcParams.update({
    "figure.dpi": 150, "savefig.dpi": 150, "font.size": 9, "axes.edgecolor": INK2, "axes.labelcolor": INK,
    "xtick.color": INK2, "ytick.color": INK2, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "axes.spines.top": False, "axes.spines.right": False, "legend.frameon": False, "lines.linewidth": 2,
})


def _seq_cmap():
    from matplotlib.colors import LinearSegmentedColormap
    return LinearSegmentedColormap.from_list("seq_blue", SEQ)


def fig_hz_diagram(ranking: pd.DataFrame, path: Path, top_n: int = 25):
    d = ranking[ranking["s_eff_med"].notna() & ranking["st_teff"].between(2500, 7500)
                & (ranking["radius_med"] < 3)]
    fig, ax = plt.subplots(figsize=(7.5, 5.2))
    ax.scatter(d["s_eff_med"], d["st_teff"], s=4, color="#bdbdbd", lw=0, label="pianeti piccoli (R < 3 R⊕)")
    teff = np.linspace(2600, 7200, 200)
    for lim, ls, lab in (("recent_venus", ":", "limiti ottimistici"), ("runaway_greenhouse", "-", "limiti conservativi"),
                         ("maximum_greenhouse", "-", None), ("early_mars", ":", None)):
        ax.plot(hz.seff_boundary(teff, lim), teff, ls=ls, color=INK2, lw=1.2, label=lab)
    top = d.sort_values("p_habitable_and_real", ascending=False).head(top_n)
    sc = ax.scatter(top["s_eff_med"], top["st_teff"], c=top["p_habitable_and_real"], cmap=_seq_cmap(), vmin=0, vmax=1,
                    s=46, edgecolor="white", linewidth=1.5, zorder=3)
    for _, r in top.head(12).iterrows():
        ax.annotate(r["name"], (r["s_eff_med"], r["st_teff"]), fontsize=6.5, color=INK, xytext=(4, 3),
                    textcoords="offset points")
    ax.set_xscale("log")
    ax.set_xlim(8, 0.08)
    ax.set_ylim(2500, 7300)
    ax.set_xlabel("flusso efficace S_eff (Terra = 1)")
    ax.set_ylabel("Teff della stella (K)")
    ax.set_title(f"Zona abitabile (Kopparapu 2014) e i {top_n} migliori candidati", color=INK, loc="left")
    cb = fig.colorbar(sc, ax=ax, pad=0.01)
    cb.set_label("P(abitabile) × P(reale)")
    ax.legend(loc="lower left", fontsize=7)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def fig_vetting(vet: dict, path: Path):
    if not vet:
        return
    fig, axes = plt.subplots(2, len(vet), figsize=(4.2 * len(vet), 6.4), squeeze=False)
    for j, (survey, m) in enumerate(vet.items()):
        sel = pd.DataFrame(m.selection)
        best = sel.groupby("family")["cv_log_loss"].min().sort_values()
        ax = axes[0, j]
        colors = [C1 if f == best.index[0] else "#9dc8f7" for f in best.index]
        ax.barh(best.index, best.values, color=colors, height=0.6)
        for y, v in enumerate(best.values):
            ax.text(v, y, f" {v:.3f}", va="center", fontsize=7, color=INK)
        ax.invert_yaxis()
        ax.set_xlabel("log-loss CV (5 fold, raggruppata per stella) ↓")
        ax.set_title(f"{survey}: ricerca del modello", color=INK, loc="left")
        ax.grid(axis="y", visible=False)
        ax = axes[1, j]
        hp = m.holdout_predictions
        bins = np.linspace(0, 1, 11)
        for col, lab, c in (("p_raw", "non calibrato", C2), ("p_calibrated", "calibrato (isotonico)", C1)):
            idx = np.clip(np.digitize(hp[col], bins) - 1, 0, 9)
            xs, ys = [], []
            for b in range(10):
                sel_b = idx == b
                if sel_b.sum() >= 5:
                    xs.append(hp[col][sel_b].mean())
                    ys.append(hp["y"][sel_b].mean())
            ax.plot(xs, ys, marker="o", ms=4, color=c, label=lab)
        ax.plot([0, 1], [0, 1], color=INK2, lw=1, ls="--", label="perfetta")
        hm = m.holdout_metrics
        ax.set_title(f"hold-out: AUC {hm['roc_auc']:.3f}, ECE {hm['ece']:.3f}", color=INK, loc="left")
        ax.set_xlabel("probabilità predetta")
        ax.set_ylabel("frazione di pianeti reali")
        ax.legend(fontsize=7, loc="upper left")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def fig_rocky(rocky, path: Path):
    tr = rocky.training_table
    fig, ax = plt.subplots(figsize=(6.8, 4.2))
    if tr is not None and "p_rocky_posterior" in tr:
        ax.scatter(tr["radius"], tr["p_rocky_posterior"], s=9, color="#bdbdbd", lw=0,
                   label="pianeti con M e R misurate (posteriore)")
    r = np.linspace(0.5, 3.5, 300)
    members = getattr(rocky, "members", {})
    for s, c in ((1.0, C1), (1000.0, C2)):
        ax.plot(r, rocky.p_given_radius(r, np.full_like(r, s)), color=c, label=f"media, S = {s:g}")
        for (name, m), ls in zip(members.items(), ("--", ":")):
            ax.plot(r, m.p_given_radius(r, np.full_like(r, s)), color=c, lw=1, ls=ls,
                    label=f"{name}, S = {s:g}")
    rogers = 1 / (1 + np.exp((r - 1.6) / 0.08))
    ax.plot(r, rogers, color=INK2, lw=1.2, ls="-.", label="taglio fisso Rogers (2015)")
    ax.set_xlabel("raggio (R⊕)")
    ax.set_ylabel("P(roccioso)")
    ax.set_title("P(roccioso | raggio, flusso): modello appreso", color=INK, loc="left")
    ax.legend(fontsize=6.5, ncol=2)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def fig_shoreline(shore: pd.DataFrame, path: Path, width_dex: float):
    d = shore.dropna(subset=["log10_ratio"]).sort_values("log10_ratio")
    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    x = np.linspace(-2, 4, 300)
    ax.plot(x, atm.retention_probability(10**x, width_dex=width_dex), color=INK2, lw=1.2,
            label="P(mantiene l'atmosfera)")
    for obs, c, lab in ((True, C1, "atmosfera osservata"), (False, C2, "nessuna atmosfera spessa"),
                        (None, C3, "marginale (Marte)")):
        sel = d["observed_atmosphere"].isna() if obs is None else (d["observed_atmosphere"] == obs)
        sel &= d["observed_atmosphere"].notna() if obs is not None else True
        dd = d[sel]
        ax.scatter(dd["log10_ratio"], dd["p_retention"], color=c, s=40, edgecolor="white", lw=1.5, zorder=3, label=lab)
        for _, r in dd.iterrows():
            if r["p_retention"] < 0.1:  # crowded floor: stagger labels upwards with a leader line
                k = int((d["p_retention"] < 0.1)[: d.index.get_loc(r.name)].sum())
                ax.annotate(r["body"], (r["log10_ratio"], r["p_retention"]), fontsize=6.5, color=INK,
                            xytext=(r["log10_ratio"] + 0.1, 0.08 + 0.055 * k), textcoords="data",
                            arrowprops=dict(arrowstyle="-", color="#bdbdbd", lw=0.8))
                continue
            below = r["body"] == "Mars"  # Mars and Ganymede share a point
            ax.annotate(r["body"], (r["log10_ratio"], r["p_retention"]), fontsize=6.5,
                        xytext=(5, -11) if below else (3, 4), textcoords="offset points", color=INK)
    ax.set_xlabel("log10 [ fluenza XUV relativa / (v_fuga relativa)^4 ]")
    ax.set_ylabel("P(ritenzione)")
    ax.set_title("Cosmic shoreline: Sistema Solare + vincoli JWST", color=INK, loc="left")
    ax.legend(fontsize=7, loc="lower left")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _md_table(df: pd.DataFrame, floatfmt: str = "{:.3f}") -> str:
    def fmt(v):
        if isinstance(v, (float, np.floating)):
            return "" if not np.isfinite(v) else floatfmt.format(v)
        return str(v)
    head = "| " + " | ".join(df.columns) + " |"
    sep = "|" + "|".join("---" for _ in df.columns) + "|"
    rows = ["| " + " | ".join(fmt(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join([head, sep, *rows])


def write_report(ranking, bench, vet, rocky, shore, ss, abl, out_dir: Path):
    figs = out_dir / "figures"
    figs.mkdir(parents=True, exist_ok=True)
    fig_hz_diagram(ranking, figs / "hz_diagram.png")
    fig_vetting(vet, figs / "vetting.png")
    fig_rocky(rocky, figs / "rocky_model.png")
    fig_shoreline(shore, figs / "shoreline.png", bench["config"]["shoreline_width_dex"])

    s = bench["summary"]
    lines = ["# Ricerca di pianeti potenzialmente abitabili: risultati", ""]
    lines += [
        f"Pianeti e candidati analizzati: **{s['n_scored']}** ({s['n_confirmed']} confermati, "
        f"{s['n_open_candidates']} candidati TESS/Kepler ancora aperti), di cui {s['n_evaluable']} con dati sufficienti. "
        f"Ogni oggetto è valutato con {bench['config']['n_samples']} campioni Monte Carlo delle incertezze. "
        f"Tempo di esecuzione: {s['runtime_s']} s.",
        "",
        f"Numero atteso di mondi abitabili (somma delle probabilità): **{s['expected_number_habitable_confirmed']:.1f}** "
        f"tra i confermati, **{s['expected_number_habitable_candidates']:.1f}** tra i candidati (già pesato per P(reale)).",
        "",
        "**Come leggere P(abitabile).** È la probabilità, date le misure e i loro errori, che il pianeta sia roccioso, "
        "stia nella zona abitabile (con incertezza sui bordi), orbiti una stella di sequenza principale e abbia potuto "
        "trattenere un'atmosfera. È una condizione *necessaria*, non una prova di vita: nessun pianeta extrasolare "
        "è mai stato osservato come abitabile.",
        "",
        "## I migliori candidati",
        "",
        "![HZ](figures/hz_diagram.png)",
        "",
    ]
    top = ranking.head(30)[["rank", "name", "source", "p_real", "p_habitable", "p_habitable_and_real",
                            "robust_top_fraction", "p_rocky", "p_hz", "p_atm_retention", "s_eff_med", "radius_med",
                            "st_teff", "dist_pc", "case", "hwc_habitable"]].copy()
    top["dist_pc"] = top["dist_pc"].round(1)
    top["st_teff"] = top["st_teff"].round(0)
    lines += [_md_table(top), "",
              "`robust_top_fraction` è la frazione di varianti del modello (posizione e larghezza della shoreline, "
              "prior sulla frazione di nucleo) in cui il pianeta resta nella top 20. `case`: A = massa e raggio misurati, "
              "B = solo raggio, C = solo massa, D = solo M sin i. `hwc_habitable`: etichetta PHL "
              "(1 conservativo, 2 ottimistico, 0 no, vuoto = non presente nel catalogo PHL).", ""]

    lines += ["## Validazione sul Sistema Solare", "",
              _md_table(ss[["name", "expected", "p_habitable", "p_rocky", "p_hz", "p_atm_retention", "s_eff_med", "case"]]),
              ""]

    lines += ["## Cosmic shoreline (perdita dell'atmosfera)", "", "![shoreline](figures/shoreline.png)", "",
              _md_table(shore[["body", "kind", "log10_ratio", "p_retention", "observed_atmosphere", "correct", "reference"]]),
              "", "Nota: 55 Cnc e è un mondo a oceano di magma con atmosfera da degassamento continuo. Il modello, che "
              "considera solo la fuga atmosferica, lo predice senza atmosfera: questo è un limite noto.", ""]

    lines += ["## Modello roccioso appreso (deconvoluzione EM)", "", "![rocky](figures/rocky_model.png)", ""]
    rmods = bench["rocky_model"].get("members", {"model": bench["rocky_model"]})
    lines += ["P(roccioso) è la media a pesi uguali di due modelli: uno addestrato su tutte le masse misurate e uno "
              "senza i sistemi TTV. Le masse TTV tendono a densità basse, quelle RV a densità alte: la media porta "
              "questa incertezza sistematica nel risultato invece di scegliere un lato.", ""]
    for member, summ in rmods.items():
        for key in ("radius", "mass"):
            rm = summ[key]
            cand = pd.DataFrame(rm["candidates"]).T.reset_index().rename(columns={"index": "modello"})
            cand = cand[["modello", "cv_mean_heldout_loglik", "cv_heldout_loglik_low_flux", "monotone"]]
            lines += [f"**{member} / variabile {key}**: scelto `{rm['chosen']}` (n = {rm['n_train']}; componente "
                      f"volatile μ = {rm['mu_volatile']:.3f} dex, τ = {rm['tau_volatile']:.3f} dex). "
                      "Log-verosimiglianza media su fold esclusi (più alta = meglio):", "", _md_table(cand, "{:.4f}"), ""]

    lines += ["## Vetting dei candidati (ML con etichette reali)", "", "![vetting](figures/vetting.png)", ""]
    for survey, v in bench["vetting"].items():
        hm, hu = v["holdout_calibrated"], v["holdout_uncalibrated"]
        lines += [f"**{survey}**: {v['n_labelled']} candidati risolti. Modello scelto: `{v['chosen']}`. "
                  f"Hold-out (stelle mai viste): AUC {hm['roc_auc']:.3f}, AP {hm['avg_precision']:.3f}, "
                  f"log-loss {hm['log_loss']:.3f} (non calibrato {hu['log_loss']:.3f}), Brier {hm['brier']:.3f}, "
                  f"ECE {hm['ece']:.3f}.", ""]
        sel = pd.DataFrame(v["model_search"]).sort_values("cv_log_loss").head(8)
        lines += [_md_table(sel[["family", "config", "cv_log_loss", "cv_roc_auc", "cv_brier", "selected"]], "{:.4f}"), ""]
        imp = pd.DataFrame(v["top_features"]).head(10)
        lines += ["Feature più importanti (aumento della log-loss permutandole):", "", _md_table(imp, "{:.4f}"), ""]

    lines += ["## Confronto tra modelli di abitabilità (ablazioni)", "",
              "Non esiste un insieme etichettato di pianeti abitabili, quindi il modello migliore non si sceglie con "
              "l'accuratezza sulle etichette di un catalogo. Si sceglie con i test fisici (Sistema Solare, JWST) e con "
              "la corretta propagazione delle incertezze. L'accordo con il PHL è riportato solo come riferimento.", ""]
    cols = [c for c in ["model", "solar_earth", "solar_mars", "solar_max_not_habitable", "solar_earth_rv_only",
                        "n_p_gt_0.5", "expected_n_habitable", "top25_overlap_with_full", "spearman_vs_full",
                        "auc_vs_hwc_any"] if c in abl.columns]
    lines += [_md_table(abl[cols]), ""]

    if "hwc_circularity" in bench:
        c = bench["hwc_circularity"]
        lines += ["## Perché non addestriamo un classificatore sulle etichette del catalogo PHL", "",
                  f"Un albero decisionale di profondità 2 su 4 colonne del catalogo stesso ottiene AUC "
                  f"{c['depth_2']['cv_auc']:.3f} in cross-validation, e di profondità 4 ottiene "
                  f"{c['depth_4']['cv_auc']:.3f} ({c['n_positive']} positivi su {c['n']}). Le etichette sono una "
                  "regola deterministica (zona abitabile + limiti di raggio/massa): un modello di ML addestrato su di "
                  "esse riscopre la regola e non aggiunge informazione fisica.", "", "```", c["rules_depth4"], "```", ""]
        a = bench.get("hwc_agreement_full_model", {})
        if a:
            lines += [f"Accordo del modello completo con il PHL (solo come riferimento): AUC {a['auc_vs_hwc_any']:.3f} "
                      f"su {a['n_matched']} pianeti in comune.", ""]
        dis = ranking[(ranking["hwc_habitable"] > 0) & (ranking["p_habitable"] < 0.05)]
        if len(dis):
            lines += ["### Pianeti abitabili per il PHL ma scartati dal modello, con il motivo", "",
                      _md_table(dis[["name", "hwc_habitable", "p_habitable", "p_rocky", "p_hz", "p_atm_retention",
                                     "p_main_sequence", "radius_med", "s_eff_med", "case"]].head(40)), ""]

    lines += ["## Dati", ""]
    for name, meta in bench["data"].items():
        lines += [f"- `{name}`: {meta['rows']} righe, scaricato {meta['fetched_at']} da {meta['url']}"]
    (out_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
