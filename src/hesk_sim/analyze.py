"""Turn raw run records into tables, paired statistics and figures.

  python -m hesk_sim.analyze runs results

Statistics: per-cell mean with a 95% percentile-bootstrap CI (2,000
resamples, fixed seed). Algorithm comparisons are *paired by seed* (same
fleet, mission and fault schedule) and reported as mean paired difference,
bootstrap CI, Wilcoxon signed-rank p-value and win rate.
"""
from __future__ import annotations

import csv
import gzip
import json
import math
import os
import random
import sys
from collections import defaultdict
from typing import Dict, List

import numpy as np
from scipy.stats import wilcoxon

# ── palette (validated: dataviz reference palette, slots 1-4) ─────────
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
STYLE = {  # algo: (color, marker, linestyle, label)
    "hesk3":   ("#2a78d6", "o", "-", "HESK v3 (this work)"),
    "cbba":    ("#eb6834", "s", "-", "CBBA"),
    "central": ("#1baf7a", "^", "-", "Centralized (quorum)"),
    "cnp":     ("#eda100", "D", "-", "Contract Net"),
    "central_noquorum": ("#4a3aa7", "v", "-", "Centralized (no quorum)"),
    "hesk":    ("#8d8c87", "x", ":", "HESK as specified"),
    "hesk2":   ("#52514e", "+", "--", "HESK v2"),
    "oracle":  ("#0b0b0b", "*", "-.", "Oracle (cheats)"),
}
METRICS = ["utility_ratio", "critical_ratio", "coverage", "tier0_share", "coalition_share",
           "duplicate_agent_s", "msgs_per_node_s", "recovery_median_s", "recovered_frac", "wall_s"]


def load(runs_dir: str) -> List[dict]:
    rows = []
    for fn in sorted(os.listdir(runs_dir)):
        path = os.path.join(runs_dir, fn)
        if fn.endswith(".jsonl"):
            fh = open(path)
        elif fn.endswith(".jsonl.gz"):
            fh = gzip.open(path, "rt")
        else:
            continue
        with fh:
            rows += [json.loads(l) for l in fh]
    return rows


def parse_cell(cell: str) -> Dict[str, object]:
    out = {}
    for part in cell.split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            try:
                out[k] = float(v)
            except ValueError:
                out[k] = v
    return out


def boot_ci(xs, n=2000, seed=0):
    xs = np.asarray([x for x in xs if x is not None], dtype=float)
    if len(xs) == 0:
        return (math.nan, math.nan, math.nan)
    if len(xs) == 1:
        return (xs[0], xs[0], xs[0])
    rng = np.random.default_rng(seed)
    means = xs[rng.integers(0, len(xs), (n, len(xs)))].mean(axis=1)
    return (float(xs.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))


def group(rows, suite):
    g = defaultdict(list)
    for r in rows:
        if r["suite"] == suite:
            g[(r["cell"], r["algo"])].append(r)
    return g


def summary_table(rows, suite) -> List[dict]:
    out = []
    for (cell, algo), rs in sorted(group(rows, suite).items()):
        rec = {"suite": suite, "cell": cell, "algo": algo, "n": len(rs)}
        for m in METRICS:
            mu, lo, hi = boot_ci([r.get(m) for r in rs])
            rec[m], rec[m + "_lo"], rec[m + "_hi"] = mu, lo, hi
        out.append(rec)
    return out


def paired(rows, suite, a, b, metric="utility_ratio") -> List[dict]:
    """Paired comparison a − b within each cell (pairs share seed)."""
    g = group(rows, suite)
    cells = sorted({c for (c, _) in g})
    out = []
    for c in cells:
        ra = {r["rep"]: r[metric] for r in g.get((c, a), [])}
        rb = {r["rep"]: r[metric] for r in g.get((c, b), [])}
        reps = sorted(set(ra) & set(rb))
        if not reps:
            continue
        d = [ra[k] - rb[k] for k in reps]
        mu, lo, hi = boot_ci(d)
        try:
            p = float(wilcoxon(d).pvalue) if any(abs(x) > 1e-12 for x in d) else 1.0
        except ValueError:
            p = 1.0
        out.append({"cell": c, "a": a, "b": b, "metric": metric, "n": len(d), "diff": mu, "lo": lo, "hi": hi,
                    "p": p, "win_rate": sum(x > 0 for x in d) / len(d)})
    return out


