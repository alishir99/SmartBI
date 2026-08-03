/**
 * Produkter and Geografi are the same page with a different lens: take the dashboard card that
 * is already grouped by that dimension, give it the whole width, and offer follow-up questions
 * that hand off to the chat.
 */

import type { ReactNode } from 'react'
import type { AnswerCard } from '../types'
import { useDashboard } from '../lib/queries'
import { usePeriod } from '../lib/usePeriod'
import { PeriodFilter } from '../components/PeriodFilter'
import { useChatStore } from '../lib/chat'
import { AnswerCardView } from '../components/AnswerCard'
import { PageHeader } from '../components/PageHeader'
import { CardSkeleton } from '../components/Skeleton'
import { EmptyState, ErrorState } from '../components/ErrorState'
import { Button } from '../components/Button'
import { IconSend } from '../components/Icons'

type Props = {
  title: string
  description: string
  /** The x dimension the card must be grouped by, e.g. `product` or `region`. */
  dimension: string
  followUps: string[]
  /** Rendered in place of the card — Geografi uses it to offer a map alongside the bars. */
  render?: (card: AnswerCard | null) => ReactNode
}

export function FocusedCardPage({ title, description, dimension, followUps, render }: Props) {
  const [period, setPeriod] = usePeriod()
  const dashboard = useDashboard(period)
  const ask = useChatStore((state) => state.ask)

  if (dashboard.isPending) {
    return (
      <>
        <PageHeader title={title} description={description}>
          <PeriodFilter value={period} onChange={setPeriod} busy />
        </PageHeader>
        <CardSkeleton height={380} />
      </>
    )
  }

  if (dashboard.isError) {
    return <ErrorState error={dashboard.error} onRetry={() => dashboard.refetch()} />
  }

  const card = pick(dashboard.data.cards, dimension)

  return (
    <>
      <PageHeader title={title} description={description} provenance={card?.provenance ?? null}>
        <PeriodFilter value={period} onChange={setPeriod} busy={dashboard.isFetching} />
      </PageHeader>

      {render ? (
        render(card)
      ) : card ? (
        <AnswerCardView card={card} onAsk={(question) => void ask(question)} height={380} />
      ) : (
        <EmptyState
          title="Ingen färdig vy för den här dimensionen"
          description="Fråga i chatten så byggs vyn från din data."
          action={
            <Button
              variant="primary"
              size="sm"
              icon={<IconSend className="h-3.5 w-3.5" />}
              onClick={() => void ask(followUps[0])}
            >
              {followUps[0]}
            </Button>
          }
        />
      )}

      <section className="mt-7">
        <h2 className="text-xs font-medium uppercase tracking-wide text-ink-muted">Fråga vidare</h2>
        <ul className="mt-3 flex flex-wrap gap-2">
          {followUps.map((question) => (
            <li key={question}>
              <button
                type="button"
                onClick={() => void ask(question)}
                className="rounded-pill bg-surface px-4 py-2 text-sm text-ink-secondary shadow-card ring-hairline transition-colors duration-200 hover:text-ink"
              >
                {question}
              </button>
            </li>
          ))}
        </ul>
      </section>
    </>
  )
}

/** Match on the chart's x dimension rather than an index — card order is the backend's. */
function pick(cards: AnswerCard[], dimension: string): AnswerCard | null {
  return cards.find((card) => card.chart?.x === dimension) ?? null
}
