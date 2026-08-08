
import { useState } from 'react'
import type { AnswerCard } from '../types'
import { downloadCsv } from '../lib/api'
import { useDeleteCard, useSaveCard, useShareCard } from '../lib/queries'
import { useT } from '../lib/i18n'
import { Button } from './Button'
import { IconCheck, IconDownload, IconLink, IconPin, IconPinFilled, IconShare, IconTrash } from './Icons'

/** The read side exists now: #/delad/{token} resolves through GET /api/shared. */
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
  const [savedCardId, setSavedCardId] = useState(card.card_id)
  const [pinned, setPinned] = useState(card.card_id !== null)

  const canPersist = savable && card.chart !== null && card.provenance !== null
  const canShare = SHARE_UI_ENABLED && (savedCardId !== null || canPersist)
  const canExport = card.query_id !== null && hasRows

  const persist = () =>
    new Promise<string>((resolve, reject) => {
      if (savedCardId) {
        resolve(savedCardId)
        return
      }
      if (!card.chart || !card.provenance) {
        reject(new Error('card has no chart or provenance to save'))
        return
      }
      save.mutate(
        {
          title: card.chart.title,
          chart: card.chart,
          tool_name: card.provenance.tool,
          tool_args: card.provenance.tool_args,
        },
        {
          onSuccess: (result) => {
            setSavedCardId(result.card_id)
            resolve(result.card_id as string)
          },
          onError: reject,
        },
      )
    })

  const onPin = () => {
    void persist().then(() => setPinned(true))
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

      {canShare && <ShareButton cardId={savedCardId} ensureSaved={persist} />}

      {canPersist && (
        <Button
          variant="ghost"
          size="sm"
          iconOnly
          loading={save.isPending}
          aria-label={pinned ? t('card.saved') : t('card.save')}
          title={pinned ? t('card.saved') : t('card.save')}
          icon={pinned ? <IconPinFilled className="h-4 w-4 text-accent" /> : <IconPin className="h-4 w-4" />}
          onClick={onPin}
          disabled={pinned}
        />
      )}

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

function ShareButton({
  cardId,
  ensureSaved,
}: {
  cardId: string | null
  ensureSaved: () => Promise<string>
}) {
  const t = useT()
  const [copied, setCopied] = useState(false)
  const share = useShareCard()
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

  const create = async () => {
    const id = cardId ?? (await ensureSaved())
    share.mutate({ cardId: id, mode: 'live' })
  }

  if (url) {
    return (
      <Button
        variant="outline"
        size="sm"
        icon={copied ? <IconCheck className="h-4 w-4" /> : <IconLink className="h-4 w-4" />}
        onClick={copy}
      >
        {copied ? t('card.share_copied') : t('card.share_copy')}
      </Button>
    )
  }

  return (
    <div className="flex items-center gap-2">
      <Button
        variant="ghost"
        size="sm"
        iconOnly
        loading={share.isPending}
        aria-label={t('card.share')}
        title={t('card.share_note')}
        icon={<IconShare className="h-4 w-4" />}
        onClick={() => void create()}
      />
      {share.isError && <p className="text-2xs text-neg">{t('card.share_failed')}</p>}
    </div>
  )
}

function csvName(card: AnswerCard): string {
  // NFD splits an accented letter into base + combining mark, which is then dropped -
  // "F\u00f6rs\u00e4ljning" becomes "forsaljning" without a per-language table.
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