# ── figures ──────────────────────────────────────────────────────────
def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
        "text.color": INK, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
        "axes.spines.top": False, "axes.spines.right": False, "font.size": 10, "axes.titlesize": 11,
        "axes.titleweight": "bold", "legend.frameon": False, "lines.linewidth": 2, "lines.markersize": 6,
    })
    return plt


def _lines(ax, table, xkey, algos, metric="utility_ratio", filt=None, label_ends=True):
    for algo in algos:
        pts = []
        for r in table:
            if r["algo"] != algo:
                continue
            cp = parse_cell(r["cell"])
            if filt and any(cp.get(k) != v for k, v in filt.items()):
                continue
            pts.append((cp[xkey], r[metric], r[metric + "_lo"], r[metric + "_hi"]))
        if not pts:
            continue
        pts.sort()
        x, y, lo, hi = map(np.array, zip(*pts))
        c, mk, ls, lab = STYLE.get(algo, ("#888", "o", "-", algo))
        ax.fill_between(x, lo, hi, color=c, alpha=0.12, linewidth=0)
        ax.plot(x, y, color=c, marker=mk, linestyle=ls, label=lab, markeredgecolor=SURFACE, markeredgewidth=1)
        if label_ends:
            ends = ax.__dict__.setdefault("_ends", [])
            ends.append([x[-1], y[-1], lab])
    if label_ends:
        _place_end_labels(ax)


def _place_end_labels(ax, min_gap_frac=0.055):
    """Direct labels at line ends, nudged apart vertically so they never overlap."""
    for t in ax.__dict__.get("_end_texts", []):
        t.remove()
    ends = sorted(ax.__dict__.get("_ends", []), key=lambda e: e[1])
    lo, hi = ax.get_ylim()
    gap = (hi - lo) * min_gap_frac
    ys = [e[1] for e in ends]
    for i in range(1, len(ys)):
        ys[i] = max(ys[i], ys[i - 1] + gap)
    texts = []
    for (x, _, lab), y in zip(ends, ys):
        texts.append(ax.annotate(lab, (x, y), xytext=(6, 0), textcoords="offset points", va="center",
                                 fontsize=8, color=INK2))
    ax._end_texts = texts


