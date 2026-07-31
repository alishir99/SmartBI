/** Failure is a designed state too. */

import type { ReactNode } from 'react'
import { ApiError } from '../lib/api'
import { Button } from './Button'
import { IconInfo } from './Icons'

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message =
    error instanceof ApiError || error instanceof Error
      ? error.message
      : 'Något gick fel när datan skulle hämtas.'

  return (
    <div className="rounded-card bg-surface p-8 text-center shadow-card ring-hairline">
      <IconInfo className="mx-auto h-6 w-6 text-ink-muted" />
      <p className="mt-3 text-sm text-ink">{message}</p>
      {onRetry && (
        <Button variant="secondary" size="sm" className="mt-5" onClick={onRetry}>
          Försök igen
        </Button>
      )}
    </div>
  )
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string
  description: string
  action?: ReactNode
}) {
  return (
    <div className="rounded-card bg-surface p-10 text-center shadow-card ring-hairline">
      <p className="text-sm font-medium text-ink">{title}</p>
      <p className="mx-auto mt-1.5 max-w-sm text-sm text-ink-secondary">{description}</p>
      {action && <div className="mt-5 flex justify-center">{action}</div>}
    </div>
  )
}
