# HESK: a reproducible study of decentralized task allocation for heterogeneous swarms under faults

**Status:** simulation study, **12,985 automated runs**, every number reproducible from this repository.
**Plain-language introduction:** [`UNDERSTANDING_HESK.md`](UNDERSTANDING_HESK.md) · **Next steps, compute budget, hardware plan:** [`ROADMAP.md`](ROADMAP.md)

---

## Abstract

HESK is a decentralized coordination kernel that assigns tasks to heterogeneous drones using
capability matching, a scarcity-aware auction, multi-drone coalitions, graceful-degradation
tiers, and a gossiped ownership ledger with partition reconciliation. We built a deterministic
discrete-event simulator, wired the kernel into a message protocol, and compared it on paired
seeds against:

* CBBA, the standard decentralized market baseline;
* an elected-leader optimal (Hungarian) dispatcher, with and without a Raft-style quorum, at its
  default and at its best failure-detector timeout;
* Contract Net;
* a zero-communication control;
* a perfect-information oracle.

The experiments cover packet loss, bursty loss, partitions, latency, attrition, compound
attacks, failure-detector tuning and fleet size.

The kernel *as specified* leads in benign conditions but **loses 0.25 of its utility at 30%
packet loss**. We trace this to four mechanisms, each confirmed by intervention:

* coalitions bypassing the scarcity guard;
* false failure suspicions evicting live task owners;
* transactional handshakes that loss destroys;
* a hard-coded bid window that makes allocation impossible above about 250 ms latency.

The resulting **HESK v6** beats CBBA by **+0.091** utility nominally and by **+0.048** at 30%
loss. It is never significantly worse than CBBA at any i.i.d. loss level, and beats a *tuned*
centralized dispatcher by up to **+0.24** at extreme or bursty loss.

We also report where it still loses: under compound faults, where CBBA repairs faster; at
50–60% loss against a well-tuned centralized dispatcher; and above 1 s latency. Along the way
we found two convergence defects in the kernel's reconciliation algorithm, and we falsified
three of our own hypotheses.

## 1. Research questions

| RQ | Question | Experiment suites |
|---|---|---|
| RQ1 | Does HESK preserve more mission utility than strong conventional allocators? | `baseline` `loss` `partition` `attrition` `burst` `latency` `scale` |
| RQ2 | Which components actually matter, and when? | `ablation` |
| RQ3 | When does HESK fail, and why? | `decomp` `fd` `fdkill` `burst` `latency` |
| RQ4 | Do the fixes work, what do they cost, and are the baselines fairly tuned? | `loss` `threshold` `fd` `fdkill` |

## 2. Method

### 2.1 Simulator (`src/hesk_sim/`)

* **Deterministic.** A run is a pure function of (scenario, algorithm, seed): every random draw
  comes from a named sub-stream of one seed. `make verify` re-runs randomly sampled published
  runs. **24/24 reproduced bit-exactly**, including runs recorded at four earlier git revisions.
* **Paired by construction.** The seed depends on (suite, condition, repetition), never on the
  algorithm, so every algorithm faces the identical fleet, mission, task-arrival times and fault
  schedule.
* **Fleet:** 24 drones in six archetypes with deliberately rare capabilities (3 thermal, 2 lidar,
  2 GPU). **Mission:** 18 tasks across five templates. 10 exist at launch and 8 are discovered
  mid-mission by the nearest drone. Each task has 1–3 degradation tiers. Drones fly at 15 m/s
  over 1 km²; value accrues only while a drone, or a whole coalition, is on station.
* **Radio:** broadcast with i.i.d. or bursty (Gilbert-Elliott) loss, latency + exponential
  jitter, partitions into *k* islands, and dead nodes that neither send nor receive.
* **Faults:** kills (random, rarest-platform-first, coordinator-first), sensor degradation,
  partitions.
* **Isolation:** agents read only their own body and the messages they receive. A test checks
  that agent modules never touch world state.
