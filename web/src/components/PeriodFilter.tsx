/** The period switcher. Everything on screen is compared to the window before the one it picks. */

import { periodOptions, type PeriodOption } from '../lib/periods'
import { useT } from '../lib/i18n'

type Props = {
  value: string
  onChange: (period: string) => void
  busy?: boolean
  options?: PeriodOption[]
  label?: string
}

export function PeriodFilter({ value, onChange, busy = false, options, label }: Props) {
  const t = useT()
  // Built inside the component, not at module load: chips are labelled in the active language,
  // and a module-level array is frozen in whichever one loaded first.
  const chips = options ?? periodOptions()
  label = label ?? t('source.period')
  return (
    <div
      role="radiogroup"
      aria-label={label}
      aria-busy={busy}
      className="inline-flex flex-wrap items-center gap-0.5 rounded-pill bg-surface-2 p-0.5 ring-hairline"
    >
      {chips.map((option) => {
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
