/** The chat rail. */

import { useEffect, useRef, useState } from 'react'
import type { ComponentType } from 'react'
import { useChatStore, type ChatTurn, type ToolChip } from '../lib/chat'
import { describeToolCall, toolLabel } from '../lib/tooltext'
import { formatNumber } from '../lib/format'
import { AnswerCardView } from './AnswerCard'
import { Button } from './Button'
import { IconCheck, IconDatabase, IconPlug, IconSend, IconSparkle, IconStop } from './Icons'

const EXAMPLES = [
  'Vilka produkter säljer bäst i Stockholm?',
  'Hur har försäljningen utvecklats per månad?',
  'Hur går det för lurar?',
  'Vad är vår marginal?',
]

export function ChatPanel({ onClose }: { onClose?: () => void }) {
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
          <h2 className="text-sm font-semibold text-ink">Fråga datan</h2>
          <p className="mt-0.5 text-2xs text-ink-muted">Svar direkt ur din försäljningsdata</p>
        </div>
        <div className="flex items-center gap-1">
          {turns.length > 0 && (
            <Button variant="ghost" size="sm" onClick={reset}>
              Rensa
            </Button>
          )}
          {onClose && (
            <Button variant="ghost" size="sm" onClick={onClose} className="xl:hidden">
              Stäng
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
            Ställ en fråga om din försäljning
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
              // Enter sends; Shift+Enter is a newline - the convention users already have.
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                submit(draft)
              }
            }}
            placeholder="Fråga om din försäljning…"
            className="max-h-[140px] flex-1 resize-none bg-transparent py-2 text-sm text-ink outline-none placeholder:text-ink-muted"
          />
          {pending ? (
            <Button
              variant="secondary"
              size="sm"
              iconOnly
              aria-label="Avbryt"
              icon={<IconStop className="h-3.5 w-3.5" />}
              onClick={cancel}
            />
          ) : (
            <Button
              type="submit"
              variant="primary"
              size="sm"
              iconOnly
              aria-label="Skicka"
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
  return (
    <div className="animate-fade-in">
      <p className="text-sm leading-relaxed text-ink-secondary">
        Ställ frågan på svenska. Varje svar kommer med ett diagram som ritas ur raderna
        frågan hämtade - aldrig ur en siffra modellen hittat på.
      </p>
      <p className="mt-5 text-2xs font-medium uppercase tracking-wide text-ink-muted">
        Prova
      </p>
      <ul className="mt-2.5 space-y-2">
        {EXAMPLES.map((example) => (
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

      {/* The streamed prose is a preview; once the card lands it owns the narrative. The
          chart-only preview card carries no narrative, so it does not yet own it. */}
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

/** Exported for the render test: a lookup that succeeded once read "✓ Uppslag · 0 rader". */
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
        {chip.rowCount !== null && ` · ${formatNumber(chip.rowCount)} rader`}
      </span>
    </li>
  )
}

/**
 * The route an answer actually takes. Nothing here reaches the database directly: the model
 * writes tool arguments, the MCP server is the only thing that talks to the warehouse, and what
 * comes back is rows the model then has to put into words. Showing the round trip is the
 * difference between "the assistant knows" and "the assistant asked, and here is who answered".
 */
const FLOW: { icon: ComponentType<{ className?: string }>; short: string; label: string }[] = [
  { icon: IconSparkle, short: 'LLM', label: 'Modellen tolkar frågan och väljer verktyg' },
  { icon: IconPlug, short: 'MCP', label: 'Anropet går genom MCP-servern' },
  { icon: IconDatabase, short: 'DB', label: 'Databasen körs mot din behörighet' },
  { icon: IconPlug, short: 'MCP', label: 'Raderna kommer tillbaka genom MCP' },
  { icon: IconSparkle, short: 'LLM', label: 'Modellen formulerar svaret ur raderna' },
]

/** Which node the turn is on right now; `FLOW.length` once the whole chain has completed. */
export function flowStage(turn: ChatTurn): number {
  if (turn.status !== 'streaming') return FLOW.length
  if (turn.streamedText) return 4
  if (turn.chips.length === 0) return 0
  // The call out and the query itself are one event from here, so the outbound hop reads as
  // passed rather than pending.
  return turn.chips.every((chip) => chip.done) ? 3 : 2
}

function RequestFlow({ turn }: { turn: ChatTurn }) {
  const stage = flowStage(turn)
  const finished = stage >= FLOW.length

  return (
    <div className="rounded-tile bg-surface-2 px-3 py-2.5">
      {/* Capped: the rail is draggable up to 720 px, and five 28 px nodes stretched across all
          of it stop reading as one chain. */}
      <ol className="flex max-w-xs items-center" aria-label="Så hanteras frågan">
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
                title={step.label}
              >
                <step.icon className="h-3.5 w-3.5" />
                {active && (
                  <span
                    className="absolute inset-0 animate-ping rounded-full bg-accent opacity-30"
                    aria-hidden="true"
                  />
                )}
                <span className="sr-only">
                  {step.label}
                  {done ? ' - klart' : active ? ' - pågår' : ''}
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
          ? `${FLOW.map((step) => step.short).join(' → ')} · svaret kommer från raderna, inte från modellens minne`
          : FLOW[stage].label}
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
