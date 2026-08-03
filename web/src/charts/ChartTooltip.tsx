import type { TooltipProps } from 'recharts'
import type { Column } from '../types'
import { formatCell } from '../lib/format'

type Props = TooltipProps<number, string> & {
  columns: Column[]
  /** Formats the x/category label — dates get Swedish month or ISO week names. */
  labelFormatter?: (value: string) => string
}

const byKey = (columns: Column[], key: string) => columns.find((column) => column.key === key)

/**
 * Values are exact here (no magnitude switching): the axis carries the rounded scale, the
 * tooltip carries the number.
 */
export function ChartTooltip({ active, payload, label, columns, labelFormatter }: Props) {
  if (!active || !payload || payload.length === 0) return null

  const heading = typeof label === 'string' ? (labelFormatter?.(label) ?? label) : String(label ?? '')

  return (
    // No min-width, and a cap narrow enough to sit inside a squeezed plot: recharts keeps the
    // tooltip inside the chart's box, but a tooltip wider than the chart has nowhere to go and
    // spills over the card — behind the chat rail, where it cannot be read.
    <div className="pointer-events-none max-w-[15rem] rounded-xl bg-surface px-3.5 py-3 shadow-pop ring-hairline">
      {heading && (
        <p className="mb-2 text-xs font-medium leading-tight text-ink-secondary">{heading}</p>
      )}
      <ul className="space-y-1.5">
        {payload.map((entry) => {
          const key = String(entry.dataKey ?? entry.name ?? '')
          const column = byKey(columns, key)
          const value = typeof entry.value === 'number' ? entry.value : null
          return (
            <li key={key} className="flex items-baseline justify-between gap-4">
              <span className="flex min-w-0 items-center gap-2">
                <span
                  className="h-2 w-2 shrink-0 rounded-full"
                  style={{ backgroundColor: entry.color }}
                />
                <span className="truncate text-xs text-ink-secondary">
                  {column?.label ?? key}
                </span>
              </span>
              <span className="tabular shrink-0 text-sm font-medium text-ink">
                {column && value !== null ? formatCell(value, column) : '–'}
              </span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
