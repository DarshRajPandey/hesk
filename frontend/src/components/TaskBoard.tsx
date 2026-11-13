import type { ReplicaView, TaskView, WorldSnapshot } from '../sim/types'
import { cx, Meter, seriesColor, Tag, TASK_STATUS_COLOR } from '../ui/kit'

const CLASS_COLOR: Record<string, string> = { CRITICAL: 'var(--color-crit)', IMPORTANT: 'var(--color-warn)', OPTIONAL: 'var(--color-ink-3)' }

export function TierPips({ t }: { t: TaskView }) {
  return (
    <span className="flex gap-0.5" title={t.status === 'ABANDONED' ? 'No tier running' : `Tier ${t.tier} of ${t.tierCount - 1}: ${t.tierLabel}`}>
      {Array.from({ length: t.tierCount }, (_, i) => (
        <span key={i} className="h-2.5 w-1.5 rounded-[1px]" style={{
          background: t.status !== 'ABANDONED' && i === t.tier ? TASK_STATUS_COLOR[t.status] : 'var(--color-bg-3)',
          outline: t.status !== 'ABANDONED' && i === t.tier ? 'none' : '1px solid var(--color-line-2)', outlineOffset: -1,
        }} />
      ))}
    </span>
  )
}

function Belief({ t, onSelect }: { t: TaskView; onSelect: (id: string) => void }) {
  if (t.status === 'ABANDONED') return <span className="num text-[11px] text-crit">unowned</span>
  return (
    <span className="flex min-w-0 flex-wrap items-center gap-x-1 gap-y-0.5">
      {t.members.map((m, i) => (
        <button key={m} type="button" onClick={() => onSelect(m)} className={cx('num text-[11px] hover:text-accent hover:underline', t.live ? 'text-ink' : 'text-warn')}>
          {m}{i < t.members.length - 1 ? ' +' : ''}
        </button>
      ))}
      {!t.live && <Tag color="var(--color-warn)" title="An assigned node is down or unreachable and peers have not yet reacted">stale</Tag>}
    </span>
  )
}

/** Mission tasks as each replica believes them. With one replica it is a plain task list; under partition it shows the split-brain. */
export function TaskBoard({ world, onSelect }: { world: WorldSnapshot; onSelect: (id: string) => void }) {
  const replicas = world.replicas
  const first = replicas[0] as ReplicaView | undefined
  if (!first) return <div className="p-3 text-[12px] text-ink-3">No live nodes.</div>
  const split = replicas.length > 1
  return (
    <div className="h-full overflow-auto">
      <table className="w-full border-collapse text-left">
        <thead className="sticky top-0 z-10 bg-bg-1">
          <tr className="border-b border-line">
            <th className="label px-3 py-1.5 font-normal">Task</th>
            {split ? replicas.map((r, i) => (
              <th key={r.id} className="label px-2 py-1.5 font-normal" style={{ color: seriesColor(i) }}>Replica {r.id}</th>
            )) : <><th className="label px-2 py-1.5 font-normal">Tier</th><th className="label px-2 py-1.5 font-normal">Owner</th><th className="label w-20 px-3 py-1.5 font-normal">Progress</th></>}
          </tr>
        </thead>
        <tbody>
          {first.tasks.map((t0, row) => {
            const views = replicas.map((r) => r.tasks[row] as TaskView)
            const disagree = split && new Set(views.map((v) => `${v.members.join('+')}@${v.tier}:${v.status}`)).size > 1
            return (
              <tr key={t0.taskId} className="border-b border-line/70 align-top">
                <td className="px-3 py-1.5">
                  <div className="flex items-center gap-1.5">
                    <span className="num text-[11px] font-medium text-ink">{t0.code}</span>
                    <span className="truncate text-[12px] text-ink-2">{t0.name}</span>
                  </div>
                  <div className="mt-0.5 flex items-center gap-1.5">
                    <span className="num text-[9.5px] tracking-wide" style={{ color: CLASS_COLOR[t0.priorityClass] }}>{t0.priorityClass}</span>
                    <span className="num text-[9.5px] text-ink-3">π {t0.missionPriority.toFixed(2)}</span>
                    {disagree && <Tag color="var(--color-s3)" title="Replicas hold different ownership claims for this task">diverged</Tag>}
                  </div>
                </td>
                {split ? views.map((v, i) => (
                  <td key={replicas[i]!.id} className="px-2 py-1.5">
                    <div className="flex items-center gap-1.5"><TierPips t={v} /><Belief t={v} onSelect={onSelect} /></div>
                  </td>
                )) : (
                  <>
                    <td className="px-2 py-2"><TierPips t={t0} /></td>
                    <td className="px-2 py-1.5">
                      <Belief t={t0} onSelect={onSelect} />
                      {t0.status !== 'ABANDONED' && <div className="mt-0.5 truncate text-[10.5px] text-ink-3">{t0.kind === 'COALITION' ? 'coalition · ' : ''}{t0.tierLabel}</div>}
                    </td>
                    <td className="px-3 py-2">
                      <Meter value={t0.progress} color={TASK_STATUS_COLOR[t0.status]} />
                      <div className="num mt-0.5 text-right text-[10px] text-ink-3">{Math.round(t0.progress * 100)}%</div>
                    </td>
                  </>
                )}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
