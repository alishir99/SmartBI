/**
 * The provenance chip (§9.3). Every number on screen can be traced from here: which
 * tool ran, under which scope, over which period, against which source, and with
 * exactly which arguments. This is the visible half of the grounding claim — the
 * architecture guarantees it, the chip lets anyone check it.
 *
 * A turn can run more than one query, and the validator has always checked the prose against
 * all of them while the card named a single one. So a figure grounded in the second query sat
 * beside a chip describing the first — the one artefact whose entire purpose is traceability,
 * quietly pointing at the wrong place. When `sources` carries more than one entry the chip
 * lists each, and the figures each licensed are printed against it: not "the numbers are
 * checked" but "this number came from that query".
 */

import { useId, useState } from 'react'
import type { Claim, Provenance, ToolCallRecord } from '../types'
import {
  describeFilters,
  describeSource,
  formatClock,
  formatNumber,
  formatPeriod,
  formatTimestamp,
} from '../lib/format'
import { IconChevronDown, IconDatabase } from './Icons'

type Props = {
  provenance: Provenance
  /** Every result the turn produced. Absent on a saved card from before this existed. */
  sources?: ToolCallRecord[]
  claims?: Claim[]
  /** The chart's query, so its source can be labelled as the one being drawn. */
  primaryQueryId?: string | null
}

export function SourceChip({ provenance, sources, claims, primaryQueryId }: Props) {
  const [open, setOpen] = useState(false)
  const panelId = useId()

  // One source is the common case and must look exactly as it did before. The multi-source
  // rendering is additive, never a redesign of the single-source chip.
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
              <span className="font-mono">{records.length} källor</span>
              <Dot />
              {records.map((record) => record.tool).join(', ')}
            </>
          ) : (
            <>
              <span className="font-mono">{provenance.tool}</span>
              <Dot />
              {describeSource(provenance.source)}
              <Dot />
              {formatNumber(provenance.row_count)} rader
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
          {multiple ? (
            records.map((record) => (
              <SourcePanel
                key={record.query_id}
                provenance={record.provenance}
                queryId={record.query_id}
                isPrimary={record.query_id === primaryQueryId}
                claims={(claims ?? []).filter((claim) => claim.query_id === record.query_id)}
              />
            ))
          ) : (
            <SourcePanel provenance={provenance} queryId={primaryQueryId ?? null} />
          )}
        </div>
      )}
    </div>
  )
}

function SourcePanel({
  provenance,
  queryId,
  isPrimary = false,
  claims,
}: {
  provenance: Provenance
  queryId: string | null
  isPrimary?: boolean
  claims?: Claim[]
}) {
  const filters = describeFilters(provenance.filters_applied)

  return (
    <dl className="grid gap-x-6 gap-y-2.5 rounded-tile bg-surface-2 p-4 text-2xs sm:grid-cols-2">
      {isPrimary && (
        <div className="sm:col-span-2">
          <span className="rounded-pill bg-surface px-2 py-0.5 text-ink-secondary ring-hairline">
            Diagrammet ritas från den här
          </span>
        </div>
      )}
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

      {/* The sentence this whole feature exists to be able to say. Only rendered when the
          card carries attributions, so a saved card from before them is unaffected. */}
      {claims && claims.length > 0 && (
        <div className="sm:col-span-2">
          <dt className="mb-1.5 text-ink-muted">Siffror i texten som kommer härifrån</dt>
          <dd className="flex flex-wrap gap-1.5">
            {claims.map((claim, index) => (
              <span
                key={`${claim.literal}-${index}`}
                className="rounded-pill bg-surface px-2 py-0.5 font-mono text-ink-secondary ring-hairline"
              >
                {claim.literal}
              </span>
            ))}
          </dd>
        </div>
      )}

      <div className="sm:col-span-2">
        <dt className="mb-1.5 text-ink-muted">
          Exakta argument{queryId ? ` · ${queryId}` : ''}
        </dt>
        <dd>
          <pre className="quiet-scroll overflow-x-auto rounded-lg bg-surface p-3 font-mono text-2xs leading-relaxed text-ink-secondary ring-hairline">
            {JSON.stringify(provenance.tool_args, null, 2)}
          </pre>
        </dd>
      </div>
    </dl>
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
