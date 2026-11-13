import { NodeInspector } from '../components/NodeInspector'
import { SwarmView } from '../components/SwarmView'
import { EXPERIMENTS, experimentById, PHASES } from '../sim/experiments'
import { lab, useUi, useWorld, type PhaseCapture } from '../state/lab'
import { Btn, Caveat, cx, Icon, Meter, Panel, pct, Tag, TASK_STATUS_COLOR } from '../ui/kit'

function PhaseCard({ label, index, capture, active, pending }: { label: string; index: number; capture?: PhaseCapture; active: boolean; pending: boolean }) {
  return (
    <div className={cx('min-w-[170px] flex-1 border-l border-line p-2.5 first:border-l-0', active && 'bg-accent/[0.06]')}>
      <div className="flex items-center gap-1.5">
        <span className={cx('num flex h-[18px] w-[18px] items-center justify-center rounded-full border text-[9.5px]', capture ? 'border-accent text-accent' : 'border-line-2 text-ink-3')}>{index + 1}</span>
        <span className={cx('label', capture && '!text-ink')}>{label}</span>
        {capture && <span className="num ml-auto text-[10px] text-ink-3">T+{capture.tick * 5}s</span>}
      </div>
      {capture ? (
        <>
          <p className="mt-1.5 min-h-[30px] text-[11px] leading-snug text-ink-2">{capture.note}</p>
          <div className="mt-1.5 flex items-baseline gap-2">
            <span className="num text-[16px] leading-none font-medium">{pct(capture.utilityRatio)}</span>
            <span className="num text-[10px] text-ink-3">utility · {capture.activeNodes} nodes · {capture.components} part.</span>
          </div>
          <div className="mt-1.5 flex flex-wrap gap-1">
            {capture.tasks.map((t, i) => (
              <span key={i} className="num rounded-[2px] border px-1 text-[9.5px] leading-[15px]"
                title={`${t.code} on replica ${t.replicaId}: ${t.status}${t.members.length ? ` (${t.members.join(' + ')})` : ''}${t.live ? '' : ' — not physically running'}`}
                style={{ color: TASK_STATUS_COLOR[t.status], borderColor: `color-mix(in oklab, ${TASK_STATUS_COLOR[t.status]} 45%, transparent)`, borderStyle: t.live || t.status === 'ABANDONED' ? 'solid' : 'dashed' }}>
                {t.code}{t.status === 'ABANDONED' ? '×' : `·T${t.tier}`}
              </span>
            ))}
          </div>
        </>
      ) : (
        <p className="mt-1.5 text-[11px] text-ink-3">{pending ? 'Waiting…' : 'Not reached'}</p>
      )}
    </div>
  )
}

