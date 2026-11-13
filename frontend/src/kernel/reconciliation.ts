/** Port of src/hesk/ledger/reconciliation.py — Algorithm 008, partition reconciliation. */
import { DRIFT_MAX, valuesEqual, type LedgerEntry, type LedgerEvent, type LocalStateLedger, type StateSemanticType } from './ledger'
import type { NodeId } from './types'

export interface SideEffect {
  type: 'RELEASE_EXECUTOR' | 'NOTIFY_WINNER'
  target: NodeId
  task: string
}

export interface Resolution {
  strategy: string
  winningValue: unknown
  winningSource: NodeId
  reason: string
  sideEffects: SideEffect[]
}

export interface Conflict {
  key: string
  localEntry: LedgerEntry
  remoteEntry: LedgerEntry
  semanticType: StateSemanticType
  resolution: Resolution | null
}

export interface ReconciliationTrace {
  detectingNode: NodeId
  remoteNode: NodeId
  detectingClock: number
  remoteClock: number
  localEventsSince: number
  remoteEventsSince: number
  conflictsFound: number
  conflictsResolved: number
  resolutionDetails: Conflict[]
  entriesMerged: number
}

const CONVERGENT: StateSemanticType[] = ['SET_LIKE', 'COUNTER', 'OBSERVATIONAL']

export function getUnseenEvents(localLog: LedgerEvent[], remoteVersionVector: Record<NodeId, number>): LedgerEvent[] {
  return localLog.filter((e) => e.originSeq > (remoteVersionVector[e.originNode] ?? 0))
}

export function reconstructEntry(remoteEvents: LedgerEvent[], key: string): LedgerEntry | null {
  let latest: LedgerEvent | null = null
  for (const e of remoteEvents) if (e.key === key && (latest === null || e.lamportClock > latest.lamportClock)) latest = e
  if (!latest) return null
  return {
    key, value: latest.newValue, semanticType: latest.semanticType, sourceNode: latest.originNode, lamportClock: latest.lamportClock,
    wallTime: latest.wallTime, confidence: 1,
    provenance: { origin: latest.originNode, observationType: 'DIRECT', originalClock: latest.lamportClock, hops: 0, authorityLevel: 100 },
    conflict: null,
  }
}

export function detectConflicts(ledger: LocalStateLedger, localEvents: LedgerEvent[], remoteEvents: LedgerEvent[]): Conflict[] {
  const remoteKeys = new Set(remoteEvents.map((e) => e.key))
  const both = [...new Set(localEvents.map((e) => e.key))].filter((k) => remoteKeys.has(k)).sort()
  const conflicts: Conflict[] = []
  for (const key of both) {
    const local = ledger.entries.get(key)
    const remote = reconstructEntry(remoteEvents, key)
    if (!local || !remote) continue
    if (CONVERGENT.includes(local.semanticType)) continue
    if (!valuesEqual(local.value, remote.value)) {
      conflicts.push({ key, localEntry: structuredClone(local), remoteEntry: remote, semanticType: local.semanticType, resolution: null })
    }
  }
  return conflicts
}

function taskInfo(value: unknown): [string, number, number] {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    const v = value as Record<string, unknown>
    return [String(v.assignee ?? ''), Number(v.progress ?? 0), Number(v.match_quality ?? 0)]
  }
  return [String(value), 0, 0]
}

/** Dual ownership cascade: progress → match quality → earlier assignment → node id. */
export function resolveExclusiveOwnership(c: Conflict): Resolution {
  const local = c.localEntry
  const remote = c.remoteEntry
  const [la, lp, lq] = taskInfo(local.value)
  const [ra, rp, rq] = taskInfo(remote.value)
  const EPS = 0.05
  let winner: LedgerEntry
  let loser: LedgerEntry
  let reason: string
  if (Math.abs(lp - rp) > EPS) {
    if (lp > rp) [winner, loser, reason] = [local, remote, `Higher progress: ${la} at ${lp.toFixed(2)} vs ${ra} at ${rp.toFixed(2)}`]
    else [winner, loser, reason] = [remote, local, `Higher progress: ${ra} at ${rp.toFixed(2)} vs ${la} at ${lp.toFixed(2)}`]
  } else if (Math.abs(lq - rq) > EPS) {
    if (lq > rq) [winner, loser, reason] = [local, remote, `Higher match quality: ${la} at ${lq.toFixed(2)}`]
    else [winner, loser, reason] = [remote, local, `Higher match quality: ${ra} at ${rq.toFixed(2)}`]
  } else if (local.wallTime < remote.wallTime) {
    [winner, loser, reason] = [local, remote, `Earlier assignment: ${local.wallTime} < ${remote.wallTime}`]
  } else if (remote.wallTime < local.wallTime) {
    [winner, loser, reason] = [remote, local, `Earlier assignment: ${remote.wallTime} < ${local.wallTime}`]
  } else if (la < ra) {
    [winner, loser, reason] = [local, remote, `Tiebreak: lower node_id ${la} < ${ra}`]
  } else {
    [winner, loser, reason] = [remote, local, `Tiebreak: lower node_id ${ra} < ${la}`]
  }
  return {
    strategy: 'EXCLUSIVE_OWNERSHIP_CASCADE', winningValue: winner.value, winningSource: winner.sourceNode, reason,
    sideEffects: [
      { type: 'RELEASE_EXECUTOR', target: taskInfo(loser.value)[0], task: c.key },
      { type: 'NOTIFY_WINNER', target: taskInfo(winner.value)[0], task: c.key },
    ],
  }
}

