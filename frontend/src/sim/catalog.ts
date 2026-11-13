/** Typed access to the scenario catalog shared with the Python parity generator. */
import raw from './catalog.json'
import { validateTaskDefinition, type CapabilityState, type DimType, type DimValue, type LinkMetrics, type TaskDefinition } from '../kernel/types'

export type ArchetypeId = 'ISR' | 'COMPUTE' | 'SCOUT' | 'LIDAR' | 'RELAY' | 'THERMAL'
export type PresetId = 'quintet' | 'baseline' | 'dense'

export interface DimensionMeta {
  type: DimType
  label: string
  max: number
}
export interface Archetype {
  prefix: string
  label: string
  hardware: string
  dims: Record<string, DimValue>
}
export interface Preset {
  label: string
  tasks: string[]
  nodes: Array<{ archetype: ArchetypeId; x: number; y: number }>
}

export const COMM_RANGE: number = raw.commRange
export const MAX_BANDWIDTH_KBPS: number = raw.maxBandwidthKbps
export const BASE_LATENCY_MS: number = raw.baseLatencyMs
export const LATENCY_PER_UNIT_MS: number = raw.latencyPerUnitMs
/** One world unit is rendered as this many metres. Presentation only. */
export const WORLD_METRES = 1000

export const DIMENSIONS = raw.dimensions as Record<string, DimensionMeta>
export const DIMENSION_IDS = Object.keys(DIMENSIONS)
export const ARCHETYPES = raw.archetypes as Record<ArchetypeId, Archetype>
export const ARCHETYPE_IDS = Object.keys(ARCHETYPES) as ArchetypeId[]
export const TASKS = raw.tasks as unknown as TaskDefinition[]
export const PRESETS = raw.presets as Record<PresetId, Preset>
export const PRESET_IDS = Object.keys(PRESETS) as PresetId[]

for (const t of TASKS) validateTaskDefinition(t)

export const taskById = (id: string): TaskDefinition => {
  const t = TASKS.find((x) => x.taskId === id)
  if (!t) throw new Error(`unknown task ${id}`)
  return t
}

export interface SeedNode {
  id: string
  archetype: ArchetypeId
  x: number
  y: number
  dims: Record<string, DimValue>
}

/** Node ids are `<prefix>-<n>`, numbered per archetype in preset order. */
export function buildPresetNodes(preset: PresetId): SeedNode[] {
  const counts: Partial<Record<ArchetypeId, number>> = {}
  return PRESETS[preset].nodes.map((n) => {
    const a = ARCHETYPES[n.archetype]
    const k = (counts[n.archetype] ?? 0) + 1
    counts[n.archetype] = k
    return { id: `${a.prefix}-${k}`, archetype: n.archetype, x: n.x, y: n.y, dims: { ...a.dims } }
  })
}

export const toState = (n: { id: string; dims: Record<string, DimValue> }, timestamp = 0): CapabilityState => ({
  nodeId: n.id, timestamp, dimensions: n.dims,
})

export const distance = (a: { x: number; y: number }, b: { x: number; y: number }): number => Math.hypot(a.x - b.x, a.y - b.y)

/** Link model: bandwidth falls linearly to zero at COMM_RANGE; latency grows with distance. */
export const linkBandwidth = (d: number): number => MAX_BANDWIDTH_KBPS * Math.max(0, 1 - d / COMM_RANGE)
export const linkLatency = (d: number): number => BASE_LATENCY_MS + LATENCY_PER_UNIT_MS * d

export function geometricLinks(pos: Record<string, { x: number; y: number }>): LinkMetrics {
  const d = (a: string, b: string) => distance(pos[a] as { x: number; y: number }, pos[b] as { x: number; y: number })
  return { getBandwidth: (a, b) => linkBandwidth(d(a, b)), getLatency: (a, b) => linkLatency(d(a, b)) }
}
