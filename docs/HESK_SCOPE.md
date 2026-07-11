# HESK — Heterogeneous Edge Swarm Kernel

## 1. Core Definition

HESK is a proposed brokerless coordination kernel for heterogeneous autonomous multi-agent systems operating under constrained, intermittent, or partitioned communication.

Its central problem is:

> How can a changing group of non-identical autonomous nodes preserve maximum mission utility as compute, energy, communication, sensors, and individual nodes progressively become unavailable?

HESK does not control motors, stabilization, or low-level flight.

Conceptually:

* HESK ↓ Decides WHAT should happen at the swarm/system level
* Planner / autonomy stack ↓ Determines HOW an individual platform should perform the assigned objective
* PX4 / ArduPilot ↓ Executes vehicle-level motion and flight control
* Flight Controller ↓ ESC ↓ Motors

HESK belongs primarily on the companion-compute / distributed coordination layer.

It should be treated as a distributed systems project applied to heterogeneous autonomous systems, not as a drone flight controller.

---

## 2. Fundamental Design Assumption

HESK rejects the assumption that a swarm consists of identical interchangeable units.

A real heterogeneous team may contain:

### Node A:
* excellent optical sensors
* weak compute
* high speed
* low endurance

### Node B:
* high compute
* poor sensing
* medium endurance

### Node C:
* high payload capacity
* strong radio
* low speed

### Node D:
* thermal sensor
* weak communication
* high mobility

Therefore:

**ONE NODE ≠ ONE EQUAL VOTE**

and:

**NODE TYPE ≠ FIXED ROLE**

Coordination should depend on current capabilities, resource state, information confidence, mission requirements, and capability scarcity.

---

## 3. Primary HESK Abstraction: Capability State

HESK should reason about machine-readable capabilities rather than predefined hardware identities.

Example conceptual capability state:

```python
node_7 = { sensing: { rgb: 0.91, thermal: 0.00, lidar: 0.72 },
  compute: {
    cpu_available: 0.44,
    gpu_available: 0.81
  },
  energy: 0.63,
  communication: {
    bandwidth: 0.37,
    link_quality: 0.58
  },
  mobility: {
    speed: 0.82,
    payload_remaining: 0.21
  }
}
```

Capabilities are dynamic.

A node's capability state may change because of:
* battery depletion
* sensor failure
* thermal throttling
* payload changes
* network degradation
* physical damage
* task commitment
* compute saturation

HESK must reason over CURRENT CAPABILITY STATE, not static platform specifications.

---

## 4. Capabilities Are Not Transferable

Physical capabilities cannot magically move between nodes.

If a LiDAR-equipped node is destroyed, its LiDAR capability is destroyed with it.

The following may be transferred:
* responsibility
* role
* task
* mission context
* state
* partial results
* data
* ownership of an objective

Therefore HESK should not model "capability inheritance."

The stronger abstraction is:

**CAPABILITY-CONSTRAINED RESPONSIBILITY SUCCESSION**

### Question:
> When a node disappears, which surviving node or coalition of nodes can reconstruct enough of its operational responsibility to preserve mission utility?

### Example:

Lost role requirements:
* camera ≥ 0.7
* localization ≥ 0.8
* compute ≥ 0.5

No surviving node satisfies all requirements.

However:

#### Drone B:
* camera = 0.9
* localization = 0.9
* compute = 0.2

#### Rover C:
* compute = 1.0

#### Possible reconstruction:
Drone B captures data ↓ Rover C processes data ↓ B + C jointly reconstruct degraded mapping capability

A lost responsibility may therefore be inherited by a temporary coalition rather than one replacement node.

---

## 5. Graceful Swarm-Level Degradation

The central architectural pillar of HESK is graceful degradation.

A weak system behaves like:

100% functionality ↓ 100% ↓ 100% ↓ FAILURE

HESK should attempt:

100% ↓ 82% ↓ 61% ↓ 37% ↓ critical functions preserved

When resources disappear, HESK decides:
* what functionality must be preserved
* what functionality may be degraded
* what functionality may be reconstructed through coalitions
* what functionality should be suspended
* what functionality should be abandoned

### Example:

* Full 3D mapping available ↓ mapping node lost
* HESK evaluates remaining capabilities ↓ camera node + remote compute node cooperate
* 3D mapping quality falls to 55% ↓ compute node lost
* HESK abandons dense 3D mapping ↓ switches to sparse landmark mapping

