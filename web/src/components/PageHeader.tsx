
import type { ReactNode } from 'react'
import type { Provenance } from '../types'
import { formatPeriod } from '../lib/format'
import { useAuthStore } from '../lib/auth'
import { useT } from '../lib/i18n'

export function PageHeader({
  title,
  description,
  provenance,
  children,
}: {
  title: string
  description?: string
  /** Any card's provenance - they share period and coverage within a page. */
  provenance?: Provenance | null
  children?: ReactNode
}) {
  const t = useT()
  const supplier = useAuthStore((state) => state.user?.supplier_name)

  return (
    <header className="mb-7 flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight text-ink">{title}</h1>
        {description && <p className="mt-1.5 text-sm text-ink-secondary">{description}</p>}
        {provenance && (
          <p className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-2xs text-ink-muted">
            <span>{formatPeriod(provenance.time_range)}</span>
            <span aria-hidden="true">·</span>
            <span>{supplier ?? provenance.scope}</span>
            <span aria-hidden="true">·</span>
            <span>
              {provenance.currency}, {t(`vat.${provenance.vat}`)}
            </span>
            <span aria-hidden="true">·</span>
            <span>
              {t('page.data_through', {
                date: formatPeriod({
                  from: provenance.coverage.to,
                  to: provenance.coverage.to,
                }),
              })}
            </span>
          </p>
        )}
      </div>
      {children}
    </header>
  )
}