def make_figures(rows, outdir):
    plt = _plt()
    os.makedirs(outdir, exist_ok=True)
    suites = {r["suite"] for r in rows}
    T = {s: summary_table(rows, s) for s in suites}
    made = []

    if "loss" in T:
        fig, axes = plt.subplots(1, 2, figsize=(12, 4.4))
        _lines(axes[0], T["loss"], "loss", ["hesk", "hesk2", "hesk3", "cbba", "central", "cnp"])
        axes[0].set(title="Mission utility vs i.i.d. packet loss", xlabel="packet loss probability",
                    ylabel="utility retained (fraction of ideal)", xlim=(-0.02, 1.12))
        _lines(axes[1], T["loss"], "loss", ["hesk", "hesk2", "hesk3", "cbba", "central", "cnp"], metric="critical_ratio")
        axes[1].set(title="Critical-task utility vs packet loss", xlabel="packet loss probability",
                    ylabel="critical utility retained", xlim=(-0.02, 1.12))
        axes[0].legend(loc="lower left", fontsize=8)
        fig.tight_layout()
        fig.savefig(os.path.join(outdir, "fig_loss.png"), dpi=150)
        made.append("fig_loss.png")

    if "baseline" in T:
        conds = ["nominal", "loss30", "partition2", "attrition30", "adversarial"]
        algos = ["oracle", "hesk", "hesk2", "hesk3", "cbba", "central", "central_noquorum", "cnp"]
        fig, ax = plt.subplots(figsize=(12, 4.6))
        w = 0.8 / len(algos)
        for i, algo in enumerate(algos):
            c, mk, _, lab = STYLE[algo]
            for j, cond in enumerate(conds):
                r = next((r for r in T["baseline"] if r["cell"] == cond and r["algo"] == algo), None)
                if r is None:
                    continue
                x = j + (i - (len(algos) - 1) / 2) * w
                ax.plot([x, x], [r["utility_ratio_lo"], r["utility_ratio_hi"]], color=c, linewidth=2)
                ax.plot(x, r["utility_ratio"], marker=mk, color=c, markersize=7, markeredgecolor=SURFACE,
                        label=lab if j == 0 else None, linestyle="none")
        ax.set_xticks(range(len(conds)), conds)
        ax.set(title="Baseline comparison: mean utility with 95% CI (30 paired seeds per point)",
               ylabel="utility retained")
        ax.legend(ncol=4, fontsize=8, loc="lower left")
        fig.tight_layout()
        fig.savefig(os.path.join(outdir, "fig_baseline.png"), dpi=150)
        made.append("fig_baseline.png")

    if "ablation" in T:
        conds = ["nominal", "loss30", "adversarial"]
        abls = ["abl-lease", "abl-coalscarcity", "abl-scarcity", "abl-tiers", "abl-coalitions", "abl-upgrade",
                "abl-gossip", "abl-reconcile", "abl-lww", "abl-raw008"]
        fig, axes = plt.subplots(1, 3, figsize=(13, 4.6), sharey=True)
        for ax, cond in zip(axes, conds):
            for i, abl in enumerate(abls):
                pr = [p for p in paired(rows, "ablation", abl, "hesk3") if p["cell"] == cond]
                if not pr:
                    continue
                p = pr[0]
                col = "#e34948" if p["hi"] < 0 else ("#008300" if p["lo"] > 0 else INK2)
                ax.plot([p["lo"], p["hi"]], [i, i], color=col, linewidth=2)
                ax.plot(p["diff"], i, "o", color=col, markeredgecolor=SURFACE)
            ax.axvline(0, color=INK2, linewidth=1)
            ax.set(title=cond, xlabel="Δ utility vs full HESK v3 (paired)")
            ax.set_yticks(range(len(abls)), [a.replace("abl-", "− ") for a in abls])
        axes[0].invert_yaxis()
        fig.suptitle("Ablation: remove one component at a time (red = component helps, green = component hurts)",
                     fontsize=11, fontweight="bold")
        fig.tight_layout()
        fig.savefig(os.path.join(outdir, "fig_ablation.png"), dpi=150)
        made.append("fig_ablation.png")

    if "fd" in T:
        algos = ["hesk2", "hesk3", "cbba", "central"]
        fig, axes = plt.subplots(1, 4, figsize=(15, 4), sharey=True)
        shades = ["#a9cbf3", "#5c9be3", "#2a78d6", "#123f75"]  # one hue, light → dark = longer timeout
        for ax, algo in zip(axes, algos):
            for k, col in zip([1.5, 3.0, 6.0, 12.0], shades):
                pts = sorted((parse_cell(r["cell"])["loss"], r["utility_ratio"]) for r in T["fd"]
                             if r["algo"] == algo and parse_cell(r["cell"])["fd_k"] == k)
                if pts:
                    x, y = zip(*pts)
                    ax.plot(x, y, color=col, marker="o", label=f"timeout = {k:g} heartbeats")
            ax.set(title=STYLE[algo][3], xlabel="packet loss")
        axes[0].set_ylabel("utility retained")
        axes[0].legend(fontsize=8, loc="lower left")
        fig.suptitle("Failure-detector timeout × packet loss", fontsize=11, fontweight="bold")
        fig.tight_layout()
        fig.savefig(os.path.join(outdir, "fig_fd.png"), dpi=150)
        made.append("fig_fd.png")

    if "attrition" in T:
        fig, axes = plt.subplots(1, 3, figsize=(15, 4.2), sharey=True)
        for ax, mode in zip(axes, ["random", "scarce", "leader"]):
            _lines(ax, T["attrition"], "kill", ["hesk3", "cbba", "central", "cnp"], filt={"mode": mode})
            ax.set(title=f"Attrition — adversary kills: {mode}", xlabel="fraction of fleet destroyed", xlim=(-0.02, 0.8))
        axes[0].set_ylabel("utility retained")
        fig.tight_layout()
        fig.savefig(os.path.join(outdir, "fig_attrition.png"), dpi=150)
        made.append("fig_attrition.png")

    if "partition" in T:
        fig, axes = plt.subplots(1, 3, figsize=(15, 4.2), sharey=True)
        for ax, k in zip(axes, [2.0, 3.0, 4.0]):
            _lines(ax, T["partition"], "dur", ["hesk3", "cbba", "central", "central_noquorum"], filt={"k": k})
            ax.set(title=f"Network split into {int(k)} islands", xlabel="partition duration (s)", xlim=(40, 400))
        axes[0].set_ylabel("utility retained")
        fig.tight_layout()
        fig.savefig(os.path.join(outdir, "fig_partition.png"), dpi=150)
        made.append("fig_partition.png")

    if "burst" in T:
        fig, axes = plt.subplots(1, 3, figsize=(15, 4.2), sharey=True)
        for ax, p in zip(axes, [0.2, 0.4, 0.6]):
            _lines(ax, T["burst"], "burst", ["hesk3", "cbba", "central", "cnp"], filt={"loss": p})
            ax.set_xscale("log", base=2)
            ax.set(title=f"Bursty loss, mean loss = {p:.0%}", xlabel="mean burst length (packets, log scale)")
        axes[0].set_ylabel("utility retained")
        fig.tight_layout()
        fig.savefig(os.path.join(outdir, "fig_burst.png"), dpi=150)
        made.append("fig_burst.png")

    if "latency" in T:
        fig, ax = plt.subplots(figsize=(7, 4.2))
        _lines(ax, T["latency"], "lat", ["hesk3", "cbba", "central", "cnp"])
        ax.set_xscale("log")
        ax.set(title="Utility vs one-way link latency", xlabel="latency (s, log scale)", ylabel="utility retained")
        fig.tight_layout()
        fig.savefig(os.path.join(outdir, "fig_latency.png"), dpi=150)
        made.append("fig_latency.png")

    if "scale" in T:
        fig, axes = plt.subplots(1, 2, figsize=(12, 4.2))
        _lines(axes[0], T["scale"], "n", ["hesk3", "cbba", "central", "oracle"])
        axes[0].set(title="Utility vs fleet size", xlabel="drones", ylabel="utility retained", xscale="log")
        for algo in ["hesk3", "cbba", "central"]:
            pts = sorted((parse_cell(r["cell"])["n"], r["msgs_per_node_s"]) for r in T["scale"] if r["algo"] == algo)
            if not pts:
                continue
            x, y = zip(*pts)
            c, mk, ls, lab = STYLE[algo]
            axes[1].plot(x, [v * n for v, n in zip(y, x)], color=c, marker=mk, label=lab)
        axes[1].set(title="Radio transmissions per second (whole fleet)", xlabel="drones", ylabel="tx / s",
                    xscale="log", yscale="log")
        axes[1].legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(os.path.join(outdir, "fig_scale.png"), dpi=150)
        made.append("fig_scale.png")
    return made


