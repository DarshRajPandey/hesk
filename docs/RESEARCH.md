# HESK: a reproducible study of decentralized task allocation for heterogeneous swarms under faults

**Status:** simulation study, 10,365 automated runs, every number reproducible from this repository.
**Plain-language introduction:** [`UNDERSTANDING_HESK.md`](UNDERSTANDING_HESK.md) · **Next steps and hardware plan:** [`ROADMAP.md`](ROADMAP.md)

---

## Abstract

HESK is a decentralized coordination kernel that assigns tasks to heterogeneous drones using
capability matching, a scarcity-aware auction, multi-drone coalitions, graceful degradation
tiers, and a gossiped ownership ledger with partition reconciliation. We built a deterministic
discrete-event simulator, wired the kernel into a message protocol, and compared it against
CBBA (the standard decentralized market baseline), an elected-leader optimal dispatcher (with
and without a Raft-style quorum), Contract Net, a zero-communication control and a
perfect-information oracle. We ran 10,365 paired experiments across packet loss, burstiness,
partitions, latency, attrition, failure-detector tuning and fleet size.

The kernel *as specified* beats every baseline except the oracle in benign conditions, but
**collapses under packet loss, losing 0.25 utility at 30% loss.** We trace the collapse to two
mechanisms, *suspicion-driven churn* and *handshake fragility*, and confirm each by
intervention. Three successive design changes, each motivated by a measured mechanism, give a
loss-adaptive variant (**HESK v5**). It is never significantly worse than CBBA at any i.i.d.
loss level. It is significantly better at 0–30% and 90% loss (up to +0.068 utility). It beats
centralized dispatch at every loss level (up to +0.457) and the perfect-information 1:1 oracle
in nominal conditions (+0.063).

We also report where HESK still loses: under **compound** faults (−0.021 vs CBBA), long
correlated loss bursts, and heavy attrition, where every algorithm converges. Along the way we
found two defects in the reconciliation algorithm and one in coalition formation, all encoded
as regression tests.

## 1. Research questions

| RQ | Question | Experiments |
|---|---|---|
| RQ1 | Does HESK preserve more mission utility than strong conventional allocators? | `baseline`, `loss`, `partition`, `attrition`, `burst`, `latency`, `scale` |
| RQ2 | Which HESK components actually matter, and when? | `ablation` |
| RQ3 | Under what conditions does HESK fail, and why? | `decomp`, `fd`, `fdkill`, `burst` |
| RQ4 | Do the fixes motivated by RQ3 work, and what do they cost? | `loss`, `threshold` |

## 2. Method

### 2.1 Simulator (`src/hesk_sim/`)

* **Deterministic discrete-event engine.** All randomness comes from named sub-streams of one
  seed, so a run is a pure function of (scenario, algorithm, seed). We re-ran 24 randomly chosen
  published runs and **all 24 reproduced bit-exactly** (`make verify`).
* **Common random numbers.** The seed depends on (suite, condition, repetition) and *not* on the
  algorithm, so every algorithm faces the same fleet, mission, task arrival times and fault
  schedule. All comparisons are **paired**.
* **Fleet:** 24 drones in 6 archetypes, with deliberately rare capabilities (3 thermal, 2 lidar,
  2 GPU). **Mission:** 18 tasks across 5 templates. 10 exist at launch and 8 are discovered
  mid-mission by whichever drone is nearest. Each task has 1–3 degradation tiers. Drones fly at
  15 m/s in a 1 km² area, and a task earns value only while a drone (or a whole coalition) is
  physically on station.
* **Radio:** unreliable broadcast with i.i.d. (Bernoulli) or bursty (Gilbert-Elliott) loss,
  latency + exponential jitter, partitions into *k* islands, and dead nodes that neither send
  nor receive.
* **Faults:** kills (random, scarce-platform-first, coordinator-first, busiest-first), sensor
  degradation, partitions, loss and jamming windows.
* **Isolation invariant:** agents read only their own body and their messages. A test
  (`tests/sim/test_harness.py`) checks that agent modules never reference world state.
