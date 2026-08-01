/** The period switcher, and the comparison-basis switcher built from the same control. */

import { BASIS_OPTIONS, PERIOD_OPTIONS, type PeriodOption } from '../lib/periods'

type Props = {
  value: string
  onChange: (period: string) => void
  /** True while the next window is loading, so the control can show it is working. */
  busy?: boolean
  options?: PeriodOption[]
  label?: string
}

export function PeriodFilter({
  value,
  onChange,
  busy = false,
  options = PERIOD_OPTIONS,
  label = 'Period',
}: Props) {
  return (
    <div
      role="radiogroup"
      aria-label={label}
      aria-busy={busy}
      className="inline-flex flex-wrap items-center gap-0.5 rounded-pill bg-surface-2 p-0.5 ring-hairline"
    >
      {options.map((option) => {
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

/** What every delta on the screen is measured against — one control, one meaning. */
export function BasisFilter(props: Omit<Props, 'options' | 'label'>) {
  return <PeriodFilter {...props} options={BASIS_OPTIONS} label="Jämförelsegrund" />
}
