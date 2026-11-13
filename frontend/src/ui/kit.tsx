/** Small presentational primitives shared by every view. */
import type { ButtonHTMLAttributes, ReactNode } from 'react'
import type { Severity } from '../sim/types'

export const cx = (...parts: Array<string | false | null | undefined>): string => parts.filter(Boolean).join(' ')

export const SEVERITY_COLOR: Record<Severity, string> = {
  info: 'var(--color-ink-3)', ok: 'var(--color-ok)', warn: 'var(--color-warn)', crit: 'var(--color-crit)',
}
/** Partition/replica colours, assigned by replica order and never reused for status. */
export const SERIES = ['var(--color-s1)', 'var(--color-s2)', 'var(--color-s3)', 'var(--color-s4)', 'var(--color-s5)']
export const seriesColor = (i: number): string => SERIES[i % SERIES.length] as string

export function Panel({ title, meta, actions, children, className, bodyClass }: {
  title?: ReactNode; meta?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; bodyClass?: string
}) {
  return (
    <section className={cx('panel flex min-h-0 flex-col', className)}>
      {(title || actions) && (
        <header className="flex h-8 shrink-0 items-center gap-2 border-b border-line px-3">
          <h2 className="label !text-ink-2">{title}</h2>
          {meta && <span className="num truncate text-[10px] text-ink-3">{meta}</span>}
          <div className="ml-auto flex items-center gap-1.5">{actions}</div>
        </header>
      )}
      <div className={cx('min-h-0 flex-1', bodyClass ?? 'p-3')}>{children}</div>
    </section>
  )
}

export function Stat({ label, value, unit, sub, tone }: { label: string; value: ReactNode; unit?: string; sub?: ReactNode; tone?: Severity }) {
  return (
    <div className="min-w-0 border-l border-line px-3 py-2 first:border-l-0">
      <div className="label truncate">{label}</div>
      <div className="mt-1 flex items-baseline gap-1">
        <span className="num text-[20px] leading-none font-medium" style={{ color: tone && tone !== 'info' ? SEVERITY_COLOR[tone] : undefined }}>{value}</span>
        {unit && <span className="num text-[11px] text-ink-3">{unit}</span>}
      </div>
      {sub && <div className="num mt-1 truncate text-[10.5px] text-ink-3">{sub}</div>}
    </div>
  )
}

