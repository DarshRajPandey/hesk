# HESK — Swarm Intelligence Laboratory

A browser frontend for the HESK kernel. React 19, TypeScript (strict), Vite, Tailwind 4, Recharts, Motion.

```bash
npm install
npm run dev        # http://localhost:5173
npm test           # kernel parity + simulation tests
npm run build
```

## What is real and what is not

HESK today is a Python library of eight algorithms (`src/hesk`) with unit tests. It has **no runtime, transport, simulator or service API**, so there is nothing for a frontend to connect to. This app therefore runs in **demonstration mode**:

| Layer | Where | Status |
| --- | --- | --- |
| Matching, bidding, coalition formation, degradation, ledger merge, reconciliation | `src/kernel/*.ts` | TypeScript port of the Python algorithms. `tests/parity.test.ts` replays 156 match, 13 allocation, 26 coalition, 6 degradation and one reconciliation case against fixtures generated from the real Python package. |
| World, radio links, failure detection delay, replica fork/merge, energy drain, message counts | `src/sim/engine.ts` | Demonstration harness. Not part of HESK. Records are tagged `kernel`, `harness` or `operator`. |
| Scenario data | `src/sim/catalog.json` | Shared by the app and the Python fixture generator. |
| UI | `src/views`, `src/components` | Talks only to `SimulationAdapter` (`src/sim/adapter.ts`). |

A remote adapter implementing `SimulationAdapter` can replace `LocalDemoAdapter` without touching any view.

Regenerate fixtures after changing the catalog or the Python kernel (from the repo root, with `pip install -e .`):

```bash
python3 frontend/scripts/gen_parity_fixtures.py
```

## Findings surfaced from the kernel

Found while building the port and shown in the Architecture Explorer: coalitions can never satisfy a categorical requirement; reconciliation ignores keys changed on only one side of a partition; graceful-degradation reassignment ignores energy and scarcity and cannot pre-empt lower-priority tasks; `ResponsibilitySuccession` is declared but unused. The core engine was not modified.

## Not included

3D view (a 2D topology was chosen for legibility), a live backend, mission "completion rate" (tasks are continuous services; mission utility is shown instead), and any benchmark of HESK on real hardware.
