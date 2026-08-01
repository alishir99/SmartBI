/** The single card renderer. */

import { useState, type ReactNode } from 'react'
import type { AnswerCard as Card } from '../types'
import { useResult } from '../lib/queries'
import { formatPeriod } from '../lib/format'
import { Chart } from '../charts/Chart'
import { DataTable } from '../charts/DataTable'
import { Skeleton } from './Skeleton'
import { SourceChip } from './SourceChip'
import { CardActions } from './CardActions'
import { IconEmptyChart, IconInfo, IconQuestion, IconShield } from './Icons'

type Props = {
  card: Card
  /** Lets suggestion and candidate chips put a new question into the chat. */
  onAsk?: (question: string) => void
  onDelete?: (cardId: string) => void
  savable?: boolean
  height?: number
}

export function AnswerCardView({ card, onAsk, onDelete, savable = true, height = 280 }: Props) {
  const [view, setView] = useState<'chart' | 'table'>('chart')
  const result = useResult(card.query_id)

  const title = card.chart?.title ?? headingFor(card)
  const subtitle = card.chart?.subtitle ?? subtitleFor(card)
  const prose = card.status === 'validation_failed' ? null : card.narrative

  return (
    <section className="animate-fade-up rounded-card bg-surface p-6 shadow-card ring-hairline sm:p-7">
      <header className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-0">
          <h3 className="text-lg font-semibold tracking-tight text-ink">{title}</h3>
          {subtitle && <p className="mt-1 text-xs text-ink-secondary">{subtitle}</p>}
        </div>
        <CardActions
          card={card}
          view={view}
          onToggleView={setView}
          onDelete={onDelete}
          savable={savable}
          hasRows={(result.data?.rows.length ?? 0) > 0}
        />
      </header>

      {card.status === 'validation_failed' && (
        <Notice tone="warn" icon={<IconShield className="h-4 w-4" />}>
          Svarstexten kunde inte verifieras mot datan och har därför utelämnats.
          Diagrammet nedan kommer direkt från databasen.
        </Notice>
      )}

      {/* `pre-line` so the model's own paragraph breaks survive; the narrative is plain text,
          never markdown — the server strips emphasis markers before it gets here. */}
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

      {card.chart && card.query_id && (
        <div className="mt-6">
          {result.isPending && (
            <div style={{ height }}>
              <Skeleton className="h-full w-full" />
            </div>
          )}
          {result.isError && (
            <Notice tone="warn" icon={<IconInfo className="h-4 w-4" />}>
              Kunde inte hämta underlaget till diagrammet. {String(result.error)}
            </Notice>
          )}
          {result.data &&
            (view === 'chart' ? (
              <Chart
                spec={card.chart}
                columns={result.data.columns}
                rows={result.data.rows}
                height={height}
              />
            ) : (
              <DataTable
                columns={result.data.columns}
                rows={result.data.rows}
                caption={card.chart.title}
              />
            ))}
          {result.data?.truncated && (
            <p className="mt-3 text-2xs text-ink-muted">
              Visar de första {result.data.rows.length} raderna av {result.data.row_count}. Hela
              underlaget finns i CSV-exporten.
            </p>
          )}
        </div>
      )}

      {/* A chart without a query_id has nothing to draw from — the result query is
          disabled in that case, so guard here rather than leaving a skeleton forever. */}
      {(!card.chart || !card.query_id) && card.status === 'ok' && <EmptyState />}

      {card.status === 'clarify' && (
        <ChipRow
          label="Menade du"
          items={card.suggestions}
          onPick={onAsk}
          icon={<IconQuestion className="h-4 w-4" />}
        />
      )}

      {card.status === 'cannot_answer' && (
        <ChipRow
          label="Det här kan jag svara på"
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

      {card.provenance && (
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
  if (card.status === 'clarify') return 'Behöver en precisering'
  if (card.status === 'cannot_answer') return 'Det här har jag inte underlag för'
  return 'Svar'
}

function subtitleFor(card: Card): string | null {
  const provenance = card.provenance
  if (!provenance) return null
  return `${formatPeriod(provenance.time_range)} · nettoförsäljning, ${provenance.vat}`
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
      <p className="mt-3 text-sm text-ink-secondary">Inget diagram för det här svaret.</p>
    </div>
  )
}