* **Same radio stack for everyone:** 1 s heartbeats, the same timeout failure detector and the
  same task-catalogue gossip. Baselines are **tier-aware**: they score each drone by the best
  tier it can serve, so HESK's degradation ladder isn't a free advantage.

### 2.2 Metric

**Utility retained** = Σ over tasks and time of *priority × quality of the best tier actually
served*, ÷ the value if every task were served at tier 0 from arrival. "Actually served" is
judged from ground truth: the drones must be alive, on station, and *truly* meet the tier.
Travel time makes 1.0 unreachable; the oracle scores about 0.77. Secondary metrics:
critical-task utility, coverage, duplicated effort (agent-seconds), recovery time after kills,
and radio traffic.

### 2.3 Algorithms

| Name | What it is | Why it's a serious baseline |
|---|---|---|
| **CBBA** | Consensus-Based Bundle Algorithm (Choi, Brunet & How, *IEEE T-RO* 2009, MIT Aerospace Controls Lab). Full receiver-side consensus table, bundle length 1, asynchronous over heartbeats | The standard decentralized baseline in multi-UAV task-allocation research. Provably conflict-free on a connected network |
| **Centralized** | Leader = lowest id it can hear. Every 2 s it solves the assignment problem *optimally* (Kuhn-Munkres via SciPy) and broadcasts the plan; may only re-plan while it hears a strict majority (Raft-style quorum). Run at the default timeout (3 heartbeats) and **tuned** (12 heartbeats, its best setting per Finding 10) | The ground-control / fleet-manager architecture used by commercial fleets in well-connected airspace, plus the safety rule of consensus stores such as etcd and ZooKeeper |
| Centralized, no quorum | Every island elects its own leader | Availability-first (AP) variant |
| **Contract Net** | Smith, *IEEE Trans. Computers* 1980 | The protocol HESK extends: HESK with every HESK addition removed |
| Oracle | Optimal assignment from ground truth, zero communication | Reference only. Perfect information, but no coalitions, so **not** an upper bound |
| No communication | Each drone serves the task that's best for itself and never transmits | What coordination is worth |
| HESK | Algorithms 001–008 exactly as specified, wired into Contract Net with ledger gossip | |
| v2 | + scarcity-aware coalition recruitment | Finding 1 |
| v3 | + lease-based ownership with epidemic per-member renewal | Finding 2 |
| v4 | v3 with the auction handshake replaced by state-based claims on the gossiped ledger | Finding 3 |
| v5 | each drone switches auctions ↔ claims from its own measured heartbeat loss | Finding 4 |
| **v6** | v5 + bid window and timeouts sized from measured round-trip delay | Finding 9 |

### 2.4 Statistics