The mission does not simply report:

**MAPPING FAILED**

Instead, HESK asks:
> What is the highest-value degraded form of this capability that the surviving system can still provide?

---

## 6. Task Requirement Model

Tasks should also have machine-readable requirement states.

Example:

```python
task_mapping_zone_b = { required: { localization: 0.7, sensing_visual: 0.6 },
  preferred: {
    lidar: 0.8,
    gpu: 0.5
  },
  mission_priority: 0.91,
  minimum_acceptable_quality: 0.40
}
```

### Important distinction:

**REQUIRED CAPABILITY versus PREFERRED CAPABILITY**

A task should not necessarily fail because its ideal execution configuration is unavailable.

HESK should search for a degraded but acceptable execution plan.

---

## 7. Capability-to-Task Matching

HESK must determine:

**WHO CAN DO WHAT?**

This requires comparing:

**NODE CAPABILITY STATE ↓ TASK REQUIREMENT STATE**

The first prototype may use normalized capability vectors and deterministic scoring.

However, HESK must avoid pretending that every capability is directly interchangeable or linearly comparable.

The matching engine should eventually reason about:
* hard requirements
* soft preferences
* capability compatibility
* resource cost
* task quality
* execution confidence
* capability scarcity
* future mission value

---

## 8. Capability Scarcity and Opportunity Cost

HESK should not allocate tasks using only immediate execution cost.

### Example:

Drone A task cost = 4 Drone B task cost = 7

A naive allocator selects Drone A.

However:

Drone A is the only thermal-capable node.

A probable future mission may require thermal sensing.

Using Drone A now consumes a strategically scarce capability.

Therefore HESK should estimate:

* IMMEDIATE EXECUTION COST
* \+ ENERGY COST
* \+ COMMUNICATION COST
* \+ CAPABILITY SCARCITY COST
* \+ FUTURE OPTION LOSS

This introduces opportunity cost.

### Core question:
> What future system capability is lost by committing this node or coalition now?

HESK should optimize SYSTEM UTILITY rather than selecting the locally cheapest node.

---

## 9. Brokerless Task Negotiation

HESK should not depend on a permanent central task manager.

Conceptually:

Task discovered ↓ Task represented as a contract / requirement state ↓ Relevant nodes evaluate local suitability ↓ Nodes or coalitions produce proposals ↓ Proposals are compared ↓ Responsibility is assigned ↓ Capability state changes ↓ Task may be renegotiated if conditions materially change

Auction and Contract Net style allocation already exist.

HESK should not claim task bidding itself as novel.

The HESK-specific research direction is:
> Capability-scarcity-aware and degradation-aware distributed allocation under dynamic resource loss.

A winning proposal may come from:

**NODE A**

or:

**NODE B + NODE C + NODE F**

Coalitions are first-class execution candidates.

---

## 10. Dynamic Coalition Formation

A coalition is a temporary collection of nodes whose combined capabilities satisfy a task.

### Example:

TASK Mapping

Requires:
* visual sensing
* localization
* compute

* Node A: visual sensing
* Node B: localization
* Node C: compute

A + B + C ↓ temporary mapping coalition

Coalitions should be:
* dynamically formed
* capability-driven
* temporary
* locally negotiated
* dissolvable after task completion
* reconstructable after node loss

HESK must consider the communication cost of a coalition.

A theoretically capable coalition may be operationally useless if its members cannot exchange required information efficiently.

---

## 11. Distributed Compute Allocation

HESK may allow computational tasks to move between nodes.

### Example:

* Scout: good camera weak compute
* Utility node: poor camera high GPU availability

Scout captures data ↓ HESK identifies remote compute availability ↓ appropriate representation is transferred ↓ utility node performs computation ↓ result returns to scout or mission ledger

HESK must NOT assume that arbitrary sensor data can always be converted into an embedding and processed elsewhere.

The system must understand:
* required computation
* compatible model/runtime
* input representation
* output representation
* bandwidth cost
* latency
* energy cost
* information loss

---

## 12. Semantic Degradation Ladder

HESK should reason about multiple representations of the same underlying information.

### Example:

