# One-command entry points. Every target is deterministic given the code revision.
PY ?= python3
W  ?= $(shell nproc 2>/dev/null || echo 4)

.PHONY: install test smoke reproduce analyze verify

install:            ## editable install with analysis extras
	$(PY) -m pip install -e '.[dev,analysis]'

test:               ## unit + harness tests (~1 min)
	$(PY) -m pytest tests -q

smoke:              ## every suite with 1 seed per cell (~10 min on 4 cores)
	$(PY) -m hesk_sim.cli run all --reps 1 --out runs_smoke --workers $(W)

reproduce:          ## the full study: 12,985 runs, 13.4 CPU-hours (~3.5-5 h on 4 cores, ~15 min on 64)
	$(PY) -m hesk_sim.cli run all --out runs --workers $(W)

analyze:            ## tables + figures from runs/ (or results/raw/)
	$(PY) -m hesk_sim.analyze $(if $(wildcard runs/*.jsonl),runs,results/raw) results

verify:             ## re-run 24 random published runs, check bit-exact match
	$(PY) scripts/verify_reproducibility.py results/raw/*.jsonl.gz --n 24
