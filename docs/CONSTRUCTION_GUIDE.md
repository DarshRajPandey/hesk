# HESK Construction Guide — Architectural Failure Modes and Builder Checklist

## Purpose
This document exists to prevent the HESK repository from becoming a large collection of professional-looking AI-generated code that does not implement a coherent distributed system.

Before implementing any module, the builder and coding agent should use this guide to identify hidden architectural mistakes.

## PROBLEM 1: Coding Before Defining the Algorithm
### Failure pattern:
Idea  
↓  
Ask AI to implement  
↓  
AI creates classes  
↓  
Repository looks professional  
↓  
No one can explain why decisions are correct  

### Example:
```
class CapabilityManager:
def allocate_optimal_resources(self):
...
```
The function name "allocate_optimal_resources" does not mean resource allocation has been solved.

### Required questions before implementation:
* What exact data enters the algorithm?
* What exact data leaves?
* What decision is being made?
* What variables affect the decision?
* What assumptions are made?
* What happens when information is missing?
* Why should this decision be considered better?
* What baseline is it being compared against?

### RULE:
ALGORITHM FIRST  
↓  
EXAMPLE ON PAPER  
↓  
EDGE CASES  
↓  
PSEUDOCODE  
↓  
TEST SCENARIOS  
↓  
CODE  

Do not reverse this order.

## PROBLEM 2: False Abstraction
AI coding agents create impressive names for unsolved problems.

### Examples:
* ConsensusEngine
* OptimalAllocator
* IntelligentRecoveryManager
* DynamicCapabilityResolver
* AutonomousNegotiator

These names may hide empty logic.

Whenever an abstraction is created, ask:
* What complexity is this abstraction actually hiding?

### Bad:
`RecoveryManager.recover()`

### Better conceptual decomposition:
* `detect_partition()`
* `compare_event_histories()`
* `identify_concurrent_events()`
* `detect_state_conflicts()`
* `classify_conflict()`
* `apply_resolution_policy()`
* `publish_reconciled_state()`

### RULE:
If a function name contains words such as:
* optimal
* intelligent
* dynamic
* automatic
* smart
* adaptive

inspect it aggressively.  
The adjective may be replacing an algorithm.

## PROBLEM 3: Accidentally Building a Centralized System
### Failure pattern:
"Build decentralized swarm coordination."

AI creates:  
`SwarmManager`

`SwarmManager` contains:
* all_nodes
* all_tasks
* global_state
* global_map
* global_capabilities

This is a central coordinator.  
A distributed system does not have a magical omniscient object called "the system."

For every piece of information ask:
* Which physical node owns this information?

Then ask:
* How did that node learn it?

If the answer is:  
"The global system knows it"  
the architecture is probably wrong.

### Correct mental model:
NODE A  
local_state_A  

NODE B  
local_state_B  

NODE C  
local_state_C  

Messages create partial synchronization.  
There may be no globally consistent state at a particular moment.

## PROBLEM 4: Confusing Simulation Truth with Node Knowledge
A simulator may know:  
Node 7 crashed at T=42.

Node 3 may only know:  
Last message from Node 7 was received 4.2 seconds ago.

These are different.

### SIMULATOR TRUTH:
Node 7 is dead.

### NODE 3 BELIEF:
Node 7 may be unreachable.

Never inject simulator ground truth directly into HESK decision logic.

Maintain a strict boundary:  
WORLD STATE  
↓  
what objectively occurred  
OBSERVATION  
↓  
what a node sensed or received  
LOCAL BELIEF  
↓  
what the node currently infers  
DECISION  
↓  
what the node does based on that belief  

This separation is mandatory.

## PROBLEM 5: Ignoring Observability
Observability asks:
* What can this node legitimately know from its available measurements and messages?

Before writing any decision algorithm, list the information available to the deciding node.

### Example:
Node A decides whether Node B failed.

* **Available:**
  * last heartbeat time
  * recent link quality
  * known trajectory
  * neighbor reports
* **Unavailable:**
  * true physical condition of B
  * B's current battery after partition
  * global network topology

The algorithm must operate only on available information.

### RULE:
For every algorithm write:  
KNOWN LOCALLY:  
[...]  
RECEIVED:  
[...]  
INFERRED:  
[...]  
UNKNOWN:  
[...]  

If the algorithm reads an UNKNOWN value, the design is cheating.

## PROBLEM 6: Treating Missing Communication as Death
No heartbeat does not necessarily mean node destruction.

### Possible causes:
* physical failure
* RF shadow
* temporary interference
* partition
* antenna failure
* compute freeze
* message loss
* extreme congestion

