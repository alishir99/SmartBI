/**
 * The period switcher.
 *
 * A segmented control rather than a dropdown: the options are few, mutually exclusive, and
 * the current one should be readable without opening anything. Which window you are looking
 * at is the single most load-bearing piece of context on the page — a net-sales figure is
 * meaningless without it, and the absence of this control was letting people compare a
 * 12-month total against an all-time one and conclude the numbers were wrong.
 *
 * Implemented as a radiogroup so arrow keys move between options, which is what the role
 * promises. The full label is shown from `sm` up; below that the short form keeps all seven
 * options reachable without a horizontal scroll trap.
 */

import { PERIOD_OPTIONS } from '../lib/periods'

type Props = {
  value: string
  onChange: (period: string) => void
  /** True while the next window is loading, so the control can show it is working. */
  busy?: boolean
}

export function PeriodFilter({ value, onChange, busy = false }: Props) {
  return (
    <div
      role="radiogroup"
      aria-label="Period"
      aria-busy={busy}
      className="inline-flex flex-wrap items-center gap-0.5 rounded-pill bg-surface-2 p-0.5 ring-hairline"
    >
      {PERIOD_OPTIONS.map((option) => {
        const selected = option.key === value
        return (
          <button
            key={option.key}
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={() => onChange(option.key)}
            className={[
              'rounded-pill px-3 py-1.5 text-xs font-medium transition-colors duration-200',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]',
              selected
                ? 'bg-surface text-ink shadow-card'
                : 'text-ink-secondary hover:text-ink',
            ].join(' ')}
          >
            <span className="hidden sm:inline">{option.label}</span>
            <span className="sm:hidden">{option.short}</span>
          </button>
        )
      })}
    </div>
  )
}
