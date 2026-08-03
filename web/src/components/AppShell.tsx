/** The frame: navigation on the left, content in the middle, chat on the right. */

import {
  useEffect,
  useRef,
  useState,
  type ComponentType,
  type CSSProperties,
  type ReactNode,
} from 'react'
import { navigate, type Route } from '../lib/router'
import { useAuthStore } from '../lib/auth'
import { useChatStore } from '../lib/chat'
import { THEME_LABELS, useThemeStore } from '../lib/theme'
import { ChatPanel } from './ChatPanel'
import { Button } from './Button'
import {
  IconGeo,
  IconLogout,
  IconMoon,
  IconOverview,
  IconPin,
  IconProducts,
  IconSend,
  IconSun,
} from './Icons'

type NavItem = { route: Route; label: string; icon: ComponentType<{ className?: string }> }

const NAV: NavItem[] = [
  { route: 'oversikt', label: 'Översikt', icon: IconOverview },
  { route: 'produkter', label: 'Produkter', icon: IconProducts },
  { route: 'geografi', label: 'Geografi', icon: IconGeo },
  { route: 'mina-vyer', label: 'Mina vyer', icon: IconPin },
]

/** Tailwind's default `xl`, where the chat rail becomes permanent. */
const RAIL_BREAKPOINT = '(min-width: 1280px)'

/** The rail's width in px: default 26rem, narrow enough to still read, wide enough for a chart. */
const RAIL_DEFAULT = 416
const RAIL_MIN = 320
const RAIL_MAX = 720
const RAIL_KEY = 'solvigo.rail'

/** Room the page keeps for itself whatever the rail is dragged to. */
const PAGE_MIN = 520

function clampRail(px: number): number {
  // The rail must not be draggable past the point where the page it sits next to stops being
  // usable - a stored width from a wider screen must not survive onto a narrower one either.
  const max = Math.max(RAIL_MIN, Math.min(RAIL_MAX, window.innerWidth - PAGE_MIN))
  return Math.min(max, Math.max(RAIL_MIN, Math.round(px)))
}

function useRailWidth(): [number, (px: number) => void] {
  const [width, set] = useState(() => {
    try {
      return clampRail(Number(localStorage.getItem(RAIL_KEY)) || RAIL_DEFAULT)
    } catch {
      // Private mode or a blocked origin - the default is a fine answer.
      return RAIL_DEFAULT
    }
  })
  return [
    width,
    (px: number) => {
      const next = clampRail(px)
      set(next)
      try {
        localStorage.setItem(RAIL_KEY, String(next))
      } catch {
        // Not being able to persist the choice must not stop it taking effect.
      }
    },
  ]
}

