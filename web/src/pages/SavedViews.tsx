
import { useDeleteCard, useSavedCards } from '../lib/queries'
import { useChatStore } from '../lib/chat'
import { AnswerCardView } from '../components/AnswerCard'
import { PageHeader } from '../components/PageHeader'
import { CardSkeleton } from '../components/Skeleton'
import { EmptyState, ErrorState } from '../components/ErrorState'
import { useT } from '../lib/i18n'

export function SavedViewsPage() {
  const t = useT()
  const cards = useSavedCards()
  const remove = useDeleteCard()
  const ask = useChatStore((state) => state.ask)

  if (cards.isPending) {
    return (
      <>
        <PageHeader title={t('saved.title')} description={t('saved.description')} />
        <CardSkeleton />
      </>
    )
  }

  if (cards.isError) {
    return <ErrorState error={cards.error} onRetry={() => cards.refetch()} />
  }

  return (
    <>
      <PageHeader title={t('saved.title')} description={t('saved.description')} />

      {cards.data.length === 0 ? (
        <EmptyState
          title={t('saved.empty_title')}
          description={t('saved.empty')}
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
