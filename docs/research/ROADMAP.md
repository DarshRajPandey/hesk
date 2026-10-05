# Roadmap: scaling the experiments, compute budget, and the path to hardware

## Where we are

| | Status |
|---|---|
| Automated runs | **30,940 simulated missions + 66,600 algebra/allocation trials per full study** (13 experiments), one command, all seeded |
| Cost of a full study | **≈1.6 CPU-hours** (24.5 min on a 4-core machine, measured) → effectively **$0** |
| Fidelity | mission-level coordination state; no physics, no real radios (rung 1 of 4) |

The 1,000-run and 10,000-run goals are therefore **already met at rung 1**. The next scaling steps are
about *fidelity*, not run count: each rung up the ladder costs 10-1,000x more per run, so the run budget
should shrink as fidelity rises, and each rung should be used only for the claims it can uniquely test.

## Compute budget by rung

Prices are rough mid-2026 public-cloud ranges; check your provider and use spot/preemptible
capacity (typically 60-80% cheaper) for batch runs. University HPC clusters are often free for students.

| Rung | Per-run cost (measured or estimated) | 1,000 runs | 10,000 runs | Recommended volume |
|---|---|---|---|---|
| **1. This simulator** | ≈0.06-0.5 CPU-seconds (measured: mean 0.18 s) | ≈3 CPU-min, **≈$0** | ≈30 CPU-min, **< $1** | 10^4-10^5: all statistics, sweeps, ablations |
| **2. PX4 SITL + Gazebo + ROS 2**, 12 drones, 5-min mission, headless | ≈1 CPU-hour (≈1 core per vehicle at real time; estimate) | ≈1,000 CPU-h ≈ **$30-100** | ≈10,000 CPU-h ≈ **$300-1,000** | 10^3: re-run the *headline* cells of E1, E12, E13 |
| **3. NVIDIA Isaac Sim**, 12 drones with sensors | ≈0.1-0.5 GPU-hour (estimate; depends on scene) | ≈100-500 GPU-h ≈ **$100-1,500** | rarely justified | 10^1-10^2: perception-coupled scenarios only |
| **4. Lab hardware** | people time, batteries, crashes | n/a | n/a | 10^1: calibrate and confirm |

**Suggested first budget: $0 for rung 1, $50-150 of cloud credit for a 1,000-run SITL campaign,
and a GPU only when a claim actually depends on perception.** Many providers give student/research
credits that cover this; also ask your college's HPC centre.

### How to run 10,000+ rung-1 runs on a bigger machine

```bash
python -m hesk.bench run all --seeds 600 --jobs 64 --out results-big   # ~10x the default seeds
python -m hesk.bench report --out results-big
```

Runs are independent and seeded, so sharding across machines is trivial: give each machine a
different experiment list, then merge the `raw/*.jsonl.gz` files into one directory and run `report`.

### Where things break as you scale (what to watch)

| Knob | What we measured | What to expect beyond it |
|---|---|---|
| Swarm size 6 → 48 | HESK-L agreement time 2.1 s → 3.7 s (≈log N); state 2.2 → 2.9 KB/replica | full-state gossip grows O(keys); switch to delta-state CRDTs before ~500 nodes |
| Packet loss | agreement time ≈ t₀ / (1 − loss); misses a 30 s budget at ~90% loss | budget settle time from the law, or raise gossip fan-out under heavy loss |
| Clock skew | LWW freshness degrades from 9% stale at 0.1 s skew to 64% at 5 s | any wall-clock ordering does; use hybrid logical clocks + GNSS time if available |
| Crashes | HESK-L unaffected up to 75% killed; quorum stops at exactly 50% | none for HESK-L's convergence; job coverage is limited by survivors' capabilities |

## Experiments to add next (in priority order)

1. **Delta-state gossip + bandwidth caps** (realistic radios carry kilobits, not full ledgers); measure
   convergence vs. link budget.
2. **Allocation fix:** combine tightest-fit with scarcity (E11 shows tightest-fit wins); add
   a CBBA baseline (Choi, Brunet & How, 2009), the standard in multi-UAV task allocation.
3. **End-to-end mission utility under attrition** (Algorithms 004 + 006 + HESK-L together): utility
   preserved vs. fraction of nodes lost, the thesis claim of the project.
4. **Byzantine / spoofed messages** (a jammed swarm can also be a spoofed swarm): authenticated entries.
5. **Formal check:** a TLA+ or Alloy model of the HESK-L ownership register (small, high value).

## Path to hardware (rungs 2-4)

**Do the radio before the rotors.** HESK is a coordination layer, so most of its claims can be tested on
real radios and real clocks **without flying anything**:

1. **Network testbed (weeks 1-3, no flight risk).** 6-12 Raspberry Pis or ESP32 boards (or old laptops)
   each run a HESK-L node over Wi-Fi / ESP-NOW. Use Linux `tc netem` to inject loss, latency and
   partitions on purpose, and log every message. Re-run E1/E12/E13 headline cells; compare with the
   simulator to calibrate its loss/latency/skew parameters. *Real clock skew is free here.*
2. **SITL integration (weeks 3-6).** PX4 SITL + Gazebo + ROS 2: HESK publishes task assignments;
   vehicles execute them. Same scenarios, now with real middleware timing.
3. **Indoor micro-drones (weeks 6-10).** A Crazyflie 2.x swarm (Bitcraze; ROS 2 via Crazyswarm2) with
   Lighthouse or mocap positioning: 4-10 drones, tabletop-safe, cheap to crash. Partition the radio on
   purpose and film the handoff/reconciliation.
4. **Outdoor PX4 quads (only with lab safety approval).** 3-5 vehicles, geofenced, with a hardware kill
   switch and HESK **never** connected directly to actuators (see README warning).

**Pre-register before each hardware campaign:** write down the scenarios, metrics, number of trials, and
the result that would count as failure *before* running. Hardware trials are few, so this is what
makes them credible.
