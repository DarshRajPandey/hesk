# Algorithm 001 — Capability Model

> **Status:** v0.1 draft — foundational data model  
> **Depends on:** nothing (this is the foundation)  
> **Consumed by:** 002 Task Model, 003 Capability Matching, 004 Scarcity Allocation, 005 Coalition Formation

---

## 1. PROBLEM

### 1.1 Core question

> How should a heterogeneous autonomous node represent its own current operational capabilities so that every downstream HESK algorithm — matching, scarcity, coalition, degradation — can reason about them without hidden type errors, false precision, or centralized ground truth?

### 1.2 Why this is harder than it appears

A capability model is not a flat feature vector.  Three concrete difficulties:

**Runtime gap.**  Hardware presence ≠ service availability.  A Jetson Nano may physically contain a GPU, but if the CUDA runtime is not installed, or the driver crashed, or VRAM is exhausted, the node has *zero* usable GPU compute.  A flat vector entry `gpu: 0.81` cannot distinguish "GPU healthy, 81 % free" from "GPU exists but unusable."

**Non-linear dependencies.**  Some capabilities require *combinations*.  A node with a camera and no localization cannot produce geo-referenced images.  A node with GPU compute but no compatible runtime (e.g., only OpenCL when the model needs CUDA) cannot execute the required inference.  Flat dot-product scoring treats every dimension as independently substitutable.

**Context-blind values.**  `battery: 0.42` means different things on a 3-cell LiPo (11.1 V nominal, 0.42 → ~11.9 V, healthy) versus a 4-cell LiPo (14.8 V nominal, 0.42 → ~15.1 V, also fine but different absolute headroom).  Normalization that erases the physical context makes cross-node comparison unreliable.

### 1.3 What this algorithm produces

A typed, versioned, locally-constructed `CapabilityState` that every other HESK module can consume *without* needing to understand raw telemetry.

---

## 2. DEFINITIONS

### 2.1 Notation (shared across all HESK documents)

| Symbol | Meaning |
|--------|---------|
| n_i | Node i |
| C_i | Capability state of node i |
| c_{i,d} | Value of dimension d for node i |
| τ_j | Task j |
| R_j | Requirement state of task j |
| R_j^req | Required capabilities of τ_j |
| R_j^pref | Preferred capabilities of τ_j |
| π_j | Mission priority of τ_j |
| f(n_i, τ_j) | Match score: node i against task j |
| Γ | Coalition (set of nodes) |
| L_i | Local ledger of node i |
| λ_i | Lamport clock of node i |
| q_{ij} | Link quality between nodes i and j |
| ε_i | Energy level of node i (normalized) |
| σ_d(S) | Scarcity of dimension d in known swarm S |

### 2.2 Dimension types

HESK capabilities are **not** uniform floats.  Each dimension has a **type** that governs comparison, normalization, matching, and serialization.

| Type | Domain | Comparison semantics | Example |
|------|--------|---------------------|---------|
| BOOLEAN | {0, 1} | Has / does not have.  No partial credit. | `thermal_sensor` |
| CONTINUOUS | [0, 1] normalized | Higher is better (or context-dependent). Supports distance, interpolation. | `camera_quality`, `cpu_available` |
| CAPACITY | ℝ⁺ with units | Absolute quantity.  Comparison is "does the node meet the threshold?" | `vram_mb`, `payload_remaining_kg` |
| CATEGORICAL | Finite named set | Equality / membership test.  No ordering. | `compute_runtime ∈ {cuda, opencl, cpu_only, none}` |
| COMPOSITE | Derived from other dimensions | Custom evaluation function. | `can_run_yolo` = f(gpu_available, runtime, vram_mb) |

### 2.3 HardwareInventory vs. RuntimeState

This is a critical separation.

**HardwareInventory** — *What physically exists on this platform.*  Determined at boot from a hardware manifest or device enumeration.  Essentially static during a mission (a sensor does not spontaneously appear).

```
HardwareInventory:
  sensors_present:   [rgb_camera, gps]       # physical devices
  compute_hardware:  [cpu_arm_cortex_a57, gpu_maxwell_128core]
  radio_hardware:    [wifi_2.4ghz]
  actuators:         [quad_rotor, gimbal_2axis]
  payload_capacity:  1.2 kg
  battery_chemistry: lipo_4s
  battery_capacity:  5200 mAh
```

**RuntimeState** — *What is currently usable, right now.*  Changes continuously with battery drain, thermal throttling, task commitment, driver crashes, and sensor degradation.

```
RuntimeState:
  sensing:
    rgb:                 0.87          # CONTINUOUS — image quality metric
    thermal:             0             # BOOLEAN — not present
    lidar:               0             # BOOLEAN — not present
  compute:
    cpu_available:       0.38          # CONTINUOUS — fraction free
    gpu_available:       0.29          # CONTINUOUS — fraction free
    runtime:             cuda          # CATEGORICAL
    vram_mb:             848           # CAPACITY — free VRAM in MB
  energy:
    level:               0.76          # CONTINUOUS — SoC fraction
    discharge_rate:      0.012         # CONTINUOUS — fraction per minute
    estimated_remaining_s: 3800        # CAPACITY — seconds
  mobility:
    speed:               0.70          # CONTINUOUS — fraction of max
    payload_remaining_kg: 0.5          # CAPACITY
    position:            (12.4, 7.1, 25.0)  # absolute (x,y,z) meters
```

The `CapabilityState` consumed by all downstream HESK algorithms is the **RuntimeState**.

The `HardwareInventory` is consulted during construction and diagnostics, but is *not* broadcast to other nodes (it is mostly redundant once RuntimeState is computed, and it is large).

### 2.4 CapabilityReport

A `CapabilityReport` is the *message-ready* wrapper that carries a RuntimeState plus provenance metadata.

```
CapabilityReport:
  node_id:          n_i
  state:            RuntimeState       # the actual capability values
  lamport_clock:    λ_i                # logical ordering
  wall_timestamp:   t_wall             # local wall clock (best effort)
  boot_epoch:       b_i                # which boot generation
  hardware_hash:    h_i                # hash of HardwareInventory (for change detection)
  state_version:    v_i                # monotonic counter per node
  ttl_hint_ms:      500                # suggested staleness window
```

Every remote state observation carries provenance and version metadata (Invariant 6).

### 2.5 LinkState vs CapabilityState

A node's intrinsic capabilities (e.g., CPU, battery) are distinct from its relational network links.
HESK separates these to prevent matching errors where a node appears "capable" but is physically unreachable.

