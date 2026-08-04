/**
 * A shared card, for someone with no account here.
 *
 * Deliberately not the app: no navigation, no chat, no period filter, nothing to save. One
 * card, who shared it, when the link stops working, and a sentence about what the reader is
 * looking at. The link cannot be widened - which card and whose scope are both signed into the
 * token, and the query runs as the supplier who shared it.
 */

import { useEffect, useState } from 'react'
import type { SharedView } from '../types'
import { fetchShared } from '../lib/api'
import { formatDateLong } from '../lib/format'
import { AnswerCardView } from '../components/AnswerCard'
import { CardSkeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'
import { useT } from '../lib/i18n'

export function SharedPage({ token }: { token: string }) {
  const t = useT()
  const [state, setState] = useState<
    { status: 'loading' } | { status: 'ok'; view: SharedView } | { status: 'error'; error: unknown }
  >({ status: 'loading' })

  useEffect(() => {
    let live = true
    setState({ status: 'loading' })
    fetchShared(token)
      .then((view) => live && setState({ status: 'ok', view }))
      .catch((error: unknown) => live && setState({ status: 'error', error }))
    return () => {
      live = false
    }
  }, [token])

  return (
    <div className="mx-auto min-h-dvh w-full max-w-4xl px-5 py-10 sm:px-8">
      <header className="mb-7">
        <p className="text-2xs font-medium uppercase tracking-wide text-ink-muted">
          {t('shared.eyebrow')}
        </p>
        {state.status === 'ok' && (
          <>
            <h1 className="mt-2 text-2xl font-semibold tracking-tight text-ink">
              {state.view.card.chart?.title ?? t('shared.title')}
            </h1>
            <p className="mt-2 text-sm text-ink-secondary">
              {t('shared.by', { name: state.view.shared_by })}
            </p>
            <p className="mt-1.5 text-2xs text-ink-muted">
              {t('shared.expires', {
                date: formatDateLong(state.view.expires_at.slice(0, 10)),
              })}
            </p>
          </>
        )}
      </header>

      {state.status === 'loading' && <CardSkeleton height={380} />}

      {state.status === 'error' && (
        <ErrorState error={state.error} onRetry={() => setState({ status: 'loading' })} />
      )}

      {state.status === 'ok' && (
        <AnswerCardView
          card={state.view.card}
          rows={state.view.result}
          savable={false}
          height={380}
        />
      )}

      <footer className="mt-8 text-2xs text-ink-muted">
        {t('shared.footer')}
      </footer>
    </div>
  )
}
