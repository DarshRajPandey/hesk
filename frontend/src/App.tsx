import { MotionConfig } from 'motion/react'
import { Component, useEffect, useState, type ErrorInfo, type ReactNode } from 'react'
import { PRESET_IDS, PRESETS, type PresetId } from './sim/catalog'
import { lab, useUi, useWorld, type ViewId } from './state/lab'
import { Btn, cx, Icon, Seg } from './ui/kit'
import { Architecture } from './views/Architecture'
import { ConsensusLab } from './views/ConsensusLab'
import { FaultLab } from './views/FaultLab'
import { MissionControl } from './views/MissionControl'
import { Observatory } from './views/Observatory'

const NAV: Array<{ id: ViewId; label: string; hint: string }> = [
  { id: 'mission', label: 'Mission Control', hint: 'Live swarm, topology and events' },
  { id: 'consensus', label: 'Consensus Laboratory', hint: 'Auctions, replica state and reconciliation' },
  { id: 'faults', label: 'Fault Injection', hint: 'Scripted and manual experiments' },
  { id: 'observatory', label: 'Performance Observatory', hint: 'Metrics, timelines and run comparison' },
  { id: 'architecture', label: 'Architecture Explorer', hint: 'Components and implementation status' },
]

class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null }
  static getDerivedStateFromError(error: Error) {
    return { error }
  }
  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[hesk-lab] view crashed', error, info.componentStack)
  }
  render() {
    if (!this.state.error) return this.props.children
    return (
      <div role="alert" className="m-6 max-w-xl rounded-[3px] border border-crit/50 bg-crit/5 p-4">
        <div className="label !text-crit">View error</div>
        <p className="mt-2 text-[13px]">This view failed to render. The simulation state is intact.</p>
        <pre className="num mt-2 overflow-auto text-[11px] whitespace-pre-wrap text-ink-2">{this.state.error.message}</pre>
        <div className="mt-3 flex gap-2">
          <Btn onClick={() => this.setState({ error: null })}>Retry view</Btn>
          <Btn tone="danger" onClick={() => { lab.reset(); this.setState({ error: null }) }}>Reset simulation</Btn>
        </div>
      </div>
    )
  }
}

function Transport() {
  const ui = useUi()
  const world = useWorld()
  const [seed, setSeed] = useState(String(world.seed))
  useEffect(() => setSeed(String(world.seed)), [world.seed])
  const exp = ui.experiment
  const applySeed = () => {
    const n = Number.parseInt(seed, 10)
    if (Number.isFinite(n) && n !== world.seed) lab.reset(world.preset, n)
    else setSeed(String(world.seed))
  }
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
      <div className="flex items-center gap-1">
        <Btn tone="primary" onClick={() => lab.toggle()} disabled={exp?.status === 'done'} aria-label={ui.playing ? 'Pause simulation' : 'Run simulation'} className="w-[74px]">
          <Icon name={ui.playing ? 'pause' : 'play'} size={12} />{ui.playing ? 'Pause' : 'Run'}
        </Btn>
        <Btn onClick={() => lab.stepOnce()} disabled={exp?.status === 'done'} aria-label="Advance one tick" title="Advance one tick (5 s of simulated time)"><Icon name="step" size={12} />Step</Btn>
        <Btn onClick={() => lab.reset()} aria-label="Reset simulation" title="Reset to the initial state of this scenario and seed"><Icon name="reset" size={12} />Reset</Btn>
      </div>
      <Seg label="Simulation speed" value={ui.speed} onChange={(s) => lab.setSpeed(s)} options={[{ value: 1, label: '1×' }, { value: 2, label: '2×' }, { value: 5, label: '5×' }]} />
      <label className="flex items-center gap-1.5">
        <span className="label">Scenario</span>
        <select className="field" value={world.preset} disabled={!!exp} onChange={(e) => lab.reset(e.target.value as PresetId, world.seed)}>
          {PRESET_IDS.map((p) => <option key={p} value={p}>{PRESETS[p].label}</option>)}
        </select>
      </label>
      <label className="flex items-center gap-1.5">
        <span className="label">Seed</span>
        <input className="field num w-14" inputMode="numeric" value={seed} disabled={!!exp} onChange={(e) => setSeed(e.target.value.replace(/\D/g, '').slice(0, 6))}
          onBlur={applySeed} onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }} aria-label="Random seed" />
      </label>
      <div className="num ml-auto flex items-baseline gap-2 text-[12px]">
        <span className="label">Sim time</span>
        <span className="text-[15px] font-medium text-ink">T+{String(Math.floor(world.timeS / 60)).padStart(2, '0')}:{String(world.timeS % 60).padStart(2, '0')}</span>
        <span className="text-ink-3">tick {world.tick}</span>
      </div>
    </div>
  )
}