Do not use:  
* ACTIVE  
* DEAD  
as the complete failure model.

Consider:  
* ACTIVE  
* DEGRADED  
* SUSPECTED_UNREACHABLE  
* PARTITIONED  
* FAILED_CONFIRMED  
* UNKNOWN  

Responsibility succession may begin while the original owner is only suspected unreachable.

This creates a future reconciliation problem:  
Node A disappears.  
↓  
Node B inherits Task X.  
↓  
Node A returns.  
↓  
Now A and B both believe they own Task X.  

HESK must explicitly design for this.

## PROBLEM 7: Underestimating Time
Distributed systems do not share perfect time.

Node A says:  
`battery = 80%`

### Questions:
* When was that observed?
* When was it transmitted?
* When was it received?
* Was it observed before a partition?
* Did another event causally happen after it?

A wall-clock timestamp alone may be insufficient.

Concepts that must eventually be understood:
* logical clock
* Lamport clock
* vector clock
* causal ordering
* concurrent events
* stale state
* timeout
* lease

Do not immediately implement vector clocks because the term sounds advanced.

First define:
* Which event-ordering question does HESK need to answer?

Then choose the appropriate mechanism.

## PROBLEM 8: Assuming Newer Means More Correct
### Example:
* Node A:
  * Thermal target detected at T1.
  * Confidence 0.98.
  * Direct thermal observation.
* Node B:
  * No target detected at T2.
  * Confidence 0.31.
  * Poor visual sensor.

T2 is newer.  
That does not automatically make Node B correct.

Conflict resolution may require:
* freshness
* sensor relevance
* confidence
* direct versus indirect observation
* causal history
* mission semantics

### RULE:
NEVER casually implement:  
`state = max(states, key=timestamp)`  
unless the specific state variable genuinely has last-write-wins semantics.

## PROBLEM 9: Treating Every State Variable the Same
Different data require different merge logic.

### Example:
`visited_zones`

Alpha:  
`[A, B]`

Beta:  
`[C, D]`

Possible merge:  
`[A, B, C, D]`  
This is naturally union-like.

But:  
`task_owner`

Alpha:  
Node 3

Beta:  
Node 8

You cannot union them without changing task semantics.

And:  
`target_position`

Alpha:  
(10, 20), confidence 0.9

Beta:  
(12, 22), confidence 0.8

This may require estimation or preserving multiple hypotheses.

Therefore HESK needs STATE SEMANTICS.

### Possible categories:
* SET-LIKE STATE
* COUNTER STATE
* EXCLUSIVE OWNERSHIP STATE
* OBSERVATIONAL STATE
* RESOURCE STATE
* MISSION POLICY STATE

Merge behaviour should depend on state type.

## PROBLEM 10: Oversimplifying Capability Vectors
It is tempting to write:
```
capability = [
camera=0.8,
compute=0.7,
battery=0.4
]
```
and calculate a dot product.

This is useful for a prototype.  
It is not automatically a realistic capability model.

### Problems:
* A thermal sensor is not simply "0.9 camera."
* 10 TOPS of compatible GPU compute may be useful.
* 10 TOPS of incompatible accelerator compute may be useless.
* Payload capacity may have a hard threshold.
* Some capabilities require combinations.
* Some capabilities are binary.
* Some degrade continuously.

Before normalizing everything to 0–1, classify the capability.

### Possible types:
* BOOLEAN
* CONTINUOUS
* CAPACITY
* CATEGORICAL
* COMPATIBILITY-CONSTRAINED
* COMPOSITE

Do not let mathematical convenience erase system semantics.

## PROBLEM 11: Confusing Physical Capability with Responsibility
Physical capabilities remain attached to hardware.

* **Transferable:**
  * task
  * role
  * state
  * data
  * mission context
  * responsibility
* **Not transferable:**
  * camera
  * LiDAR
  * payload bay
  * antenna
  * GPU hardware

If a capability disappears, ask:
* Can another node substitute?
* Can a coalition reconstruct the service?
* Can quality degrade?
* Must the service be abandoned?

This is the core of HESK graceful degradation.

## PROBLEM 12: Ignoring Capability Scarcity
A node may be the cheapest current executor and still be the wrong assignment.

### Example:
* A can perform Task X for cost 4.
* B can perform Task X for cost 7.
* A is the only thermal node.
* Task X does not require thermal sensing.

Assigning A consumes a scarce future option.

The allocator should eventually consider:
* execution cost
* energy cost
* communication cost
* scarcity cost
* future option loss

Do not call this "optimal" until the objective function is explicitly defined.