export function AppShell({ route, children }: { route: Route; children: ReactNode }) {
  const [chatOpen, setChatOpen] = useState(false)
  const [railWidth, setRailWidth] = useRailWidth()
  const turnCount = useChatStore((state) => state.turns.length)
  const seenTurns = useRef(turnCount)

  // A question can start from outside the chat - the suggestion chips under every card call
  // `ask` directly.
  useEffect(() => {
    const started = turnCount > seenTurns.current
    seenTurns.current = turnCount
    if (started && !window.matchMedia(RAIL_BREAKPOINT).matches) setChatOpen(true)
  }, [turnCount])

  // The slide-over is a modal on small screens; Escape must close it.
  useEffect(() => {
    if (!chatOpen) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setChatOpen(false)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [chatOpen])

  return (
    // `--rail` rather than an inline width: the rail only exists from xl up, and keeping the
    // breakpoint in the class list is what stops the custom width leaking into the slide-over.
    <div className="flex min-h-screen bg-page" style={{ '--rail': `${railWidth}px` } as CSSProperties}>
      <Sidebar route={route} />

      <div className="min-w-0 flex-1 xl:mr-[var(--rail)]">
        <MobileBar route={route} />
        <main id="main" tabIndex={-1} className="px-5 py-6 outline-none sm:px-8 sm:py-8">
          {children}
        </main>
      </div>

      {/* Permanent rail from xl up. */}
      <aside className="fixed right-0 top-0 hidden h-screen w-[var(--rail)] border-l border-hairline xl:block">
        <RailHandle width={railWidth} onResize={setRailWidth} />
        <ChatPanel />
      </aside>

      {/* Slide-over below xl. */}
      {chatOpen && (
        <div className="fixed inset-0 z-40 xl:hidden">
          <div
            className="animate-fade-in absolute inset-0 bg-black/30"
            onClick={() => setChatOpen(false)}
            aria-hidden="true"
          />
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Fråga datan"
            className="animate-fade-in absolute right-0 top-0 h-full w-full max-w-[26rem] shadow-pop"
          >
            <ChatPanel onClose={() => setChatOpen(false)} />
          </div>
        </div>
      )}

      <Button
        variant="primary"
        size="lg"
        icon={<IconSend className="h-4 w-4" />}
        onClick={() => setChatOpen(true)}
        className="fixed bottom-6 right-6 z-30 shadow-lift xl:hidden"
      >
        Fråga datan
      </Button>
    </div>
  )
}

/**
 * The drag edge between the page and the chat rail - the ARIA window-splitter pattern, so it
 * works from the keyboard too rather than being a mouse-only affordance.
 */
function RailHandle({ width, onResize }: { width: number; onResize: (px: number) => void }) {
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="Ändra chattens bredd"
      aria-valuenow={width}
      aria-valuemin={RAIL_MIN}
      aria-valuemax={RAIL_MAX}
      tabIndex={0}
      // Dragging leftwards widens the rail, so the width is the distance from the right edge.
      onPointerDown={(event) => {
        event.preventDefault()
        event.currentTarget.setPointerCapture(event.pointerId)
      }}
      onPointerMove={(event) => {
        if (!event.currentTarget.hasPointerCapture(event.pointerId)) return
        onResize(window.innerWidth - event.clientX)
      }}
      onKeyDown={(event) => {
        const step = event.key === 'ArrowLeft' ? 24 : event.key === 'ArrowRight' ? -24 : 0
        if (!step) return
        event.preventDefault()
        onResize(width + step)
      }}
      className="absolute left-0 top-0 z-10 h-full w-2 -translate-x-1/2 cursor-col-resize touch-none transition-colors duration-200 hover:bg-accent/40 focus-visible:bg-accent/60 focus-visible:outline-none"
    />
  )
}

