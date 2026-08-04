/**
 * Produkter - the movers page. It used to be the same "Topp 10 produkter" chart that is already
 * on the overview, which gave it no reason to exist. "What is rising and what is falling" is the
 * question a supplier opens a product page to ask.
 */

import type { Provenance } from '../types'
import { useMovers } from '../lib/queries'
import { usePeriod } from '../lib/usePeriod'
import { PeriodFilter } from '../components/PeriodFilter'
import { useChatStore } from '../lib/chat'
import { AnswerCardView } from '../components/AnswerCard'
import { PageHeader } from '../components/PageHeader'
import { CardSkeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'
import { useT } from '../lib/i18n'

// Keys, not sentences, and none of them names a place: a suggested question mentioning a
// Swedish county is unanswerable against a warehouse holding anything else.
const FOLLOW_UP_KEYS = [
  'ask.why_falling',
  'ask.online_vs_store',
  'ask.top_products',
  'ask.highest_avg_price',
]

/**
 * `auto-fit` rather than `xl:grid-cols-2`: the chat rail is draggable, so a viewport breakpoint
 * says nothing about how much width these two cards actually have. Below the track's minimum
 * they stack instead of squeezing a ten-row ranking into 200 px.
 */
const CARD_GRID = 'grid gap-6 grid-cols-[repeat(auto-fit,minmax(min(26rem,100%),1fr))]'

export function ProductsPage() {
  const t = useT()
  const [period, setPeriod] = usePeriod()
  const movers = useMovers(period)
  const ask = useChatStore((state) => state.ask)

  const header = (provenance: Provenance | null = null) => (
    <PageHeader
      title={t('products.title')}
      description={t('products.description')}
      provenance={provenance}
    >
      <PeriodFilter value={period} onChange={setPeriod} busy={movers.isFetching} />
    </PageHeader>
  )

  if (movers.isPending) {
    return (
      <>
        {header()}
        <div className={CARD_GRID}>
          <CardSkeleton height={340} />
          <CardSkeleton height={340} />
        </div>
      </>
    )
  }

  if (movers.isError) {
    return <ErrorState error={movers.error} onRetry={() => movers.refetch()} />
  }

  const { cards } = movers.data

  return (
    <>
      {header(cards[0]?.provenance ?? null)}

      {/* Side by side when there is room, stacked when there is not: two ranked lists of ten
          each need the width. */}
      <div className={CARD_GRID}>
        {cards.map((card) => (
          <AnswerCardView
            key={card.query_id}
            card={card}
            onAsk={(question) => void ask(question)}
            height={340}
          />
        ))}
      </div>

      <section className="mt-7">
        <h2 className="text-xs font-medium uppercase tracking-wide text-ink-muted">
          {t('page.ask_more')}
        </h2>
        <ul className="mt-3 flex flex-wrap gap-2">
          {FOLLOW_UP_KEYS.map((key) => t(key)).map((question) => (
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
