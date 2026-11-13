/** Laboratory controller: transport, selection, experiment runner and saved runs. UI state only — no simulation logic. */
import { useSyncExternalStore } from 'react'
import { LocalDemoAdapter, type SimulationAdapter } from '../sim/adapter'
import type { PresetId } from '../sim/catalog'
import { experimentById, type ExperimentDef, type PhaseId } from '../sim/experiments'
import type { Command, FaultRecord, MetricSample, ReconciliationRecord, SimEvent, WorldSnapshot } from '../sim/types'

export type ViewId = 'mission' | 'consensus' | 'faults' | 'observatory' | 'architecture'
export const VIEW_IDS: ViewId[] = ['mission', 'consensus', 'faults', 'observatory', 'architecture']

export interface PhaseCapture {
  phase: PhaseId
  tick: number
  note: string
  utilityRatio: number
  activeNodes: number
  components: number
  agreement: number
  tasks: Array<{ code: string; status: string; tier: number; members: string[]; replicaId: string; live: boolean }>
}

export interface ExperimentRun {
  defId: string
  status: 'running' | 'paused' | 'done'
  applied: number[]
  memo: Record<string, string>
  phases: PhaseCapture[]
}

export interface RunSummary {
  ticks: number
  minUtility: number
  finalUtility: number
  meanResponseS: number | null
  peakPartitions: number
  conflicts: number
  meanConvergenceS: number | null
  messages: number
  diverged: number
}

export interface RunRecord {
  id: string
  label: string
  experimentId: string | null
  preset: PresetId
  seed: number
  samples: MetricSample[]
  events: SimEvent[]
  faults: FaultRecord[]
  reconciliations: ReconciliationRecord[]
  summary: RunSummary
}

export interface UiState {
  view: ViewId
  selectedNodeId: string | null
  playing: boolean
  speed: number
  experiment: ExperimentRun | null
  runs: RunRecord[]
}

const RUNS_KEY = 'hesk-lab.runs.v1'
const MAX_RUNS = 8
const mean = (xs: number[]): number | null => (xs.length ? xs.reduce((s, x) => s + x, 0) / xs.length : null)

export function summarise(s: Pick<WorldSnapshot, 'metrics' | 'faults' | 'reconciliations' | 'tickSeconds'>): RunSummary {
  const u = s.metrics.map((m) => m.utilityRatio)
  return {
    ticks: s.metrics.at(-1)?.tick ?? 0,
    minUtility: u.length ? Math.min(...u) : 0,
    finalUtility: u.at(-1) ?? 0,
    meanResponseS: mean(s.faults.filter((f) => f.respondedTick !== null).map((f) => ((f.respondedTick as number) - f.tick) * s.tickSeconds)),
    peakPartitions: Math.max(1, ...s.metrics.map((m) => m.components)),
    conflicts: s.reconciliations.reduce((n, r) => n + r.conflicts.length, 0),
    meanConvergenceS: mean(s.reconciliations.map((r) => r.ticksSinceChange * s.tickSeconds)),
    messages: s.metrics.reduce((n, m) => n + m.messages, 0),
    diverged: s.reconciliations.reduce((n, r) => n + r.divergedKeys.length, 0),
  }
}

function loadRuns(): RunRecord[] {
  try {
    const raw = localStorage.getItem(RUNS_KEY)
    return raw ? (JSON.parse(raw) as RunRecord[]) : []
  } catch {
    return []
  }
}

