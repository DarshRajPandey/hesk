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
STYLE = {  # algo: (color, marker, linestyle, label) — slots from the validated reference palette
    "hesk6":   ("#2a78d6", "o", "-", "HESK v6 (this work)"),
    "hesk5":   ("#4a3aa7", "h", "-", "HESK v5 (loss-adaptive)"),
    "cbba":    ("#eb6834", "s", "-", "CBBA"),
    "central_t12": ("#1baf7a", "^", "-", "Centralized (tuned timeout)"),
    "central": ("#1baf7a", "v", "--", "Centralized (default timeout)"),
    "hesk3":   ("#eda100", "D", "-", "HESK v3 (leases)"),
    "hesk4":   ("#e87ba4", "P", "-", "HESK v4 (claims only)"),
    "cnp":     ("#008300", "X", "-", "Contract Net"),
    "central_noquorum": ("#e34948", "v", "-", "Centralized (no quorum)"),
    "hesk":    ("#8d8c87", "x", ":", "HESK as specified"),
    "hesk2":   ("#52514e", "+", "--", "HESK v2"),
    "oracle":  ("#0b0b0b", "*", "-.", "Oracle (cheats)"),
    "independent": ("#8d8c87", "1", "--", "No communication"),
}
COND_LABEL = {"nominal": "Nominal", "loss30": "30% packet loss", "partition2": "2-way partition",
              "attrition30": "30% attrition", "adversarial": "Compound attack"}
ABL_LABEL = {"abl-lease": "leases (v3)", "abl-coalscarcity": "scarcity-aware recruitment (v2)",
             "abl-scarcity": "scarcity term (Alg 004)", "abl-tiers": "degradation tiers (Alg 006)",
             "abl-coalitions": "coalitions (Alg 005)", "abl-upgrade": "tier upgrades",
             "abl-gossip": "ledger gossip (Alg 007)", "abl-reconcile": "Alg 008 tie-break → none",
             "abl-lww": "Alg 008 tie-break → last-writer-wins", "abl-raw008": "epochs + leases → raw Alg 008"}


