/**
 * The provenance chip (§9.3). Every number on screen can be traced from here: which
 * tool ran, under which scope, over which period, against which source, and with
 * exactly which arguments. This is the visible half of the grounding claim — the
 * architecture guarantees it, the chip lets anyone check it.
 */

import { useId, useState } from 'react'
import type { Provenance } from '../types'
import {
  describeFilters,
  describeSource,
  formatClock,
  formatNumber,
  formatPeriod,
  formatTimestamp,
} from '../lib/format'
import { IconChevronDown, IconDatabase } from './Icons'

export function SourceChip({ provenance }: { provenance: Provenance }) {
  const [open, setOpen] = useState(false)
  const panelId = useId()

  const filters = describeFilters(provenance.filters_applied)

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
          <span className="font-mono">{provenance.tool}</span>
          <Dot />
          {describeSource(provenance.source)}
          <Dot />
          {formatNumber(provenance.row_count)} rader
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
        <dl
          id={panelId}
          className="animate-fade-in mt-3 grid gap-x-6 gap-y-2.5 rounded-tile bg-surface-2 p-4 text-2xs sm:grid-cols-2"
        >
          <Row label="Verktyg" value={provenance.tool} mono />
          <Row label="Källa" value={provenance.source} mono />
          <Row label="Behörighet" value={provenance.scope} mono />
          <Row label="Period" value={formatPeriod(provenance.time_range)} />
          {provenance.compare_range && (
            <Row label="Jämförelseperiod" value={formatPeriod(provenance.compare_range)} />
          )}
          <Row label="Datatäckning" value={formatPeriod(provenance.coverage)} />
          <Row label="Valuta" value={`${provenance.currency}, ${provenance.vat}`} />
          <Row
            label="Rader"
            value={`${formatNumber(provenance.row_count)}${provenance.truncated ? ' (trunkerad)' : ''}`}
          />
          {filters && <Row label="Filter" value={filters} span />}
          <Row label="Kördes" value={formatTimestamp(provenance.executed_at)} span />
          <div className="sm:col-span-2">
            <dt className="mb-1.5 text-ink-muted">Exakta argument</dt>
            <dd>
              <pre className="quiet-scroll overflow-x-auto rounded-lg bg-surface p-3 font-mono text-2xs leading-relaxed text-ink-secondary ring-hairline">
                {JSON.stringify(provenance.tool_args, null, 2)}
              </pre>
            </dd>
          </div>
        </dl>
      )}
    </div>
  )
}

function Row({
  label,
  value,
  mono = false,
  span = false,
}: {
  label: string
  value: string
  mono?: boolean
  span?: boolean
}) {
  return (
    <div className={span ? 'sm:col-span-2' : undefined}>
      <dt className="text-ink-muted">{label}</dt>
      <dd className={`mt-0.5 break-words text-ink-secondary ${mono ? 'font-mono' : ''}`}>{value}</dd>
    </div>
  )
}

const Dot = () => <span className="mx-1.5 text-ink-muted">·</span>