* **Fairness:** every algorithm uses the same heartbeat period (1 s), the same failure detector
  (suspect after 3 missed heartbeats unless stated) and the same catalogue gossip. Baselines are
  **tier-aware**: they score each drone by the best tier it can serve, so HESK's degradation
  ladder is not a free advantage.

### 2.2 Metric

**Utility retained** = Σ over tasks and time of `priority × quality of the best tier actually
served` ÷ the value if every task were served at tier 0 from its arrival. "Actually served"
uses ground truth: the drone(s) must be alive, on station, and *truly* satisfy the tier. Travel
time makes 1.0 unreachable. The oracle scores about 0.77. Secondary metrics: critical-task
utility, coverage, duplicated effort (agent-seconds), recovery time after kills, and radio
transmissions.

### 2.3 Algorithms

| Name | What it is | Why it's a serious baseline |
|---|---|---|
| **CBBA** | Consensus-Based Bundle Algorithm, Choi, Brunet & How, *IEEE T-RO* 2009 (MIT Aerospace Controls Lab). Full receiver-side consensus table, bundle length 1, run asynchronously over heartbeats | The standard decentralized baseline in multi-UAV task-allocation research. Provably converges to a conflict-free assignment on a connected network |
| **Centralized (quorum)** | Leader = lowest id it can hear. Every 2 s it solves the assignment problem *optimally* (Kuhn-Munkres / Hungarian via SciPy) and broadcasts the plan. It may only re-plan while it hears a strict majority (Raft-style) | The fleet-manager / ground-control-station architecture used by commercial fleets operating in well-connected airspace, plus the safety rule of consensus systems such as etcd or ZooKeeper |
| **Centralized (no quorum)** | Same, but every island elects its own leader | The availability-first (AP) version of the same design |
| **Contract Net** | Smith, *IEEE Trans. Computers* 1980: announce, bid, award | The protocol HESK extends. Equivalent to HESK with every HESK addition removed |
| **Oracle** | Optimal Hungarian assignment from ground truth, zero communication | Reference only: perfect information for a 1:1 assigner. **Not** an upper bound, since it can't form coalitions |
| **No communication** | Each drone serves the task that's best for itself; it never transmits | Null hypothesis: what coordination is worth |
| HESK (as specified) | Algorithms 001–008 exactly as in `docs/algorithms`, wired into Contract Net with ledger gossip | |
| HESK v2 | + scarcity-aware coalition recruitment (Finding 1) | |
| HESK v3 | + lease-based ownership with epidemic per-member renewal (Finding 2) | |
| HESK v4 | v3 with the auction handshake replaced by state-based claims on the gossiped ledger (Finding 3) | |
| **HESK v5** | Each drone switches between v3 auctions and v4 claims from its own measured heartbeat loss | |

### 2.4 Statistics

Each cell reports the mean and a 95% percentile-bootstrap CI (2,000 resamples). Comparisons
are paired by seed: mean paired difference, bootstrap CI, Wilcoxon signed-rank *p*, and win
rate. Below, **bold** = *p* < 0.01. Seeds per cell: 30 (`baseline`, `ablation`, `decomp`,
`threshold`), 20 (`loss`, `fdkill`), 15 (`burst`, `partition`, `latency`), 10 (`attrition`,
`fd`), 5 (`scale`). Full tables: `results/tables/`.

## 3. Findings

### Finding K1: Two of the reconciliation rules don't converge (kernel defect)

`resolve_resource` and `resolve_mission_policy` break ties in favour of the **local** replica.
When two observations fall inside the 2 s clock-drift window with equal provenance, replica A
keeps its value and replica B keeps its own, **forever**. This violates the convergence
property a CRDT-style merge must have. Found by direct probing before any swarm was simulated.
Encoded as a strict `xfail` in `tests/sim/test_kernel_findings.py`, so the suite will flag the
day it's fixed. *Fix:* any tie-break must be a total order independent of which replica runs it
(e.g. compare `(value_hash, node_id)`).

