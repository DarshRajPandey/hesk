# How HESK works, in plain terms

*Read this first. It explains what HESK is, what each part does, what we found when we tested it,
and the systems-thinking lessons behind each finding. No distributed-systems background assumed.*

---

## 1. The one-paragraph version

HESK is a **coordination layer for a team of different robots** (drones with cameras, drones with
thermal sensors, a few with big computers, many cheap ones). It decides *who does which job*, keeps
working when robots break or the radio link is jammed, and gets everyone back on the same page when the
links come back. It sits **above** the autopilot (PX4 flies the drone; HESK decides what the drone
should be doing) and has **no central server**: every robot keeps its own notebook and they compare
notes whenever they can talk.

## 2. The problem it attacks

Imagine 12 drones searching a forest. Halfway through, a hill blocks the radio and the swarm splits
into three groups that cannot hear each other. In each group, someone notices "the drone doing the
thermal scan of sector 4 has gone silent" and takes over that job. When the groups reconnect, **three
drones believe they own sector 4**. Two of them must stand down, every drone must agree on which one,
and no other piece of shared knowledge (battery levels, sightings, counters) may be lost or corrupted.

That last step, *getting everyone to agree again after being cut off*, is the hardest part of the
whole system, and it is where our research found most of the problems.

## 3. The eight algorithms, one sentence each

| # | Name | What it does, in plain words |
|---|------|------------------------------|
| 001 | Capability model | Describes what a robot *can do right now* (a hot GPU or a nearly-flat battery counts), not just what hardware it carries. |
| 002 | Task model | Describes a job as "needs thermal ≥ 0.6, prefers good RGB", plus cheaper fallback versions of the job. |
| 003 | Capability matching | Answers "can this robot do this job, and how well?" |
| 004 | Scarcity-aware allocation | Robots bid for jobs; a robot that is the *only* one with a rare sensor is discouraged from taking a job anyone could do. |
| 005 | Coalition formation | Combines several robots when no single one can do a job. |
| 006 | Graceful degradation | When things break, drops to cheaper versions of jobs instead of failing outright. |
| 007 | Local state ledger | Each robot's notebook of what it believes: who owns which job, battery levels, sightings, counters. |
| 008 | Partition reconciliation | When separated groups reconnect, merge their notebooks into one consistent story. |

The study in this repository focuses on **007 + 008 (the ledger)**, because every other algorithm
reads from the ledger: if two robots disagree about who owns a job, allocation and degradation are
computing on contradictory facts. There is also a smaller study of **004 (allocation)**.

## 4. How the ledger stores different kinds of facts

Different facts need different rules for "merging two notebooks":

| Kind of fact | Example | The right merge rule |
|---|---|---|
| Ownership | "drone 7 owns sector 4" | Exactly one owner must win, and everyone must pick the *same* one. |
| Counter | "targets found: 14" | Increments from different drones must **add up**, not overwrite each other. |
| Observations | "last 5 sightings" | Hearing the same sighting twice must not count it twice. |
| Resource | "drone 3 battery: 41%" | The newest report should win. |

A merge rule is only safe if it satisfies three laws, which have names but are simple to state:

- **Order doesn't matter** (commutative): merging A into B gives the same result as B into A.
- **Grouping doesn't matter** (associative): (A + B) + C equals A + (B + C).
- **Repeats don't matter** (idempotent): merging A twice equals merging it once.

If all three hold, every robot that has heard the same news ends up with the same notebook, no matter
in which order or how many times the messages arrived. This guarantee is called **strong eventual
consistency**, and the data structures that provide it are called **CRDTs** (Shapiro et al., 2011).
Radio networks reorder, drop and duplicate messages all the time, so these laws are not academic:
**a rule that breaks one of them will eventually disagree with itself in the field.**

## 5. What we found when we tested the original ledger

We built a simulator (see [SIMULATION.md](SIMULATION.md)) and ran the unmodified HESK ledger
through about 31,000 automated missions. Of the merge rules we tested (ownership, counter, observation, resource, set), only the set rule (plain union) was correct; mission-policy and reachability rules were not tested.
Each problem has a tiny standalone test in `tests/failures/` that fails today:

