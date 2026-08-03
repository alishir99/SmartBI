/** Geografi - the regional cut, in two views. */

import { useState } from 'react'
import type { AnswerCard } from '../types'
import { FocusedCardPage } from './FocusedCardPage'
import { AnswerCardView } from '../components/AnswerCard'
import { RegionMap, type RegionDatum } from '../charts/RegionMap'
import { EmptyState } from '../components/ErrorState'
import { CardSkeleton } from '../components/Skeleton'
import { useResult } from '../lib/queries'
import { useChatStore } from '../lib/chat'

type Tab = 'ranking' | 'map'

export function GeographyPage() {
  const [tab, setTab] = useState<Tab>('ranking')

  return (
    <FocusedCardPage
      title="Geografi"
      description="Försäljning per län. Rangordningen är det man läser av - kartan visar var efterfrågan ligger."
      dimension="region"
      followUps={[
        'Var växer vi snabbast jämfört med förra året?',
        'Visa försäljning per vecka i Skåne',
        'Vilka län säljer mest online?',
        'Hur stor är vår andel av kategorin i Stockholms län?',
      ]}
      render={(card) =>
        card ? (
          <section>
            <TabBar value={tab} onChange={setTab} />
            {tab === 'ranking' ? <RankingTab card={card} /> : <MapTab card={card} />}
          </section>
        ) : (
          <EmptyState
            title="Ingen regional vy tillgänglig"
            description="Fråga i chatten så byggs vyn från din data."
          />
        )
      }
    />
  )
}

function TabBar({ value, onChange }: { value: Tab; onChange: (tab: Tab) => void }) {
  const tabs: { key: Tab; label: string }[] = [
    { key: 'ranking', label: 'Rangordning' },
    { key: 'map', label: 'Karta' },
  ]
  return (
    <div
      role="tablist"
      aria-label="Vy"
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
  const result = useResult(card.query_id ?? null)

  if (result.isPending) return <CardSkeleton height={560} />
  if (result.isError || !result.data) {
    return (
      <EmptyState
        title="Kunde inte läsa resultatet"
        description="Kartan ritas från samma resultat som stapeldiagrammet."
      />
    )
  }

  const measure = card.chart?.y?.[0] ?? 'net_sales_sek'
  const data: RegionDatum[] = result.data.rows
    .map((row) => ({
      region: String(row.region ?? ''),
      value: typeof row[measure] === 'number' ? (row[measure] as number) : 0,
    }))
    .filter((datum) => datum.region !== '')

  return (
    <div className="rounded-card bg-surface p-5 shadow-card ring-hairline">
      <RegionMap data={data} />
    </div>
  )
}