function viewFromHash(): ViewId {
  const h = (typeof location === 'undefined' ? '' : location.hash.replace(/^#\/?/, '')) as ViewId
  return VIEW_IDS.includes(h) ? h : 'mission'
}

export class Lab {
  readonly adapter: SimulationAdapter
  private ui: UiState
  private listeners = new Set<() => void>()
  private timer: ReturnType<typeof setInterval> | null = null

  constructor(adapter: SimulationAdapter = new LocalDemoAdapter('baseline', 7)) {
    this.adapter = adapter
    this.ui = { view: viewFromHash(), selectedNodeId: null, playing: false, speed: 2, experiment: null, runs: loadRuns() }
    if (typeof window !== 'undefined') window.addEventListener('hashchange', () => this.set({ view: viewFromHash() }))
  }

  getUi = (): UiState => this.ui
  subscribe = (l: () => void): (() => void) => {
    this.listeners.add(l)
    return () => this.listeners.delete(l)
  }
  private set(patch: Partial<UiState>): void {
    this.ui = { ...this.ui, ...patch }
    this.listeners.forEach((l) => l())
  }
  get world(): WorldSnapshot {
    return this.adapter.getSnapshot()
  }

  setView(view: ViewId): void {
    if (typeof location !== 'undefined') location.hash = `/${view}`
    this.set({ view })
  }
  select(id: string | null): void {
    this.set({ selectedNodeId: id })
  }

  // ─── transport ──────────────────────────────────────────────────────
  play(): void {
    if (this.ui.experiment?.status === 'done') return
    if (this.ui.experiment?.status === 'paused') this.set({ experiment: { ...this.ui.experiment, status: 'running' } })
    this.set({ playing: true })
    this.restartTimer()
  }
  pause(): void {
    if (this.timer) clearInterval(this.timer)
    this.timer = null
    const exp = this.ui.experiment
    this.set({ playing: false, experiment: exp?.status === 'running' ? { ...exp, status: 'paused' } : exp })
  }
  toggle(): void {
    if (this.ui.playing) this.pause()
    else this.play()
  }
  setSpeed(speed: number): void {
    this.set({ speed })
    if (this.ui.playing) this.restartTimer()
  }
  private restartTimer(): void {
    if (this.timer) clearInterval(this.timer)
    this.timer = setInterval(() => this.advance(), 1000 / this.ui.speed)
  }
  stepOnce(): void {
    if (this.ui.playing) this.pause()
    this.advance(true)
  }
  reset(preset: PresetId = this.world.preset, seed: number = this.world.seed): void {
    this.pause()
    this.set({ experiment: null, selectedNodeId: null })
    this.adapter.dispatch({ type: 'reset', preset, seed })
  }
  send(cmd: Command): void {
    this.adapter.dispatch(cmd)
    const sel = this.ui.selectedNodeId
    if (sel && !this.world.nodes.some((n) => n.id === sel)) this.set({ selectedNodeId: null })
  }

  private advance(manual = false): void {
    const exp = this.ui.experiment
    const def = exp ? experimentById(exp.defId) : undefined
    if (exp && def && exp.status !== 'done') {
      if (this.world.tick >= def.duration) {
        this.finishExperiment(def)
        return
      }
      this.adapter.dispatch({ type: 'step' })
      this.applyDueSteps(def)
      if (this.world.tick >= def.duration) this.finishExperiment(def)
      else if (manual) this.set({ experiment: { ...(this.ui.experiment as ExperimentRun), status: 'paused' } })
      return
    }
    this.adapter.dispatch({ type: 'step' })
  }

  // ─── experiments ────────────────────────────────────────────────────
  startExperiment(id: string): void {
    const def = experimentById(id)
    if (!def) return
    this.pause()
    this.adapter.dispatch({ type: 'reset', preset: def.preset, seed: def.seed })
    this.set({ selectedNodeId: null, experiment: { defId: id, status: 'running', applied: [], memo: {}, phases: [] } })
    this.applyDueSteps(def)
    this.play()
  }
  clearExperiment(): void {
    this.pause()
    this.set({ experiment: null })
  }

  private applyDueSteps(def: ExperimentDef): void {
    const exp = this.ui.experiment
    if (!exp) return
    const tick = this.world.tick
    const applied = [...exp.applied]
    const memo = { ...exp.memo }
    const phases = [...exp.phases]
    def.steps.forEach((step, i) => {
      if (step.at !== tick || applied.includes(i)) return
      applied.push(i)
      const cmd = step.command?.(this.world, memo)
      if (cmd) this.adapter.dispatch(cmd)
      const cap = this.capture(step.phase, step.note)
      const at = phases.findIndex((p) => p.phase === step.phase)
      if (at >= 0) phases[at] = cap
      else phases.push(cap)
    })
    this.set({ experiment: { ...exp, applied, memo, phases } })
  }

  private capture(phase: PhaseId, note: string): PhaseCapture {
    const w = this.world
    const m = w.metrics.at(-1)
    return {
      phase, tick: w.tick, note, utilityRatio: m?.utilityRatio ?? 0, activeNodes: m?.activeNodes ?? 0, components: m?.components ?? 1,
      agreement: m?.agreement ?? 1,
      tasks: w.replicas.flatMap((r) => r.tasks.map((t) => ({ code: t.code, status: t.status, tier: t.tier, members: t.members, replicaId: r.id, live: t.live }))),
    }
  }

  private finishExperiment(def: ExperimentDef): void {
    if (this.timer) clearInterval(this.timer)
    this.timer = null
    const exp = this.ui.experiment
    this.set({ playing: false, experiment: exp ? { ...exp, status: 'done' } : null })
    this.saveRun(`${String(def.index).padStart(2, '0')} ${def.title}`, def.id)
  }

  // ─── saved runs ─────────────────────────────────────────────────────
  saveRun(label: string, experimentId: string | null = null): void {
    const w = this.world
    const record: RunRecord = {
      id: `${Date.now().toString(36)}-${w.tick}`, label, experimentId, preset: w.preset, seed: w.seed, samples: w.metrics,
      events: w.events.filter((e) => e.source !== 'harness' || e.kind === 'PARTITION' || e.kind === 'DETECT'),
      faults: w.faults, reconciliations: w.reconciliations, summary: summarise(w),
    }
    const runs = [record, ...this.ui.runs.filter((r) => !(experimentId && r.experimentId === experimentId))].slice(0, MAX_RUNS)
    this.set({ runs })
    this.persist(runs)
  }
  deleteRun(id: string): void {
    const runs = this.ui.runs.filter((r) => r.id !== id)
    this.set({ runs })
    this.persist(runs)
  }
  private persist(runs: RunRecord[]): void {
    try {
      localStorage.setItem(RUNS_KEY, JSON.stringify(runs))
    } catch {
      /* storage unavailable: runs stay in memory for this session */
    }
  }
}

export const lab = new Lab()
export const useWorld = (): WorldSnapshot => useSyncExternalStore(lab.adapter.subscribe, lab.adapter.getSnapshot)
export const useUi = (): UiState => useSyncExternalStore(lab.subscribe, lab.getUi)