export function FaultLab() {
  const world = useWorld()
  const ui = useUi()
  const run = ui.experiment
  const def = run ? experimentById(run.defId) : undefined
  const selected = ui.selectedNodeId && world.nodes.some((n) => n.id === ui.selectedNodeId) ? ui.selectedNodeId : null
  const currentPhase = run?.phases.at(-1)?.phase
  const saved = def ? ui.runs.find((r) => r.experimentId === def.id) : undefined
  const faults = [...world.faults].reverse()

  return (
    <div className="grid gap-3 p-3 xl:grid-cols-[290px_minmax(0,1fr)_360px]">
      <Panel title="Experiments" meta="deterministic scripts" bodyClass="">
        <ul>
          {EXPERIMENTS.map((e) => {
            const active = def?.id === e.id
            const done = ui.runs.some((r) => r.experimentId === e.id)
            return (
              <li key={e.id} className={cx('border-b border-line/70 p-3', active && 'bg-accent/[0.06]')}>
                <div className="flex items-center gap-2">
                  <span className="num text-[10px] text-ink-3">{String(e.index).padStart(2, '0')}</span>
                  <span className="text-[12.5px] font-medium">{e.title}</span>
                  {done && <Tag color="var(--color-ok)" title="A run of this experiment is saved in the Performance Observatory">saved</Tag>}
                </div>
                <p className="mt-1 text-[11.5px] leading-snug text-ink-2">{e.question}</p>
                <div className="mt-2 flex items-center gap-2">
                  <Btn size="sm" tone={active ? 'default' : 'primary'} onClick={() => lab.startExperiment(e.id)}><Icon name={active ? 'reset' : 'play'} size={10} />{active ? 'Restart' : 'Run'}</Btn>
                  <span className="num text-[10px] text-ink-3">{e.preset} · seed {e.seed} · {e.duration * 5}s</span>
                </div>
              </li>
            )
          })}
        </ul>
      </Panel>

      <div className="flex min-w-0 flex-col gap-3">
        <Panel
          title={def ? `Experiment ${String(def.index).padStart(2, '0')} · ${def.title}` : 'Manual injection'} bodyClass="" className="h-[460px]"
          meta={def ? def.faultClass : 'use the map tools, or select a node for per-node faults'}
          actions={run && def && (
            <>
              {run.status !== 'done' && <Btn size="sm" tone="primary" onClick={() => lab.toggle()}><Icon name={ui.playing ? 'pause' : 'play'} size={10} />{ui.playing ? 'Pause' : run.applied.length > 0 && world.tick > 0 ? 'Resume' : 'Start'}</Btn>}
              <Btn size="sm" onClick={() => lab.startExperiment(def.id)}><Icon name="reset" size={10} />Reset</Btn>
              <Btn size="sm" tone="ghost" onClick={() => lab.clearExperiment()} title="Leave the experiment and keep the current swarm for free exploration">Exit</Btn>
            </>
          )}
        >
          <SwarmView world={world} selectedId={selected} onSelect={(id) => lab.select(id)} />
        </Panel>

        <section className="panel">
          <header className="flex h-8 items-center gap-3 border-b border-line px-3">
            <h2 className="label !text-ink-2">Experiment phases</h2>
            {run && def ? (
              <>
                <Tag color={run.status === 'done' ? 'var(--color-ok)' : run.status === 'running' ? 'var(--color-accent)' : 'var(--color-warn)'} solid>{run.status.toUpperCase()}</Tag>
                <div className="flex-1"><Meter value={Math.min(world.tick, def.duration)} max={def.duration} /></div>
                <span className="num text-[10.5px] text-ink-3">T+{Math.min(world.tick, def.duration) * 5}s / {def.duration * 5}s</span>
              </>
            ) : <span className="text-[11px] text-ink-3">Choose an experiment to record its five phases.</span>}
          </header>
          <div className="flex overflow-x-auto">
            {PHASES.map((p, i) => (
              <PhaseCard key={p.id} label={p.label} index={i} capture={run?.phases.find((c) => c.phase === p.id)} active={currentPhase === p.id && run?.status !== 'done'} pending={!!run && run.status !== 'done'} />
            ))}
          </div>
        </section>

        <Panel title="Injected faults" meta={`${faults.length} this run`} bodyClass="">
          {faults.length === 0 ? <p className="p-3 text-[12px] text-ink-3">Nothing injected yet.</p> : (
            <div className="max-h-[240px] overflow-auto">
              <table className="w-full border-collapse text-left">
                <thead className="sticky top-0 bg-bg-1"><tr className="label border-b border-line">
                  <th className="px-3 py-1.5 font-normal">At</th><th className="px-2 font-normal">Fault</th><th className="px-2 font-normal" title="Time until the affected replicas acted. Mostly the harness detection delay.">Response after</th><th className="px-3 text-right font-normal">Utility before → after</th>
                </tr></thead>
                <tbody>
                  {faults.map((f) => (
                    <tr key={f.id} className="border-b border-line/60">
                      <td className="num px-3 py-1 text-[11px] text-ink-3">T+{f.tick * world.tickSeconds}s</td>
                      <td className="px-2 text-[11.5px]">{f.label}</td>
                      <td className="num px-2 text-[11px] text-ink-2">{f.respondedTick === null ? 'pending' : `${(f.respondedTick - f.tick) * world.tickSeconds}s`}</td>
                      <td className="num px-3 text-right text-[11px]">{f.utilityBefore.toFixed(2)} → {f.utilityAfter === null ? '…' : f.utilityAfter.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </div>

      <div className="flex min-w-0 flex-col gap-3">
        {selected ? (
          <div className="panel h-[700px] overflow-hidden"><NodeInspector world={world} nodeId={selected} onClose={() => lab.select(null)} /></div>
        ) : def ? (
          <Panel title="Protocol">
            <div className="space-y-3">
              <div><div className="label mb-1">Question</div><p className="text-[12.5px] leading-snug">{def.question}</p></div>
              <div><div className="label mb-1">Kernel path exercised</div><p className="num text-[11px] leading-snug text-ink-2">{def.exercises}</p></div>
              <div>
                <div className="label mb-1">Schedule</div>
                <ol className="space-y-1">
                  {def.steps.map((s, i) => (
                    <li key={i} className={cx('grid grid-cols-[44px_1fr] gap-x-2 text-[11.5px] leading-snug', run?.applied.includes(i) ? 'text-ink' : 'text-ink-3')}>
                      <span className="num">T+{s.at * 5}s</span><span>{s.note}</span>
                    </li>
                  ))}
                </ol>
              </div>
              <Caveat tone="warn">{def.caveat}</Caveat>
              {saved && run?.status === 'done' && (
                <div className="border-t border-line pt-3">
                  <div className="label mb-1.5">Result of this run</div>
                  <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5">
                    {[
                      ['Lowest utility', pct(saved.summary.minUtility)], ['Final utility', pct(saved.summary.finalUtility)],
                      ['Mean response', saved.summary.meanResponseS === null ? '—' : `${saved.summary.meanResponseS.toFixed(1)} s`], ['Peak partitions', String(saved.summary.peakPartitions)],
                      ['Conflicts resolved', String(saved.summary.conflicts)], ['Modelled messages', String(saved.summary.messages)],
                    ].map(([k, v]) => (<div key={k}><dt className="label">{k}</dt><dd className="num text-[14px]">{v}</dd></div>))}
                  </dl>
                  <Btn className="mt-3" size="sm" onClick={() => lab.setView('observatory')}>Open in Performance Observatory</Btn>
                </div>
              )}
            </div>
          </Panel>
        ) : (
          <Panel title="How to use this laboratory">
            <div className="space-y-2.5 text-[12px] leading-snug text-ink-2">
              <p>Run one of the six scripted experiments, or inject faults by hand on the current swarm:</p>
              <ul className="space-y-1.5">
                <li><span className="text-ink">Node failure / recovery / removal</span> — select a node, then use the controls at the bottom of its inspector.</li>
                <li><span className="text-ink">Network partition</span> — <span className="num">Jam E | W</span> or <span className="num">N | S</span> on the map, or jam one node's radio.</li>
                <li><span className="text-ink">Communication latency</span> — the ×1 / ×2 / ×4 control on the map.</li>
                <li><span className="text-ink">New node joining</span> — pick an agent type and <span className="num">Add</span> or <span className="num">Place</span>.</li>
                <li><span className="text-ink">Capability degradation</span> — select a node, choose a dimension, <span className="num">Degrade −50%</span>.</li>
              </ul>
              <Caveat>Faults are applied to the simulated world. Replicas learn of silent failures only after {world.detectTicks} missed beacons ({world.detectTicks * world.tickSeconds}s); that delay is a harness setting, not a HESK measurement.</Caveat>
            </div>
          </Panel>
        )}
      </div>
    </div>
  )
}
