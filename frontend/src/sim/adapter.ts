/**
 * The boundary between the laboratory UI and whatever produces swarm state.
 *
 * The UI only ever sees `WorldSnapshot` and sends `Command`s. Today the single
 * implementation is `LocalDemoAdapter`, which runs the TypeScript port of the
 * kernel in the browser. HESK has no service API yet; when one exists, a remote
 * adapter implementing this interface can replace it without touching any view.
 */
import type { PresetId } from './catalog'
import { SimEngine } from './engine'
import type { Command, WorldSnapshot } from './types'

export interface AdapterInfo {
  kind: 'local-demo' | 'remote'
  label: string
  description: string
}

export interface SimulationAdapter {
  readonly info: AdapterInfo
  getSnapshot(): WorldSnapshot
  subscribe(listener: () => void): () => void
  dispatch(cmd: Command): void
}

export class LocalDemoAdapter implements SimulationAdapter {
  readonly info: AdapterInfo = {
    kind: 'local-demo',
    label: 'DEMONSTRATION MODE',
    description:
      'Deterministic in-browser simulation. Decisions come from a TypeScript port of the HESK kernel algorithms, ' +
      'checked against the Python package by parity tests. The world, links, timing and failure detection are a ' +
      'demonstration harness — HESK has no runtime, transport or backend API yet.',
  }
  private engine: SimEngine
  private listeners = new Set<() => void>()

  constructor(preset: PresetId = 'baseline', seed = 7) {
    this.engine = new SimEngine(preset, seed)
  }
  getSnapshot = (): WorldSnapshot => this.engine.snapshot
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }
  dispatch(cmd: Command): void {
    this.engine.dispatch(cmd)
    this.listeners.forEach((l) => l())
  }
}