export function Btn({ tone = 'default', size = 'md', active, className, children, ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & {
  tone?: 'default' | 'primary' | 'danger' | 'ghost'; size?: 'sm' | 'md'; active?: boolean
}) {
  const tones = {
    default: 'border-line-2 bg-bg-2 text-ink hover:border-ink-3 hover:bg-bg-3',
    primary: 'border-accent/60 bg-accent/10 text-accent hover:bg-accent/20',
    danger: 'border-crit/50 bg-crit/10 text-crit hover:bg-crit/20',
    ghost: 'border-transparent text-ink-2 hover:bg-bg-3 hover:text-ink',
  }
  return (
    <button
      type="button"
      {...rest}
      className={cx(
        'inline-flex shrink-0 items-center justify-center gap-1.5 rounded-[2px] border font-medium whitespace-nowrap transition-colors duration-100',
        'disabled:cursor-not-allowed disabled:opacity-35',
        size === 'sm' ? 'h-[22px] px-2 text-[11px]' : 'h-[26px] px-2.5 text-[12px]',
        active ? 'border-accent/70 bg-accent/15 text-accent' : tones[tone], className,
      )}
    >
      {children}
    </button>
  )
}

export function Tag({ children, color, title, solid }: { children: ReactNode; color?: string; title?: string; solid?: boolean }) {
  const c = color ?? 'var(--color-ink-3)'
  return (
    <span
      title={title}
      className="num inline-flex h-[17px] shrink-0 items-center rounded-[2px] border px-1.5 text-[10px] leading-none tracking-wide whitespace-nowrap"
      style={{ color: c, borderColor: `color-mix(in oklab, ${c} 45%, transparent)`, background: solid ? `color-mix(in oklab, ${c} 14%, transparent)` : undefined }}
    >
      {children}
    </span>
  )
}

/** Provenance marker: which layer produced a record. */
export function SourceTag({ source }: { source: 'kernel' | 'harness' | 'operator' }) {
  const map = {
    kernel: { c: 'var(--color-accent)', t: 'Decision made by a ported HESK kernel algorithm' },
    harness: { c: 'var(--color-ink-3)', t: 'Produced by the demonstration harness, not by HESK' },
    operator: { c: 'var(--color-violet)', t: 'Injected by you' },
  }[source]
  return <Tag color={map.c} title={map.t}>{source}</Tag>
}

export function Meter({ value, max = 1, color = 'var(--color-accent)', mark, height = 4 }: { value: number; max?: number; color?: string; mark?: number; height?: number }) {
  const pct = Math.max(0, Math.min(1, max ? value / max : 0)) * 100
  return (
    <div className="relative w-full overflow-hidden rounded-[1px] bg-bg-3" style={{ height }}>
      <div className="h-full transition-[width] duration-300" style={{ width: `${pct}%`, background: color }} />
      {mark !== undefined && <div className="absolute top-0 h-full w-px bg-ink-2" style={{ left: `${Math.min(100, (mark / max) * 100)}%` }} />}
    </div>
  )
}

export function Seg<T extends string | number>({ value, options, onChange, label }: {
  value: T; options: Array<{ value: T; label: string }>; onChange: (v: T) => void; label: string
}) {
  return (
    <div role="group" aria-label={label} className="inline-flex overflow-hidden rounded-[2px] border border-line-2">
      {options.map((o) => (
        <button
          key={String(o.value)} type="button" aria-pressed={o.value === value} onClick={() => onChange(o.value)}
          className={cx('num h-6 border-l border-line-2 px-2 text-[11px] first:border-l-0', o.value === value ? 'bg-accent/15 text-accent' : 'bg-bg-2 text-ink-2 hover:text-ink')}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="flex h-full min-h-16 items-center justify-center px-4 text-center text-[12px] text-ink-3">{children}</div>
}

/** Inline note used wherever the lab has to be explicit about what is and is not real. */
export function Caveat({ children, tone = 'info' }: { children: ReactNode; tone?: 'info' | 'warn' }) {
  const c = tone === 'warn' ? 'var(--color-warn)' : 'var(--color-ink-3)'
  return (
    <p className="border-l-2 py-0.5 pl-2.5 text-[11.5px] leading-snug text-ink-2" style={{ borderColor: c }}>
      {children}
    </p>
  )
}

const ICONS: Record<string, string> = {
  play: 'M5 3.5v9l7.5-4.5z',
  pause: 'M4.5 3.5h2.5v9H4.5zM9 3.5h2.5v9H9z',
  step: 'M4 3.5v9l6-4.5zM11 3.5h1.5v9H11z',
  reset: 'M8 3a5 5 0 1 0 4.6 3M8 1v3.5H4.5',
  plus: 'M8 3v10M3 8h10',
  minus: 'M3 8h10',
  fit: 'M3 6V3h3M10 3h3v3M13 10v3h-3M6 13H3v-3',
  close: 'M4 4l8 8M12 4l-8 8',
  mission: 'M8 1.5l5.6 3.2v6.6L8 14.5l-5.6-3.2V4.7zM8 6a2 2 0 1 0 0 4 2 2 0 0 0 0-4',
  consensus: 'M3 4h10M3 8h10M3 12h10M5.5 2.5v3M10.5 6.5v3M7 10.5v3',
  faults: 'M9 1.5L3.5 9H8l-1 5.5L12.5 7H8z',
  observatory: 'M2 13h12M3.5 10.5l3-4 2.5 2 3.5-5',
  architecture: 'M2.5 2.5h4v4h-4zM9.5 9.5h4v4h-4zM4.5 6.5v5h5M9.5 2.5h4v4h-4z',
}
export function Icon({ name, size = 14 }: { name: keyof typeof ICONS | string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d={ICONS[name] ?? ''} />
    </svg>
  )
}

export const pct = (v: number, digits = 0): string => `${(v * 100).toFixed(digits)}%`
export const TASK_STATUS_COLOR: Record<string, string> = {
  EXECUTING: 'var(--color-ok)', DEGRADED: 'var(--color-warn)', ABANDONED: 'var(--color-crit)', COMPLETED: 'var(--color-ink-3)',
}
