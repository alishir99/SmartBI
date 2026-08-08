
import type { Kpi } from '../types'
import { formatDelta, formatKpiValue } from '../lib/format'
import { kpiQuestion } from '../lib/questions'
import { useT } from '../lib/i18n'
import { IconArrowDown, IconArrowUp, IconMinus } from './Icons'

export function KpiTile({ kpi, onAsk }: { kpi: Kpi; onAsk?: (question: string) => void }) {
  const t = useT()
  const delta = formatDelta(kpi.delta_pct, kpi.delta_label, kpi.unit)
  const question = kpiQuestion(kpi)

  return (
    <div className="rounded-tile bg-surface p-5 shadow-card ring-hairline sm:p-6">
      <p className="text-xs font-medium text-ink-secondary">{kpi.label}</p>
      {/* The number is the control: click it and the chat opens on the question it raises.
          A real button, so it is keyboard-reachable too. */}
      {onAsk ? (
        <button
          type="button"
          onClick={() => onAsk(question)}
          aria-label={question}
          className="tabular mt-3 block text-2xl font-semibold tracking-tight text-ink underline-offset-4 transition-colors duration-200 hover:text-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]"
        >
          {formatKpiValue(kpi.value, kpi.unit)}
        </button>
      ) : (
        <p className="tabular mt-3 text-2xl font-semibold tracking-tight text-ink">
          {formatKpiValue(kpi.value, kpi.unit)}
        </p>
      )}

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
          <span className="text-ink-muted">{t('card.no_comparison')}</span>
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

/** Shape, not reading: no axis, no ticks, no labels - the tile's value and delta already
 * carry the numbers. */
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
