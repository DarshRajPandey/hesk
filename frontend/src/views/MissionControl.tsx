import { AnimatePresence, motion } from 'motion/react'
import { EventStream } from '../components/EventStream'
import { NodeInspector } from '../components/NodeInspector'
import { SwarmView } from '../components/SwarmView'
import { TaskBoard } from '../components/TaskBoard'
import { experimentById } from '../sim/experiments'
import { lab, useUi, useWorld } from '../state/lab'
import { Panel, pct, seriesColor, Stat } from '../ui/kit'

export function MissionControl() {
  const world = useWorld()
  const ui = useUi()
  const m = world.metrics.at(-1)
  const total = world.nodes.length
  const active = world.nodes.filter((n) => n.alive).length
  const largest = Math.max(0, ...world.replicas.map((r) => r.members.length))
  const lastRecon = world.reconciliations.at(-1)
  const partitions = world.replicas.length
  const exp = ui.experiment ? experimentById(ui.experiment.defId) : undefined
  const upLinks = world.links.filter((l) => l.up).length
  const selected = ui.selectedNodeId && world.nodes.some((n) => n.id === ui.selectedNodeId) ? ui.selectedNodeId : null

  const consensus = world.pendingDetection !== null
    ? { v: 'PENDING', tone: 'warn' as const, sub: `change undetected · ${world.pendingDetection} beacon(s)` }
    : partitions > 1
      ? { v: 'DIVERGED', tone: 'crit' as const, sub: `${partitions} replicas · ${pct(m?.agreement ?? 0)} of task claims agree` }
      : { v: 'CONVERGED', tone: 'ok' as const, sub: lastRecon ? `last merge T+${lastRecon.tick * world.tickSeconds}s · ${lastRecon.conflicts.length} conflicts` : 'single replica since boot' }

  return (
    <div className="flex min-h-full flex-col gap-3 p-3 xl:h-full">
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-1 px-1">
        <p className="text-[15px] font-medium tracking-tight">The swarm becomes the machine.</p>
        <p className="max-w-3xl text-[11.5px] leading-snug text-ink-3">
          Each node is an independent sensing and compute unit. HESK allocates mission tasks by capability, re-plans when nodes or links are lost,
          and reconciles state when partitions rejoin. Select a node to inspect it; inject faults to watch the response.
        </p>
      </div>

      <div className="panel grid shrink-0 grid-cols-2 sm:grid-cols-3 xl:grid-cols-6">
        <Stat label="Swarm size" value={total} unit="nodes" sub={`${world.taskIds.length} mission tasks`} />
        <Stat label="Connected" value={largest} unit={`/ ${active}`} sub={partitions > 1 ? `${partitions} partitions` : 'one component'} tone={partitions > 1 ? 'warn' : undefined} />
        <Stat label="Failed" value={total - active} unit="nodes" tone={total - active > 0 ? 'crit' : undefined} sub={`${world.nodes.filter((n) => n.health === 'DEGRADED' || n.health === 'DEPLETED').length} impaired`} />
        <Stat label="Network health" value={pct(m?.connectivity ?? 1)} sub={`${upLinks} links up · latency ×${world.latencyFactor}`} tone={(m?.connectivity ?? 1) < 1 ? 'warn' : undefined} />
        <Stat label="State agreement" value={consensus.v} tone={consensus.tone} sub={consensus.sub} />
        <Stat label="Mission utility" value={pct(m?.utilityRatio ?? 0)} sub={`Σ π·q = ${(m?.utility ?? 0).toFixed(2)} of ${(m?.maxUtility ?? 0).toFixed(2)}`} tone={(m?.utilityRatio ?? 1) < 0.999 ? 'warn' : 'ok'} />
      </div>

      <div className="grid min-h-0 flex-1 gap-3 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="flex min-h-0 flex-col gap-3">
          <Panel
            title="Swarm topology" bodyClass="relative" className="min-h-[420px] flex-1"
            meta={`${active} live · ${upLinks} links · radio range 360 m`}
            actions={<>
              {partitions > 1 && world.replicas.map((r, i) => (
                <span key={r.id} className="num flex items-center gap-1 text-[10px]" style={{ color: seriesColor(i) }}><span className="h-1.5 w-1.5 rounded-full" style={{ background: seriesColor(i) }} />{r.id}</span>
              ))}
              <span className="num text-[10px] text-ink-3">{exp ? `EXPERIMENT ${String(exp.index).padStart(2, '0')} · ${exp.title.toUpperCase()}` : 'FREE RUN'}</span>
            </>}
          >
            <SwarmView world={world} selectedId={selected} onSelect={(id) => lab.select(id)} />
          </Panel>
          <Panel title="System events" meta={`${world.events.length} recorded`} bodyClass="" className="h-[230px] shrink-0">
            <EventStream events={world.events} tickSeconds={world.tickSeconds} onSelectNode={(id) => lab.select(id)} />
          </Panel>
        </div>

        <div className="flex min-h-0 flex-col gap-3">
          <AnimatePresence mode="wait" initial={false}>
            {selected ? (
              <motion.div key="inspector" className="panel min-h-[480px] flex-1 overflow-hidden xl:min-h-0"
                initial={{ opacity: 0, x: 8 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 8 }} transition={{ duration: 0.14 }}>
                <NodeInspector world={world} nodeId={selected} onClose={() => lab.select(null)} />
              </motion.div>
            ) : (
              <motion.div key="tasks" className="flex min-h-0 flex-1 flex-col gap-3" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.12 }}>
                <Panel title="Mission tasks" meta={partitions > 1 ? 'as each replica believes them' : `replica ${world.replicas[0]?.id ?? '—'}`} bodyClass="" className="min-h-[260px] flex-1">
                  <TaskBoard world={world} onSelect={(id) => lab.select(id)} />
                </Panel>
                <Panel title="Topology" className="shrink-0">
                  <div className="space-y-2">
                    {world.replicas.map((r, i) => (
                      <div key={r.id}>
                        <div className="flex items-center justify-between">
                          <span className="num text-[11.5px]" style={{ color: partitions > 1 ? seriesColor(i) : undefined }}>Replica {r.id}</span>
                          <span className="num text-[10.5px] text-ink-3">Lamport {r.lamport} · {r.eventCount} events · U {r.utility.toFixed(2)}</span>
                        </div>
                        <div className="mt-1 flex flex-wrap gap-x-2 gap-y-0.5">
                          {r.members.map((id) => (
                            <button key={id} type="button" className="num text-[10.5px] text-ink-2 hover:text-accent hover:underline" onClick={() => lab.select(id)}>{id}</button>
                          ))}
                        </div>
                      </div>
                    ))}
                    {world.replicas.length === 0 && <p className="text-[12px] text-ink-3">No live nodes.</p>}
                    <p className="border-t border-line pt-2 text-[10.5px] leading-snug text-ink-3">
                      A replica is the coordination ledger of one connected component. The harness keeps one per component; HESK specifies one per node.
                    </p>
                  </div>
                </Panel>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </div>
  )
}
