
import { useState, type ReactNode } from 'react'
import type { AnswerCard as Card, ResultResponse } from '../types'
import { useResult } from '../lib/queries'
import { formatPeriod } from '../lib/format'
import { t as translate, useT } from '../lib/i18n'
import { Chart } from '../charts/Chart'
import { DataTable } from '../charts/DataTable'
import { Skeleton } from './Skeleton'
import { SourceChip } from './SourceChip'
import { CardActions } from './CardActions'
import { IconEmptyChart, IconInfo, IconQuestion, IconShield } from './Icons'

type Props = {
  card: Card
  /** Puts a new question into the chat: used by suggestion/candidate chips and by chart marks
   * and table rows - every number on the card is the start of a question. */
  onAsk?: (question: string) => void
  onDelete?: (cardId: string) => void
  savable?: boolean
  height?: number
  /** The chart-first card shown while the prose is still written; says so, because a card that
   * looks final and then rewrites its own numbers is worse than one that waited. */
  preview?: boolean
  /** Rows the caller already has - the shared-link page's reader has no session, so
   * /api/result would 404 and the rows travel with the card instead. */
  rows?: ResultResponse | null
  /** The source chip; only the chat shows it. A dashboard card already states period/supplier
   * once in the page header, so repeating a source line per tile there is just noise. */
  showSource?: boolean
}

export function AnswerCardView({ card, onAsk, onDelete, savable = true, height = 280,
                                preview = false, rows = null, showSource = false }: Props) {
  const t = useT()
  const [view, setView] = useState<'chart' | 'table'>('chart')
  // Disabled when the rows are already here - the hook has to be called either way.
  const fetched = useResult(rows ? null : card.query_id)
  const result = rows
    ? { data: rows, isPending: false, isError: false, error: null }
    : fetched

  const title = card.chart?.title ?? headingFor(card)
  const subtitle = subtitleFor(card, card.chart?.subtitle ?? null)
  const prose = card.status === 'validation_failed' ? null : card.narrative

  return (
    <section className="animate-fade-up rounded-card bg-surface p-6 shadow-card ring-hairline sm:p-7">
      <header className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-0">
          <h3 className="text-lg font-semibold tracking-tight text-ink">{title}</h3>
          {subtitle && <p className="mt-1 text-xs text-ink-secondary">{subtitle}</p>}
          {preview && (
            <p className="mt-1.5 inline-flex items-center gap-1.5 rounded-full bg-surface-2 px-2 py-0.5 text-2xs text-ink-muted">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" aria-hidden="true" />
              {t('card.preview')}
            </p>
          )}
        </div>
        <CardActions
          card={card}
          view={view}
          onToggleView={setView}
          onDelete={onDelete}
          // A preview is one tool result that a later one may replace, so it is never savable -
          // here rather than in the caller, so no caller can get it wrong.
          savable={savable && !preview}
          hasRows={(result.data?.rows.length ?? 0) > 0}
        />
      </header>

      {card.status === 'validation_failed' && (
        <Notice tone="warn" icon={<IconShield className="h-4 w-4" />}>
          {t('card.validation_failed')}
        </Notice>
      )}

      {/* `pre-line` so the model's own paragraph breaks survive; the narrative is plain text,
          never markdown - the server strips emphasis markers before it gets here. */}
      {prose && (
        <p className="mt-4 whitespace-pre-line text-base leading-relaxed text-ink">{prose}</p>
      )}

      {card.insights.length > 0 && (
        <ul className="mt-4 space-y-2">
          {card.insights.map((insight) => (
            <li key={insight} className="flex gap-2.5 text-sm text-ink-secondary">
              <span className="mt-[0.55rem] h-1 w-1 shrink-0 rounded-full bg-accent" aria-hidden="true" />
              {insight}
            </li>
          ))}
        </ul>
      )}

      {card.chart && (card.query_id || rows) && (
        <div className="mt-6">
          {result.isPending && (
            <div style={{ height }}>
              <Skeleton className="h-full w-full" />
            </div>
          )}
          {result.isError && (
            <Notice tone="warn" icon={<IconInfo className="h-4 w-4" />}>
              {t('card.chart_data_failed')} {String(result.error)}
            </Notice>
          )}
          {result.data &&
            (view === 'chart' ? (
              <Chart
                spec={card.chart}
                columns={result.data.columns}
                rows={result.data.rows}
                height={height}
                onAsk={onAsk}
              />
            ) : (
              <DataTable
                columns={result.data.columns}
                rows={result.data.rows}
                caption={card.chart.title}
                onAsk={onAsk}
              />
            ))}
          {result.data?.truncated && (
            <p className="mt-3 text-2xs text-ink-muted">
              {t('card.truncated', {
                shown: result.data.rows.length,
                total: result.data.row_count,
              })}
            </p>
          )}
        </div>
      )}

      {/* A chart without a query_id and without rows has nothing to draw from - the result
          query is disabled in that case, so guard here rather than leaving a skeleton forever. */}
      {(!card.chart || !(card.query_id || rows)) && card.status === 'ok' && <EmptyState />}

      {card.status === 'clarify' && (
        <ChipRow
          label={t('card.did_you_mean')}
          items={card.suggestions}
          onPick={onAsk}
          icon={<IconQuestion className="h-4 w-4" />}
        />
      )}

      {card.status === 'cannot_answer' && (
        <ChipRow
          label={t('card.can_answer')}
          items={card.suggestions}
          onPick={onAsk}
          icon={<IconInfo className="h-4 w-4" />}
        />
      )}

      {card.caveats.length > 0 && (
        <ul className="mt-5 space-y-1.5">
          {card.caveats.map((caveat) => (
            <li key={caveat} className="text-2xs text-ink-muted">
              {caveat}
            </li>
          ))}
        </ul>
      )}

      {showSource && card.provenance && (
        <SourceChip
          provenance={card.provenance}
          sources={card.sources}
          claims={card.claims}
          primaryQueryId={card.query_id}
        />
      )}
    </section>
  )
}

