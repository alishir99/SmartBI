/** The selected period, shared by every page that reads the dashboard. */

import { useSyncExternalStore } from 'react'
import { DEFAULT_PERIOD, PERIOD_KEYS } from './periods'

// Keyed on the option keys, not labelled options: labels are language-dependent, and a
// validity check tied to the active language would reject a stored period after a switch.
function choiceStore(storageKey: string, keys: readonly string[], fallback: string) {
  const listeners = new Set<() => void>()

  let current = fallback
  try {
    const stored = localStorage.getItem(storageKey)
    if (stored && keys.includes(stored)) current = stored
  } catch {
    // Private mode or a blocked origin - the default is a fine answer.
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

const periodStore = choiceStore('smartbi.period', PERIOD_KEYS, DEFAULT_PERIOD)

export const setPeriod = periodStore.set

export function usePeriod(): [string, (period: string) => void] {
  const value = useSyncExternalStore(periodStore.subscribe, periodStore.read,
                                     () => periodStore.fallback)
  return [value, periodStore.set]
}
