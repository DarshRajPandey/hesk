/** Port of src/hesk/capabilities/matching.py — Algorithm 003, capability matching. */
import type { CapabilityState, DimType, DimValue, TaskRequirement } from './types'

export const DEFAULT_T_HALF = 30.0
export const DEFAULT_CONFIDENCE_FLOOR = 0.05
export const DEFAULT_SURPLUS_CAP = 1.0
export const DEFAULT_W_SAT = 0.8
export const DEFAULT_W_HEAD = 0.2

export interface CompResult {
  met: boolean
  surplus: number
}

export interface DimensionResult {
  dimension: string
  dimType: DimType
  required: boolean
  met: boolean
  surplus: number
  nodeValue: DimValue | string[] | null
  taskValue: TaskRequirement
}

export interface MatchResult {
  eligible: boolean
  quality: number
  confidence: number
  weightedQuality: number
  dimensionDetails: Record<string, DimensionResult>
  unmetRequired: string[]
  missingDimensions: string[]
}

/**
 * Type-aware comparison. `nodeValue` may be a string[] only for a composed
 * coalition value (UNION semantic); as in the Python kernel, a set is never a
 * member of the required set, so composed categorical values are never met.
 */
export function compare(nodeValue: DimValue | string[], req: TaskRequirement): CompResult {
  switch (req.dimType) {
    case 'BOOLEAN':
      return { met: nodeValue === true || req.value === false, surplus: 0 }
    case 'CONTINUOUS':
    case 'CAPACITY': {
      const v = Number(nodeValue)
      const th = req.threshold ?? 0
      return { met: v >= th, surplus: Math.max(v - th, 0) }
    }
    case 'CATEGORICAL': {
      const met = typeof nodeValue === 'string' && (req.requiredSet ?? []).includes(nodeValue)
      return { met, surplus: 0 }
    }
  }
}

export function computeConfidence(ageS: number, tHalf = DEFAULT_T_HALF, floor = DEFAULT_CONFIDENCE_FLOOR): number {
  if (ageS <= 0) return 1
  const raw = Math.pow(0.5, ageS / tHalf)
  return raw < floor ? 0 : raw
}

export function checkEligibility(c: { dimensions: Record<string, DimValue | string[]> }, required: Record<string, TaskRequirement>): boolean {
  for (const [d, req] of Object.entries(required)) {
    const v = c.dimensions[d]
    if (v === undefined || v === null) return false
    if (!compare(v, req).met) return false
  }
  return true
}

export function computeMatchQuality(
  c: CapabilityState,
  preferred: Record<string, TaskRequirement>,
  wSat = DEFAULT_W_SAT,
  wHead = DEFAULT_W_HEAD,
  surplusCap = DEFAULT_SURPLUS_CAP,
): number {
  const prefs = Object.entries(preferred)
  if (prefs.length === 0) return 1
  let total = 0
  for (const [d, pref] of prefs) {
    const v = c.dimensions[d]
    let score = 0
    if (v !== undefined) {
      const r = compare(v, pref)
      if (pref.dimType === 'BOOLEAN' || pref.dimType === 'CATEGORICAL') {
        score = r.met ? 1 : 0
      } else {
        const sat = r.met ? 1 : 0
        const th = pref.threshold ?? 0
        const headroom = th === 0 ? 0 : Math.min(r.surplus / th, surplusCap)
        score = wSat * sat + wHead * headroom
      }
    }
    total += score
  }
  return Math.max(0, Math.min(1, total / prefs.length))
}

export function computeFullMatch(
  c: CapabilityState,
  required: Record<string, TaskRequirement>,
  preferred: Record<string, TaskRequirement>,
  ageS = 0,
): MatchResult {
  const confidence = computeConfidence(ageS)
  if (confidence === 0) {
    return {
      eligible: false, quality: 0, confidence: 0, weightedQuality: 0, dimensionDetails: {},
      unmetRequired: Object.keys(required), missingDimensions: Object.keys(required),
    }
  }
  const eligible = checkEligibility(c, required)
  const details: Record<string, DimensionResult> = {}
  const unmet: string[] = []
  const missing: string[] = []
  const all = [...new Set([...Object.keys(required), ...Object.keys(preferred)])]
  for (const d of all) {
    const isReq = d in required
    const spec = (isReq ? required[d] : preferred[d]) as TaskRequirement
    const v = c.dimensions[d]
    if (v === undefined) {
      missing.push(d)
      details[d] = { dimension: d, dimType: spec.dimType, required: isReq, met: false, surplus: 0, nodeValue: null, taskValue: spec }
      if (isReq) unmet.push(d)
    } else {
      const r = compare(v, spec)
      details[d] = { dimension: d, dimType: spec.dimType, required: isReq, met: r.met, surplus: r.surplus, nodeValue: v, taskValue: spec }
      if (isReq && !r.met) unmet.push(d)
    }
  }
  const quality = eligible ? computeMatchQuality(c, preferred) : 0
  return { eligible, quality, confidence, weightedQuality: quality * confidence, dimensionDetails: details, unmetRequired: unmet, missingDimensions: missing }
}