Each cell reports the mean with a 95% percentile-bootstrap CI (2,000 resamples). Comparisons are
paired by seed: mean paired difference, bootstrap CI, Wilcoxon signed-rank *p*, and win rate.
**Bold** = *p* < 0.01. Seeds per cell: 30 (`baseline` `ablation` `decomp` `threshold`), 20
(`loss` `fdkill`), 15 (`burst` `partition` `latency`), 10 (`attrition` `fd`), 5 (`scale`;
directional only, since a Wilcoxon test can't reach *p* < 0.05 with 5 pairs). All tables:
[`results/tables/`](../results/tables). Raw records: [`results/raw/`](../results/raw).

## 3. Findings

### K1. Two reconciliation rules never converge (kernel defect)

`resolve_resource` and `resolve_mission_policy` (Alg 008) break ties in favour of the
**local** replica. When two observations fall inside the 2 s clock-drift window with equal
provenance, replica A keeps its value and replica B keeps its own, **permanently**. That violates
the convergence a CRDT-style merge needs. We found it by direct probing before any swarm was
simulated. It's encoded as a strict `xfail` in `tests/sim/test_kernel_findings.py`, which will
flag the day it's fixed. *Fix:* tie-breaks must be a total order that doesn't depend on which
replica evaluates them.

### K2. The ownership cascade has no causal order (kernel defect; costs up to −0.136)

Alg 008's cascade (progress → match quality → earliest time → id) can't tell a *newer*
assignment from a *concurrent* one, so a dead owner's stale record (progress 0.6) beats its
legitimate successor (progress 0). Using raw Alg 008 for ownership costs **−0.051 nominal,
−0.136 at 30% loss, −0.109 under compound attack** (ablation). Swapping the cascade's tie-break
for nothing, or for last-writer-wins, costs **≤ 0.015**. **The causal layer is critical; the
tie-break cascade barely matters.**

### 1. The scarcity guard had a back door

Running the kernel as specified, a priority-0.6 detection task formed a **4-drone coalition
containing both remaining thermal drones**, purely to pool compute. Critical search-and-rescue
tasks discovered later found no thermal drone free and starved. Alg 004 penalises solo bids that
waste rare capabilities; Alg 005 recruits coalition members without that check. *Fix (v2):*
bidders report their scarcity penalty for every tier, and high-penalty drones are excluded from
recruitment. *Effect (30 seeds):* critical-task utility **0.576 → 0.844**, overall utility
**0.769 → 0.830**. A guard that only one code path enforces isn't a guard.

### 2. Under loss, the failure detector becomes the allocator

At 30% i.i.d. loss, v2 lost 0.30 utility. Each drone was falsely suspecting **0.54 live peers at
any instant**, matching theory: 0.3³ × 23 peers ≈ 0.62. A falsely suspected owner got its task
re-auctioned, and the higher-epoch award **evicted the live incumbent**: 78 evictions per mission
versus 1 at 0% loss, each costing a full flight time. *Fix (v3):* ownership is a **lease** (Gray
& Cheriton, 1989). Owners renew per-member timestamps that spread through *any* neighbour's
gossip, so a live incumbent can't be evicted except by an explicit upgrade. *Effect:* **+0.247**
at 30% loss. *Independent confirmation (`fd`):* without leases, the failure-detector timeout is
the dominant parameter (v2 at 30% loss: 0.42 at a 1.5-heartbeat timeout, 0.73 at 12). With
leases it barely matters (0.73–0.77). **Leases decouple correctness from timeout tuning.**

### 3. Transactions are what loss destroys, yet coordination still pays

Even with leases, v3 fell behind CBBA beyond 40% loss, while CBBA stayed flat to 90%.

* **Falsified hypothesis:** "CBBA just degrades into everyone-for-themselves." The
  zero-communication control scores **0.31** versus CBBA's **0.75** at 90% loss, so coordination
  is still worth **+0.44** at 90% loss.
* **Mechanism:** CBBA has no request/response. A drone *claims* by writing to its own table,
  and every heartbeat rebroadcasts the full table, so any one surviving packet from any neighbour
  carries the whole state forward. HESK's award needs ANNOUNCE → BID → AWARD → ACK through one
  announcer, and coalition awards need *every* member's ACK.
* **Intervention (v4):** keep costs, scarcity, tiers and leases, but make solo allocation a
  state-based claim on the gossiped ledger. v4 is **flat from 0% to 90% loss (0.773 → 0.774)**
  and beats CBBA at 90% loss with **47× less duplicated effort** (44 vs 2,076 agent-seconds).
  Mechanism confirmed.
* **Cost:** claims are single-drone, so coalitions survive only through periodic upgrade
  auctions (coalition share 0.23 → 0.15), and v4 gives up the nominal edge (0.773 vs 0.824).
  **Multi-party composition needs transactions, and transactions are what loss destroys.**

### 4. A purely local loss estimate gets both

v5/v6 switch each drone from auctions to claims when its *own* heartbeat-reception rate implies
more than 30% loss. Paired Δ utility (20 seeds per point):

| loss | 0% | 10% | 20% | 30% | 40% | 50% | 60% | 70% | 80% | 90% |
|---|---|---|---|---|---|---|---|---|---|---|
| v6 − CBBA | **+.068** | **+.064** | **+.045** | **+.032** | +.003 | −.015 | −.024 | −.014 | +.007 | **+.016** |
| v6 − centralized (tuned) | **+.052** | **+.044** | **+.025** | **+.022** | −.004 | **−.027** | **−.022** | +.004 | **+.072** | **+.242** |
| v6 − centralized (default) | **+.052** | **+.045** | **+.038** | **+.066** | **+.088** | **+.128** | **+.200** | **+.281** | **+.313** | **+.457** |
| v6 − v3 | 0 | 0 | 0 | +.020 | +.017 | **+.035** | **+.108** | **+.183** | **+.232** | **+.286** |

v6 is **never significantly worse than CBBA** and is significantly better at 5 of 10 loss levels.
Against the *tuned* centralized dispatcher there are three regimes: HESK wins at low loss
(coalitions), the tuned centralized design wins slightly at 50–60%, and HESK wins large at
extreme loss.

**Mode-boundary turbulence.** The 50–60% band where v6 dips is exactly where its duplicated
effort spikes (160–190 agent-seconds, versus 0–10 below 30%). There, drones' local estimates
straddle the threshold and the fleet runs two protocols at once. That's a switching controller
without hysteresis.

### 5. Component importance reorders completely across regimes (ablation, 30 seeds)

Δ utility when one component is removed from v3 (negative = it helps):

| Removed | nominal | 30% loss | compound attack |
|---|---|---|---|
| scarcity term (Alg 004) | **−0.108** | **−0.064** | −0.018 |
| coalitions (Alg 005) | **−0.087** | **−0.035** | **+0.020** (removing helps) |
| degradation tiers (Alg 006) | **−0.062** | −0.036 | **−0.197** |
| scarcity-aware recruitment (v2) | **−0.056** | +0.020 | −0.001 |
| tier upgrades | **−0.044** | **−0.039** | −0.010 |
| leases (v3) | 0.000 | **−0.228** | **−0.075** |
| ledger gossip (Alg 007) | 0.000 | **−0.113** | **−0.021** |
| Alg 008 tie-break → none / LWW | 0.000 / 0.000 | 0.000 / 0.000 | **−0.015** / −0.006 |
| epochs + leases → raw Alg 008 | **−0.051** | **−0.136** | **−0.109** |

The most important component is **scarcity** when the network is healthy, **leases** under loss,
and **degradation tiers** under compound attack. Gossip and leases are worth exactly zero on a
perfect network and dominant on a lossy one. Coalitions *hurt* under attack: they tie up two
drones, and losing either one breaks the task. **No single test condition would have shown what
the components are for.**

### 6. Faults interact; repair needs the channel (`decomp`, 30 seeds)

| condition | v6 − CBBA | v6 − centralized (tuned) |
|---|---|---|
| bursty loss alone | **+0.031** | **+0.056** |
| partition alone | **+0.039** | **+0.043** |
| sensor failures alone | **+0.044** | **+0.019** |
| rare-drone kills alone | +0.007 | −0.006 |
| **all four** (compound attack) | **−0.021** | **+0.013** |
| all except bursty loss | **−0.013** | +0.003 |
| all except partition | **−0.043** | −0.014 |
| all except kills | −0.007 | **+0.035** |

Every single stressor favours HESK; the combination doesn't. The harmful interaction is
**kills × loss**. Kills create re-allocation demand, and HESK's re-allocation (still in auction
mode, because 20% bursty loss is below the switching threshold) is handshake-bound. Coverage
shows the effect. With kills alone, HESK trails CBBA by 0.019. Adding bursty loss and sensor
failures triples the gap to 0.062, while median repair time goes 52 → 62 s for HESK and 41 → 26 s
for CBBA. **HESK optimises allocation quality, CBBA optimises repair speed, and loss taxes
repair.** Testing one fault at a time would have reported the opposite conclusion.