## PROBLEM 13: Creating Fake Coalitions
AI may create:  
`Coalition(nodes=[A, B, C])`

That does not mean A, B, and C can actually perform a task together.

Ask:
* What data must move between them?
* At what frequency?
* At what bandwidth?
* What is the latency limit?
* Are their representations compatible?
* What happens if one coalition member disconnects?

A coalition is not a Python list.  
A coalition is a temporary distributed execution dependency.

## PROBLEM 14: Ignoring Communication Cost
### Theoretically:
* A has sensor.
* B has localization.
* C has compute.
* A + B + C can map.

### Operationally:
* A ↔ B = good link
* B ↔ C = 4 kbps
* A ↔ C = disconnected

The coalition may be useless.  
Capability composition must include network feasibility.

### Conceptually:
"CAN WE DO THE TASK?"  
is not enough.

Ask:
* CAN WE DO THE TASK WITH THE CURRENT COMMUNICATION GRAPH WITHIN THE TASK DEADLINE AT ACCEPTABLE ENERGY COST?

## PROBLEM 15: Assuming MAVLink Solves Heterogeneity
MAVLink helps systems exchange standardized messages.  
It does not define HESK-level capability semantics.

MAVLink may tell HESK:  
* battery = 43%
* position = X,Y,Z
* vehicle_type = ...

HESK still needs to represent:
* mapping_quality = 0.72
* thermal_observation = supported
* model_runtime = compatible
* remote_compute = available
* task_semantics = understood

HESK likely needs an abstraction layer above MAVLink and ROS 2.  
Do not modify MAVLink unnecessarily for the first prototype.  
Build adapters.

```
MAVLink / ROS data
↓
Platform Adapter
↓
HESK Capability State
```

## PROBLEM 16: Building Against Real Drones Too Early
Real hardware introduces:
* motor problems
* firmware problems
* GPS problems
* serial connection problems
* battery problems
* radio problems
* driver problems

These can distract from the actual HESK research question.

Initial HESK development should use simulation.

The simulation must model:
* heterogeneous capabilities
* battery depletion
* compute load
* network links
* partitions
* message delay
* message loss
* node failure
* task arrival

The first goal is not:  
FLY A DRONE.

The first goal is:  
PROVE HESK MAKES A MEANINGFUL DISTRIBUTED DECISION.

## PROBLEM 17: Making the Simulator Omniscient
The simulator needs global world state internally.  
HESK nodes must not access it.

### Suggested conceptual separation:
simulation/  
world.py  

hesk/  
node.py  
local_state.py  

world.py may know everything.  
node.py may only receive observations and messages.

Never allow:  
`node.world.nodes`  
or:  
`hesk.get_global_state()`  
inside decision logic.  
That destroys the distributed model.

## PROBLEM 18: Building Everything at Once
Do not begin with:
* discovery
* consensus
* task allocation
* coalitions
* split-brain
* compute offloading
* semantic degradation
* prediction

all simultaneously.

### Recommended conceptual progression:
* PHASE 1: Capability representation
* PHASE 2: Task requirement representation
* PHASE 3: Single-node capability matching
* PHASE 4: Scarcity-aware allocation
* PHASE 5: Coalition capability composition
* PHASE 6: Dynamic capability loss
* PHASE 7: Graceful service degradation
* PHASE 8: Local state ledgers
* PHASE 9: Network partitions
* PHASE 10: Partition reconciliation
* PHASE 11: Semantic communication degradation
* PHASE 12: Predictive preparation

Every phase should produce a measurable experiment.

## PROBLEM 19: Letting Claude Code Design Research Through Momentum
Coding agents have momentum.  
If the current architecture contains:  
`SwarmManager`  
the agent will continue extending `SwarmManager`.

Ten prompts later:  
`SwarmManager`  
├── consensus  
├── recovery  
├── allocation  
├── networking  
└── state  

The initial mistake becomes deeply embedded.

Before every major coding session provide the agent:
* HESK scope document
* current algorithm specification
* architecture invariants
* explicit non-goals
* current experiment

Tell the agent not to invent missing research decisions.  
If an algorithmic decision is unspecified, the agent should expose the ambiguity rather than silently choose an architecture.

## PROBLEM 20: Not Defining Architectural Invariants
An invariant is a rule that should always remain true.

