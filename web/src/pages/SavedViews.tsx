/**
 * Mina vyer. A saved card holds the spec plus the tool arguments — not a screenshot —
 * so every card on this page re-runs live against fresh data when it is opened. That is
 * also why deleting one is cheap: nothing is lost but the pin.
 */

import { useDeleteCard, useSavedCards } from '../lib/queries'
import { useChatStore } from '../lib/chat'
import { AnswerCardView } from '../components/AnswerCard'
import { PageHeader } from '../components/PageHeader'
import { CardSkeleton } from '../components/Skeleton'
import { EmptyState, ErrorState } from '../components/ErrorState'

export function SavedViewsPage() {
  const cards = useSavedCards()
  const remove = useDeleteCard()
  const ask = useChatStore((state) => state.ask)

  if (cards.isPending) {
    return (
      <>
        <PageHeader title="Mina vyer" description="Kort du har sparat." />
        <CardSkeleton />
      </>
    )
  }

  if (cards.isError) {
    return <ErrorState error={cards.error} onRetry={() => cards.refetch()} />
  }

  return (
    <>
      <PageHeader
        title="Mina vyer"
        description="Sparade kort körs om mot färsk data varje gång du öppnar dem."
      />

      {cards.data.length === 0 ? (
        <EmptyState
          title="Inga sparade vyer än"
          description="Fäst ett kort från översikten eller från ett chattsvar, så hamnar det här."
        />
      ) : (
        <div className="space-y-6">
          {cards.data.map((card) => (
            <AnswerCardView
              key={card.card_id ?? card.query_id}
              card={card}
              onAsk={(question) => void ask(question)}
              onDelete={(cardId) => remove.mutate(cardId)}
              savable={false}
              height={300}
            />
          ))}
        </div>
      )}
    </>
  )
}