```
LinkState:
  source_node:      NodeId
  target_node:      NodeId
  bandwidth_kbps:   float              # dynamically measured
  latency_ms:       float              # dynamically measured
  last_heartbeat:   float              # wall time
```
LinkState is managed by the network topology layer, not the Capability Model. It is used during Coalition Formation (005) to evaluate the feasibility of multi-node assignments.

---

## 3. ASSUMPTIONS

1. Each node knows its own hardware manifest at boot (loaded from a config file or device enumeration).
2. The node has access to OS-level metrics: CPU load, memory usage, GPU temperature, GPU memory usage.
3. The node has access to MAVLink telemetry (or equivalent): battery voltage, GPS quality, RSSI, vehicle state.
4. The node has access to sensor health registers or watchdog flags for each sensor.
5. The companion computer runs Linux with `/proc`, `/sys`, or equivalent telemetry interfaces.
6. There is no global clock; logical clocks provide ordering.
7. Physical capabilities are never transferred between nodes (Invariant 4).
8. Self-assessment is entirely local; no other node's input is needed to construct one's own CapabilityState.

---

## 4. INPUTS

### 4.1 Raw telemetry sources (at the deciding node)

These are the physical signals that feed `construct_capability_state()`:

| Source | Data | Access method |
|--------|------|---------------|
| Battery management system | Voltage (V), current (A), cell count, chemistry | MAVLink `BATTERY_STATUS` or I²C |
| CPU | Per-core utilization (%), frequency (MHz), temperature (°C) | `/proc/stat`, `/sys/devices/system/cpu/` |
| GPU | Utilization (%), temperature (°C), memory used/total (MB), clock (MHz) | `nvidia-smi`, `tegrastats`, or vendor API |
| GPU runtime | Installed frameworks | File/library presence check at boot |
| RGB camera | Frame rate (fps), exposure status, error flags | V4L2 ioctl or ROS diagnostic |
| Thermal sensor | Health flag, last frame timestamp | Vendor SDK status register |
| LiDAR | Point rate (pts/s), health byte | Vendor SDK or ROS diagnostic |
| GPS | Fix type, HDOP, satellite count | MAVLink `GPS_RAW_INT` |
| Radio | RSSI (dBm), noise floor (dBm), TX rate (kbps) | MAVLink `RADIO_STATUS` or `/proc/net/wireless` |
| Neighbor discovery | Heartbeat table with last-seen timestamps | HESK heartbeat subsystem |
| IMU | Health flags, vibration level | MAVLink `VIBRATION` |
| Payload | Mass sensor or manifest (kg) | MAVLink `PAYLOAD_STATUS` or config |

### 4.2 Events that trigger state update

The capability state is not recomputed on a fixed timer alone.  The following events trigger `update_capability_state()`:

- Periodic tick (default: every 1 second)
- Battery voltage crosses a threshold boundary
- CPU or GPU utilization changes by > 10 % since last report
- Sensor health flag changes
- Task committed or released (changes available compute/energy budget)
- Communication neighbor gained or lost
- GPS fix quality changes (fix type transition)
- Thermal throttle event detected

---

## 5. LOCALLY AVAILABLE INFORMATION

> This section is mandatory per the Construction Guide (Problem 5).
> For **self-assessment**, this analysis is from the perspective of node n_i constructing its own CapabilityState C_i.

### KNOWN LOCALLY

Everything about the node's own hardware and current telemetry:

- Complete HardwareInventory (loaded at boot)
- All raw telemetry listed in Section 4.1 (CPU, GPU, battery, sensors, radio, GPS)
- Current task commitments of this node (what tasks n_i has accepted)
- Own Lamport clock λ_i
- Own boot epoch b_i
- Own state version counter v_i
- Historical telemetry buffer (last N seconds of own readings, for trend detection)

### RECEIVED VIA MESSAGES

For **self-assessment**: **nothing**.  A node does not need any external message to determine its own capabilities.

For **evaluating another node's capabilities**: CapabilityReports received from that node, each carrying `(state, λ, t_wall, boot_epoch, state_version, ttl_hint_ms)`.

### INFERRED

- `estimated_remaining_s`: derived from current voltage, discharge rate, and battery curve model
- `discharge_rate`: derived from voltage delta over a sliding window
- `camera_quality`: derived from frame rate, exposure flags, and sensor health
- `gpu_available`: derived from GPU utilization % and thermal throttle state
- Composite capabilities like `can_run_yolo`: derived from gpu_available, runtime, vram_mb
- Trend predictions: "battery will cross critical threshold in ~T seconds"

### UNKNOWN

