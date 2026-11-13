import { useState } from 'react'
import { SwarmView } from '../components/SwarmView'
import { taskById } from '../sim/catalog'
import type { AuctionRound, ReconciliationRecord, WorldSnapshot } from '../sim/types'
import { lab, useUi, useWorld } from '../state/lab'
import { Caveat, cx, Empty, Meter, Panel, pct, seriesColor, Tag } from '../ui/kit'

/** Ledger keys × replicas. A row is "agreed" when every replica holding the key shows the same value. */
function ReplicaMatrix({ world }: { world: WorldSnapshot }) {
  const [showAll, setShowAll] = useState(false)
  const replicas = world.replicas
  const keys = [...new Set(replicas.flatMap((r) => r.ledger.map((e) => e.key)))].sort((a, b) => {
    const rank = (k: string) => (k.startsWith('task_owner.') ? 0 : k.startsWith('node.') ? 2 : 1)
    return rank(a) - rank(b) || (a < b ? -1 : 1)
  })
  const rows = keys.map((key) => {
    const cells = replicas.map((r) => r.ledger.find((e) => e.key === key))
    // Progress and counters advance independently per replica; agreement is about who owns what.
    const norm = (d: string | undefined) => (key.startsWith('task_owner.') ? d?.replace(/ · \d+%$/, '') : key === 'beacons' ? 'counter' : d)
    const agreed = new Set(cells.map((c) => norm(c?.digest))).size === 1
    return { key, cells, agreed }
  })
  const agreedCount = rows.filter((r) => r.agreed).length
  const visible = showAll ? rows : rows.filter((r) => !r.key.startsWith('node.') || !r.agreed)
  const hidden = rows.length - visible.length

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 border-b border-line px-3 py-2">
        <div className="flex items-baseline justify-between">
          <span className="label">Keys in agreement</span>
          <span className="num text-[13px]" style={{ color: agreedCount === rows.length ? 'var(--color-ok)' : 'var(--color-warn)' }}>{agreedCount} / {rows.length}</span>
        </div>
        <div className="mt-1.5"><Meter value={agreedCount} max={Math.max(1, rows.length)} color={agreedCount === rows.length ? 'var(--color-ok)' : 'var(--color-warn)'} /></div>
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-full border-collapse text-left">
          <thead className="sticky top-0 z-10 bg-bg-1">
            <tr className="border-b border-line align-bottom">
              <th className="label px-3 py-1.5 font-normal">Ledger key</th>
              {replicas.map((r, i) => (
                <th key={r.id} className="px-2 py-1.5 font-normal">
                  <div className="num text-[11px]" style={{ color: replicas.length > 1 ? seriesColor(i) : 'var(--color-ink)' }}>{r.id}</div>
                  <div className="num text-[9.5px] text-ink-3" title={`Version vector ${JSON.stringify(r.versionVector)}`}>L{r.lamport} · seq {r.seq} · {r.members.length}n</div>
                </th>
              ))}
              <th className="w-6" />
            </tr>
          </thead>
          <tbody>
            {visible.map((row) => (
              <tr key={row.key} className={cx('border-b border-line/60', !row.agreed && 'bg-warn/[0.05]')}>
                <td className="px-3 py-1">
                  <div className="num text-[11px] text-ink">{row.key}</div>
                  <div className="num text-[9px] text-ink-3">{row.cells.find((c) => c)?.type}</div>
                </td>
                {row.cells.map((c, i) => (
                  <td key={replicas[i]!.id} className="num px-2 py-1 text-[11px]" style={{ color: c ? (row.agreed ? 'var(--color-ink-2)' : 'var(--color-ink)') : 'var(--color-ink-3)' }}>
                    {c ? c.digest : '∅'}
                  </td>
                ))}
                <td className="pr-2 text-right"><span className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: row.agreed ? 'var(--color-ok)' : 'var(--color-warn)' }} title={row.agreed ? 'Agreed' : 'Replicas differ'} /></td>
              </tr>
            ))}
          </tbody>
        </table>
        {replicas.length === 0 && <Empty>No live replica.</Empty>}
      </div>
      <button type="button" onClick={() => setShowAll((s) => !s)} className="num shrink-0 border-t border-line px-3 py-1.5 text-left text-[10.5px] text-ink-3 hover:text-ink">
        {showAll ? 'Hide agreed node-status keys' : `Show ${hidden} agreed node-status key${hidden === 1 ? '' : 's'}`}
      </button>
    </div>
  )
}

