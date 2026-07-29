/**
 * The selected period, shared by every page that reads the dashboard.
 *
 * Held in one module-level store rather than per page, so switching to Produkter after
 * choosing "Hittills i år" does not silently drop back to twelve months. It is also
 * persisted: coming back to a dashboard and finding a different window than you left it on
 * is the kind of small dishonesty that makes people stop trusting the numbers.
 */

import { useSyncExternalStore } from 'react'
import { DEFAULT_PERIOD, PERIOD_OPTIONS } from './periods'

const STORAGE_KEY = 'solvigo.period'

function initial(): string {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored && PERIOD_OPTIONS.some((option) => option.key === stored)) return stored
  } catch {
    // Private mode or a blocked origin — the default is a fine answer.
  }
  return DEFAULT_PERIOD
}

let current = initial()
const listeners = new Set<() => void>()

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function setPeriod(period: string): void {
  if (period === current) return
  current = period
  try {
    localStorage.setItem(STORAGE_KEY, period)
  } catch {
    // Not being able to persist the choice must not stop it taking effect.
  }
  listeners.forEach((listener) => listener())
}

export function usePeriod(): [string, (period: string) => void] {
  const period = useSyncExternalStore(subscribe, () => current, () => DEFAULT_PERIOD)
  return [period, setPeriod]
}
