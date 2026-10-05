# How the simulation works and how to reproduce it

## Reproduce everything (one command)

```bash
git clone https://github.com/DarshRajPandey/hesk && cd hesk
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,bench]"
make test       # 71 tests + 9 expected-failure defect tests, ~15 s
make results    # every experiment (~31,000 missions + 66,600 trials), ~25 min on 4 cores
```

`results/manifest.json` records the commit, Python version, platform, seeds and the exact command.
`results/raw/*.jsonl.gz` holds one line per run (configuration, seed, every metric), so any table or
figure can be recomputed, or re-analysed with a different statistic, without re-simulating.
`results/REPORT.md` and `results/figures/` are regenerated with `make report`.

Determinism is tested, not assumed: `tests/sim/test_determinism.py` runs the same seed in separate
processes with different `PYTHONHASHSEED`s and requires byte-identical output.

## What is simulated

The simulator (`src/hesk/sim/scenario.py`) is a **discrete-event** simulation: a priority queue of
timestamped events (a drone writes something, a gossip round fires, a message arrives, a node crashes)
processed in time order on a **virtual clock**. One 65-second mission runs in 0.1-0.5 s of real time,
which is what makes tens of thousands of runs cheap.

**Nodes.** Each drone is a *replica*: a ledger plus the code under test. The same workload drives every
implementation through one interface (`src/hesk/sim/replicas.py`):

| Implementation | What it is |
|---|---|
| `legacy/*` | the original HESK ledger, **unmodified**, in four protocol readings (below) |
| `hesk-l` | the lattice ledger (HESK-L) |
| `hesk-l/<ablation>` | HESK-L with one design choice reverted to the legacy behaviour |
| `baseline/quorum` | idealised Raft/Paxos replicated log (etcd, Consul, CockroachDB model) |
| `baseline/lww-gossip` | Cassandra / DynamoDB-global-tables style last-writer-wins |
| `legacy/...+resolver+window+clock` | the original code with surgical defect patches (root-cause study) |

**Network.** Every second each node gossips its state to 2 random peers. Each message can be lost
(default 5%), duplicated (2%), and delayed (150 ms + jitter), so messages also reorder. Clocks are
skewed per node (σ = 0.1 s by default). All of these are swept.

**Mission timeline.**

```
 0 s ─────────── 20 s ──────────────── 35 s ─────────────────── 65 s
 connected        network splits into   network heals; gossip
 (handoffs,       groups (concurrent     until the horizon; we
  counts,          claims on the same     measure whether and when
  sightings,       jobs; work continues)  everyone agrees, and on what
  battery)
```

**Faults.** Partitions (2-6 groups, even or with one majority group, 5-90 s long), packet loss
(0-90%), latency (50 ms-2 s), crash-stop failures (0-75% of drones killed mid-mission), clock skew
(0-5 s), duplicates and reordering.

**Ground truth, used only for scoring.** The simulator records what really happened (the true last
handoff, the true number of increments, the newest battery report in real time) and compares it with
what each surviving drone believes at the end. Drones never read it.

## Fairness rules (so baselines and the legacy code get their best shot)

- **Same workload, same network fate.** The workload and every message's fate (lost? delayed?
  duplicated?) are drawn from seed-derived random streams *before* the run, so all implementations face
  the identical scenario; only their logic differs.
- **Perfect failure detector for the legacy reconnection path.** The legacy design reconciles "on
  reconnection". We tell it *exactly* which links were partitioned, which is more than real hardware could.
- **Four readings of the legacy wire protocol** (relay vs. own-entries-only; reconcile once vs. on every
  message), with the most favourable one reported as "best legacy".
- **Idealised quorum.** Leader election is instant, failure detection perfect, commits need only a
  majority of acks to survive packet loss, and lost counter/sighting writes are queued and retried.
- **CRDT-equipped LWW.** The Cassandra-style baseline gets every CRDT fix HESK-L has; only its
  ownership rule differs, so the comparison isolates exactly that design choice.
- **At most one claimant per connected group** in the main workload, because the allocation layer is
  supposed to prevent two claimants inside one connected group; the unconstrained case is a separate
  stress test (E8).

## Metrics (all per run, aggregated with 95% confidence intervals)

| Metric | Question it answers |
|---|---|
| `conv_*` | At the end, do all live drones show the same value? (Wilson CI) |
| `t_conv_*` | How many seconds after healing until they agree and stay agreed? |
| `chain_stale` | After a *deliberate* handoff, what share of drones still name the old owner? |
| `contest_split` | Share of contested jobs where drones disagree about the owner |
| `contest_regret` | Progress thrown away by keeping a less-advanced claimant |
| `contest_orphan` | Share of reassigned jobs nobody was allowed to take (availability) |
| `contest_dup` | Extra drones working the same job during the partition (duplicated work) |
| `ctr_loss` | Share of counter increments lost |
| `obs_dup` | Share of stored sightings that are duplicates |
| `res_stale`, `res_lag_s` | Is the battery value the newest report? By how many seconds is it behind? |
| `bytes`, `aborted` | State size; runs stopped by the state-explosion guard (F5) |

## What is *not* simulated (threats to validity)

- **No physics, no sensing, no flight.** This is a *mission-level* simulation of coordination state.
  Effects such as radio range shrinking with distance are modelled only as loss and partitions.
- **Gossip is full-state.** Real deployments would send deltas; this affects bandwidth, not correctness.
- **The quorum model is an abstraction**, not a Raft implementation; it is deliberately optimistic
  (no election downtime, commit latency not modelled).
- **Workload realism.** Claim timings, progress distributions and report rates are plausible guesses,
  swept where they matter (E2-E5), not measured from real missions. Hardware runs must calibrate them.
- **Sizes.** 6-48 drones; the cost curve (E6) is smooth, but 500+ is untested.

## The multi-fidelity ladder (where this fits)

| Rung | Tool | Runs | What it can prove |
|---|---|---|---|
| 1 | this simulator | 10^4-10^5 | algorithmic correctness, failure modes, ablations, statistics |
| 2 | PX4 SITL + Gazebo + ROS 2, `tc netem` for the radio | 10^2-10^3 | integration, timing, real middleware |
| 3 | NVIDIA Isaac Sim | 10^1-10^2 | perception and physics coupling |
| 4 | real drones / radios in the lab | 10^1 | calibration of rungs 1-3; the claims that matter to users |

See [ROADMAP.md](ROADMAP.md) for the budget and plan for rungs 2-4.