/** Below `md` the sidebar is gone, so navigation, identity and theme move up here. */
function MobileBar({ route }: { route: Route }) {
  const user = useAuthStore((state) => state.user)
  const signOut = useAuthStore((state) => state.signOut)
  const theme = useThemeStore((state) => state.theme)
  const cycle = useThemeStore((state) => state.cycle)

  return (
    <div className="hairline-b sticky top-0 z-20 bg-page/85 backdrop-blur md:hidden">
      <div className="flex items-center justify-between gap-3 px-5 pt-4">
        <div className="min-w-0">
          <p className="text-sm font-semibold tracking-tight text-ink">Solvigo Insights</p>
          {user?.supplier_name && (
            <p className="truncate text-2xs text-ink-muted">{user.supplier_name}</p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <Button
            variant="ghost"
            size="sm"
            iconOnly
            aria-label={THEME_LABELS[theme]}
            title={THEME_LABELS[theme]}
            icon={
              theme === 'dark' ? <IconMoon className="h-4 w-4" /> : <IconSun className="h-4 w-4" />
            }
            onClick={cycle}
          />
          <Button
            variant="ghost"
            size="sm"
            iconOnly
            aria-label="Logga ut"
            title="Logga ut"
            icon={<IconLogout className="h-4 w-4" />}
            onClick={signOut}
          />
        </div>
      </div>

      <nav aria-label="Huvudmeny" className="quiet-scroll overflow-x-auto px-5 pb-3 pt-3">
        <ul className="flex gap-1.5">
          {NAV.map((item) => {
            const active = item.route === route
            return (
              <li key={item.route}>
                <a
                  href={`#/${item.route}`}
                  aria-current={active ? 'page' : undefined}
                  onClick={(event) => {
                    event.preventDefault()
                    navigate(item.route)
                  }}
                  className={`inline-flex items-center gap-2 whitespace-nowrap rounded-pill px-3.5 py-1.5 text-xs transition-colors duration-200 ${
                    active ? 'bg-surface text-ink shadow-card' : 'text-ink-secondary'
                  }`}
                >
                  <item.icon className={`h-3.5 w-3.5 ${active ? 'text-accent' : 'text-ink-muted'}`} />
                  {item.label}
                </a>
              </li>
            )
          })}
        </ul>
      </nav>
    </div>
  )
}

function Sidebar({ route }: { route: Route }) {
  const user = useAuthStore((state) => state.user)
  const signOut = useAuthStore((state) => state.signOut)
  const theme = useThemeStore((state) => state.theme)
  const cycle = useThemeStore((state) => state.cycle)

  return (
    <nav
      aria-label="Huvudmeny"
      className="hairline-r sticky top-0 hidden h-screen w-60 shrink-0 flex-col justify-between px-4 py-6 md:flex"
    >
      <div>
        <div className="px-3">
          <p className="text-base font-semibold tracking-tight text-ink">Solvigo Insights</p>
          {user?.supplier_name && (
            <p className="mt-0.5 truncate text-2xs text-ink-muted">{user.supplier_name}</p>
          )}
        </div>

        <ul className="mt-8 space-y-0.5">
          {NAV.map((item) => {
            const active = item.route === route
            return (
              <li key={item.route}>
                <a
                  href={`#/${item.route}`}
                  aria-current={active ? 'page' : undefined}
                  onClick={(event) => {
                    event.preventDefault()
                    navigate(item.route)
                  }}
                  className={`flex items-center gap-3 rounded-tile px-3 py-2 text-sm transition-colors duration-200 ${
                    active
                      ? 'bg-surface text-ink shadow-card'
                      : 'text-ink-secondary hover:bg-surface-2 hover:text-ink'
                  }`}
                >
                  <item.icon className={`h-4 w-4 ${active ? 'text-accent' : 'text-ink-muted'}`} />
                  {item.label}
                </a>
              </li>
            )
          })}
        </ul>
      </div>

      <div className="space-y-1">
        {user && (
          <div className="px-3 pb-2">
            <p className="truncate text-xs font-medium text-ink">{user.display_name}</p>
            <p className="truncate text-2xs text-ink-muted">{roleLabel(user.role)}</p>
          </div>
        )}
        <button
          type="button"
          onClick={cycle}
          className="flex w-full items-center gap-3 rounded-tile px-3 py-2 text-sm text-ink-secondary transition-colors duration-200 hover:bg-surface-2 hover:text-ink"
        >
          {theme === 'dark' ? (
            <IconMoon className="h-4 w-4 text-ink-muted" />
          ) : (
            <IconSun className="h-4 w-4 text-ink-muted" />
          )}
          {THEME_LABELS[theme]}
        </button>
        <button
          type="button"
          onClick={signOut}
          className="flex w-full items-center gap-3 rounded-tile px-3 py-2 text-sm text-ink-secondary transition-colors duration-200 hover:bg-surface-2 hover:text-ink"
        >
          <IconLogout className="h-4 w-4 text-ink-muted" />
          Logga ut
        </button>
      </div>
    </nav>
  )
}

const ROLE_LABELS: Record<string, string> = {
  supplier_viewer: 'Leverantör · läsare',
  supplier_admin: 'Leverantör · administratör',
  retail_analyst: 'Handelsanalytiker',
  system_admin: 'Systemadministratör',
}

function roleLabel(role: string): string {
  return ROLE_LABELS[role] ?? role
}
