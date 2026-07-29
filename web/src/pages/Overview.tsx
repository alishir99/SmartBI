/**
 * Översikt — the deterministic dashboard. No model is involved in producing it: the
 * backend runs the same MCP tools server-side, so the numbers here and the numbers the
 * chat returns are the same numbers, with the same provenance.
 */

import { useDashboard } from '../lib/queries'
import { usePeriod } from '../lib/usePeriod'
import { PeriodFilter } from '../components/PeriodFilter'
import { useChatStore } from '../lib/chat'
import { AnswerCardView } from '../components/AnswerCard'
import { KpiTile } from '../components/KpiTile'
import { PageHeader } from '../components/PageHeader'
import { CardSkeleton, KpiSkeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'

export function OverviewPage() {
  const [period, setPeriod] = usePeriod()
  const dashboard = useDashboard(period)
  const ask = useChatStore((state) => state.ask)

  if (dashboard.isPending) {
    return (
      <>
        <PageHeader
          title="Översikt"
          description="Din försäljning hos handlaren."
        >
          <PeriodFilter value={period} onChange={setPeriod} busy />
        </PageHeader>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
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
        description="Din försäljning hos handlaren."
        provenance={provenance}
      >
        <PeriodFilter value={period} onChange={setPeriod} busy={dashboard.isFetching} />
      </PageHeader>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {kpis.map((kpi) => (
          <KpiTile key={kpi.key} kpi={kpi} />
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
