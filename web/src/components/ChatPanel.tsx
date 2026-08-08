
import { useEffect, useRef, useState } from 'react'
import type { ComponentType } from 'react'
import { useChatStore, type ChatTurn, type ToolChip } from '../lib/chat'
import { describeToolCall, toolLabel } from '../lib/tooltext'
import { formatNumber } from '../lib/format'
import { t as translate, useT } from '../lib/i18n'
import { AnswerCardView } from './AnswerCard'
import { Button } from './Button'
import { IconCheck, IconDatabase, IconPlug, IconSend, IconSparkle, IconStop } from './Icons'

// Deliberately generic: an example naming a Swedish county was a question nobody could ask
// of a warehouse holding anything else. "What is our margin?" stays to demonstrate a refusal.
const EXAMPLE_KEYS = ['ask.best_sellers', 'ask.monthly_trend', 'ask.top_products', 'ask.margin']

export function ChatPanel({ onClose }: { onClose?: () => void }) {
  const t = useT()
  const turns = useChatStore((state) => state.turns)
  const pending = useChatStore((state) => state.pending)
  const ask = useChatStore((state) => state.ask)
  const cancel = useChatStore((state) => state.cancel)
  const reset = useChatStore((state) => state.reset)

  const [draft, setDraft] = useState('')
  const scroller = useRef<HTMLDivElement>(null)
  const input = useRef<HTMLTextAreaElement>(null)

  // Follow the stream.
  useEffect(() => {
    const node = scroller.current
    if (node) node.scrollTop = node.scrollHeight
  }, [turns])

  const submit = (question: string) => {
    const trimmed = question.trim()
    if (!trimmed || pending) return
    setDraft('')
    void ask(trimmed)
  }

  return (
    <div className="flex h-full flex-col bg-surface">
      <header className="hairline-b flex items-center justify-between gap-3 px-5 py-4">
        <div>
          <h2 className="text-sm font-semibold text-ink">{t('chat.title')}</h2>
          <p className="mt-0.5 text-2xs text-ink-muted">{t('chat.subtitle')}</p>
        </div>
        <div className="flex items-center gap-1">
          {turns.length > 0 && (
            <Button variant="ghost" size="sm" onClick={reset}>
              {t('chat.clear')}
            </Button>
          )}
          {onClose && (
            <Button variant="ghost" size="sm" onClick={onClose} className="xl:hidden">
              {t('chat.close')}
            </Button>
          )}
        </div>
      </header>

      <div ref={scroller} className="quiet-scroll flex-1 space-y-6 overflow-y-auto px-5 py-5">
        {turns.length === 0 ? (
          <Welcome onPick={submit} />
        ) : (
          turns.map((turn) => <Turn key={turn.id} turn={turn} onAsk={submit} />)
        )}
      </div>

      <form
        className="hairline-t px-5 py-4"
        onSubmit={(event) => {
          event.preventDefault()
          submit(draft)
        }}
      >
        <div className="flex items-end gap-2 rounded-card bg-surface-2 p-2 pl-3.5 ring-hairline focus-within:ring-1 focus-within:ring-accent">
          <label htmlFor="chat-input" className="sr-only">
            {t('chat.input_label')}
          </label>
          <textarea
            id="chat-input"
            ref={input}
            rows={1}
            value={draft}
            onChange={(event) => {
              setDraft(event.target.value)
              const node = event.target
              node.style.height = 'auto'
              node.style.height = `${Math.min(node.scrollHeight, 140)}px`
            }}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                submit(draft)
              }
            }}
            placeholder={t('chat.placeholder')}
            className="max-h-[140px] flex-1 resize-none bg-transparent py-2 text-sm text-ink outline-none placeholder:text-ink-muted"
          />
          {pending ? (
            <Button
              variant="secondary"
              size="sm"
              iconOnly
              aria-label={t('chat.stop')}
              icon={<IconStop className="h-3.5 w-3.5" />}
              onClick={cancel}
            />
          ) : (
            <Button
              type="submit"
              variant="primary"
              size="sm"
              iconOnly
              aria-label={t('chat.send')}
              disabled={!draft.trim()}
              icon={<IconSend className="h-4 w-4" />}
            />
          )}
        </div>
      </form>
    </div>
  )
}

