/** Översikt - the deterministic dashboard. */

import { useDashboard } from '../lib/queries'
import { usePeriod } from '../lib/usePeriod'
import { PeriodFilter } from '../components/PeriodFilter'
import { useChatStore } from '../lib/chat'
import { AnswerCardView } from '../components/AnswerCard'
import { KpiTile } from '../components/KpiTile'
import { PageHeader } from '../components/PageHeader'
import { CardSkeleton, KpiSkeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'

const DESCRIPTION = 'Din försäljning hos handlaren, mot perioden dessförinnan.'

/**
 * `auto-fit` rather than a viewport breakpoint: the chat rail is draggable, so how wide the
 * viewport is says nothing about how wide this column is. `min(…, 100%)` is what stops a track
 * wider than its container overflowing when the rail is pulled out.
 */
const KPI_GRID = 'grid gap-4 grid-cols-[repeat(auto-fit,minmax(min(13rem,100%),1fr))]'

export function OverviewPage() {
  const [period, setPeriod] = usePeriod()
  const dashboard = useDashboard(period)
  const ask = useChatStore((state) => state.ask)

  if (dashboard.isPending) {
    return (
      <>
        <PageHeader
          title="Översikt"
          description={DESCRIPTION}
        >
          <PeriodFilter value={period} onChange={setPeriod} busy />
        </PageHeader>
        <div className={KPI_GRID}>
          {[0, 1, 2, 3].map((index) => (
            <KpiSkeleton key={index} />
          ))}
        </div>
        <div className="mt-6 space-y-6">
          <CardSkeleton />
          <CardSkeleton />
        </div>
      </>
    )
  }

  if (dashboard.isError) {
    return <ErrorState error={dashboard.error} onRetry={() => dashboard.refetch()} />
  }

  const { kpis, cards } = dashboard.data
  const provenance = cards.find((card) => card.provenance)?.provenance ?? null

  return (
    <>
      <PageHeader
        title="Översikt"
        description={DESCRIPTION}
        provenance={provenance}
      >
        <PeriodFilter value={period} onChange={setPeriod} busy={dashboard.isFetching} />
      </PageHeader>

      <div className={KPI_GRID}>
        {kpis.map((kpi) => (
          <KpiTile key={kpi.key} kpi={kpi} onAsk={(question) => void ask(question)} />
        ))}
      </div>

      <div className="mt-6 space-y-6">
        {cards.map((card, index) => (
          <AnswerCardView
            key={card.card_id ?? card.query_id ?? index}
            card={card}
            onAsk={(question) => void ask(question)}
            height={index === 0 ? 300 : 280}
          />
        ))}
      </div>
    </>
  )
}
