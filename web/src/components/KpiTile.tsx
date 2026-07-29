/**
 * A KPI tile. The delta never appears without the period it is measured against —
 * a bare "▲ 8,2 %" is the classic dashboard lie, so `formatDelta` always returns the
 * label and this component always renders it.
 */

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

      {kpi.rank_label && (
        <p className="mt-2.5 inline-flex rounded-pill bg-surface-2 px-2.5 py-1 text-2xs text-ink-secondary">
          {kpi.rank_label}
        </p>
      )}
    </div>
  )
}

function DeltaIcon({ direction }: { direction: 'up' | 'down' | 'flat' }) {
  const className = 'h-3 w-3'
  if (direction === 'up') return <IconArrowUp className={className} />
  if (direction === 'down') return <IconArrowDown className={className} />
  return <IconMinus className={className} />
}