LEVEL 0 Raw LiDAR point cloud 500 MB  
↓  
LEVEL 1 Compressed point cloud 80 MB  
↓  
LEVEL 2 Voxel map 8 MB  
↓  
LEVEL 3 Object graph 200 KB  
↓  
LEVEL 4 Obstacle coordinates + confidence 120 bytes  

When communication degrades, the system should not immediately treat the link as unusable.

Instead:

* Bandwidth high ↓ send high-fidelity representation
* Bandwidth falls ↓ send compressed representation
* Bandwidth collapses ↓ send semantic summary
* Critical link ↓ send minimum mission-relevant fact

### Core question:
> What is the cheapest representation of information sufficient for the required downstream decision?

This is referred to within the HESK concept as a Semantic Degradation Ladder.

This term is currently a proposed HESK abstraction and should not be presented as an established standard.

---

## 13. Local State Ledgers

There is no magical global swarm state.

Each node or locally connected sub-swarm maintains its own view of reality.

The state ledger contains:

**CURRENT BELIEFS**

### Example:
`leader = node_4 task_owner.mapping = node_7 zone_b.status = scanned node_9.status = suspected_unreachable`

An event log contains:

**HOW THOSE BELIEFS CHANGED**

### Example:
`T1: Node 7 accepted mapping responsibility T2: Zone B scan started T3: Node 9 heartbeat expired T4: Mapping quality degraded T5: Node 4 assumed coordination responsibility`

The system must distinguish:

**GROUND TRUTH**

from:

**WHAT A PARTICULAR NODE CURRENTLY BELIEVES**

This distinction is fundamental.

---

## 14. Network Partition and Split-Brain Operation

Communication partitioning should be treated as a normal operating mode rather than an exceptional crash.

Before partition:

A ↔ B ↔ C ↔ D ↔ E

After partition:

A ↔ B ↔ C

D ↔ E

Each partition continues operating independently.

Each sub-swarm maintains:
* local state
* local event history
* local task ownership
* local capability view
* local resource state
* local decisions

No partition should assume that its view is globally authoritative.

---

## 15. Partition Reconciliation

When partitions reconnect:

SUB-SWARM ALPHA  
\+ SUB-SWARM BETA  

they may contain contradictory state.

### Example:

* Alpha: Task X assigned to Node 3
* Beta: Task X assigned to Node 8

* Alpha: Node 6 suspected dead
* Beta: Node 6 currently active

* Alpha: Zone C unvisited
* Beta: Zone C completed

HESK requires a reconciliation mechanism.

Potential building blocks include:
* event logs
* logical clocks
* vector clocks
* causal ordering
* state versioning
* confidence
* source authority
* mission priority
* task semantics

The reconciliation system must not blindly use:

**LATEST WALL-CLOCK TIMESTAMP WINS**

because clocks may disagree and newer information is not automatically more trustworthy.

### The intended question is:
> Which events causally happened, which events are concurrent, and how should mission semantics resolve genuine contradictions?

The exact HESK reconciliation algorithm remains to be designed.

---

## 16. Weighted Decision Influence

HESK rejects universal one-node-one-vote decision logic.

Decision influence should depend on the decision domain.

### Example:

#### Question: Is the thermal target real?
* Thermal node: high evidential relevance
* Cargo node: low evidential relevance

#### Question: Can the team sustain a 20 km movement?
* High-endurance mobility node: high relevance
* Stationary compute node: low relevance

Therefore decision weight may depend on:
* relevant sensor capability
* confidence
* information freshness
* direct observation
* domain expertise
* state consistency

HESK should distinguish:

**POLITICAL VOTING**

from:

**EVIDENCE-WEIGHTED DISTRIBUTED DECISION MAKING**

The exact consensus mechanism must be designed carefully to prevent a high-capability node from becoming an implicit permanent central authority.

---

## 17. Failure Suspicion and Observability

A node cannot directly know:

**NODE A IS DEAD**

unless it has sufficient evidence.

It may know:

**NO HEARTBEAT FROM A FOR 4.2 SECONDS**

Therefore HESK must model uncertainty.

Possible states:

**ACTIVE SUSPECTED_UNREACHABLE PARTITIONED DEGRADED FAILED_CONFIRMED UNKNOWN**

Failure detection should influence task succession and reconciliation.

The system must distinguish:

**FACT**

from:

**LOCAL INFERENCE**

from:

**SUSPICION**