def _mk(marker, color):
    """Filled markers get a surface-coloured ring; line-only glyphs must keep their own colour."""
    if marker in ("x", "+", "1", "2", "3", "4", "|", "_"):
        return dict(markeredgecolor=color, markeredgewidth=1.8)
    return dict(markeredgecolor=SURFACE, markeredgewidth=1)


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
        ax.plot(x, y, color=c, marker=mk, linestyle=ls, label=lab, **_mk(mk, c))
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
        fig, axes = plt.subplots(1, 2, figsize=(13, 4.6), sharey=True)
        _lines(axes[0], T["loss"], "loss", ["hesk", "hesk3", "cbba", "central", "central_t12", "independent"])
        axes[0].set(title="(a) The problem: handshake-based HESK vs baselines", xlabel="packet loss probability",
                    ylabel="utility retained (fraction of ideal)", xlim=(-0.02, 1.32), xticks=[0, .2, .4, .6, .8])
        _lines(axes[1], T["loss"], "loss", ["hesk3", "hesk4", "hesk6", "cbba", "central_t12"])
        axes[1].set(title="(b) The fix: claims (v4) and adaptive switching (v5/v6)", xlabel="packet loss probability",
                    xlim=(-0.02, 1.32), xticks=[0, .2, .4, .6, .8])
        axes[0].legend(loc="lower left", fontsize=8)
        axes[1].legend(loc="lower left", fontsize=8)
        fig.tight_layout()
        fig.savefig(os.path.join(outdir, "fig_loss.png"), dpi=150)
        made.append("fig_loss.png")

    if "baseline" in T:
        conds = ["nominal", "loss30", "partition2", "attrition30", "adversarial"]
        algos = ["oracle", "hesk", "hesk3", "hesk6", "cbba", "central", "central_t12", "cnp", "independent"]
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
                ax.plot(x, r["utility_ratio"], marker=mk, color=c, markersize=7, label=lab if j == 0 else None,
                        linestyle="none", **_mk(mk, c))
        ax.set_xticks(range(len(conds)), [COND_LABEL[c] for c in conds])
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
            ax.set(title=COND_LABEL[cond], xlabel="Δ utility when removed (paired, 95% CI)")
            ax.set_yticks(range(len(abls)), ["without " + ABL_LABEL[a] for a in abls])
        axes[0].invert_yaxis()
        fig.suptitle("Ablation of HESK v3, 30 paired seeds (red: the component helps; green: removing it helps; grey: no effect)",
                     fontsize=11, fontweight="bold")
        fig.tight_layout()
        fig.savefig(os.path.join(outdir, "fig_ablation.png"), dpi=150)
        made.append("fig_ablation.png")

    if "fd" in T:
        algos = ["hesk3", "hesk5", "cbba", "central"]
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
            _lines(ax, T["attrition"], "kill", ["hesk6", "cbba", "central", "central_t12", "cnp"], filt={"mode": mode})
            ax.set(title={"random": "Random kills", "scarce": "Adversary hunts rare drones", "leader": "Adversary targets the coordinator"}[mode],
                   xlabel="fraction of fleet destroyed", xlim=(-0.02, 0.85))
        axes[0].set_ylabel("utility retained")
        fig.tight_layout()
        fig.savefig(os.path.join(outdir, "fig_attrition.png"), dpi=150)
        made.append("fig_attrition.png")

    if "partition" in T:
        fig, axes = plt.subplots(1, 3, figsize=(15, 4.2), sharey=True)
        for ax, k in zip(axes, [2.0, 3.0, 4.0]):
            _lines(ax, T["partition"], "dur", ["hesk6", "cbba", "central_t12", "central_noquorum"], filt={"k": k})
            ax.set(title=f"Network split into {int(k)} islands", xlabel="partition duration (s)", xlim=(40, 400))
        axes[0].set_ylabel("utility retained")
        fig.tight_layout()
        fig.savefig(os.path.join(outdir, "fig_partition.png"), dpi=150)
        made.append("fig_partition.png")

    if "burst" in T:
        fig, axes = plt.subplots(1, 3, figsize=(15, 4.2), sharey=True)
        for ax, p in zip(axes, [0.2, 0.4, 0.6]):
            _lines(ax, T["burst"], "burst", ["hesk3", "hesk6", "cbba", "central", "central_t12"], filt={"loss": p})
            ax.set_xscale("log", base=2)
            ax.set(title=f"Bursty loss, mean loss = {p:.0%}", xlabel="mean burst length (packets, log scale)")
        axes[0].set_ylabel("utility retained")
        fig.tight_layout()
        fig.savefig(os.path.join(outdir, "fig_burst.png"), dpi=150)
        made.append("fig_burst.png")

    if "latency" in T:
        fig, ax = plt.subplots(figsize=(7, 4.2))
        _lines(ax, T["latency"], "lat", ["hesk5", "hesk6", "cbba", "central_t12", "cnp"])
        ax.set_xscale("log")
        ax.set(title="Utility vs one-way link latency (fixed 350 ms bid window → cliff)", xlabel="one-way latency (log scale)",
               ylabel="utility retained")
        ticks = [0.02, 0.1, 0.25, 0.5, 1.0, 2.0]
        ax.set_xticks(ticks, ["20 ms", "100 ms", "250 ms", "500 ms", "1 s", "2 s"])
        ax.minorticks_off()
        fig.tight_layout()
        fig.savefig(os.path.join(outdir, "fig_latency.png"), dpi=150)
        made.append("fig_latency.png")

    if "scale" in T:
        fig, axes = plt.subplots(1, 2, figsize=(12, 4.2))
        _lines(axes[0], T["scale"], "n", ["hesk3", "hesk5", "cbba", "central", "oracle"])
        axes[0].set(title="Utility vs fleet size", xlabel="drones", ylabel="utility retained", xscale="log")
        for algo in ["hesk5", "cbba", "central"]:
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
    if "threshold" in T:
        conds = ["nominal", "loss30", "adversarial"]
        variants = [("hesk5_t0.05", 0.05), ("hesk5_t0.1", 0.1), ("hesk5_t0.2", 0.2), ("hesk5", 0.3), ("hesk5_t0.5", 0.5)]
        fig, axes = plt.subplots(1, 3, figsize=(14, 4.2), sharey=False)
        for ax, cond in zip(axes, conds):
            rows_c = {r["algo"]: r for r in T["threshold"] if r["cell"] == cond}
            xs = [t for a, t in variants if a in rows_c]
            ys = [rows_c[a]["utility_ratio"] for a, t in variants if a in rows_c]
            lo = [rows_c[a]["utility_ratio_lo"] for a, t in variants if a in rows_c]
            hi = [rows_c[a]["utility_ratio_hi"] for a, t in variants if a in rows_c]
            c, mk, _, lab = STYLE["hesk5"]
            ax.fill_between(xs, lo, hi, color=c, alpha=0.12, linewidth=0)
            ax.plot(xs, ys, color=c, marker=mk, label="HESK v5 at threshold")
            for ref in ["cbba", "central_t12", "hesk4"]:
                if ref in rows_c:
                    rc, _, rls, rlab = STYLE[ref]
                    ax.axhline(rows_c[ref]["utility_ratio"], color=rc, linestyle="--", linewidth=1.5, label=rlab)
            ax.set(title=COND_LABEL[cond], xlabel="switch to claims when local loss estimate exceeds")
        axes[0].set_ylabel("utility retained")
        axes[0].legend(fontsize=8, loc="lower left")
        fig.suptitle("HESK v5 switching threshold (30 paired seeds)", fontsize=11, fontweight="bold")
        fig.tight_layout()
        fig.savefig(os.path.join(outdir, "fig_threshold.png"), dpi=150)
        made.append("fig_threshold.png")

    if "decomp" in T:
        cells = ["only=burstloss", "only=partition", "only=scarcekill", "only=degrade",
                 "all-minus=burstloss", "all-minus=partition", "all-minus=scarcekill", "all-minus=degrade"]
        fig, ax = plt.subplots(figsize=(11, 4.6))
        for k, (a, off) in enumerate([("hesk3", -0.12), ("hesk6", 0.12)]):
            ps = {p["cell"]: p for p in paired(rows, "decomp", a, "cbba")}
            c, mk, _, lab = STYLE[a]
            for i, cell in enumerate(cells):
                if cell not in ps:
                    continue
                p = ps[cell]
                ax.plot([p["lo"], p["hi"]], [i + off, i + off], color=c, linewidth=2)
                ax.plot(p["diff"], i + off, mk, color=c, label=f"{lab} − CBBA" if i == 0 else None, **_mk(mk, c))
        ax.axvline(0, color=INK2, linewidth=1)
        names = {"burstloss": "bursty loss", "partition": "partition", "scarcekill": "rare-drone kills", "degrade": "sensor failures"}
        ax.set_yticks(range(len(cells)), [("only " if c.startswith("only") else "all except ") + names[c.split("=")[1]]
                                          for c in cells])
        ax.axhline(3.5, color=GRID, linewidth=1.5)
        ax.invert_yaxis()
        ax.set(title="Failure analysis: each stressor alone vs all-but-one (paired Δ utility vs CBBA, 95% CI)",
               xlabel="Δ utility (right of zero = HESK better)")
        ax.legend(fontsize=8, loc="lower right")
        fig.tight_layout()
        fig.savefig(os.path.join(outdir, "fig_decomp.png"), dpi=150)
        made.append("fig_decomp.png")
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
    refs = ["cbba", "central", "central_t12", "central_noquorum", "cnp", "oracle", "independent", "hesk", "hesk3"]
    for suite in ["baseline", "loss", "attrition", "partition", "burst", "latency", "fd", "scale", "decomp", "fdkill",
                  "threshold"]:
        present = {r["algo"] for r in rows if r["suite"] == suite}
        heads = ["hesk3", "hesk5", "hesk6"] + (["hesk5_t0.05", "hesk5_t0.1", "hesk5_t0.2", "hesk5_t0.5"] if suite == "threshold" else [])
        for a in heads:
            for b in refs:
                if a != b and a in present and b in present:
                    comps += [dict(suite=suite, **p) for p in paired(rows, suite, a, b)]
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