### Potential HESK invariants:
* INVARIANT 1: No node may directly access global simulation truth.
* INVARIANT 2: Every operational decision must be derivable from local state and received messages.
* INVARIANT 3: No permanent central coordinator is required for correctness.
* INVARIANT 4: Physical capabilities are never transferred between nodes.
* INVARIANT 5: Task responsibility and physical capability are separate concepts.
* INVARIANT 6: Every remote state observation carries provenance and version/order metadata.
* INVARIANT 7: Communication failure is not automatically classified as node death.
* INVARIANT 8: Degradation decisions must preserve explicitly defined critical mission services before optional services.
* INVARIANT 9: Coalition feasibility includes communication feasibility.
* INVARIANT 10: Simulation ground truth is used for evaluation, never distributed decision making.

These invariants should be tested.

## PROBLEM 21: Writing Code Without a Baseline
Suppose HESK completes 81% of mission tasks.  
Is that good?  
Unknown.  
You need comparison systems.

### Possible baseline:
* BASELINE A: Random capable-node assignment
* BASELINE B: Lowest immediate cost assignment
* BASELINE C: Static predefined roles
* HESK: Scarcity-aware degradation architecture

### Then compare:
* mission utility preserved
* tasks completed
* critical services maintained
* energy consumed
* messages transmitted
* recovery time
* duplicate task execution
* state conflicts
* coalition failures

Without baselines, a simulator produces numbers but not evidence.

## PROBLEM 22: Claiming Novelty Too Early
Many HESK components already have research histories:
* task auctions
* Contract Net Protocol
* multi-robot task allocation
* coalition formation
* compute offloading
* vector clocks
* CRDTs
* failure detection
* event-triggered communication

Do not claim:  
"We invented decentralized bidding."

Instead ask:
* What combination, assumption, objective function, or failure model is insufficient in existing approaches?

### Potential HESK research target:
Capability-aware, state-aware graceful degradation under simultaneous heterogeneous resource loss and intermittent communication.

Novelty must eventually be established through literature comparison.

## PROBLEM 23: AI-Generated Tests That Only Confirm AI-Generated Assumptions
Claude writes algorithm.  
Claude writes tests.  
Tests pass.  
This does not prove the architecture is correct.

### Example:
Algorithm assumes newest timestamp wins.

Claude writes:
`assert newest_state_wins()`

Test passes beautifully.  
The wrong assumption is now "100% tested."

Tests should come from independently designed scenarios.  
Before implementation, define adversarial scenarios manually.

### Example:
* newer low-confidence observation conflicts with older direct sensor observation
* temporary partition causes duplicate task ownership
* scarce node wins cheap non-specialized task
* coalition forms across unusable network link
* node returns after responsibility succession
* three partitions independently modify mission state

Then test the algorithm.

## PROBLEM 24: Repository Size Becoming a Success Metric
Do not measure:
* lines of code
* number of modules
* number of classes
* number of commits

### Measure:
* Can the algorithm be explained?
* Can it be simulated?
* Can it fail?
* Can the failure be reproduced?
* Can HESK outperform a baseline?
* Can a graph show the difference?
* Can another engineer understand the decision trace?

A 2,000-line repository demonstrating one strong systems idea is more valuable than a 40,000-line fake operating system.

## PROBLEM 25: Losing Decision Explainability
Every important HESK decision should ideally produce a trace.

### Example:
```
TASK MAPPING_ZONE_B
Node A rejected:
localization below minimum
Node B eligible:
execution cost = 4.2
scarcity penalty = 8.1
system cost = 12.3
Node C eligible:
execution cost = 7.0
scarcity penalty = 0.4
system cost = 7.4
ASSIGNED:
Node C
REASON:
Preserved unique thermal capability of Node B
```

This is useful for:
* debugging
* research evaluation
* documentation
* GitHub demonstrations
* AI-agent code review

If HESK produces a decision and the builder cannot explain why, the system is becoming opaque.

## FINAL BUILD RULE
For every HESK feature:
```
PROBLEM
↓
WHY EXISTING SIMPLE METHOD FAILS
↓
SYSTEM ASSUMPTIONS
↓
AVAILABLE LOCAL INFORMATION
↓
DATA STRUCTURE
↓
DECISION RULE
↓
PSEUDOCODE
↓
ADVERSARIAL EXAMPLE
↓
BASELINE
↓
METRIC
↓
IMPLEMENTATION
```
Claude Code should enter near the end of this pipeline.

The human builder's highest-value contribution is not typing Python.  
It is deciding:
* WHAT PROBLEM IS ACTUALLY BEING SOLVED?
* WHAT DOES EACH NODE ACTUALLY KNOW?
* WHAT ASSUMPTIONS ARE ALLOWED?
* WHY SHOULD THIS DECISION RULE WORK?
* WHAT WOULD PROVE IT IS BETTER?

The coding agent can implement the answer.  
It should not silently invent the answer.
