/** Port of src/hesk/ledger/ledger.py and ledger/model.py — Algorithm 007, local state ledger. */
import type { NodeId } from './types'

export type StateSemanticType =
  | 'SET_LIKE' | 'COUNTER' | 'EXCLUSIVE_OWNERSHIP' | 'OBSERVATIONAL' | 'RESOURCE' | 'MISSION_POLICY' | 'REACHABILITY'
export type ObservationType = 'DIRECT' | 'RELAYED' | 'INFERRED'
export type EventType = 'WRITE' | 'UPDATE' | 'DELETE' | 'CONFLICT_DETECTED'

export interface Provenance {
  origin: NodeId
  observationType: ObservationType
  originalClock: number
  hops: number
  authorityLevel: number
}

export interface ConflictRecord {
  localValue: unknown
  remoteValue: unknown
  remoteSource: NodeId
  remoteClock: number
  detectedAt: number
}

export interface LedgerEntry {
  key: string
  value: unknown
  semanticType: StateSemanticType
  sourceNode: NodeId
  lamportClock: number
  wallTime: number
  confidence: number
  provenance: Provenance
  conflict: ConflictRecord | null
}

export interface LedgerEvent {
  eventId: string
  type: EventType
  key: string
  semanticType: StateSemanticType
  oldValue: unknown
  newValue: unknown
  lamportClock: number
  originNode: NodeId
  originSeq: number
  wallTime: number
}

export const CONCURRENCY_CLOCK_THRESHOLD = 5
export const CONCURRENCY_WALL_THRESHOLD = 3.0
export const DRIFT_MAX = 2.0
export const MAX_OBSERVATIONS_PER_KEY = 5

/** Stable structural serialisation; stands in for Python value equality. */
export function canonical(v: unknown): string {
  return JSON.stringify(v, (_k, val: unknown) => {
    if (val && typeof val === 'object' && !Array.isArray(val)) {
      const o = val as Record<string, unknown>
      return Object.fromEntries(Object.keys(o).sort().map((k) => [k, o[k]]))
    }
    return val
  })
}
export const valuesEqual = (a: unknown, b: unknown): boolean => canonical(a) === canonical(b)

/** Python sets are modelled as sorted, de-duplicated string arrays. */
const asSet = (v: unknown): string[] => [...new Set(Array.isArray(v) ? (v as string[]) : [])].sort()

export function isPotentiallyConcurrent(local: LedgerEntry, _sourceClock: number, sourceWallTime: number): boolean {
  // In the Python kernel the clock-distance clause is subsumed by the wall-time clause.
  return Math.abs(local.wallTime - sourceWallTime) <= DRIFT_MAX + CONCURRENCY_WALL_THRESHOLD
}

export function acceptResourceUpdate(local: LedgerEntry, sourceWallTime: number, confidence: number, prov: Provenance): boolean {
  const diff = sourceWallTime - local.wallTime
  if (diff > DRIFT_MAX) return true
  if (diff < -DRIFT_MAX) return false
  if (prov.observationType === 'DIRECT' && local.provenance.observationType !== 'DIRECT') return true
  return confidence > local.confidence
}

export interface ReceivedWrite {
  key: string
  value: unknown
  semanticType: StateSemanticType
  sourceNode: NodeId
  sourceClock: number
  sourceWallTime: number
  confidence: number
  provenance: Provenance
  originSeq?: number
  updateLamportClock?: boolean
}

export class LocalStateLedger {
  entries = new Map<string, LedgerEntry>()
  eventLog: LedgerEvent[] = []
  lamportClock = 0
  seqNum = 0
  versionVector: Record<NodeId, number>

  constructor(public nodeId: NodeId, private now: () => number) {
    this.versionVector = { [nodeId]: 0 }
  }

  writeLocal(key: string, value: unknown, semanticType: StateSemanticType): LedgerEntry {
    this.lamportClock += 1
    this.seqNum += 1
    this.versionVector[this.nodeId] = this.seqNum
    const old = this.entries.get(key)
    const entry: LedgerEntry = {
      key, value, semanticType, sourceNode: this.nodeId, lamportClock: this.lamportClock, wallTime: this.now(), confidence: 1,
      provenance: { origin: this.nodeId, observationType: 'DIRECT', originalClock: this.lamportClock, hops: 0, authorityLevel: 100 },
      conflict: null,
    }
    this.entries.set(key, entry)
    this.appendEvent(old ? 'UPDATE' : 'WRITE', key, semanticType, old ? old.value : null, value, this.nodeId, this.seqNum)
    return entry
  }

