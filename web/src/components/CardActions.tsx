/**
 * The action row on a card: switch to the table view, export the underlying rows, pin the card,
 * or share it.
 */

import { useEffect, useRef, useState } from 'react'
import type { AnswerCard } from '../types'
import { downloadCsv } from '../lib/api'
import { useDeleteCard, useSaveCard, useShareCard } from '../lib/queries'
import { useT } from '../lib/i18n'
import { Button } from './Button'
import { IconCheck, IconDownload, IconPin, IconShare, IconTrash } from './Icons'

/** The read side exists now: `#/delad/{token}` resolves through GET /api/shared. */
const SHARE_UI_ENABLED = true

type Props = {
  card: AnswerCard
  view: 'chart' | 'table'
  onToggleView: (view: 'chart' | 'table') => void
  onDelete?: (cardId: string) => void
  savable: boolean
  hasRows: boolean
}

export function CardActions({ card, view, onToggleView, onDelete, savable, hasRows }: Props) {
  const t = useT()
  const save = useSaveCard()
  const remove = useDeleteCard()
  const [saved, setSaved] = useState(false)

  const canSave = savable && !card.card_id && card.chart !== null && card.provenance !== null
  const canExport = card.query_id !== null && hasRows

  const onSave = () => {
    if (!card.chart || !card.provenance) return
    save.mutate(
      {
        title: card.chart.title,
        chart: card.chart,
        tool_name: card.provenance.tool,
        tool_args: card.provenance.tool_args,
      },
      { onSuccess: () => setSaved(true) },
    )
  }

  if (!card.chart && !canExport) return null

  return (
    <div className="flex shrink-0 flex-wrap items-center gap-1.5">
      {card.chart && (
        <div
          role="group"
          aria-label={t('card.view_mode')}
          className="flex items-center gap-0.5 rounded-pill bg-surface-2 p-0.5"
        >
          <ViewTab active={view === 'chart'} onClick={() => onToggleView('chart')}>
            {t('card.view_chart')}
          </ViewTab>
          <ViewTab active={view === 'table'} onClick={() => onToggleView('table')}>
            {t('card.view_table')}
          </ViewTab>
        </div>
      )}

      {canExport && (
        <Button
          variant="ghost"
          size="sm"
          iconOnly
          aria-label={t('card.export_csv')}
          title={t('card.export_csv')}
          icon={<IconDownload className="h-4 w-4" />}
          onClick={() => downloadCsv(card.query_id as string, csvName(card))}
        />
      )}

      {canSave && (
        <Button
          variant="ghost"
          size="sm"
          iconOnly
          loading={save.isPending}
          aria-label={saved ? t('card.saved') : t('card.save')}
          title={saved ? t('card.saved') : t('card.save')}
          icon={saved ? <IconCheck className="h-4 w-4 text-pos" /> : <IconPin className="h-4 w-4" />}
          onClick={onSave}
          disabled={saved}
        />
      )}

      {SHARE_UI_ENABLED && card.card_id && <ShareMenu cardId={card.card_id} />}

      {card.card_id && onDelete && (
        <Button
          variant="ghost"
          size="sm"
          iconOnly
          loading={remove.isPending}
          aria-label={t('card.delete')}
          title={t('card.delete')}
          icon={<IconTrash className="h-4 w-4" />}
          onClick={() => onDelete(card.card_id as string)}
        />
      )}
    </div>
  )
}

function ViewTab({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: string
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`rounded-pill px-3 py-1 text-2xs font-medium transition-colors duration-200 ${
        active ? 'bg-surface text-ink shadow-card' : 'text-ink-secondary hover:text-ink'
      }`}
    >
      {children}
    </button>
  )
}

function ShareMenu({ cardId }: { cardId: string }) {
  const t = useT()
  const [open, setOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  const share = useShareCard()
  const container = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (event: MouseEvent) => {
      if (!container.current?.contains(event.target as Node)) setOpen(false)
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const url = share.data?.url ?? null

  const copy = async () => {
    if (!url) return
    try {
      await navigator.clipboard.writeText(url)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      /* clipboard blocked - the link is on screen and selectable */
    }
  }

  return (
    <div className="relative" ref={container}>
      <Button
        variant="ghost"
        size="sm"
        iconOnly
        aria-label={t('card.share')}
        aria-expanded={open}
        title={t('card.share')}
        icon={<IconShare className="h-4 w-4" />}
        onClick={() => setOpen((current) => !current)}
      />

      {open && (
        <div className="animate-fade-in absolute right-0 top-full z-20 mt-2 w-72 rounded-tile bg-surface p-4 shadow-pop ring-hairline">
          <p className="text-xs font-medium text-ink">{t('card.share_title')}</p>
          <div className="mt-3 space-y-2">
            {/* One option, because one is served. A frozen snapshot means storing the rows as
                they were, which is a table and a retention rule rather than a flag. */}
            <ShareOption
              title={t('card.share_create')}
              description={t('card.share_note')}
              loading={share.isPending}
              onClick={() => share.mutate({ cardId, mode: 'live' })}
            />
          </div>

          {url && (
            <div className="mt-3">
              <p className="break-all rounded-lg bg-surface-2 p-2.5 font-mono text-2xs text-ink-secondary">
                {url}
              </p>
              <Button variant="quiet" size="sm" className="mt-2 w-full" onClick={copy}>
                {copied ? t('card.share_copied') : t('card.share_copy')}
              </Button>
            </div>
          )}
          {share.isError && (
            <p className="mt-3 text-2xs text-neg">{t('card.share_failed')}</p>
          )}
        </div>
      )}
    </div>
  )
}

function ShareOption({
  title,
  description,
  loading,
  onClick,
}: {
  title: string
  description: string
  loading: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={loading}
      className="w-full rounded-lg p-2.5 text-left transition-colors duration-200 hover:bg-surface-2 disabled:opacity-50"
    >
      <span className="block text-xs font-medium text-ink">{title}</span>
      <span className="mt-0.5 block text-2xs leading-snug text-ink-muted">{description}</span>
    </button>
  )
}

/** `topp-10-produkter-2026-06-30.csv` - readable in a downloads folder a week later. */
function csvName(card: AnswerCard): string {
  // NFD splits an accented letter into base + combining mark, and the mark is then
  // dropped: "Försäljning" becomes "forsaljning" without a per-language table, and Greek,
  // Cyrillic or Japanese titles fall back to the date rather than to a row of hyphens.
  const base = (card.chart?.title ?? 'export')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
    .slice(0, 48)
  const day = (card.provenance?.executed_at ?? new Date().toISOString()).slice(0, 10)
  return `${base || 'export'}-${day}.csv`
}
