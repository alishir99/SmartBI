/** A KPI tile. */

import type { Kpi } from '../types'
import { formatDelta, formatKpiValue } from '../lib/format'
import { IconArrowDown, IconArrowUp, IconMinus } from './Icons'

export function KpiTile({ kpi }: { kpi: Kpi }) {
  const delta = formatDelta(kpi.delta_pct, kpi.delta_label, kpi.unit)

  return (
    <div className="rounded-tile bg-surface p-5 shadow-card ring-hairline sm:p-6">
      <p className="text-xs font-medium text-ink-secondary">{kpi.label}</p>
      <p className="tabular mt-3 text-2xl font-semibold tracking-tight text-ink">
        {formatKpiValue(kpi.value, kpi.unit)}
      </p>

      <div className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
        {delta ? (
          <>
            <span
              className={`inline-flex items-center gap-1 font-medium ${
                delta.direction === 'up'
                  ? 'text-pos'
                  : delta.direction === 'down'
                    ? 'text-neg'
                    : 'text-ink-secondary'
              }`}
            >
              <DeltaIcon direction={delta.direction} />
              <span className="tabular">{delta.magnitude}</span>
            </span>
            <span className="text-ink-muted">{delta.label}</span>
          </>
        ) : (
          <span className="text-ink-muted">Ingen jämförelseperiod</span>
        )}
      </div>

      {kpi.spark.length > 0 && <Sparkline values={kpi.spark} />}

      {kpi.rank_label && (
        <p className="mt-2.5 inline-flex rounded-pill bg-surface-2 px-2.5 py-1 text-2xs text-ink-secondary">
          {kpi.rank_label}
        </p>
      )}
    </div>
  )
}

const SPARK = { width: 100, height: 24, pad: 2 }

/**
 * Shape, not reading: no axis, no ticks, no labels — so it must not be given any, or it
 * implies a precision it is not showing. The tile's value and delta carry the numbers, which
 * is why this is hidden from the accessibility tree rather than described badly.
 */
export function sparkPoints(values: number[]): string {
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min
  const usable = SPARK.height - 2 * SPARK.pad
  return values
    .map((value, index) => {
      const x = (index / (values.length - 1)) * SPARK.width
      // A flat series sits on the midline rather than dividing by zero.
      const y = SPARK.pad + (span === 0 ? usable / 2 : usable * (1 - (value - min) / span))
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
}

function Sparkline({ values }: { values: number[] }) {
  return (
    <svg
      className="mt-3 block w-full"
      height={SPARK.height}
      viewBox={`0 0 ${SPARK.width} ${SPARK.height}`}
      preserveAspectRatio="none"
      aria-hidden="true"
      focusable="false"
    >
      <polyline
        points={sparkPoints(values)}
        fill="none"
        stroke="var(--series-1)"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
        // preserveAspectRatio="none" stretches the stroke horizontally with the tile; this
        // keeps it an even 1.5px whatever the tile's width.
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  )
}

function DeltaIcon({ direction }: { direction: 'up' | 'down' | 'flat' }) {
  const className = 'h-3 w-3'
  if (direction === 'up') return <IconArrowUp className={className} />
  if (direction === 'down') return <IconArrowDown className={className} />
  return <IconMinus className={className} />
}