- Future sensor failures (cannot predict hardware faults)
- Future network conditions (topology changes from other nodes' movement)
- Other nodes' actual states (only known via received CapabilityReports, which may be stale)
- Physical damage not yet reflected in telemetry (e.g., cracked lens producing subtly degraded images)
- Environmental factors affecting future capability (e.g., upcoming RF shadow zone)

---

## 6. OUTPUT

The primary outputs of this algorithm:

1. **`CapabilityState` (RuntimeState)** — The structured, typed representation of what this node can currently do.  Consumed by the matching engine (003), scarcity calculator (004), coalition evaluator (005), and degradation engine (006).

2. **`CapabilityReport`** — The serialized, versioned wrapper suitable for broadcast to neighbors.  Consumed by other nodes' local ledgers (007).

3. **`CapabilityChangeEvent`** — Emitted when a dimension value changes beyond a hysteresis threshold.  Consumed by the local event log and triggers re-evaluation of current task assignments.

```
CapabilityChangeEvent:
  node_id:         n_i
  dimension:       "compute.gpu_available"
  old_value:       0.71
  new_value:       0.23
  change_type:     DEGRADED           # DEGRADED | IMPROVED | LOST | GAINED
  lamport_clock:   λ_i
  cause_hint:      "thermal_throttle"  # optional diagnostic
```

---

## 7. DECISION RULE — Normalization and Assessment

### 7.1 Per-type normalization functions

Each dimension type has its own assessment function.  There is no universal normalization.

#### BOOLEAN dimensions

```
assess_boolean(raw_value, health_flag) → {0, 1}
  if sensor_not_present:      return 0
  if health_flag ≠ OK:        return 0      # exists but broken = 0
  return 1
```

No partial credit.  A thermal sensor either works or it does not.

#### CONTINUOUS dimensions

```
assess_continuous(raw_value, min_physical, max_physical, context) → [0, 1]
  # Clamp to physical bounds
  clamped = clamp(raw_value, min_physical, max_physical)
  # Linear normalization
  normalized = (clamped - min_physical) / (max_physical - min_physical)
  # Context-dependent inversion (e.g., CPU load: higher raw = LESS available)
  if context.inverted:
    normalized = 1.0 - normalized
  return normalized
```

Examples:
- CPU available: raw = 62% used → inverted → `cpu_available = 0.38`
- Battery level: raw = 11.2 V on 4S LiPo (range 12.0–16.8 V) → `level = (11.2 - 12.0) / (16.8 - 12.0) = -0.17 → clamp → 0.0`
  - Wait — 11.2 V on a 4S LiPo with 3.0 V/cell min: range is [12.0, 16.8].  11.2 V is **below** safe minimum.  This should produce near-zero or trigger a CRITICAL flag.
  - Better: use per-chemistry voltage-to-SoC curve lookup.  See Section 7.3.

#### CAPACITY dimensions

```
assess_capacity(raw_value, unit) → (value, unit)
  # No normalization — preserve absolute value and unit
  return (raw_value, unit)
```

Capacity dimensions are compared by threshold: "does this node have ≥ X units?"  Normalizing 2048 MB VRAM to 0.7 is meaningless without knowing the scale.

#### CATEGORICAL dimensions

```
assess_categorical(raw_value, valid_set) → element ∈ valid_set ∪ {none}
  if raw_value ∈ valid_set:  return raw_value
  return none
```

Categorical values are tested by equality or set membership.  `runtime = cuda` is not "better" or "worse" than `runtime = opencl` — it is *compatible or incompatible* with a task's requirement.

### 7.2 Hysteresis to prevent oscillation

Without hysteresis, a CPU hovering at 59–61 % utilization would cause `cpu_available` to oscillate between 0.39 and 0.41 every second, triggering constant CapabilityChangeEvents and re-broadcasts.

**Hysteresis rule:**  A dimension value change is reported only if it exceeds a **dead-band threshold** relative to the last *reported* value.

```
should_report_change(current, last_reported, threshold) → bool
  return |current - last_reported| > threshold
```

Default thresholds (provisional v0.1, subject to tuning):

| Dimension | Dead-band threshold |
|-----------|-------------------|
| cpu_available | 0.05 (5 %) |
| gpu_available | 0.05 |
| energy.level | 0.03 (3 %) |
| camera_quality (rgb) | 0.10 |
| vram_mb | 64 MB |
| speed | 0.05 |

BOOLEAN and CATEGORICAL dimensions have no hysteresis — any change is significant.

### 7.3 Battery assessment (worked sub-example)

Battery is critical enough to warrant a dedicated model rather than naive linear interpolation.

**Input:** voltage (V), current (A), cell count, chemistry.

**Method:**
1. Compute per-cell voltage: `v_cell = voltage / cell_count`
2. Look up State-of-Charge (SoC) from a piecewise-linear curve for the chemistry:

```
# LiPo discharge curve (approximate, per-cell)
LIPO_SOC_TABLE = [
  (4.20, 1.00),   # fully charged
  (4.05, 0.90),
  (3.90, 0.75),
  (3.80, 0.55),
  (3.70, 0.30),
  (3.60, 0.15),
  (3.50, 0.05),   # critical
  (3.30, 0.00),   # empty / damage threshold
]

assess_battery(voltage, cell_count, chemistry) → (level, discharge_rate, estimated_remaining_s)
  v_cell = voltage / cell_count
  level = interpolate(LIPO_SOC_TABLE, v_cell)

  # Discharge rate from sliding window (last 60 seconds)
  discharge_rate = (level_60s_ago - level) / 60.0   # fraction per second

  # Estimated remaining
  if discharge_rate > 0:
    estimated_remaining_s = level / discharge_rate
  else:
    estimated_remaining_s = ∞   # not discharging (charging or idle)

  return (level, discharge_rate, estimated_remaining_s)
```

3. Flag `CRITICAL` if `level < 0.10` or `v_cell < 3.55 V`.

### 7.4 Staleness model for received CapabilityReports

When node n_i evaluates another node n_k's capabilities (received via a CapabilityReport), it must account for staleness.

```
staleness_discount(report, current_lamport_clock) → discount_factor ∈ [0, 1]
  age_ticks = current_lamport_clock - report.lamport_clock
  age_ms = now_wall() - report.wall_timestamp   # best-effort wall time

  # Use the worse (more conservative) of the two estimates
  effective_age_ms = max(age_ms, age_ticks * ASSUMED_TICK_MS)

  if effective_age_ms <= report.ttl_hint_ms:
    return 1.0   # fresh
  elif effective_age_ms <= report.ttl_hint_ms * 3:
    # Linear decay
    return 1.0 - (effective_age_ms - report.ttl_hint_ms) / (report.ttl_hint_ms * 2)
  else:
    return 0.0   # too stale to trust
```

A staleness factor of 0.0 does not mean the node is dead (Invariant 7) — it means the *report* is too old to inform operational decisions.

---

## 8. PLAIN-ENGLISH ALGORITHM

### 8.1 Constructing a CapabilityState from scratch (at boot or reset)

1. Load the HardwareInventory from the platform manifest file.
2. For each sensor in the manifest, probe its health register.  Populate BOOLEAN dimensions (present and healthy → 1, else → 0).
3. For each CONTINUOUS sensing dimension (e.g., rgb camera quality), query the sensor's current operating parameters (frame rate, resolution, exposure) and compute a normalized quality score.
4. Read OS metrics for CPU utilization and normalize to `cpu_available`.
5. Query GPU subsystem: check if GPU hardware exists, if runtime (CUDA/OpenCL) is installed, current utilization, temperature, and free VRAM.  If GPU exists but runtime is missing → `gpu_available = 0.0`, `runtime = none`.
6. Read battery voltage, current, and cell count.  Compute SoC using the chemistry-specific curve.  Compute discharge rate from initial readings (may be inaccurate for first few seconds).
7. Read radio interface max capacity for `bandwidth_kbps`.
8. Read current speed capability and payload state from vehicle telemetry.
9. Read GPS fix quality.  Store position.
10. Assemble all dimensions into a RuntimeState structure.
11. Wrap in a CapabilityReport with `lamport_clock = 0`, `state_version = 1`, `boot_epoch = current`.
12. Emit initial CapabilityChangeEvent for all dimensions (change_type = GAINED for each present capability).

### 8.2 Updating a CapabilityState (on event or periodic tick)

1. Read updated telemetry for the affected subsystem(s).
2. Re-assess the relevant dimension(s) using the type-appropriate normalization function (Section 7.1).
3. For each dimension, compare the new value against the last *reported* value using hysteresis (Section 7.2).
4. If any dimension crossed the hysteresis threshold:
   a. Update the RuntimeState.
   b. Increment `state_version`.
   c. Increment `lamport_clock`.
   d. Emit CapabilityChangeEvent(s) for changed dimensions.
   e. Mark the CapabilityReport as dirty (needs re-broadcast at next opportunity).
5. If no dimension crossed the threshold: update internal tracking values but do *not* increment version or trigger broadcast.

---

## 9. PSEUDOCODE

### 9.1 `construct_capability_state()`

```python
def construct_capability_state(hardware_inventory, telemetry) -> CapabilityReport:
    """
    Called at boot or after a full reset.
    Inputs:  hardware manifest, current raw telemetry
    Outputs: initial CapabilityReport
    """
    state = RuntimeState()

    # ── Sensing ─────────────────────────────────────────────
    # RGB camera
    if hardware_inventory.has("rgb_camera"):
        health = telemetry.sensor_health("rgb_camera")
        if health == OK:
            fps = telemetry.camera_fps()
            max_fps = hardware_inventory.camera_max_fps()
            state.sensing.rgb = assess_continuous(fps, 0, max_fps, inverted=False)
        else:
            state.sensing.rgb = 0.0   # present but unhealthy
    else:
        state.sensing.rgb = 0.0

    # Thermal sensor
    state.sensing.thermal = assess_boolean(
        present = hardware_inventory.has("thermal_sensor"),
        health  = telemetry.sensor_health("thermal_sensor")
    )

    # LiDAR
    if hardware_inventory.has("lidar"):
        health = telemetry.sensor_health("lidar")
        if health == OK:
            pts_rate = telemetry.lidar_point_rate()
            max_rate = hardware_inventory.lidar_max_rate()
            state.sensing.lidar = assess_continuous(pts_rate, 0, max_rate, inverted=False)
        else:
            state.sensing.lidar = 0.0
    else:
        state.sensing.lidar = 0.0

    # ── Compute ─────────────────────────────────────────────
    cpu_load = telemetry.cpu_utilization_percent()
    state.compute.cpu_available = assess_continuous(
        cpu_load, 0, 100, inverted=True   # higher load → less available
    )

    if hardware_inventory.has("gpu"):
        runtime = detect_gpu_runtime()   # returns "cuda" | "opencl" | "none"
        state.compute.runtime = assess_categorical(runtime, {"cuda", "opencl", "cpu_only"})

        if runtime != "none":
            gpu_util = telemetry.gpu_utilization_percent()
            gpu_temp = telemetry.gpu_temperature_c()

            # Thermal throttle penalty
            throttle_factor = 1.0
            if gpu_temp > GPU_THROTTLE_THRESHOLD_C:       # e.g., 80°C
                throttle_factor = max(0.0,
                    1.0 - (gpu_temp - GPU_THROTTLE_THRESHOLD_C) / GPU_SHUTDOWN_DELTA_C)

            state.compute.gpu_available = assess_continuous(
                gpu_util, 0, 100, inverted=True
            ) * throttle_factor

            state.compute.vram_mb = telemetry.gpu_vram_free_mb()   # CAPACITY, absolute
        else:
            # GPU hardware exists but runtime missing → unusable
            state.compute.gpu_available = 0.0
            state.compute.runtime = "none"
            state.compute.vram_mb = 0
    else:
        state.compute.gpu_available = 0.0
        state.compute.runtime = "none"
        state.compute.vram_mb = 0

    # ── Energy ──────────────────────────────────────────────
    voltage = telemetry.battery_voltage()
    cell_count = hardware_inventory.battery_cell_count()
    chemistry = hardware_inventory.battery_chemistry()

    level, discharge_rate, remaining_s = assess_battery(voltage, cell_count, chemistry)
    state.energy.level = level
    state.energy.discharge_rate = discharge_rate
    state.energy.estimated_remaining_s = remaining_s

    # ── Mobility ────────────────────────────────────────────
    max_speed = hardware_inventory.max_speed_mps()
    current_speed_cap = telemetry.achievable_speed_mps()   # may be limited by wind, payload
    state.mobility.speed = assess_continuous(
        current_speed_cap, 0, max_speed, inverted=False
    )
    state.mobility.payload_remaining_kg = telemetry.payload_remaining_kg()
    state.mobility.position = telemetry.position_xyz()

    # ── Wrap in report ──────────────────────────────────────
    report = CapabilityReport(
        node_id        = self.node_id,
        state          = state,
        lamport_clock  = self.lamport_clock,
        wall_timestamp = now_wall(),
        boot_epoch     = self.boot_epoch,
        hardware_hash  = hash(hardware_inventory),
        state_version  = 1,
        ttl_hint_ms    = DEFAULT_TTL_MS    # e.g., 500 ms
    )

    return report
```

### 9.2 `update_capability_state()`

```python
def update_capability_state(current_report, event, telemetry) -> (CapabilityReport, list[CapabilityChangeEvent]):
    """
    Called on periodic tick or triggered event.
    Inputs:  current CapabilityReport, triggering event, fresh telemetry
    Outputs: updated CapabilityReport (or same if no material change),
             list of CapabilityChangeEvents (empty if no material change)
    """
    old_state = current_report.state
    new_state = deep_copy(old_state)
    changes = []

    # ── Re-assess affected dimensions based on event type ──
    if event.type in {PERIODIC_TICK, BATTERY_THRESHOLD, TASK_CHANGE}:
        # Re-assess energy
        voltage = telemetry.battery_voltage()
        level, rate, remaining = assess_battery(
            voltage, self.hardware.battery_cell_count(), self.hardware.battery_chemistry()
        )
        new_state.energy.level = level
        new_state.energy.discharge_rate = rate
        new_state.energy.estimated_remaining_s = remaining

    if event.type in {PERIODIC_TICK, COMPUTE_CHANGE, TASK_CHANGE, THERMAL_THROTTLE}:
        # Re-assess compute
        cpu_load = telemetry.cpu_utilization_percent()
        new_state.compute.cpu_available = assess_continuous(cpu_load, 0, 100, inverted=True)

        if self.hardware.has("gpu") and new_state.compute.runtime != "none":
            gpu_util = telemetry.gpu_utilization_percent()
            gpu_temp = telemetry.gpu_temperature_c()
            throttle_factor = compute_throttle_factor(gpu_temp)
            new_state.compute.gpu_available = assess_continuous(
                gpu_util, 0, 100, inverted=True
            ) * throttle_factor
            new_state.compute.vram_mb = telemetry.gpu_vram_free_mb()

    if event.type in {SENSOR_HEALTH_CHANGE}:
        # Re-assess affected sensor
        sensor_id = event.sensor_id
        health = telemetry.sensor_health(sensor_id)
        if sensor_id == "rgb_camera":
            if health == OK:
                fps = telemetry.camera_fps()
                new_state.sensing.rgb = assess_continuous(fps, 0, self.hardware.camera_max_fps(), inverted=False)
            else:
                new_state.sensing.rgb = 0.0
        elif sensor_id == "thermal_sensor":
            new_state.sensing.thermal = assess_boolean(True, health)
        elif sensor_id == "lidar":
            if health == OK:
                pts = telemetry.lidar_point_rate()
                new_state.sensing.lidar = assess_continuous(pts, 0, self.hardware.lidar_max_rate(), inverted=False)
            else:
                new_state.sensing.lidar = 0.0

    if event.type in {PERIODIC_TICK, NEIGHBOR_CHANGE, RSSI_CHANGE}:
        # Re-assess communication
        new_state.communication.bandwidth_kbps = telemetry.current_tx_rate_kbps()

    # ── Hysteresis check ────────────────────────────────────
    for dimension_path, old_val, new_val, threshold in iterate_dimensions_with_thresholds(old_state, new_state):
        if should_report_change(new_val, old_val, threshold):
            change_type = classify_change(old_val, new_val, dimension_path)
            changes.append(CapabilityChangeEvent(
                node_id       = self.node_id,
                dimension     = dimension_path,
                old_value     = old_val,
                new_value     = new_val,
                change_type   = change_type,
                lamport_clock = self.lamport_clock + 1,
                cause_hint    = event.type
            ))

    # ── Commit or skip ──────────────────────────────────────
    if len(changes) > 0:
        self.lamport_clock += 1
        updated_report = CapabilityReport(
            node_id        = self.node_id,
            state          = new_state,
            lamport_clock  = self.lamport_clock,
            wall_timestamp = now_wall(),
            boot_epoch     = self.boot_epoch,
            hardware_hash  = current_report.hardware_hash,
            state_version  = current_report.state_version + 1,
            ttl_hint_ms    = DEFAULT_TTL_MS
        )
        return (updated_report, changes)
    else:
        # No material change — keep current report, no broadcast
        return (current_report, [])
```

### 9.3 `serialize_for_broadcast()`

```python
def serialize_for_broadcast(report, available_bandwidth_kbps) -> bytes:
    """
    Serialize a CapabilityReport for transmission.
    Adapts detail level to available bandwidth.
    """
    # ── Full report (~200 bytes) ────────────────────────────
    if available_bandwidth_kbps >= BANDWIDTH_FULL_THRESHOLD:    # e.g., 500 kbps
        return msgpack.encode(report)                           # all fields

    # ── Compact report (~80 bytes) ──────────────────────────
    elif available_bandwidth_kbps >= BANDWIDTH_COMPACT_THRESHOLD:  # e.g., 50 kbps
        compact = CompactReport(
            node_id       = report.node_id,
            energy_level  = quantize_8bit(report.state.energy.level),
            cpu_available = quantize_8bit(report.state.compute.cpu_available),
            gpu_available = quantize_8bit(report.state.compute.gpu_available),
            sensing_flags = pack_boolean_flags(report.state.sensing),
            state_version = report.state_version,
            lamport_clock = report.lamport_clock
        )
        return msgpack.encode(compact)

    # ── Minimal heartbeat (~16 bytes) ───────────────────────
    else:
        heartbeat = MinimalHeartbeat(
            node_id       = report.node_id,
            alive_and_energy = quantize_4bit(report.state.energy.level),
            state_version = report.state_version
        )
        return msgpack.encode(heartbeat)
```

This is a simple example of the Semantic Degradation Ladder (HESK_SCOPE Section 12) applied to capability reporting itself.

---

## 10. WORKED EXAMPLE — Scout Alpha

### 10.1 Platform specification

**Node:** Scout Alpha (n_1)  
**Platform:** Quadrotor with Jetson Nano companion computer

**HardwareInventory:**
```
sensors_present:    [rgb_camera, gps, imu]
compute_hardware:   [cpu_arm_cortex_a57_quad, gpu_maxwell_128core]
radio_hardware:     [wifi_2.4ghz]
battery_chemistry:  lipo_4s
battery_capacity:   5200 mAh
max_speed_mps:      12.0
payload_capacity_kg: 1.0
```

**No** thermal sensor.  **No** LiDAR.

### 10.2 Raw telemetry at time T

| Telemetry | Value |
|-----------|-------|
| Camera health | OK |
| Camera FPS | 27 of 30 max |
| Thermal sensor | NOT PRESENT |
| LiDAR | NOT PRESENT |
| CPU utilization | 62 % |
| GPU utilization | ~45 % (see below) |
| GPU temperature | 71 °C |
| GPU VRAM total | 2048 MB |
| GPU VRAM used | 1200 MB |
| CUDA installed | Yes |
| Battery voltage | 14.8 V (4 cells) |
| Battery current | 8.2 A |
| WiFi RSSI | -72 dBm |
| Neighbors | 3 (nodes n_2, n_5, n_8) |
| Speed capability | 8.5 m/s (wind-limited) |
| Payload remaining | 0.5 kg |
| GPS fix | 3D fix, HDOP=1.2 |
| Position | (45.2, 12.8, 25.0) meters |

### 10.3 Step-by-step construction

#### Sensing

**RGB camera:**  
- Present: yes.  Health: OK.  
- FPS = 27, max = 30.  
- `rgb = assess_continuous(27, 0, 30, inverted=False) = 27/30 = 0.90`

**Thermal:**  
- Not present in HardwareInventory.  
- `thermal = 0` (BOOLEAN)

**LiDAR:**  
- Not present in HardwareInventory.  
- `lidar = 0.0`

#### Compute

**CPU:**  
- Utilization = 62 %.  
- `cpu_available = assess_continuous(62, 0, 100, inverted=True) = 1.0 - 0.62 = 0.38`

**GPU runtime:**  
- GPU hardware: present.  CUDA: installed.  
- `runtime = assess_categorical("cuda", {"cuda","opencl","cpu_only"}) = "cuda"` ✓

**GPU available:**  
- GPU utilization: we need the actual value. The GPU is running inference (45 % utilization).  
- Temperature: 71 °C.  Throttle threshold = 80 °C.  71 < 80 → `throttle_factor = 1.0` (no throttle).  
- `gpu_available = assess_continuous(45, 0, 100, inverted=True) * 1.0 = 0.55`

**VRAM:**  
- Total: 2048 MB, Used: 1200 MB, Free: 848 MB.  
- `vram_mb = 848` (CAPACITY, absolute value)

#### Energy

**Battery:**  
- Voltage: 14.8 V, Cells: 4.  
- Per-cell: 14.8 / 4 = 3.70 V.  
- Lookup in LIPO_SOC_TABLE: 3.70 V → SoC = 0.30.  
- `level = 0.30`  
- (Note: this means Scout Alpha is at 30 % charge — getting low.)

**Discharge rate:**  
- Suppose 60 seconds ago, level was 0.33.  
- `discharge_rate = (0.33 - 0.30) / 60 = 0.0005` per second = 0.03 per minute.

**Estimated remaining:**  
- `estimated_remaining_s = 0.30 / 0.0005 = 600 seconds` (10 minutes).

#### Communication

**Bandwidth:** `bandwidth_kbps = 1200` (intrinsic max interface capability)

#### Mobility

**Speed:**  
- Achievable: 8.5 m/s, Max: 12.0 m/s.  
- `speed = 8.5 / 12.0 = 0.71`

**Payload:** `payload_remaining_kg = 0.5`

**Position:** `(45.2, 12.8, 25.0)`

### 10.4 Assembled RuntimeState

```
RuntimeState (Scout Alpha, T):
  sensing:
    rgb:                   0.90    CONTINUOUS
    thermal:               0       BOOLEAN
    lidar:                 0.0     CONTINUOUS (not present)
  compute:
    cpu_available:         0.38    CONTINUOUS
    gpu_available:         0.55    CONTINUOUS
    runtime:               cuda    CATEGORICAL
    vram_mb:               848     CAPACITY (MB)
  energy:
    level:                 0.30    CONTINUOUS  ⚠️ LOW
    discharge_rate:        0.0005  CONTINUOUS (per second)
    estimated_remaining_s: 600     CAPACITY (seconds)
  communication:
    bandwidth_kbps:        1200    CAPACITY
  mobility:
    speed:                 0.71    CONTINUOUS
    payload_remaining_kg:  0.5     CAPACITY (kg)
    position:              (45.2, 12.8, 25.0)
```

### 10.5 Wrapped as CapabilityReport

```
CapabilityReport:
  node_id:          n_1
  state:            [above RuntimeState]
  lamport_clock:    47
  wall_timestamp:   1720834200000     # ms since epoch
  boot_epoch:       3                 # third boot this mission
  hardware_hash:    0xA3F7...         # hash of HardwareInventory
  state_version:    23                # 23rd state update since boot
  ttl_hint_ms:      500
```

### 10.6 Observations

- Scout Alpha has **good RGB vision** (0.90) but **no thermal or LiDAR** — it cannot be assigned to tasks requiring those sensors.
- It has **usable GPU compute** (0.55 available, CUDA runtime, 848 MB VRAM) — it could run small inference models locally.
- **Energy is concerning**: 30 % SoC, ~10 minutes remaining.  The scarcity allocator (004) should be reluctant to assign it new long-duration tasks.
- **Communication is mediocre**: link quality 0.35.  Coalition membership requiring high-bandwidth data exchange may be infeasible.
- A flat vector `[0.90, 0, 0, 0.38, 0.55, 0.30, 0.35, 0.71]` would lose the facts that: runtime is specifically CUDA, VRAM is 848 MB (enough for YOLOv5-small but not YOLOv5-large), battery is critically low despite the 0.30 looking like "just another low number," and link quality 0.35 implies ~1200 kbps which may or may not be sufficient depending on the task's data rate.

---

## 11. EDGE CASES

### 11.1 Sensor health = OK but data is garbage

**Scenario:** RGB camera reports `health = OK` and `fps = 28`, but the images are severely degraded (lens obstruction, condensation, sun glare).  The health register does not detect image quality problems.

**Impact:** `rgb = 0.93` — the capability model reports excellent camera, but the camera is operationally useless.

**Mitigation (v0.1):** This is **acknowledged as a limitation**.  The capability model trusts hardware health registers.  Image-quality-aware assessment (e.g., checking exposure histogram variance) is a future enhancement.

**Provisional choice:** Accept the risk.  Document the limitation.  A downstream task failure (e.g., mapping produces garbage) should trigger a manual or automated capability downgrade via a `SENSOR_HEALTH_CHANGE` event.

> **[PROVISIONAL v0.1]** The capability model does not perform data-plane quality inspection.  It relies on control-plane health flags.  This is a known gap.

### 11.2 GPU exists but driver crashed mid-mission

**Scenario:** At boot, GPU was healthy, CUDA runtime detected, `gpu_available = 0.65`.  At T=300s, the GPU driver crashes.  The `tegrastats` command returns an error.

**Handling:**
1. The periodic telemetry read for GPU utilization returns an error code.
2. `update_capability_state()` detects the error and sets:
   - `gpu_available = 0.0`
   - `runtime = "none"` (driver is gone, runtime is unusable)
   - `vram_mb = 0`
3. A `CapabilityChangeEvent` is emitted with `change_type = LOST`, `cause_hint = "gpu_driver_crash"`.
4. The node's state version increments.  The change is broadcast.
5. Any task currently using GPU compute on this node receives a resource-loss notification.

**Note:** If the driver recovers (auto-restart), a subsequent telemetry read will succeed, and the capability is restored via a GAINED event.

### 11.3 Stale battery reading

**Scenario:** The battery management system (BMS) stops responding.  The last battery voltage reading was 14.2 V, 45 seconds ago.

**Handling:**
1. The telemetry read for battery voltage returns a stale-data flag or timeout.
2. The capability model **does not** assume the last reading is still valid.
3. Conservative policy: extrapolate using the last known `discharge_rate`:
   - `estimated_current_level = last_level - (discharge_rate * elapsed_seconds)`
   - Mark the energy dimensions with a `confidence = DEGRADED` flag.
4. If the BMS has been unresponsive for > `BMS_TIMEOUT_S` (e.g., 30 s), set `energy.level` to a **pessimistic floor** (e.g., 0.10) to prevent the node from being assigned energy-intensive tasks.

> **[PROVISIONAL v0.1]** Pessimistic extrapolation on BMS timeout.  Alternative: treat the node as energy-unknown and exclude from energy-sensitive tasks entirely.  The tradeoff is: pessimistic floor keeps the node partially usable vs. full exclusion may be safer but wastes remaining capability.

### 11.4 Node rebooted and lost calibration

**Scenario:** Node n_3 reboots mid-mission.  Its `boot_epoch` increments.  The IMU requires a warm-up calibration period (~15 seconds).  During this period, GPS-denied localization is unreliable.

**Handling:**
1. At boot, `construct_capability_state()` detects that IMU calibration is incomplete.
2. Dimensions dependent on IMU calibration (e.g., `speed`, `position` accuracy) are set to degraded values.
3. A `calibration_timer` is started.  When calibration completes, a `SENSOR_HEALTH_CHANGE` event triggers re-assessment.
4. The `boot_epoch` change is visible in the CapabilityReport.  Other nodes receiving this report know that n_3's previous state is invalidated — they should not trust any cached CapabilityReport from a prior boot epoch.

### 11.5 Task commitment reducing available compute

**Scenario:** Node n_5 accepts a YOLOv5 inference task.  This will consume ~40 % GPU and 600 MB VRAM.

**Handling:**
1. When the task is committed, a `TASK_CHANGE` event triggers `update_capability_state()`.
2. The task's expected resource consumption is *reserved* (subtracted from available):
   - `gpu_available` decreases by the reservation amount.
   - `vram_mb` decreases by the reservation amount.
   - `cpu_available` may also decrease if the task uses CPU.
3. The updated CapabilityReport reflects the *post-commitment* availability.
4. This prevents other nodes from counting n_5's GPU as free when it is already allocated.

**Design decision:** Should reservations be based on *measured* resource usage (reactive) or *declared* resource requirements (proactive)?

> **[PROVISIONAL v0.1]** Use declared task resource requirements for immediate reservation, then adjust based on measured usage after the task starts.  This avoids double-booking but may over-reserve.

---

## 12. FAILURE MODES

| Failure | Impact on capability model | Mitigation |
|---------|--------------------------|------------|
| Telemetry source offline | Affected dimensions stale or zero | Timeout → pessimistic default, emit LOST event |
| Clock drift between nodes | Staleness calculation inaccurate | Use Lamport clock as primary ordering; wall time as secondary hint |
| Hysteresis too wide | Real capability changes missed | Tune thresholds per dimension; critical dimensions (energy) get tighter bands |
| Hysteresis too narrow | Excessive broadcast churn | Widen threshold; monitor broadcast rate |
| Hardware manifest wrong | Static capabilities misrepresented | Validate manifest against actual device enumeration at boot |
| CapabilityReport lost in transit | Remote nodes have stale view | Periodic re-broadcast; requesting node can poll |
| Node sends fabricated report | Remote nodes trust false capabilities | Out of scope for v0.1; future: cross-validation with task outcomes |
| Composite capability eval wrong | Task assigned to incapable node | Test composite rules against concrete scenarios; include in baseline comparison |

---

## 13. INVARIANTS

The following invariants **must** hold for the capability model:

| # | Invariant | How this design respects it |
|---|-----------|---------------------------|
| 1 | No node may directly access global simulation truth | `construct_capability_state()` reads only local telemetry. No `world.get_state()` call. |
| 2 | Every operational decision derivable from local state + received messages only | Self-assessment is purely local. Evaluating remote nodes uses received CapabilityReports. |
| 3 | No permanent central coordinator | Each node independently constructs its own CapabilityState. No registration server. |
| 4 | Physical capabilities never transferred between nodes | HardwareInventory is read-only after boot. Only RuntimeState changes. |
| 5 | Task responsibility and physical capability are separate | CapabilityState describes what a node *can* do, not what it *is assigned to* do. Task commitments only affect *available* resources. |
| 6 | Every remote state observation carries provenance and version metadata | CapabilityReport includes node_id, lamport_clock, wall_timestamp, boot_epoch, state_version, ttl_hint_ms. |
| 7 | Communication failure ≠ node death | Staleness discount reduces trust in old reports but does not mark the node as dead. |
| 8 | Degradation preserves critical services first | Energy-critical thresholds cause early warnings; capability model feeds degradation engine (006). |
| 9 | Coalition feasibility includes communication feasibility | Network feasibility is assessed dynamically via local LinkState graphs, not intrinsic capability broadcasts. |
| 10 | Simulation ground truth for evaluation only | The capability model has no import path from any simulator world state. |

---

## 14. OPEN QUESTIONS

### 14.1 Composite capabilities

**Question:** How should composite (derived) capabilities be defined and evaluated?

**Design options:**
- **Option A: Rule-based.**  Define composite capabilities as boolean expressions over base dimensions.  E.g., `can_run_yolo = (runtime ∈ {cuda} AND vram_mb ≥ 512 AND gpu_available ≥ 0.20)`.  Simple, interpretable, but requires manual rule authoring for each composite.
- **Option B: Capability profiles.**  Define named profiles (e.g., "gpu_inference_small", "gpu_inference_large") with pre-specified requirement vectors.  A node evaluates itself against each profile at construction time.
- **Option C: Lazy evaluation.**  Do not pre-compute composites.  Let the matching engine (003) evaluate compatibility on demand by inspecting base dimensions.

**Tradeoffs:** Option A is explicit and debuggable but doesn't scale.  Option C defers complexity to the matching engine.  Option B is a middle ground but adds a profile registry.

> **[PROVISIONAL v0.1]** Option A (rule-based) for the initial prototype.  Define 3–5 critical composite capabilities manually.  Re-evaluate if the number of composites exceeds ~10.

### 14.2 Compute compatibility across runtimes

**Question:** How should the model handle runtime-specific compute capabilities?

A task may require CUDA.  A node with OpenCL compute is not a substitute, even if its GPU utilization is 0 %.

**Design options:**
- **Option A: Categorical gate.**  `runtime` is CATEGORICAL.  The matching engine checks `task.required_runtime ⊆ node.runtime`.  If not, match score for compute = 0 regardless of gpu_available.
- **Option B: Compatibility matrix.**  Define pairwise compatibility: `cuda ↔ cuda = 1.0, cuda ↔ opencl = 0.0, opencl ↔ opencl = 1.0, cpu_only ↔ * = 0.3` (CPU can do anything, slowly).

> **[PROVISIONAL v0.1]** Option A — strict categorical gate.  The matching engine will reject incompatible runtimes entirely.  Option B is more nuanced and may be needed later when CPU fallback is modeled.

### 14.3 Hysteresis threshold tuning

**Question:** How should hysteresis thresholds be set per dimension?

**Tradeoffs:**
- Tight thresholds → more broadcasts, better freshness, higher bandwidth cost.
- Wide thresholds → fewer broadcasts, risk of stale remote views.

> **[PROVISIONAL v0.1]** Use the defaults in Section 7.2.  Instrument broadcast rate in simulation.  If broadcast rate exceeds 2 reports/second/node, widen thresholds.  If staleness causes task assignment failures, tighten them.

### 14.4 Staleness versioning across reboots

**Question:** When a node reboots (new `boot_epoch`), should all cached CapabilityReports from prior epochs be invalidated?

**Design options:**
- **Option A: Full invalidation.**  Any report with `boot_epoch < current_epoch` is treated as stale (discount = 0).
- **Option B: Conditional invalidation.**  Compare `hardware_hash`.  If hardware hasn't changed, prior reports may retain partial validity for slowly-changing dimensions (e.g., battery is still a LiPo).

> **[PROVISIONAL v0.1]** Option A — full invalidation on epoch change.  A reboot may change driver state, calibration, and running processes.  No prior assumptions are safe.

### 14.5 Position representation

**Question:** Should `position` be a capability dimension or metadata?

Position is not a "capability" in the same sense as `cpu_available`.  However, it is essential for coalition feasibility (are nodes close enough to cooperate?) and task requirements (is the node near the task area?).

> **[PROVISIONAL v0.1]** Include position in RuntimeState as metadata (not typed as CONTINUOUS/CAPACITY).  It is not scored by the matching engine but is used by the coalition evaluator for spatial feasibility checks.

### 14.6 Confidence per dimension

**Question:** Should each dimension carry a confidence value?

When a battery reading is extrapolated (Section 11.3), the confidence is lower than a direct reading.  Should the model carry per-dimension confidence scores?

**Tradeoffs:**  More information for downstream algorithms, but doubles the size of the state and complicates every comparison.

> **[PROVISIONAL v0.1]** No per-dimension confidence.  Use the staleness model (Section 7.4) for received reports, and the pessimistic-default strategy (Section 11.3) for local telemetry failures.  Revisit if simulation reveals cases where downstream decisions are degraded by the lack of confidence metadata.

---

## 15. BASELINE FOR COMPARISON

### 15.1 Baseline: Flat [0,1] vector with dot-product matching

The simplest alternative to the typed capability model is:

```
capability_flat = [rgb, thermal, lidar, cpu, gpu, battery, link, speed]
                = [0.90, 0.0, 0.0, 0.38, 0.55, 0.30, 0.35, 0.71]
```

Task requirements are also flat vectors.  Match score = dot product (or cosine similarity).

### 15.2 Three concrete failures of the flat baseline

#### Failure 1: Runtime gap invisible

**Scenario:** Task τ_1 requires GPU inference (CUDA).

- Node A: `gpu = 0.55`, runtime = CUDA.  Can actually run inference.
- Node B: `gpu = 0.70`, runtime = OpenCL.  Cannot run the CUDA model.

**Flat vector:** Node B scores higher (`0.70 > 0.55`).  Dot product assigns the task to B.  
**Result:** Task fails at runtime — incompatible GPU framework.  
**Typed model:** CATEGORICAL gate on `runtime` rejects B.  A is correctly selected.

#### Failure 2: Capacity threshold ignored

**Scenario:** Task τ_2 requires ≥ 1024 MB VRAM for a large detection model.

- Node A: `gpu = 0.80`, VRAM = 512 MB.  Cannot fit the model.
- Node B: `gpu = 0.40`, VRAM = 2048 MB.  Can fit the model.

**Flat vector:** Normalizing VRAM to [0,1] across the swarm, A's `gpu = 0.80` dominates B's `gpu = 0.40`.  A wins.  
**Result:** Model fails to load.  Out-of-memory error.  
**Typed model:** VRAM is a CAPACITY dimension.  Threshold check: `512 < 1024 → FAIL`.  B is selected.

#### Failure 3: Battery criticality hidden

**Scenario:** Two nodes compete for a 20-minute mapping task.

- Node A: `battery = 0.30` (per-cell 3.70 V, ~10 min remaining, critically low for a 4S LiPo).
- Node B: `battery = 0.55` (per-cell 3.80 V, ~35 min remaining, healthy).

**Flat vector:** Both nodes have energy values in [0,1].  The difference is `0.55 - 0.30 = 0.25`, which the dot product weights equally with a 0.25 difference in any other dimension.  If A is better on other dimensions, it wins.  
**Result:** A accepts the 20-minute task with 10 minutes of battery.  Mission fails at minute 10.  
**Typed model:** `estimated_remaining_s = 600` (CAPACITY, seconds).  Task duration = 1200 seconds.  `600 < 1200 → insufficient`.  A is rejected for this task regardless of other scores.

### 15.3 What the baseline is useful for

The flat vector baseline is the **lower bound** for evaluation.  In simulation, we compare:

| Metric | Flat vector baseline | HESK typed model |
|--------|---------------------|-----------------|
| Task assignment correctness | Measured | Measured |
| Runtime failures (assigned but cannot execute) | Measured | Measured |
| Capability-threshold violations | Measured | Measured |
| Broadcast bandwidth consumed | Measured | Measured |
| State staleness at decision time | Measured | Measured |
| Computation cost of assessment | Measured | Measured |

If the typed model does not measurably reduce task assignment failures compared to flat vectors, the additional complexity is not justified.

---

## 16. REFERENCES AND PRIOR ART

| Concept | Source | How HESK uses it |
|---------|--------|-----------------|
| Multi-dimensional capability representation | Gerkey & Matarić, "A Formal Analysis and Taxonomy of Task Allocation in Multi-Robot Systems," 2004 | HESK extends beyond their ST-SR/MT-MR taxonomy by adding typed dimensions and dynamic state |
| Contract Net Protocol | Smith, 1980 | Task bidding structure.  HESK adds capability-scarcity weighting (not claimed as novel bidding). |
| Logical clocks | Lamport, "Time, Clocks, and the Ordering of Events in a Distributed System," 1978 | Used for event ordering in CapabilityReport versioning |
| Typed attributes in multi-agent systems | Parker, "ALLIANCE: An Architecture for Fault Tolerant Multirobot Cooperation," 1998 | Motivation for capability types; HESK adds runtime-state separation |
| Degradation-aware systems | Various (graceful degradation literature) | HESK's central thesis; capability model is the foundation |

---

*End of Algorithm 001 — Capability Model (v0.1 draft)*  
*Next: [002 — Task Model](./002_task_model.md)*