def write_tables(rows, outdir):
    os.makedirs(outdir, exist_ok=True)
    for s in sorted({r["suite"] for r in rows}):
        tab = summary_table(rows, s)
        with open(os.path.join(outdir, f"summary_{s}.csv"), "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(tab[0].keys()))
            w.writeheader()
            w.writerows(tab)
    comps = []
    for suite, refs in [("baseline", ["cbba", "central", "cnp", "oracle", "hesk"]), ("loss", ["cbba", "central", "hesk", "hesk2"]),
                        ("attrition", ["cbba", "central"]), ("partition", ["cbba", "central", "central_noquorum"]),
                        ("burst", ["cbba", "central"]), ("latency", ["cbba", "central"]), ("fd", ["cbba", "hesk2"]),
                        ("scale", ["cbba", "central"])]:
        for b in refs:
            comps += [dict(suite=suite, **p) for p in paired(rows, suite, "hesk3", b)]
    comps += [dict(suite="ablation", **p) for a in sorted({r["algo"] for r in rows if r["suite"] == "ablation"} - {"hesk3"})
              for p in paired(rows, "ablation", a, "hesk3")]
    if comps:
        with open(os.path.join(outdir, "paired_comparisons.csv"), "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(comps[0].keys()))
            w.writeheader()
            w.writerows(comps)
    return comps


def main(argv=None):
    argv = argv or sys.argv[1:]
    runs, out = (argv + ["runs", "results"])[:2] if len(argv) < 2 else argv[:2]
    rows = load(runs)
    print(f"loaded {len(rows)} runs")
    write_tables(rows, os.path.join(out, "tables"))
    figs = make_figures(rows, os.path.join(out, "figures"))
    print("figures:", ", ".join(figs))


if __name__ == "__main__":
    main()
