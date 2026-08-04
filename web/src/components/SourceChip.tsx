/**
 * Where the numbers came from, in the words a supplier uses.
 *
 * The chip used to lead with `query_sales`, `mv_sales_daily (rollup)`, `supplier:8f2a` and a
 * block of raw tool arguments. To an engineer that reads as provenance; to the person the
 * product is for it reads as the application handing out database internals, which is the
 * opposite of the reassurance the chip exists to give. Same guarantee, stated as what was
 * counted, over which period, from how many rows.
 */

import { useId, useState } from 'react'
import type { Claim, Provenance, ToolCallRecord } from '../types'
import {
  describeFilters,
  formatClock,
  formatNumber,
  formatPeriod,
  formatTimestamp,
} from '../lib/format'
import { t as translate, useT } from '../lib/i18n'
import { IconChevronDown, IconDatabase } from './Icons'

/** What each tool read, said as a business fact rather than as a table name. */
function sourceWords(tool: string): string {
  return tool === 'query_market_share'
    ? translate('source.market_share')
    : translate('source.own_sales')
}

type Props = {
  provenance: Provenance
  /** Every result the turn produced. Absent on a saved card from before this existed. */
  sources?: ToolCallRecord[]
  claims?: Claim[]
  /** The chart's query, so its source can be labelled as the one being drawn. */
  primaryQueryId?: string | null
}

export function SourceChip({ provenance, sources, claims, primaryQueryId }: Props) {
  const t = useT()
  const [open, setOpen] = useState(false)
  const panelId = useId()

  // One source is the common case and must look exactly as it did before.
  const records = sources && sources.length > 0 ? sources : []
  const multiple = records.length > 1

  return (
    <div className="mt-5">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
        aria-controls={panelId}
        className="group inline-flex max-w-full items-center gap-2 rounded-pill bg-surface-2 py-1.5 pl-3 pr-2.5 text-2xs text-ink-secondary transition-colors duration-200 hover:bg-surface-3"
      >
        <IconDatabase className="h-3.5 w-3.5 shrink-0 text-ink-muted" />
        <span className="truncate">
          {multiple ? (
            <>
              <span className="font-medium text-ink">{t('source.plural')}</span>
              <Dot />
              {t('source.fetches', { count: records.length })}
            </>
          ) : (
            <>
              <span className="font-medium text-ink">{t('source.singular')}</span>
              <Dot />
              {sourceWords(provenance.tool)}
              <Dot />
              {formatPeriod(provenance.time_range)}
              <Dot />
              {t('source.rows_count', { count: formatNumber(provenance.row_count) })}
            </>
          )}
          <Dot />
          {formatClock(provenance.executed_at)}
        </span>
        <IconChevronDown
          className={`h-3.5 w-3.5 shrink-0 text-ink-muted transition-transform duration-200 ${
            open ? 'rotate-180' : ''
          }`}
        />
      </button>

      {open && (
        <div id={panelId} className="animate-fade-in mt-3 space-y-3">
          <p className="text-2xs leading-relaxed text-ink-muted">{t('source.explainer')}</p>
          {multiple ? (
            records.map((record) => (
              <SourcePanel
                key={record.query_id}
                provenance={record.provenance}
                isPrimary={record.query_id === primaryQueryId}
                claims={(claims ?? []).filter((claim) => claim.query_id === record.query_id)}
              />
            ))
          ) : (
            <SourcePanel provenance={provenance} claims={claims} />
          )}
        </div>
      )}
    </div>
  )
}

function SourcePanel({
  provenance,
  isPrimary = false,
  claims,
}: {
  provenance: Provenance
  isPrimary?: boolean
  claims?: Claim[]
}) {
  const t = useT()
  const filters = describeFilters(provenance.filters_applied)

  return (
    <dl className="grid gap-x-6 gap-y-2.5 rounded-tile bg-surface-2 p-4 text-2xs sm:grid-cols-2">
      {isPrimary && (
        <div className="sm:col-span-2">
          <span className="rounded-pill bg-surface px-2 py-0.5 text-ink-secondary ring-hairline">
            {t('source.is_charted')}
          </span>
        </div>
      )}
      <Row label={t('source.basis')} value={sourceWords(provenance.tool)} />
      <Row label={t('source.period')} value={formatPeriod(provenance.time_range)} />
      {provenance.compare_range && (
        <Row label={t('source.compare_period')} value={formatPeriod(provenance.compare_range)} />
      )}
      <Row label={t('source.coverage')} value={formatPeriod(provenance.coverage)} />
      {/* The currency code comes off the result's own provenance, not off a client-side
          assumption: a card is allowed to say which currency it was computed in, and only the
          words around it are translated. */}
      <Row
        label={t('source.currency')}
        value={`${provenance.currency}, ${t(`vat.${provenance.vat}`)}`}
      />
      <Row
        label={t('source.rows')}
        value={`${formatNumber(provenance.row_count)}${
          provenance.truncated ? t('source.truncated') : ''
        }`}
      />
      {filters && <Row label={t('source.selection')} value={filters} span />}
      <Row label={t('source.fetched')} value={formatTimestamp(provenance.executed_at)} span />

      {/* The sentence this whole feature exists to be able to say. Only rendered when the
          card carries attributions, so a saved card from before them is unaffected. */}
      {claims && claims.length > 0 && (
        <div className="sm:col-span-2">
          <dt className="mb-1.5 text-ink-muted">{t('source.claims')}</dt>
          <dd className="flex flex-wrap gap-1.5">
            {claims.map((claim, index) => (
              <span
                key={`${claim.literal}-${index}`}
                className="rounded-pill bg-surface px-2 py-0.5 text-ink-secondary ring-hairline"
              >
                {claim.literal}
              </span>
            ))}
          </dd>
        </div>
      )}
    </dl>
  )
}

function Row({
  label,
  value,
  span = false,
}: {
  label: string
  value: string
  span?: boolean
}) {
  return (
    <div className={span ? 'sm:col-span-2' : undefined}>
      <dt className="text-ink-muted">{label}</dt>
      <dd className="mt-0.5 break-words text-ink-secondary">{value}</dd>
    </div>
  )
}

const Dot = () => <span className="mx-1.5 text-ink-muted">·</span>
