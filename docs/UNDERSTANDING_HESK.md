# Understanding HESK, in plain terms

## The one-sentence version

HESK decides **which drone does which job** in a mixed fleet, without a boss, while drones die,
sensors break and the radio gets jammed, and tries to keep the *mission's total value* as high
as possible rather than keeping every drone busy.

## The problem, as a story

You have 24 drones. They are not identical:

| Kind | How many | What it's good at |
|---|---|---|
| scout | 10 | cheap camera, little compute. Expendable |
| EO | 5 | sharp camera |
| thermal | 3 | **only drones that can see body heat** (search & rescue) |
| lidar | 2 | 3-D mapping |
| GPU | 2 | heavy onboard AI compute |
| relay | 2 | strong radio |

You have 18 jobs: 3 search-and-rescue (critical), 2 mapping, 3 object detection, 2 radio relay,
8 patrols. Some jobs exist at launch, and some are discovered mid-mission.

Three things make this hard:

1. **Rare things are precious.** If a thermal drone wanders off to do a patrol (which any scout
   could do), a search-and-rescue job discovered later has nobody to serve it.
2. **Nobody sees the whole picture.** Each drone only knows what it has heard over a lossy
   radio. Messages vanish, arrive late, or never cross a gap between two groups of drones.
3. **Things break.** Drones get shot down, sensors fail, and the network splits into islands
   that later rejoin with contradictory beliefs ("I own task 7." "No, *I* own task 7.").

## What each of the 8 algorithms does

| # | Name | Plain meaning | Code |
|---|---|---|---|
| 001 | Capability model | A drone describes what it can do *right now* (a throttled GPU counts as less GPU) | `capabilities/model.py` |
| 002 | Task model | A job lists what it **needs** and a ladder of *fallback versions* (tiers): "thermal + compute" → "thermal only" → "a good camera" | `tasks/model.py` |
| 003 | Matching | "Can this drone do this tier, and how well?" | `capabilities/matching.py` |
| 004 | Scarcity-aware allocation | Auction-style bidding where a drone's bid is **penalised for wasting rare abilities** it won't use | `tasks/allocation.py` |
| 005 | Coalitions | If no single drone can do a job, combine several (lidar drone + GPU drone = mapping with onboard processing) | `coalitions/formation.py` |
| 006 | Graceful degradation | When something breaks, slide down the tier ladder instead of failing outright | `degradation/logic.py` |
| 007 | Local ledger | Each drone's private notebook of beliefs, stamped with logical clocks | `ledger/ledger.py` |
| 008 | Reconciliation | When two notebooks disagree after a network split, a deterministic rule picks the winner | `ledger/reconciliation.py` |

## How they fit together at runtime

The kernel in `src/hesk/` is a *library* of these decisions. On its own it never sends a message.
`src/hesk_sim/agents/hesk_agent.py` turns it into a running protocol:

```
                 ┌──── heartbeat every 1 s: "I'm alive, here's what I can do,
                 │      here's my notebook of who-owns-what"   (Alg 001, 007)
                 ▼
  responsible drone (lowest id it can hear) notices a job with no live owner
                 │
                 ├─ ANNOUNCE  "job t7, tiers 0-2 on offer"
                 ├─ BID       idle drones reply with a cost:
                 │              match quality (003) + energy + travel
                 │              + penalty for wasting rare abilities (004)
                 ├─ decide    best tier first; solo winner, else a coalition (005, 006)
                 ├─ AWARD → ACK
                 ▼
  owner records "t7: me, epoch 4" in its notebook; gossip spreads it
                 │
  network heals, two owners found → reconcile (008)
```

## What the research harness adds

| Piece | What it is | File |
|---|---|---|
| World | Ground truth: positions, real capabilities, faults. **Only the scorer reads it.** | `hesk_sim/world.py` |
| Network | Lossy broadcast radio: random or bursty loss, latency, partitions | `hesk_sim/network.py` |
| Baselines | CBBA, centralized optimal dispatch, Contract Net, a cheating oracle | `hesk_sim/agents/` |
| Suites | 6,570 automated runs across 9 experiment families | `hesk_sim/suites.py` |
| Analysis | Paired statistics, confidence intervals, figures | `hesk_sim/analyze.py` |

## The scoring rule (what "better" means)

Every half-second the scorer asks, for each job: *is a group of live drones physically on
station whose **true** capabilities satisfy some tier?* If yes, the mission earns
`priority × tier quality` for that half-second. **Utility retained** is earned value divided by
the value you'd get if every job were served at its best tier from the moment it appeared.
Because travel time counts, the maximum achievable is well under 1.0. Even the cheating oracle
scores about 0.78.

A drone that *believes* it can do a job but can't (a broken sensor it hasn't noticed) earns
nothing. Duplicated effort earns nothing extra, and it's reported as waste.

## Systems-thinking lessons the experiments taught (details in `RESEARCH.md`)

1. **A guard that one code path bypasses is not a guard.** Scarcity protection lived in solo
   bidding. Coalition formation recruited drones without it, and drafted thermal drones as spare
   compute.
2. **Under unreliable networks, the failure detector becomes the allocator.** Most reassignments
   at 30% loss were caused by drones *wrongly believing* a working owner was dead, not by
   anything breaking.
3. **"Newest wins" and "incumbent wins" each fail on a different fault.** Newest-wins turns false
   alarms into churn. Incumbent-wins resurrects dead owners. Leases (incumbent wins *while it
   keeps proving it's alive*) get both right.
4. **Multi-party commitments are the most fragile thing you can build on a lossy link.** A
   coalition needs every member to stay reachable, so its failure probability compounds with size.