  /** Returns [entry, changed]. */
  writeReceived(w: ReceivedWrite): [LedgerEntry, boolean] {
    if (w.updateLamportClock ?? true) this.lamportClock = Math.max(this.lamportClock, w.sourceClock) + 1
    const originSeq = w.originSeq ?? 0
    const local = this.entries.get(w.key)
    if (!local) {
      const entry: LedgerEntry = {
        key: w.key, value: w.value, semanticType: w.semanticType, sourceNode: w.sourceNode, lamportClock: this.lamportClock,
        wallTime: w.sourceWallTime, confidence: w.confidence, provenance: w.provenance, conflict: null,
      }
      this.entries.set(w.key, entry)
      this.appendEvent('WRITE', w.key, w.semanticType, null, w.value, w.sourceNode, originSeq)
      return [entry, true]
    }
    const [merged, changed, conflict] = this.semanticMerge(local, w)
    if (changed) {
      const oldVal = local.value
      local.value = merged
      local.lamportClock = this.lamportClock
      local.wallTime = Math.max(local.wallTime, w.sourceWallTime)
      local.sourceNode = w.sourceNode
      local.confidence = w.confidence
      local.provenance = w.provenance
      this.appendEvent('UPDATE', w.key, w.semanticType, oldVal, merged, w.sourceNode, originSeq)
    }
    if (conflict) {
      local.conflict = {
        localValue: local.value, remoteValue: w.value, remoteSource: w.sourceNode, remoteClock: w.sourceClock, detectedAt: this.lamportClock,
      }
      this.appendEvent('CONFLICT_DETECTED', w.key, w.semanticType, local.value, w.value, w.sourceNode, originSeq)
    }
    return [local, changed]
  }

  /** Type-specific merge rules. Returns [mergedValue, changed, conflict]. */
  private semanticMerge(local: LedgerEntry, w: ReceivedWrite): [unknown, boolean, boolean] {
    switch (local.semanticType) {
      case 'SET_LIKE': {
        const mine = asSet(local.value)
        const merged = [...new Set([...mine, ...asSet(w.value)])].sort()
        return [merged, merged.length !== mine.length, false]
      }
      case 'COUNTER': {
        const merged = Math.max(Number(local.value), Number(w.value))
        return [merged, merged !== local.value, false]
      }
      case 'EXCLUSIVE_OWNERSHIP':
        if (isPotentiallyConcurrent(local, w.sourceClock, w.sourceWallTime)) return [local.value, false, true]
        if (w.sourceClock > local.lamportClock) return [w.value, true, false]
        if (w.sourceClock < local.lamportClock) return [local.value, false, false]
        return w.sourceNode < local.sourceNode ? [w.value, true, false] : [local.value, false, false]
      case 'OBSERVATIONAL': {
        const list = Array.isArray(local.value) ? [...(local.value as unknown[])] : [{ value: local.value, provenance: local.provenance }]
        list.push({ value: w.value, provenance: w.provenance })
        const trimmed = list.length > MAX_OBSERVATIONS_PER_KEY
          ? (list as Array<{ provenance: Provenance }>).sort((a, b) => b.provenance.originalClock - a.provenance.originalClock).slice(0, MAX_OBSERVATIONS_PER_KEY)
          : list
        return [trimmed, true, false]
      }
      case 'RESOURCE':
        return acceptResourceUpdate(local, w.sourceWallTime, w.confidence, w.provenance) ? [w.value, true, false] : [local.value, false, false]
      case 'MISSION_POLICY':
        return w.provenance.authorityLevel < local.provenance.authorityLevel ? [w.value, true, false] : [local.value, false, false]
      case 'REACHABILITY':
        return w.sourceClock > local.lamportClock ? [w.value, true, false] : [local.value, false, false]
    }
  }

  getEventsSince(clock: number): LedgerEvent[] {
    return this.eventLog.filter((e) => e.lamportClock > clock)
  }

  private appendEvent(type: EventType, key: string, semanticType: StateSemanticType, oldValue: unknown, newValue: unknown, originNode: NodeId, originSeq: number): void {
    this.eventLog.push({
      eventId: `${this.nodeId}_${this.lamportClock}`, type, key, semanticType, oldValue, newValue,
      lamportClock: this.lamportClock, originNode, originSeq, wallTime: this.now(),
    })
  }

  /** Deep copy under a new replica identity (a partition fork). Not part of the Python kernel. */
  fork(newId: NodeId): LocalStateLedger {
    const f = new LocalStateLedger(newId, this.now)
    f.entries = new Map(structuredClone([...this.entries]))
    f.eventLog = structuredClone(this.eventLog)
    f.lamportClock = this.lamportClock
    f.seqNum = newId === this.nodeId ? this.seqNum : 0
    f.versionVector = newId === this.nodeId ? { ...this.versionVector } : { ...this.versionVector, [newId]: 0 }
    return f
  }
}