function headingFor(card: Card): string {
  if (card.status === 'clarify') return translate('card.clarify')
  if (card.status === 'cannot_answer') return translate('card.cannot_answer')
  // Neither a data answer nor a refusal - labelling it as either was how "vad betyder den
  // streckade linjen?" got a correct explanation under "Det här har jag inte underlag för".
  if (card.status === 'explain') return translate('card.explain')
  return translate('card.answer')
}

/** The window that actually ran is never dropped: it varies run to run (12 months by default,
 * sometimes `all_time`), so a subtitle that's only the model's prose can hide why totals moved. */
function subtitleFor(card: Card, modelSubtitle: string | null): string | null {
  const provenance = card.provenance
  if (!provenance) return modelSubtitle
  const period = formatPeriod(provenance.time_range)
  if (!modelSubtitle) {
    return translate('card.subtitle_vat', {
      period,
      vat: translate(`vat.${provenance.vat}`),
    })
  }
  return modelSubtitle.includes(period) ? modelSubtitle : `${modelSubtitle} · ${period}`
}

function ChipRow({
  label,
  items,
  onPick,
  icon,
}: {
  label: string
  items: string[]
  onPick?: (question: string) => void
  icon: ReactNode
}) {
  if (items.length === 0) return null
  return (
    <div className="mt-5">
      <p className="flex items-center gap-2 text-xs font-medium text-ink-secondary">
        <span className="text-ink-muted">{icon}</span>
        {label}
      </p>
      <ul className="mt-2.5 flex flex-wrap gap-2">
        {items.map((item) => (
          <li key={item}>
            <button
              type="button"
              disabled={!onPick}
              onClick={() => onPick?.(item)}
              className="rounded-pill bg-accent-soft px-3.5 py-1.5 text-xs text-accent transition-opacity duration-200 hover:opacity-80 disabled:cursor-default disabled:opacity-100"
            >
              {item}
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

function Notice({
  tone,
  icon,
  children,
}: {
  tone: 'warn'
  icon: ReactNode
  children: ReactNode
}) {
  return (
    <div
      role="status"
      className={`mt-4 flex gap-3 rounded-tile p-3.5 text-sm ${
        tone === 'warn' ? 'bg-notice-bg text-notice-ink ring-1 ring-inset ring-notice-border' : ''
      }`}
    >
      <span className="mt-0.5 shrink-0">{icon}</span>
      <p className="leading-relaxed">{children}</p>
    </div>
  )
}

function EmptyState() {
  return (
    <div className="mt-6 flex flex-col items-center justify-center rounded-tile bg-surface-2 px-6 py-10 text-center">
      <IconEmptyChart className="h-8 w-8 text-ink-muted" />
      <p className="mt-3 text-sm text-ink-secondary">{translate('card.no_chart')}</p>
    </div>
  )
}
