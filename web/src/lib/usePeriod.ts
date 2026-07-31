/** The selected period, shared by every page that reads the dashboard. */

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