### 7. Allocation intelligence is a luxury good (attrition, 10 seeds)

v6's lead over CBBA is **+0.101** with the full fleet, **+0.049** after losing 10%, **+0.040** at
20%, and gone from about 30–40% destroyed. That holds whether the adversary kills randomly,
hunts rare platforms, or targets the coordinator. HESK's gains come from managing slack
(reserving rare drones, composing coalitions from spare ones), and attrition removes slack.

### 8. Partitions: the edge shrinks with split duration; consistency has a price (15 seeds)

v6 − CBBA (v6 − tuned centralized):

| islands | 60 s split | 150 s | 300 s |
|---|---|---|---|
| 2 | **+0.066** (**+0.061**) | **+0.046** (**+0.055**) | +0.017 (**+0.039**) |
| 3 | **+0.057** (**+0.056**) | +0.013 (+0.015) | +0.008 (+0.019) |
| 4 | **+0.050** (**+0.049**) | **+0.039** (**+0.038**) | −0.011 (−0.002) |

Long-lived islands behave like small separate fleets, with little slack to manage (compare
Finding 7). The quorum comparison prices the CAP trade-off: for a 300 s two-way split, Raft-style
quorum costs **−0.047 utility** versus the no-quorum leader (0.654 vs 0.701) and in exchange
cuts duplicated effort **about 6×** (395 vs 2,311 agent-seconds).