This is essential for avoiding incorrect role reassignment during temporary communication loss.

---

## 18. Anticipatory Degradation

HESK should eventually explore predictive adaptation.

Instead of:

link fails ↓ recover

HESK may attempt:

link quality declining  
\+ trajectory predicts obstruction  
\+ energy state worsening  
↓ predict likely capability loss  
↓ replicate critical state  
↓ reduce data fidelity  
↓ prepare responsibility successor  
↓ pre-form alternative coalition  
↓ failure occurs  
↓ degraded operation continues  

The system should not claim that all failures can be predicted.

### The research question is:
> Can lightweight local signals allow useful pre-failure preparation without wasting excessive bandwidth and compute on false predictions?

---

## 19. HESK Integration Boundary

HESK should not reinvent existing robotics infrastructure unnecessarily.

Possible architecture:

* Sensors ↓ PX4 / ArduPilot telemetry ↓ MAVLink
* ROS 2 nodes / platform adapters ↓ normalize platform state
* HESK Capability Layer ↓ Capability Registry
* HESK State Layer ↓ Local Ledger + Event History
* HESK Coordination Layer ↓ Task Matching Coalition Formation Responsibility Succession
* HESK Degradation Layer ↓ Capability Preservation Semantic Degradation Service Reduction
* HESK Reconciliation Layer ↓ Partition Detection Causal History Comparison Conflict Resolution

HESK should define a capability and task semantics layer above vehicle-specific telemetry.

MAVLink answers questions such as:
* battery status
* vehicle position
* vehicle state

HESK must answer questions such as:
* can this node perform mapping?
* at what quality?
* at what systemic cost?
* what scarce capability is consumed?
* can a coalition reconstruct this service?
* what should degrade if resources disappear?

---

## 20. HESK's Sharpened Research Thesis

HESK is NOT primarily:
* a drone communication protocol
* a flight controller
* a new auction algorithm
* a generic swarm voting system
* a centralized swarm manager
* a collection of existing algorithms under one repository

The sharpened HESK thesis is:
> A brokerless coordination kernel that enables heterogeneous autonomous nodes to preserve maximum mission utility through capability-aware allocation, coalition-based responsibility succession, semantic information degradation, local-state operation, and automatic reconciliation under compound resource loss and intermittent communication.

The strongest research pillar is:

**CAPABILITY-AWARE, STATE-AWARE GRACEFUL DEGRADATION AT SWARM LEVEL**

The system should continuously answer four questions:

1. What can the surviving system currently do?
2. What should the surviving system preserve?
3. What can be reconstructed or degraded?
4. How should distributed nodes agree on the resulting operational state without a permanent central authority?

---

## 21. Current Open Questions

These are intentionally unresolved and represent algorithm-design opportunities.

1. How should capabilities be represented without oversimplifying hardware differences?
2. How should task requirements represent minimum versus preferred capabilities?
3. How should capability scarcity be calculated?
4. How should future opportunity cost influence current allocation?
5. When should one node execute a task versus a coalition?
6. How should coalition communication cost be modeled?
7. How should HESK choose an information representation under bandwidth degradation?
8. How should semantic information loss be measured?
9. How should nodes distinguish failure from temporary partition?
10. Which state should be replicated before predicted disconnection?
11. How should concurrent state histories be reconciled?
12. When should conflicting facts be merged, replaced, or preserved as uncertainty?
13. How should decision influence be weighted by domain-specific capability?
14. How can weighted consensus avoid creating permanent elite nodes?
15. How should a mission define which services are critical and which may degrade?
16. How should degraded service quality be quantified?
17. How should HESK prove that a degradation decision preserved more mission utility than a baseline allocator?
18. What information can a node legitimately know locally?
19. Which parts of the architecture accidentally assume global state?
20. What is the smallest deterministic HESK prototype capable of demonstrating the central thesis?

These questions should be resolved at the algorithm and simulation-design level before production implementation.

---

## What Not to Build

* ❌ Real drone hardware integration
* ❌ Jetson-specific optimization
* ❌ ROS 2/PX4 deep integration
* ❌ Beautiful dashboard or GUI
* ❌ Production networking stack
* ❌ Cloud infrastructure
* ❌ Perfect repository architecture
* ❌ Every HESK module
* ❌ 10,000 lines of AI-generated code
* ❌ Months of performance optimization