### Finding K2: Alg 008 has no notion of causality (kernel defect, measured cost up to −0.136)

The ownership cascade (progress → match quality → earliest time → id) cannot tell a *newer*
assignment from a *concurrent* one. A dead owner's stale record (progress 0.6) beats its
legitimate successor (progress 0) and resurrects the dead owner. Using Alg 008 raw as the only
ownership rule costs **−0.051 nominal, −0.136 at 30% loss, −0.109 adversarial** (ablation
`abl-raw008`). In contrast, replacing the cascade's tie-break with nothing (`abl-reconcile`) or
with last-writer-wins (`abl-lww`) costs **≤ 0.015**. **Lesson: the causal-ordering layer is
critical; the tie-break cascade is nearly irrelevant.**

### Finding 1: Coalition formation is a back door around the scarcity guard

Running HESK as specified, a priority-0.6 detection task formed a **4-drone coalition that
included both remaining thermal drones**, purely to pool compute. Critical search-and-rescue
tasks discovered later found no thermal drone free and starved for the rest of the mission.
Alg 004 penalises solo bids that waste scarce capabilities, but Alg 005 recruits coalition
members without that check.

*Fix (v2):* bidders report their scarcity penalty for every tier, including tiers they can't
serve alone, and the announcer excludes high-penalty drones from coalition recruitment.
*Effect (baseline, 30 seeds):* critical-task utility **0.576 → 0.844**, overall utility
**0.769 → 0.830**. *Lesson:* a guard that only one code path enforces isn't a guard.

### Finding 2: Under loss, the failure detector becomes the allocator ("suspicion-driven churn")

At 30% i.i.d. loss, HESK v2 lost 0.30 utility. Instrumentation showed each drone falsely
suspecting **0.54 live peers at any instant**, matching theory (P(3 missed heartbeats) =
0.3³ = 2.7% per peer × 23 peers ≈ 0.62). When the announcer falsely suspected a working owner,
it re-auctioned the task. The new award's higher epoch then **evicted the live incumbent**,
which happened 78 times per mission versus once at 0% loss. Each eviction costs a full
flight-time of zero utility.

*Fix (v3):* ownership is a **lease** (Gray & Cheriton, 1989). Each owner renews a per-member
timestamp every tick. Renewals spread epidemically through *any* neighbour's gossip, not only
direct heartbeats. A live incumbent with a fresh lease can't be evicted except by an explicit
upgrade.

*Effect:* +0.247 utility at 30% loss (v3 vs as-specified, 30 seeds, *p* = 2e-9).

*Independent confirmation (`fd` suite):* without leases, the failure-detector timeout is the
single most important parameter. At 30% loss, v2 goes from 0.42 at a 1.5-heartbeat timeout to
0.73 at 12. With leases, v3 is essentially insensitive (0.73–0.77). **Leases decouple
correctness from failure-detector tuning.**

### Finding 3: Transactional allocation is what loss kills; coordination still pays

Even with leases, v3 fell behind CBBA beyond 40% loss, and CBBA was flat from 0% to 90% loss.

* **Falsified hypothesis.** We suspected CBBA was simply degrading into "everyone does their
  own thing". The zero-communication control scores **0.31** versus CBBA's **0.75** at 90%
  loss, so coordination is still worth +0.44 utility at 90% loss. Hypothesis rejected.
* **Mechanism.** CBBA has no request/response handshake. A drone *claims* by writing to its own
  table, and every heartbeat rebroadcasts the full table, so any single surviving packet from
  any neighbour carries the whole state forward. HESK's award needs ANNOUNCE → BID → AWARD → ACK
  through one announcer, and every step must survive. Multi-party coalition awards need every
  member's ACK.
* **Intervention (v4).** Keep everything else (costs, scarcity, tiers, leases), but make solo
  allocation a state-based claim on the gossiped ledger. Then v4 is **flat from 0% to 90% loss
  (0.773 → 0.774)** and beats CBBA at 90% loss (0.774 vs 0.749) with **47× less duplicated
  effort** (44 vs 2,076 agent-seconds). Mechanism confirmed.
