/** The selected period, shared by every page that reads the dashboard. */

import { useSyncExternalStore } from 'react'
import { DEFAULT_PERIOD, PERIOD_OPTIONS, type PeriodOption } from './periods'

/** One persisted choice out of a fixed set, readable from any page. */
function choiceStore(storageKey: string, options: PeriodOption[], fallback: string) {
  const listeners = new Set<() => void>()

  let current = fallback
  try {
    const stored = localStorage.getItem(storageKey)
    if (stored && options.some((option) => option.key === stored)) current = stored
  } catch {
    // Private mode or a blocked origin — the default is a fine answer.
  }

  const subscribe = (listener: () => void) => {
    listeners.add(listener)
    return () => listeners.delete(listener)
  }

  const read = () => current

  const set = (value: string): void => {
    if (value === current) return
    current = value
    try {
      localStorage.setItem(storageKey, value)
    } catch {
      // Not being able to persist the choice must not stop it taking effect.
    }
    listeners.forEach((listener) => listener())
  }

  return { subscribe, read, set, fallback }
}

const periodStore = choiceStore('solvigo.period', PERIOD_OPTIONS, DEFAULT_PERIOD)

export const setPeriod = periodStore.set

export function usePeriod(): [string, (period: string) => void] {
  const value = useSyncExternalStore(periodStore.subscribe, periodStore.read,
                                     () => periodStore.fallback)
  return [value, periodStore.set]
}