| ID | What goes wrong, in plain words |
|----|---------------------------------|
| F1 | The "who owns the job" comparison can go in a circle: A beats B, B beats C, C beats A. |
| F2 | If drone B takes a job over **less than 5 seconds** after hearing drone A had it, the other drones ignore B. |
| F3 | A busy drone can ignore a takeover that happened 30 s later, because it compares *its own* clock with the sender's. |
| F4 | Two drones each count +1 at the same time; the swarm records +1, not +2. Over a mission **about 60% of counts were lost.** |
| F5 | Re-hearing the same sighting stores it again; relayed sightings get wrapped inside each other until state is ~130× too big. |
| F6 | Battery reports within 2 s of each other are treated as "ambiguous" and different drones keep different values forever. |
| F7 | When two drones in the *same* group grab a job at once, the conflict is written down but never resolved. |
| F8 | The ledger's "send what the other side hasn't seen" feature can never forward news it heard second-hand. |
| F9 | Reconnection always keeps the claim with **more progress**, even when the newer owner deliberately took over (e.g. after the old owner was declared lost). |

The single most important *surprise* was about F1. It looked like the headline bug, a comparison
that goes in circles. A careful experiment (E10, a "root-cause factorial") switched each defect off one at a time
**in the original code** and showed F1 almost never decides the outcome. The real killers are F2 and
F3 *together*: fixing either alone does nothing; fixing both repairs most of it.
This is the core lesson of research: **the bug that looks worst is not necessarily the bug that matters.**

## 6. What HESK-L is

HESK-L (`src/hesk/ledger/lattice.py`) is a rebuilt ledger in which every merge rule provably satisfies
the three laws:

- **Ownership** keeps *every* claim that nobody had seen when it was made (a "multi-value register"
  with "dotted version vectors", the technique Amazon Dynamo and Riak use for "siblings"). A takeover
  that *knew about* an earlier claim replaces it, whatever the clocks say. Claims made blind to each other
  are all kept, and every drone applies the **same deterministic rule** to pick the visible owner:
  most progress, then best match, then earliest, then lowest ID. Same set of claims gives the same owner
  everywhere.
- **Counters** keep one tally per drone and add them up (a G-counter): concurrent +1s are never lost.
- **Observations** are stored by a unique ID, so repeats are harmless; only the newest 5 are kept.
- **Resources** use "newest timestamp wins", with drone ID as a tie-break so it is a strict order.

HESK-L **is not a new invention in distributed systems**; it is a careful, tested composition of
well-known CRDTs. What is specific to HESK is the ownership read rule (progress-aware, causality-first)
and the evidence about which failure modes actually matter in a swarm.

## 7. The trade-off nobody gets to skip (CAP)

When the network splits, a coordination system must choose:

- **Stay available.** Every group keeps assigning jobs, accepting that two groups may duplicate a job
  until they reconnect. This is HESK-L, and Cassandra-style databases.
- **Stay consistent.** Refuse to assign anything unless a strict majority of all drones agrees. This is
  Raft/Paxos (etcd, Consul, CockroachDB). Never a duplicate, but a group without a majority does nothing.

This is the CAP theorem (Brewer 2000; Gilbert & Lynch 2002), and **no design escapes it**. HESK-L is
on the "available" side on purpose, because a drone swarm that stops working whenever the radio is
jammed is useless. The price is visible in our data: during a 3-way split HESK-L runs about 2 extra
copies of each reassigned job; the quorum system runs zero, but leaves 100% of them undone.

## 8. Systems-thinking lessons you can reuse

1. **Write the invariant before the code.** "Order, grouping and repeats must not matter" would have
   caught F1, F4, F5 and F6 on paper.
2. **Time is not causality.** Two clocks never agree exactly. "Later timestamp" ≠ "happened after".
   Track *what each writer had seen* (F2, F3, F9, and the LWW baseline's 26% reverted handoffs).
3. **Agreement is not correctness.** Several broken variants *agree perfectly on the wrong answer*
   (counters losing 56-62%; a patched legacy agreeing 100% on a stale owner). Always measure "is it right?"
   separately from "does everyone agree?".
4. **Agreement is not usefulness either.** At 80-90% packet loss the quorum baseline "agrees" 100%,
   because it stopped doing anything at all.
5. **Find root causes with controlled removal, not intuition** (E10). Switch one thing off at a time,
   in the real code, and measure.
6. **Margins beat thresholds.** A quorum that has *exactly* a majority needs every member to answer;
   10% packet loss then orphans about a third of the work (E13).
7. **Use negative controls.** Before believing a failure, check that it disappears when the cause is
   removed (no partition, no loss, gaps longer than the window). We did, and it did.
8. **Report the losses.** A simple "use the least-capable robot that can do the job" rule beat HESK's
   scarcity-aware allocator (E11). That is a result too, and it points at what to improve.