* **The cost.** Claims are single-drone. v4 can only form coalitions through the periodic
  upgrade auction, so coalition share at 0% loss falls from 0.23 to 0.15, and claim switching
  races with upgrades (250 duplicate agent-seconds at 0% loss vs 0 for v3). v4 loses the
  nominal edge (0.773 vs 0.824). **Multi-party composition needs transactions,
  and transactions are what loss kills.**

### Finding 4: A locally measured loss estimate is enough to get both

**HESK v5** switches each drone from auctions to claims when its *own* heartbeat-reception rate
implies more than 30% loss. No oracle is involved: a drone counts the heartbeats it receives
against the number it expects.

Paired utility difference vs CBBA and vs centralized dispatch (20 seeds per point):

| loss | 0% | 10% | 20% | 30% | 40% | 50% | 60% | 70% | 80% | 90% |
|---|---|---|---|---|---|---|---|---|---|---|
| v5 − CBBA | **+.068** | **+.064** | **+.045** | **+.032** | +.003 | −.015 | −.024 | −.014 | +.007 | **+.016** |
| v5 − Centralized | **+.052** | **+.045** | **+.038** | **+.066** | **+.088** | **+.128** | **+.200** | **+.281** | **+.313** | **+.457** |
| v5 − v3 | 0 | 0 | 0 | +.020 | +.017 | **+.035** | **+.108** | **+.183** | **+.232** | **+.286** |

v5 is **never significantly worse than CBBA** and is significantly better in 5 of 10 loss levels.

**Mode-boundary turbulence.** At 40–60% loss, v5's duplicated effort spikes to 160–190
agent-seconds, versus 0–10 below and about 60–110 above. In that band, drones' local estimates
straddle the threshold, so part of the fleet runs auctions while the rest runs claims. That's
the classic signature of a switching controller without hysteresis. Threshold sensitivity:
§3.9.

### Finding 5: Component importance reorders completely across regimes (ablation, 30 seeds)

Δ utility when one component is removed from v3 (negative = the component helps):

| Removed | nominal | 30% loss | adversarial |
|---|---|---|---|
| scarcity term (Alg 004) | **−0.108** | **−0.064** | −0.018 |
| coalitions (Alg 005) | **−0.087** | **−0.035** | **+0.020** (hurts!) |
| degradation tiers (Alg 006) | **−0.062** | −0.036 | **−0.197** |
| scarcity-aware recruitment (v2) | **−0.056** | +0.020 | −0.001 |
| upgrades | **−0.044** | **−0.039** | −0.010 |
| leases (v3) | 0.000 | **−0.228** | **−0.075** |
| ledger gossip (Alg 007) | 0.000 | **−0.113** | **−0.021** |
| Alg 008 cascade → nothing / LWW | 0.000 | 0.000 | **−0.015** / −0.006 |
| raw Alg 008 instead of epochs + leases | **−0.051** | **−0.136** | **−0.109** |

The most important component is **scarcity** in benign conditions, **leases** under loss, and
**degradation tiers** under compound attack. Gossip and leases are worth exactly zero when the
network is perfect, and dominant when it isn't. Coalitions *hurt* under compound attack: they
tie up two drones, and either one dying breaks the task. **No single evaluation condition would
have revealed what HESK's components are for.**

### Finding 6: Faults interact non-additively; repair needs the channel (`decomp`, 30 seeds)

Under the combined adversarial condition (20% bursty loss + 2-way partition + 25% kills of the
scarcest drones + 3 sensor failures), v5 loses to CBBA by −0.021 (*p* = 2e-4). One factor at a
time:

| condition | v5 − CBBA |
|---|---|
| bursty loss alone | **+0.031** |
| partition alone | **+0.039** |
| sensor degradation alone | **+0.044** |
| scarce kills alone | +0.007 |
| all four | **−0.021** |
| all but partition | **−0.013** |
| all but kills | −0.007 |

