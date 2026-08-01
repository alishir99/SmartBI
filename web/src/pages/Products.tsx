/**
 * Produkter — the movers page. It used to be the same "Topp 10 produkter" chart that is already
 * on the overview, which gave it no reason to exist. "What is rising and what is falling" is the
 * question a supplier opens a product page to ask.
 */

import type { Provenance } from '../types'
import { useMovers } from '../lib/queries'
import { useCompareBasis, usePeriod } from '../lib/usePeriod'
import { BasisFilter, PeriodFilter } from '../components/PeriodFilter'
import { useChatStore } from '../lib/chat'
import { AnswerCardView } from '../components/AnswerCard'
import { PageHeader } from '../components/PageHeader'
import { CardSkeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'

const FOLLOW_UPS = [
  'Varför tappar produkten som backar mest?',
  'Vilka produkter säljer bäst online jämfört med i butik?',
  'Visa topp 10 produkter i Stockholms län',
  'Vilken produkt har högst snittpris?',
]

export function ProductsPage() {
  const [period, setPeriod] = usePeriod()
  // "Ingen jämförelse" has no meaning here — movers are a comparison by definition, and the
  // server falls back to the default for that reason. The control still picks which comparison.
  const [basis, setBasis] = useCompareBasis()
  const movers = useMovers(period, basis)
  const ask = useChatStore((state) => state.ask)

  const header = (provenance: Provenance | null = null) => (
    <PageHeader
      title="Produkter"
      description="Vad som rör sig mest — upp och ned — mot jämförelseperioden."
      provenance={provenance}
    >
      <div className="flex flex-wrap items-center justify-end gap-2">
        <PeriodFilter value={period} onChange={setPeriod} busy={movers.isFetching} />
        <BasisFilter value={basis} onChange={setBasis} busy={movers.isFetching} />
      </div>
    </PageHeader>
  )

  if (movers.isPending) {
    return (
      <>
        {header()}
        <div className="grid gap-6 xl:grid-cols-2">
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

      {/* Side by side above xl, stacked below: two ranked lists of ten each need the full
          width on a laptop. */}
      <div className="grid gap-6 xl:grid-cols-2">
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
        <h2 className="text-xs font-medium uppercase tracking-wide text-ink-muted">Fråga vidare</h2>
        <ul className="mt-3 flex flex-wrap gap-2">
          {FOLLOW_UPS.map((question) => (
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