### 9. A hard-coded 350 ms bid window makes HESK fail over satellite links

| one-way latency | 20 ms | 100 ms | 250 ms | 500 ms | 1 s | 2 s |
|---|---|---|---|---|---|---|
| v5 | 0.841 | 0.830 | **0.050** | **0.038** | 0.322 | 0.634 |
| **v6** | 0.841 | 0.823 | 0.774 | 0.776 | 0.767 | 0.671 |
| CBBA | 0.746 | 0.753 | 0.749 | 0.742 | 0.758 | 0.769 |

Once the ANNOUNCE + BID round trip exceeds the bid window, **no bid ever arrives**. A
geostationary satellite hop (about 250 ms one-way) is enough. The partial recovery at 1–2 s is
an artefact: delayed heartbeats make drones falsely suspect the announcer, many appoint
themselves, and each awards the task to itself. v5's loss-based switch can't see this, because
latency isn't loss. *Fix (v6):* size the bid window, award timeout and bidder commitment from
the measured p90 heartbeat delay (GPS-disciplined clocks assumed). v6 is **bit-identical to v5
in all 1,235 paired runs at normal latency**. *Still open:* at 2 s, v6 loses to CBBA (−0.098)
because the *failure detector's* fixed 3.25 s timeout is now itself shorter than delivery
delays. Every timeout must derive from measured delay.

### 10. Fairness check: the centralized baseline was handicapped by its timeout (falsified hypothesis)

The `fd` suite showed the centralized dispatcher is very timeout-sensitive under loss. At 50%
loss it scores 0.604 with a 3-heartbeat timeout and **0.781** with 12. We expected long timeouts
to cost it once drones really die, since the leader notices late. **They don't** (`fdkill`, loss +
30% kills, 20 seeds): the 12-heartbeat timeout is its best setting (0.682 at 30% loss, 0.690 at
50%, versus 0.662 and 0.570 at 3 heartbeats). The asymmetry: a *false* suspicion costs a full
flight time and happens constantly under loss, while a *late* detection costs about 12 s and
happens rarely. All headline comparisons therefore include this tuned baseline. Against it,
HESK's loss advantage shrinks from "+0.05 to +0.46" to the three-regime picture in Finding 4. HESK
itself needs no such tuning: leases make it timeout-insensitive (Finding 2).

### 11. Mixed-protocol fleets and correlated outages

