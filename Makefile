.PHONY: install test quick results report clean
PY ?= python

install:
	$(PY) -m pip install -e ".[dev,bench]"

test:            ## unit + simulator + property tests (~15 s)
	$(PY) -m pytest tests -q

quick:           ## 5-seed smoke run of every experiment (~1 min)
	$(PY) -m hesk.bench run all --seeds 5 --out /tmp/hesk-quick && $(PY) -m hesk.bench report --out /tmp/hesk-quick

results:         ## full, publication-size run (all seeds; writes ./results)
	$(PY) -m hesk.bench run all --out results && $(PY) -m hesk.bench report --out results

report:
	$(PY) -m hesk.bench report --out results

clean:
	rm -rf .pytest_cache .hypothesis build src/*.egg-info