function AuctionDetail({ round }: { round: AuctionRound }) {
  const def = taskById(round.taskId)
  const tier = def.tiers[round.tier]
  const maxCost = Math.max(0.001, ...round.bids.map((b) => b.cost))
  return (
    <div className="space-y-3 p-3">
      <div>
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="num text-[13px] font-medium">{def.code} · tier {round.tier}</span>
          <Tag color={round.outcome === 'UNFILLED' ? 'var(--color-crit)' : round.outcome === 'COALITION' ? 'var(--color-violet)' : 'var(--color-ok)'} solid>{round.outcome}</Tag>
          <span className="num text-[10.5px] text-ink-3">round #{round.id} · T+{round.tick * 5}s · replica {round.replicaId}</span>
        </div>
        <div className="mt-1 text-[11.5px] text-ink-2">{tier?.label} — requires {Object.entries(tier?.required ?? {}).map(([d, r]) => `${d}${r.threshold !== undefined ? ` ≥ ${r.threshold}` : ''}`).join(', ')}</div>
      </div>
      <div>
        <div className="label mb-1">Bids · {round.bids.length} of {round.participants} free nodes eligible</div>
        {round.bids.length === 0 ? <p className="text-[11.5px] text-ink-3">No single node met every required dimension.</p> : (
          <table className="w-full border-collapse">
            <thead><tr className="label text-left"><th className="py-1 font-normal">Node</th><th className="font-normal">System cost</th><th className="text-right font-normal">Quality</th><th className="text-right font-normal">Energy</th><th className="text-right font-normal" title="Scarcity penalty: rare capabilities the node holds that this task would waste">Scarcity</th></tr></thead>
            <tbody>
              {round.bids.map((b) => (
                <tr key={b.nodeId} className="border-t border-line/60">
                  <td className="py-1">
                    <button type="button" className={cx('num text-[11.5px] hover:underline', b.nodeId === round.winner ? 'text-ok' : 'text-ink')} onClick={() => lab.select(b.nodeId)}>{b.nodeId}</button>
                    {b.nodeId === round.winner && <span className="num ml-1 text-[9px] text-ok">AWARDED</span>}
                    {b.nodeId === round.runnerUp && <span className="num ml-1 text-[9px] text-ink-3">RUNNER-UP</span>}
                  </td>
                  <td className="w-[38%]">
                    <div className="flex items-center gap-2"><Meter value={b.cost} max={maxCost} color={b.nodeId === round.winner ? 'var(--color-ok)' : 'var(--color-ink-3)'} /><span className="num w-10 text-right text-[11px]">{b.cost.toFixed(3)}</span></div>
                  </td>
                  <td className="num text-right text-[11px] text-ink-2">{b.quality.toFixed(2)}</td>
                  <td className="num text-right text-[11px] text-ink-2">{Math.round(b.energy * 100)}%</td>
                  <td className="num text-right text-[11px]" style={{ color: b.scarcityPenalty > 0 ? 'var(--color-violet)' : 'var(--color-ink-3)' }}>{b.scarcityPenalty.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {round.coalition && <div><div className="label mb-1">Coalition formed · Algorithm 005</div><p className="num text-[11.5px] text-violet">{round.coalition.join(' + ')}</p></div>}
      {round.coalitionNote && <div><div className="label mb-1">Coalition attempt</div><p className="text-[11.5px] text-ink-2">{round.coalitionNote}</p></div>}
      {round.ineligible.length > 0 && (
        <div>
          <div className="label mb-1">Did not bid · {round.ineligible.length}</div>
          <ul className="grid grid-cols-1 gap-x-4 sm:grid-cols-2">
            {round.ineligible.map((n) => (
              <li key={n.nodeId} className="num flex justify-between gap-2 border-t border-line/60 py-0.5 text-[10.5px]"><span className="text-ink-2">{n.nodeId}</span><span className="truncate text-ink-3">lacks {n.unmet.join(', ')}</span></li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function ReconDetail({ r, tickSeconds }: { r: ReconciliationRecord; tickSeconds: number }) {
  const ownership = r.conflicts.filter((c) => c.type === 'EXCLUSIVE_OWNERSHIP')
  const other = r.conflicts.filter((c) => c.type !== 'EXCLUSIVE_OWNERSHIP')
  const steps: Array<{ t: string; d: string }> = [
    { t: 'Reconnection detected', d: `${r.ticksSinceChange * tickSeconds}s after the link came back (harness detection delay)` },
    { t: 'Unseen events exchanged', d: `${r.eventsToSurvivor} → ${r.survivor} · ${r.eventsToAbsorbed} → ${r.absorbed} (filtered by version vector)` },
    { t: 'Convergent types merged', d: `SET_LIKE union, COUNTER max — ${r.mergedForward} entries changed on ${r.survivor}, ${r.mergedReverse} on ${r.absorbed}` },
    { t: 'Conflicts detected', d: `${r.conflicts.length} keys written on both sides with different values` },
    { t: 'Conflicts resolved', d: `${ownership.length} dual ownership (progress → quality → time → id) · ${other.length} observations (recency with drift guard)` },
    { t: 'Unknown keys transferred', d: `${r.transferred} entries one side had never seen` },
  ]
  return (
    <div className="space-y-3 p-3">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="num text-[13px] font-medium">{r.absorbed} → {r.survivor}</span>
        <Tag color={r.converged ? 'var(--color-ok)' : 'var(--color-warn)'} solid>{r.converged ? 'BOTH SIDES CONVERGED' : `${r.divergedKeys.length} KEYS DIFFER`}</Tag>
        <span className="num text-[10.5px] text-ink-3">T+{r.tick * tickSeconds}s · {r.wallMs.toFixed(1)} ms in this browser</span>
      </div>
      <ol className="space-y-1.5">
        {steps.map((s, i) => (
          <li key={s.t} className="grid grid-cols-[18px_1fr] gap-x-2">
            <span className="num mt-px flex h-[18px] w-[18px] items-center justify-center rounded-full border border-line-2 text-[9.5px] text-ink-2">{i + 1}</span>
            <div><div className="text-[12px] text-ink">{s.t}</div><div className="text-[11px] leading-snug text-ink-3">{s.d}</div></div>
          </li>
        ))}
        <li className="grid grid-cols-[18px_1fr] gap-x-2">
          <span className="num mt-px flex h-[18px] w-[18px] items-center justify-center rounded-full border text-[9.5px]" style={{ borderColor: r.converged ? 'var(--color-ok)' : 'var(--color-warn)', color: r.converged ? 'var(--color-ok)' : 'var(--color-warn)' }}>7</span>
          <div>
            <div className="text-[12px] text-ink">Convergence check</div>
            <div className="text-[11px] leading-snug text-ink-3">
              The algorithm was run from both sides and the resulting ledgers compared.{' '}
              {r.converged ? 'Every shared key holds the same value.' : `Differing keys: ${r.divergedKeys.join(', ')}.`}
            </div>
          </div>
        </li>
      </ol>
      {ownership.length > 0 && (
        <div>
          <div className="label mb-1">Dual-ownership resolutions</div>
          <table className="w-full border-collapse">
            <thead><tr className="label text-left"><th className="py-1 font-normal">Task</th><th className="font-normal">{r.survivor} claimed</th><th className="font-normal">{r.absorbed} claimed</th><th className="font-normal">Kept</th></tr></thead>
            <tbody>
              {ownership.map((c) => (
                <tr key={c.key} className="border-t border-line/60 align-top">
                  <td className="num py-1 text-[11px] text-ink">{taskById(c.key.replace('task_owner.', '')).code}</td>
                  <td className={cx('num text-[11px]', c.winner === r.survivor ? 'text-ink' : 'text-ink-3 line-through')}>{c.local}</td>
                  <td className={cx('num text-[11px]', c.winner === r.absorbed ? 'text-ink' : 'text-ink-3 line-through')}>{c.remote}</td>
                  <td className="text-[10.5px] leading-snug text-ink-2">{c.reason}{c.sideEffects.length > 0 && <div className="num text-[9.5px] text-ink-3">{c.sideEffects.join(' · ')}</div>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export function ConsensusLab() {
  const world = useWorld()
  const ui = useUi()
  const [auctionId, setAuctionId] = useState<number | null>(null)
  const [reconId, setReconId] = useState<number | null>(null)
  const auctions = [...world.auctions].reverse()
  const recons = [...world.reconciliations].reverse()
  const auction = auctions.find((a) => a.id === auctionId) ?? auctions[0]
  const recon = recons.find((r) => r.id === reconId) ?? recons[0]
  const m = world.metrics.at(-1)

  return (
    <div className="flex flex-col gap-3 p-3">
      <div className="panel grid gap-x-6 gap-y-2 p-3 lg:grid-cols-[1fr_1fr]">
        <div>
          <h2 className="text-[13px] font-semibold">HESK does not vote.</h2>
          <p className="mt-1 text-[12px] leading-snug text-ink-2">
            Despite the name, the kernel contains no quorum protocol, leader election or voting rounds. Agreement is reached two ways, and this laboratory shows both:
            an <span className="text-ink">auction</span> awards each task to the lowest-cost eligible node (Algorithms 003–005), and replicas that diverged during a partition are brought back
            together by <span className="text-ink">semantic reconciliation</span> of their ledgers (Algorithms 007–008).
          </p>
        </div>
        <div className="space-y-1.5">
          <Caveat>Rounds, participants and outcomes below are computed by the ported kernel functions on the simulated swarm. They are not results from a deployed HESK system.</Caveat>
          <Caveat tone="warn">No vote counts, quorum sizes or Byzantine tolerance figures are shown because HESK defines none.</Caveat>
        </div>
      </div>

      <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <Panel title="Swarm" meta={`${world.replicas.length} replica${world.replicas.length === 1 ? '' : 's'} · ownership agreement ${pct(m?.agreement ?? 1)} · ${m?.duplicated ?? 0} task(s) duplicated`} bodyClass="" className="h-[440px]">
          <SwarmView world={world} selectedId={ui.selectedNodeId} onSelect={(id) => lab.select(id)} />
        </Panel>
        <Panel title="Replica state · Algorithm 007" meta="ledger keys as each replica holds them" bodyClass="" className="h-[440px]">
          <ReplicaMatrix world={world} />
        </Panel>
      </div>

      <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <Panel title="Allocation rounds · Algorithms 003–005" meta={`${auctions.length} recorded`} bodyClass="" className="min-h-[420px]">
          {auctions.length === 0 ? <Empty>No auction has run.</Empty> : (
            <div className="grid h-full min-h-0 grid-cols-[150px_1fr]">
              <ol className="max-h-[520px] overflow-auto border-r border-line">
                {auctions.map((a) => (
                  <li key={a.id}>
                    <button type="button" onClick={() => setAuctionId(a.id)} aria-current={auction?.id === a.id}
                      className={cx('flex w-full items-center gap-1.5 border-b border-line/60 px-2.5 py-1.5 text-left', auction?.id === a.id ? 'bg-accent/[0.08]' : 'hover:bg-bg-2')}>
                      <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: a.outcome === 'UNFILLED' ? 'var(--color-crit)' : a.outcome === 'COALITION' ? 'var(--color-violet)' : 'var(--color-ok)' }} />
                      <span className="num text-[11px] text-ink">{taskById(a.taskId).code}·T{a.tier}</span>
                      <span className="num ml-auto text-[9.5px] text-ink-3">{a.replicaId} +{a.tick * world.tickSeconds}s</span>
                    </button>
                  </li>
                ))}
              </ol>
              <div className="min-w-0 overflow-auto">{auction && <AuctionDetail round={auction} />}</div>
            </div>
          )}
        </Panel>
        <Panel title="Partition reconciliation · Algorithm 008" meta={`${recons.length} recorded`} bodyClass="" className="min-h-[420px]">
          {recons.length === 0 ? (
            <Empty>
              <span>No reconciliation yet. Jam the swarm with <span className="num text-ink-2">E | W</span> on the map, run a few ticks, then <span className="num text-ink-2">Lift</span> — or run experiment 02 in Fault Injection.</span>
            </Empty>
          ) : (
            <div className="grid h-full min-h-0 grid-cols-[150px_1fr]">
              <ol className="max-h-[520px] overflow-auto border-r border-line">
                {recons.map((r) => (
                  <li key={r.id}>
                    <button type="button" onClick={() => setReconId(r.id)} aria-current={recon?.id === r.id}
                      className={cx('flex w-full items-center gap-1.5 border-b border-line/60 px-2.5 py-1.5 text-left', recon?.id === r.id ? 'bg-accent/[0.08]' : 'hover:bg-bg-2')}>
                      <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: r.converged ? 'var(--color-ok)' : 'var(--color-warn)' }} />
                      <span className="num text-[11px] text-ink">{r.absorbed}→{r.survivor}</span>
                      <span className="num ml-auto text-[9.5px] text-ink-3">{r.conflicts.length}c +{r.tick * world.tickSeconds}s</span>
                    </button>
                  </li>
                ))}
              </ol>
              <div className="min-w-0 overflow-auto">{recon && <ReconDetail r={recon} tickSeconds={world.tickSeconds} />}</div>
            </div>
          )}
        </Panel>
      </div>
    </div>
  )
}