function Welcome({ onPick }: { onPick: (question: string) => void }) {
  const t = useT()
  return (
    <div className="animate-fade-in">
      <p className="text-sm leading-relaxed text-ink-secondary">{t('chat.welcome')}</p>
      <p className="mt-5 text-2xs font-medium uppercase tracking-wide text-ink-muted">
        {t('chat.try')}
      </p>
      <ul className="mt-2.5 space-y-2">
        {EXAMPLE_KEYS.map((key) => t(key)).map((example) => (
          <li key={example}>
            <button
              type="button"
              onClick={() => onPick(example)}
              className="w-full rounded-tile bg-surface-2 px-3.5 py-2.5 text-left text-sm text-ink-secondary transition-colors duration-200 hover:bg-surface-3 hover:text-ink"
            >
              {example}
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

function Turn({ turn, onAsk }: { turn: ChatTurn; onAsk: (question: string) => void }) {
  return (
    <article className="space-y-3">
      <p className="ml-auto w-fit max-w-[85%] rounded-card rounded-br-md bg-accent px-4 py-2.5 text-sm text-accent-fg">
        {turn.question}
      </p>

      <RequestFlow turn={turn} />

      {turn.chips.length > 0 && (
        <ul className="space-y-1.5">
          {turn.chips.map((chip) => (
            <ToolChipRow key={chip.id} chip={chip} />
          ))}
        </ul>
      )}

      {turn.statusMessage && (
        <p className="flex items-center gap-2 text-xs text-ink-muted">
          <span className="flex gap-1" aria-hidden="true">
            <Dot delay="0ms" />
            <Dot delay="160ms" />
            <Dot delay="320ms" />
          </span>
          {turn.statusMessage}
        </p>
      )}

      {(!turn.card || turn.cardIsPreview) && turn.streamedText && (
        <p className="text-sm leading-relaxed text-ink">{turn.streamedText}</p>
      )}

      {turn.card && (
        <AnswerCardView card={turn.card} onAsk={onAsk} height={220}
                        preview={turn.cardIsPreview} showSource />
      )}

      {turn.error && (
        <p className="rounded-tile bg-notice-bg p-3.5 text-sm text-notice-ink ring-1 ring-inset ring-notice-border">
          {turn.error}
        </p>
      )}
    </article>
  )
}

export function ToolChipRow({ chip }: { chip: ToolChip }) {
  return (
    <li className="flex items-center gap-2 text-2xs text-ink-secondary">
      <span className="inline-flex items-center gap-1.5 rounded-pill bg-surface-2 py-1 pl-2 pr-2.5">
        {chip.done ? (
          <IconCheck className="h-3 w-3 text-pos" />
        ) : (
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" aria-hidden="true" />
        )}
        <span className="whitespace-nowrap">{toolLabel(chip.tool)}</span>
      </span>
      <span className="truncate">
        {describeToolCall(chip.tool, chip.args)}
        {chip.rowCount !== null &&
          ` · ${translate('source.rows_count', { count: formatNumber(chip.rowCount) })}`}
      </span>
    </li>
  )
}

const FLOW: { icon: ComponentType<{ className?: string }>; short: string; labelKey: string }[] = [
  { icon: IconSparkle, short: 'LLM', labelKey: 'chat.step_llm' },
  { icon: IconPlug, short: 'MCP', labelKey: 'chat.step_mcp' },
  { icon: IconDatabase, short: 'DB', labelKey: 'chat.step_db' },
  { icon: IconPlug, short: 'MCP', labelKey: 'chat.step_mcp_back' },
  { icon: IconSparkle, short: 'LLM', labelKey: 'chat.step_llm_writes' },
]

export function flowStage(turn: ChatTurn): number {
  if (turn.status !== 'streaming') return FLOW.length
  if (turn.streamedText) return 4
  if (turn.chips.length === 0) return 0
  return turn.chips.every((chip) => chip.done) ? 3 : 2
}

function RequestFlow({ turn }: { turn: ChatTurn }) {
  const t = useT()
  const stage = flowStage(turn)
  const finished = stage >= FLOW.length

  return (
    <div className="rounded-tile bg-surface-2 px-3 py-2.5">
      <ol className="flex max-w-xs items-center" aria-label={t('chat.pipeline')}>
        {FLOW.map((step, index) => {
          const done = index < stage
          const active = index === stage
          return (
            <li key={index} className="flex min-w-0 flex-1 items-center last:flex-none">
              <span
                className={[
                  'relative grid h-7 w-7 shrink-0 place-items-center rounded-full transition-colors duration-300',
                  active
                    ? 'bg-accent text-accent-fg'
                    : done
                      ? 'bg-accent-soft text-accent'
                      : 'bg-surface text-ink-muted ring-hairline',
                ].join(' ')}
                title={t(step.labelKey)}
              >
                <step.icon className="h-3.5 w-3.5" />
                {active && (
                  <span
                    className="absolute inset-0 animate-ping rounded-full bg-accent opacity-30"
                    aria-hidden="true"
                  />
                )}
                <span className="sr-only">
                  {t(step.labelKey)}
                  {done ? t('chat.step_done') : active ? t('chat.step_active') : ''}
                </span>
              </span>
              {index < FLOW.length - 1 && (
                <span
                  aria-hidden="true"
                  className={`mx-1 h-0.5 min-w-2 flex-1 rounded-full ${
                    active ? 'flow-line' : done ? 'bg-accent' : 'bg-surface-3'
                  }`}
                />
              )}
            </li>
          )
        })}
      </ol>
      <p className="mt-2 text-2xs text-ink-muted">
        {finished
          ? `${FLOW.map((step) => step.short).join(' → ')} · ${t('chat.flow_done')}`
          : t(FLOW[stage].labelKey)}
      </p>
    </div>
  )
}

const Dot = ({ delay }: { delay: string }) => (
  <span
    className="h-1 w-1 animate-pulse rounded-full bg-ink-muted"
    style={{ animationDelay: delay }}
  />
)