* **Switching threshold (30 paired seeds).** At 30% loss, v5 does best with its threshold *at*
  the true loss rate (+0.039 vs CBBA), better than lower or higher thresholds (−0.006 to +0.008)
  and better than always-claims (+0.002). There, noisy local estimates split the fleet between
  protocols. **A mixed fleet beat both pure fleets** (0.788 vs 0.756 and 0.755). *Hypothesis, not
  yet tested:* claim-mode drones keep solo tasks robustly covered while auction-mode drones can
  still assemble coalitions. This sits in tension with the 50–60% turbulence above. Under
  compound attack, no threshold beats CBBA, so the threshold is the wrong lever there.
* **Bursty loss (15 seeds).** Holding mean loss fixed, long bursts are what break the
  centralized design: one leader's links going dark for a minute. With 16–64-packet bursts, v6
  beats the *tuned* centralized dispatcher by **+0.09 to +0.22**. Against CBBA, v6 ties at most
  burst lengths but **loses at 60% loss with 64-packet bursts (−0.076)**, an open weakness:
  minute-long link outages behave like a shifting topology, which v6 doesn't model.
* **Scale (5 seeds, directional).** v6's lead over CBBA holds from 12 to 96 drones (+0.03 to
  +0.08). What breaks is bandwidth: fleet radio traffic grows about N² (12 → 96 drones:
  4.8 → 271 kB/s, ≈ 2.2 Mbit/s on a shared channel). Range-limited, delta-encoded gossip is the
  top scaling priority.

## 4. What this means

* **HESK's real contribution** is allocation *quality* in a heterogeneous fleet: scarcity
  management, coalitions and degradation tiers. That's worth **+0.06 to +0.10** utility over
  every baseline, including the perfect-information 1:1 oracle, whenever the fleet has slack.
* **Its original protocol undermined that contribution.** The robustness claims in the original
  README (EW resilience) did not hold for the kernel as specified. They hold for v6 against
  i.i.d. loss, partitions and latency up to 1 s, but **not** for compound attacks, very long
  outages, or more than 1 s latency.
* **Design principles the data supports:** (1) enforce guards at every entry point; (2) make
  ownership a lease, not a fact; (3) prefer state-based convergence over request/response on bad
  links, and spend transactions only where composition needs them; (4) derive every timeout
  from measurement; (5) evaluate faults in combination, and tune baselines before claiming wins.

## 5. Threats to validity

* **Simulation, not flight.** Kinematic movement (constant speed, no wind or collisions) and an
  all-to-all radio within an island (no range-limited multi-hop). Absolute utilities are
  model-specific; the claims are *shapes, crossovers and mechanisms*. [`ROADMAP.md`](ROADMAP.md)
  plans a sim-to-real check of exactly those.
* **One mission family.** One fleet mix and one task mix, scaled. HESK's nominal edge needs
  coalitions to be possible, and a homogeneous fleet would remove it by construction.
* **Redundancy is free in the metric.** Duplicated effort is reported but not penalised.
  Penalising it would favour HESK, since CBBA duplicates up to 18× more at high loss.
* **Baselines are our implementations.** CBBA follows the paper's consensus table; the
  centralized dispatcher uses SciPy's Hungarian solver. Both pass the same harness tests. Only
  the centralized design was tuned (Finding 10). CBBA and HESK were insensitive to timeout
  across the tested range (`fd`).
* **Researcher degrees of freedom.** v2–v6 were designed *after* seeing data. Every claim about
  them comes from full suites on seeds fixed in advance by cell name, every intermediate version
  stays in the registry, and the falsified hypotheses (Findings 3, 10, and the "long timeouts
  hurt" expectation) are reported alongside the confirmed ones.

## 6. Reproduce

```bash
pip install -e '.[dev,analysis]'
make test        # kernel + harness tests, ~1 min
make verify      # re-run 24 random published runs, check bit-exact match
make reproduce   # all 12,985 runs (~5 h on 4 cores; ~20 min on a 64-vCPU VM)
make analyze     # tables + figures into results/
```

Each raw record (one JSON line per run) carries its seed, full configuration, git revision
and every metric.
