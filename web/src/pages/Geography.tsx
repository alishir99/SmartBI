
import { useState } from 'react'
import type { AnswerCard } from '../types'
import { FocusedCardPage } from './FocusedCardPage'
import { AnswerCardView } from '../components/AnswerCard'
import { RegionMap, type RegionDatum } from '../charts/RegionMap'
import { EmptyState } from '../components/ErrorState'
import { CardSkeleton } from '../components/Skeleton'
import { useRegions, useResult } from '../lib/queries'
import { useChatStore } from '../lib/chat'
import { columnLabel, useT } from '../lib/i18n'

type Tab = 'ranking' | 'map'

// Keys, and none of them names a place: a suggested question about "Skåne" is unanswerable
// against a warehouse holding any other market.
const FOLLOW_UP_KEYS = [
  'ask.grew_fastest',
  'ask.weekly_in_region',
  'ask.best_online',
  'ask.category_share_region',
]

export function GeographyPage() {
  const t = useT()
  const [tab, setTab] = useState<Tab>('ranking')

  return (
    <FocusedCardPage
      title={t('geography.title')}
      description={t('geography.description')}
      dimension="region"
      followUps={FOLLOW_UP_KEYS.map((key) => t(key))}
      render={(card) =>
        card ? (
          <section>
            <TabBar value={tab} onChange={setTab} />
            {tab === 'ranking' ? <RankingTab card={card} /> : <MapTab card={card} />}
          </section>
        ) : (
          <EmptyState title={t('geography.empty_title')} description={t('page.no_view')} />
        )
      }
    />
  )
}

function TabBar({ value, onChange }: { value: Tab; onChange: (tab: Tab) => void }) {
  const t = useT()
  const tabs: { key: Tab; label: string }[] = [
    { key: 'ranking', label: t('geography.tab_ranking') },
    { key: 'map', label: t('geography.tab_map') },
  ]
  return (
    <div
      role="tablist"
      aria-label={t('geography.tab_group')}
      className="mb-4 inline-flex gap-0.5 rounded-pill bg-surface-2 p-0.5 ring-hairline"
    >
      {tabs.map((tab) => (
        <button
          key={tab.key}
          type="button"
          role="tab"
          aria-selected={value === tab.key}
          onClick={() => onChange(tab.key)}
          className={[
            'rounded-pill px-4 py-1.5 text-xs font-medium transition-colors duration-200',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]',
            value === tab.key
              ? 'bg-surface text-ink shadow-card'
              : 'text-ink-secondary hover:text-ink',
          ].join(' ')}
        >
          {tab.label}
        </button>
      ))}
    </div>
  )
}

function RankingTab({ card }: { card: AnswerCard }) {
  const ask = useChatStore((state) => state.ask)
  return <AnswerCardView card={card} onAsk={(question) => void ask(question)} height={380} />
}

/** The map reads the same frozen result the bar chart draws from. */
function MapTab({ card }: { card: AnswerCard }) {
  const t = useT()
  const result = useResult(card.query_id ?? null)
  // Coordinates come from the warehouse, not a table shipped with the client - an ungeocoded
  // market gets an honest "no map" rather than invented positions.
  const regions = useRegions()

  if (result.isPending || regions.isPending) return <CardSkeleton height={560} />
  if (result.isError || !result.data) {
    return (
      <EmptyState
        title={t('geography.result_error_title')}
        description={t('geography.result_error')}
      />
    )
  }
  if (!regions.data || regions.data.length === 0) {
    return (
      <EmptyState
        title={t('geography.map_unavailable_title')}
        description={t('geography.map_unavailable')}
      />
    )
  }

  const measure = card.chart?.y?.[0] ?? 'net_sales_sek'
  const measureColumn = result.data.columns.find((column) => column.key === measure)
  const data: RegionDatum[] = result.data.rows
    .map((row) => ({
      region: String(row.region ?? ''),
      value: typeof row[measure] === 'number' ? (row[measure] as number) : 0,
    }))
    .filter((datum) => datum.region !== '')

  return (
    <div className="rounded-card bg-surface p-5 shadow-card ring-hairline">
      <RegionMap
        data={data}
        places={regions.data}
        label={columnLabel(measure, measureColumn?.label ?? measure)}
      />
    </div>
  )
}
