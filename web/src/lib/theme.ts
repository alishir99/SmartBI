
import { create } from 'zustand'

import { t } from './i18n'

export type Theme = 'light' | 'dark' | 'system'

const THEME_KEY = 'smartbi.theme'

// Light until the user picks otherwise; 'system' is stored explicitly so it survives a reload.
// index.html applies the same default before first paint.
const DEFAULT_THEME: Theme = 'light'

function readStoredTheme(): Theme {
  try {
    const raw = localStorage.getItem(THEME_KEY)
    return raw === 'light' || raw === 'dark' || raw === 'system' ? raw : DEFAULT_THEME
  } catch {
    return DEFAULT_THEME
  }
}

function apply(theme: Theme): void {
  const root = document.documentElement
  if (theme === 'system') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', theme)
  try {
    localStorage.setItem(THEME_KEY, theme)
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

/** Translated on read, so a language switch relabels the toggle without a store update. */
export function themeLabel(theme: Theme): string {
  return t(`theme.${theme}`)
}