export function App() {
  const ui = useUi()
  const [aboutOpen, setAboutOpen] = useState(false)
  const current = NAV.find((n) => n.id === ui.view) ?? NAV[0]!
  const info = lab.adapter.info

  return (
    <MotionConfig reducedMotion="user">
      <div className="flex h-full flex-col lg:flex-row">
        <nav aria-label="Laboratory sections" className="flex shrink-0 border-b border-line bg-bg-1 lg:w-[236px] lg:flex-col lg:border-r lg:border-b-0">
          <div className="hidden items-center gap-2.5 border-b border-line px-3.5 py-3.5 lg:flex">
            <svg width="26" height="26" viewBox="0 0 32 32" aria-hidden>
              <path d="M16 3.5l10.8 6.25v12.5L16 28.5 5.2 22.25V9.75z" fill="none" stroke="var(--color-accent)" strokeWidth="1.4" />
              <path d="M16 3.5v8M26.8 22.25l-7-4M5.2 22.25l7-4" stroke="var(--color-accent)" strokeWidth="1" opacity=".55" />
              <circle cx="16" cy="16" r="3" fill="var(--color-accent)" />
            </svg>
            <div>
              <div className="num text-[15px] leading-none font-medium tracking-[0.18em]">HESK</div>
              <div className="mt-1 text-[10.5px] leading-tight text-ink-3">Swarm Intelligence Laboratory</div>
            </div>
          </div>
          <ul className="flex min-w-0 flex-1 overflow-x-auto lg:flex-col lg:overflow-visible lg:py-2">
            {NAV.map((n, i) => (
              <li key={n.id} className="shrink-0">
                <button type="button" onClick={() => lab.setView(n.id)} aria-current={ui.view === n.id ? 'page' : undefined} title={n.hint}
                  className={cx('flex w-full items-center gap-2.5 border-b-2 px-3.5 py-2.5 text-left text-[12.5px] transition-colors lg:border-b-0 lg:border-l-2 lg:py-2',
                    ui.view === n.id ? 'border-accent bg-accent/[0.07] text-ink' : 'border-transparent text-ink-2 hover:bg-bg-2 hover:text-ink')}>
                  <span className={ui.view === n.id ? 'text-accent' : 'text-ink-3'}><Icon name={n.id} size={15} /></span>
                  <span className="num hidden text-[10px] text-ink-3 lg:inline">0{i + 1}</span>
                  <span className="whitespace-nowrap">{n.label}</span>
                </button>
              </li>
            ))}
          </ul>
          <div className="hidden border-t border-line p-3 lg:block">
            <button type="button" onClick={() => setAboutOpen((o) => !o)} aria-expanded={aboutOpen} className="w-full rounded-[2px] border border-warn/40 bg-warn/[0.06] px-2 py-1.5 text-left hover:bg-warn/10">
              <div className="num flex items-center gap-1.5 text-[10px] tracking-[0.08em] text-warn"><span className="h-1.5 w-1.5 rounded-full bg-warn" />{info.label}</div>
              <div className="mt-1 text-[10.5px] leading-snug text-ink-2">Simulated swarm · ported kernel logic · no live backend</div>
            </button>
            {aboutOpen && <p className="mt-2 text-[10.5px] leading-snug text-ink-3">{info.description}</p>}
          </div>
        </nav>

        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          <header className="shrink-0 border-b border-line bg-bg-1 px-4 py-2">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
              <div className="min-w-[180px]">
                <h1 className="text-[14px] leading-tight font-semibold">{current.label}</h1>
                <p className="text-[11px] text-ink-3">{current.hint}</p>
              </div>
              <div className="w-full min-w-0 sm:w-auto sm:flex-1"><Transport /></div>
            </div>
            <div className="num mt-1.5 flex items-center gap-1.5 text-[10px] text-warn lg:hidden"><span className="h-1.5 w-1.5 rounded-full bg-warn" />{info.label} · simulated swarm, no live backend</div>
          </header>
          <main className="min-h-0 min-w-0 flex-1 overflow-auto">
            <ErrorBoundary key={ui.view}>
              {ui.view === 'mission' && <MissionControl />}
              {ui.view === 'consensus' && <ConsensusLab />}
              {ui.view === 'faults' && <FaultLab />}
              {ui.view === 'observatory' && <Observatory />}
              {ui.view === 'architecture' && <Architecture />}
            </ErrorBoundary>
          </main>
        </div>
      </div>
    </MotionConfig>
  )
}