/** Most recent observation wins, with a wall-clock drift guard. */
export function resolveResource(c: Conflict): Resolution {
  const { localEntry: local, remoteEntry: remote } = c
  const diff = remote.wallTime - local.wallTime
  if (diff > DRIFT_MAX) {
    return { strategy: 'RESOURCE_RECENCY', winningValue: remote.value, winningSource: remote.sourceNode, reason: `Remote observation is ${diff.toFixed(1)}s newer`, sideEffects: [] }
  }
  if (diff < -DRIFT_MAX) {
    return { strategy: 'RESOURCE_RECENCY', winningValue: local.value, winningSource: local.sourceNode, reason: `Local observation is ${(-diff).toFixed(1)}s newer`, sideEffects: [] }
  }
  const score = (e: LedgerEntry) => ({ DIRECT: 1.0, RELAYED: 0.7, INFERRED: 0.5 })[e.provenance.observationType] * e.confidence
  const ls = score(local)
  const rs = score(remote)
  return ls >= rs
    ? { strategy: 'RESOURCE_PROVENANCE', winningValue: local.value, winningSource: local.sourceNode, reason: `Within drift margin; local provenance score ${ls.toFixed(2)} >= remote ${rs.toFixed(2)}`, sideEffects: [] }
    : { strategy: 'RESOURCE_PROVENANCE', winningValue: remote.value, winningSource: remote.sourceNode, reason: `Within drift margin; remote provenance score ${rs.toFixed(2)} > local ${ls.toFixed(2)}`, sideEffects: [] }
}

export function resolveMissionPolicy(c: Conflict): Resolution {
  const la = c.localEntry.provenance.authorityLevel
  const ra = c.remoteEntry.provenance.authorityLevel
  return la <= ra
    ? { strategy: 'MISSION_POLICY_AUTHORITY', winningValue: c.localEntry.value, winningSource: c.localEntry.sourceNode, reason: `Local authority level ${la} <= remote ${ra}`, sideEffects: [] }
    : { strategy: 'MISSION_POLICY_AUTHORITY', winningValue: c.remoteEntry.value, winningSource: c.remoteEntry.sourceNode, reason: `Remote authority level ${ra} < local ${la}`, sideEffects: [] }
}

export function handleReconnection(
  ledger: LocalStateLedger, remoteNodeId: NodeId, remoteClock: number, remoteVersionVector: Record<NodeId, number>,
  remoteEvents: LedgerEvent[], executeSideEffect: (e: SideEffect) => void = () => {},
): ReconciliationTrace {
  const detectingClock = ledger.lamportClock
  const localEvents = getUnseenEvents(ledger.eventLog, remoteVersionVector)
  let merged = 0

  for (const ev of remoteEvents) {
    if (!CONVERGENT.includes(ev.semanticType)) continue
    const [, changed] = ledger.writeReceived({
      key: ev.key, value: ev.newValue, semanticType: ev.semanticType, sourceNode: ev.originNode, sourceClock: ev.lamportClock,
      sourceWallTime: ev.wallTime, confidence: 1,
      provenance: { origin: ev.originNode, observationType: 'DIRECT', originalClock: ev.lamportClock, hops: 0, authorityLevel: 100 },
    })
    if (changed) merged += 1
  }

  const conflicts = detectConflicts(ledger, localEvents, remoteEvents)
  for (const c of conflicts) {
    if (c.semanticType === 'EXCLUSIVE_OWNERSHIP') c.resolution = resolveExclusiveOwnership(c)
    else if (c.semanticType === 'RESOURCE') c.resolution = resolveResource(c)
    else if (c.semanticType === 'MISSION_POLICY') c.resolution = resolveMissionPolicy(c)
    else c.resolution = { strategy: 'FALLBACK', winningValue: c.localEntry.value, winningSource: c.localEntry.sourceNode, reason: 'Fallback resolution', sideEffects: [] }
    ledger.writeLocal(c.key, c.resolution.winningValue, c.semanticType)
    merged += 1
  }
  for (const c of conflicts) for (const e of c.resolution?.sideEffects ?? []) executeSideEffect(e)

  return {
    detectingNode: ledger.nodeId, remoteNode: remoteNodeId, detectingClock, remoteClock,
    localEventsSince: localEvents.length, remoteEventsSince: remoteEvents.length,
    conflictsFound: conflicts.length, conflictsResolved: conflicts.filter((c) => c.resolution).length,
    resolutionDetails: conflicts, entriesMerged: merged,
  }
}
