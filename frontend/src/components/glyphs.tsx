/** One outline glyph per agent type, so node class is readable without colour. */
import type { ArchetypeId } from '../sim/catalog'

const poly = (n: number, r: number, rot = -90): string =>
  Array.from({ length: n }, (_, i) => {
    const a = ((rot + (360 / n) * i) * Math.PI) / 180
    return `${(r * Math.cos(a)).toFixed(2)},${(r * Math.sin(a)).toFixed(2)}`
  }).join(' ')

export function GlyphShape({ archetype, r }: { archetype: ArchetypeId; r: number }) {
  switch (archetype) {
    case 'ISR': return <polygon points={poly(4, r * 1.15)} />
    case 'COMPUTE': return <rect x={-r * 0.85} y={-r * 0.85} width={r * 1.7} height={r * 1.7} />
    case 'SCOUT': return <polygon points={poly(3, r * 1.2)} />
    case 'LIDAR': return <polygon points={poly(6, r * 1.05, 0)} />
    case 'RELAY': return <circle r={r * 0.95} />
    case 'THERMAL': return <polygon points={poly(5, r * 1.1)} />
  }
}

export function Glyph({ archetype, size = 14, color = 'currentColor' }: { archetype: ArchetypeId; size?: number; color?: string }) {
  return (
    <svg width={size} height={size} viewBox="-12 -12 24 24" fill="none" stroke={color} strokeWidth="1.6" strokeLinejoin="round" aria-hidden className="shrink-0">
      <GlyphShape archetype={archetype} r={8} />
      {archetype === 'RELAY' && <circle r={2} fill={color} stroke="none" />}
    </svg>
  )
}
