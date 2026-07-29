/**
 * Theme. The stamp on <html data-theme> is applied before first paint by the inline
 * script in index.html; this store only keeps it in sync afterwards. "system" means
 * no stamp at all, so the CSS media query decides.
 */

import { create } from 'zustand'

export type Theme = 'light' | 'dark' | 'system'

const THEME_KEY = 'solvigo.theme'

function readStoredTheme(): Theme {
  try {
    const raw = localStorage.getItem(THEME_KEY)
    return raw === 'light' || raw === 'dark' ? raw : 'system'
  } catch {
    return 'system'
  }
}

function apply(theme: Theme): void {
  const root = document.documentElement
  if (theme === 'system') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', theme)
  try {
    if (theme === 'system') localStorage.removeItem(THEME_KEY)
    else localStorage.setItem(THEME_KEY, theme)
  } catch {
    /* private browsing */
  }
}

type ThemeState = {
  theme: Theme
  setTheme: (theme: Theme) => void
  /** Cycles light → dark → system, which keeps the toggle a single control. */
  cycle: () => void
}

const ORDER: Theme[] = ['light', 'dark', 'system']

export const useThemeStore = create<ThemeState>((set, get) => ({
  theme: readStoredTheme(),
  setTheme: (theme) => {
    apply(theme)
    set({ theme })
  },
  cycle: () => {
    const next = ORDER[(ORDER.indexOf(get().theme) + 1) % ORDER.length]
    apply(next)
    set({ theme: next })
  },
}))

export const THEME_LABELS: Record<Theme, string> = {
  light: 'Ljust läge',
  dark: 'Mörkt läge',
  system: 'Följer systemet',
}
