# Contributing to HESK

HESK is a research prototype. The most valuable contributions are the ones that make a claim
**falsifiable**: a failing test, a minimal counterexample, a new baseline, or an experiment that
could embarrass the current design.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,bench]"
make test        # ~15 s: unit, simulator and property tests
make quick       # 5-seed smoke run of every experiment (~1 min)
```

## Ground rules

1. **Determinism is a feature.** Everything in `hesk.sim` and `hesk.bench` must be a pure function of
   `(parameters, seed)`. Draw randomness from `random.Random(f"hesk:{seed}:<stream>")`, never from
   the global generator, and never iterate a `set` of strings in a result-affecting way.
   `tests/sim/test_determinism.py` enforces bit-identical results across processes.
2. **Nodes never read simulator truth.** The simulator may know global state only to *score* a run.
3. **Fair baselines.** If you add a competitor, give it its most favourable reading of the protocol
   (see the `relay`/`direct` and perfect-failure-detector choices in `docs/research/FINDINGS.md`).
4. **A new defect needs three things:** a minimal standalone repro in `tests/failures/` marked
   `xfail(strict=True)` that asserts the *correct* behaviour, an entry in the findings table, and, where
   it matters at system level, an experiment cell showing its effect size with a confidence interval.
5. **A new design choice needs an ablation.** Add a switch that restores the old behaviour and an
   experiment cell that isolates it (see `LatticeConfig` and `hesk.bench.legacy_patches`).
6. **Report negative results.** If a fix does not help, or a baseline beats HESK, that goes in the
   findings with the same prominence as a win.

## Adding an experiment

1. Add a branch to `hesk/bench/experiments.py:build` returning `Cell`s (labels, `Params`, implementations).
2. `python -m hesk.bench run <ID> --seeds 20 --out /tmp/x && python -m hesk.bench report --out /tmp/x`.
3. Add the experiment to `EXPERIMENTS`, and a table title / figure in `hesk/bench/analyze.py`.
4. Re-generate `results/` with `make results` and commit the raw `.jsonl.gz`, `manifest.json`, `REPORT.md`.

## Style

Match the surrounding code. Keep comments for the *why* (an invariant, a paper, a trap).
