# Roadmap: compute budget, scaling, and the path to hardware

## 1. Compute budget (measured, not guessed)

Measured from the 12,985 published runs (`wall_s` in every record; Python 3.11, one core each):

| Configuration | CPU-seconds per run |
|---|---|
| 24 drones, centralized / oracle / no-comm | 0.3–1.9 |
| 24 drones, HESK variants | 3.6–4.5 |
| 24 drones, CBBA (full consensus tables in every heartbeat) | 4.6 |
| 48 drones, decentralized | 40–47 |
| 96 drones, decentralized | ~300 (broadcast cost grows as N²) |

| Campaign | Runs | CPU-hours | 4-core laptop | 64-vCPU cloud VM |
|---|---|---|---|---|
| **This study** (all suites) | 12,985 | **13.4 (measured)** | ~3.5–5 h | ~15 min |
| Another 10,000 runs at 24 drones | 10,000 | ~10 | ~3 h | ~10 min |
| 1,000 runs at 96 drones | 1,000 | ~85 | ~21 h | ~80 min |

**Budget recommendation: $0–50.** Everything in this repository ran inside a 4-core cloud
container. One 64-vCPU spot VM (AWS `c7a.16xlarge`, GCP `c3d-highcpu-60` or similar) costs a few
dollars per hour at spot pricing (check current prices). Ten hours of that, enough for roughly
100k small runs or 1,000 large ones, stays under $50. **Don't buy GPUs:** the simulator is
branch-heavy, single-threaded Python, so GPUs give no speedup.

How to run it on a cloud VM:

```bash
git clone https://github.com/DarshRajPandey/hesk && cd hesk
pip install -e '.[analysis]'
python -m hesk_sim.cli run all --workers $(nproc)     # resumable: re-run after preemption
python -m hesk_sim.analyze runs results
```

The runner appends to `runs/<suite>.jsonl` and skips finished runs, so spot-instance
preemption costs nothing but a restart.

## 2. Scaling further: where things break

0. **Bandwidth, not utility, breaks first at scale.** Fleet radio traffic grows about N²
   (271 kB/s at 96 drones). Range-limited, delta-encoded gossip is the top model upgrade.
1. **Statistics, not compute, is the first limit.** With 30 paired seeds, differences of
   about 0.02 utility are detectable. To claim effects of 0.01, use about 120 seeds per cell.
   Spend extra runs on *the cells near crossovers*, not on uniform grids.
2. **N² broadcast.** Every heartbeat reaches every drone. At 100+ drones, add a radio-range
   model (only neighbours within *r* metres hear you). That also creates realistic multi-hop
   partitions and is the most valuable next model upgrade.
3. **Single announcer.** HESK's "lowest id I can hear" announcer serialises auctions. Beyond
   about 50 drones or 50 tasks, shard announcer duty by rendezvous hashing of task ids.
4. **Python speed.** If 1,000-drone runs become necessary, port `network.py` delivery and
   gossip merge to NumPy vectors, or run each agent in Rust via PyO3. Profile first. The hot
   path is ~4 functions (`merge`, `on_message`, `send`, `_deliver`).

## 3. From simulation to hardware

The simulator was built so the *same agent code* can run on a real drone. An agent only
uses `send()`, `on_message()`, `on_tick()`, its own `Body`, and `intent()`. Swap those four
seams for real implementations and nothing in `hesk_agent.py` changes.

### Stage A: software-in-the-loop (no hardware, about 2 weeks)
- PX4 SITL + Gazebo, 3–6 vehicles, ROS 2 Humble.
- A thin ROS 2 node per vehicle: `Body` ← PX4 telemetry (position, battery), `intent()` →
  MAVROS/uXRCE-DDS offboard setpoints (go to task location, loiter).
- Network: ROS 2 DDS on a single host, with `tc netem` (Linux traffic control) injecting the
  same loss, latency and partitions as the simulator. **Goal:** reproduce the simulator's
  loss-curve *shape* with 5 vehicles.

### Stage B: tabletop hardware (college lab, about 3–4 weeks)
- **Cheapest credible fleet:** 4–6 Crazyflie 2.1 (Bitcraze), or ESP32-based "nodes on a
  table" with no flight at all. The coordination layer doesn't need to fly to be tested.
- Radio: ESP-NOW or Wi-Fi UDP broadcast on ESP32 boards. Inject loss in firmware (drop with
  probability *p*) so the loss level is controlled and matches the simulator sweep.
- Heterogeneity: give each node a *declared* capability profile (thermal/GPU/…) and a
  physical "kill switch" button. Pressing it is your attrition fault.
- **Measure:** time-to-reassign after a kill, duplicate ownership seconds, and convergence
  after a partition (unplug the AP, plug it back). Compare against simulator predictions for
  the same N, loss and timeout.

### Stage C: edge runtime profiling (Jetson Orin Nano, about 1 week)
- Run `hesk_agent.py` decision functions on the Jetson. Report p50/p99 latency of bid
  computation, coalition formation and gossip merge vs. fleet size. These numbers bound how
  fast HESK can react on real compute.

### What would make the hardware result *publishable*
A **sim-to-real validation plot**: the same loss sweep (0–60%) on 5 physical nodes and in
simulation, overlaid, showing the curve shapes and crossovers agree. That's the single figure
that turns "simulation results" into "a validated model".

## 4. Open research questions this work surfaced
1. Can coalition commitments be made loss-tolerant (e.g. members joining incrementally with
   partial-utility tiers) instead of all-or-nothing?
2. What's the optimal failure-detector timeout *as a function of measured loss*? An adaptive
   φ-accrual detector (Hayashibara et al., 2004) is the natural next experiment.
3. Fix the RESOURCE/MISSION_POLICY non-convergence (Finding K1) and prove convergence with
   property-based tests (`hypothesis`) over random partition/merge orders.
4. Add hysteresis to v6's auction↔claims switch (the 50–60% loss turbulence), and test *why*
   a mixed-protocol fleet beat both pure fleets at 30% loss.
5. Make repair state-based even in auction mode: the compound-attack gap vs CBBA is a
   repair-speed gap (Finding 6).
6. Derive the failure-detector timeout itself from measured delay (v6 still loses at 2 s
   latency), and model minute-long correlated outages as topology change.