Every single fault favours HESK, but the combination doesn't. The harmful interaction is
**kills × loss**. Kills create *re-allocation demand*, and HESK's re-allocation in auction mode
is handshake-bound. With kills alone, HESK's coverage trails CBBA's by 0.019. Add bursty loss
and the gap triples to 0.062, while median repair time goes from 52 s → 62 s (HESK) versus
41 s → 26 s (CBBA). Bursty loss averages 20%, below v5's switching threshold, so v5 stays in
auction mode. Always-claims v4 matches CBBA here (0.566 vs 0.564). **HESK optimises allocation
quality; CBBA optimises repair speed; loss taxes repair.**

### Finding 7: Allocation intelligence is a luxury good (attrition, 10 seeds)

HESK v5's lead over CBBA is **+0.10 with the full fleet**. It shrinks to about +0.05 at 10%
losses and about +0.03 at 20%, and is statistically gone by about 40% destroyed. That holds
whether the adversary kills at random, hunts scarce platforms, or targets the coordinator.
HESK's gains come from managing slack (reserving rare drones, composing coalitions from spare
ones), and slack is exactly what attrition removes.

### Finding 8: Partitions: HESK's edge depends on split duration; the price of consistency (15 seeds)

v5 − CBBA (and v5 − centralized) by number of islands *k* and split duration:

| | 60 s | 150 s | 300 s |
|---|---|---|---|
| k = 2 | **+0.066** (**+0.063**) | **+0.046** (**+0.059**) | +0.017 (**+0.043**) |
| k = 3 | **+0.057** (**+0.056**) | +0.013 (+0.016) | +0.008 (+0.021) |
| k = 4 | **+0.050** (**+0.049**) | **+0.039** (**+0.038**) | −0.011 (−0.003) |

HESK's advantage is clear for short splits and **disappears for long ones**. Long-lived islands
behave like separate, smaller fleets with less slack to manage (compare Finding 7).

The quorum comparison quantifies the CAP trade-off. For a 300 s two-way split, Raft-style
quorum costs **−0.047 utility** versus the no-quorum leader (0.654 vs 0.701), and in exchange
cuts duplicated effort **about 6×** (395 vs 2,311 agent-seconds).

### 3.9 Further results

*Filled in from `results/tables/` once all suites are complete: bursty loss, latency, scale,
switching threshold, and failure-detector fairness under kills.*

## 4. Threats to validity

* **Simulation, not flight.** Movement is kinematic (constant speed, no wind, no collisions)
  and the radio is all-to-all within an island (no range-limited multi-hop). Absolute utility
  numbers are model-specific. *Shapes, crossovers and mechanisms* are the claims, and
  [`ROADMAP.md`](ROADMAP.md) plans a sim-to-real check of exactly those.
* **One mission family.** All results use one fleet mix and one task mix, scaled. HESK's
  nominal edge depends on coalitions being possible (GPU + lidar/EO). A homogeneous fleet would
  erase it by construction.
* **Utility counts redundancy as free insurance.** Duplicated effort is reported but not
  penalised. Penalising it would favour HESK more, because CBBA duplicates up to 18× more at
  high loss.
* **Baselines are our implementations.** CBBA is implemented from the paper's consensus table;
  the centralized dispatcher uses SciPy's Hungarian solver. Both pass the same harness tests.
  The `fd` suite shows the centralized baseline is sensitive to the failure-detector timeout,
  which we test explicitly (`fdkill`).
* **Researcher degrees of freedom.** v2–v5 were designed *after* looking at data. Every claim
  about them is backed by suites re-run from scratch on seeds that were fixed in advance by
  cell name, and every intermediate version stays in the registry so the progression can be
  checked.

## 5. Reproduce

```bash
pip install -e '.[dev,analysis]'
make test        # 1 min
make verify      # re-run 24 random published runs, check bit-exact match
make reproduce   # all 10,365 runs (~4 h on 4 cores, ~15 min on a 64-vCPU VM)
make analyze     # tables + figures into results/
```

Raw records (one JSON line per run, including seed, config, git revision and every metric)
are in `results/raw/`.
