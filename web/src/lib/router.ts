/** Minimal hash router - 30 lines instead of a dependency. */

import { useEffect, useState } from 'react'

export type Route = 'oversikt' | 'produkter' | 'geografi' | 'mina-vyer'

const ROUTES: Route[] = ['oversikt', 'produkter', 'geografi', 'mina-vyer']

function parse(): Route {
  const raw = window.location.hash.replace(/^#\/?/, '').split('?')[0]
  return (ROUTES as string[]).includes(raw) ? (raw as Route) : 'oversikt'
}

export function useRoute(): [Route, (next: Route) => void] {
  const [route, setRoute] = useState<Route>(parse)

  useEffect(() => {
    const onChange = () => setRoute(parse())
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])

  return [route, navigate]
}

/** The token in `#/<prefix>/<token>`, or null. Not `Route`s: both sit outside the auth gate. */
function tokenAfter(prefix: string): string | null {
  const raw = window.location.hash.replace(/^#\/?/, '').split('?')[0]
  const token = raw.startsWith(`${prefix}/`) ? raw.slice(prefix.length + 1) : ''
  return token ? decodeURIComponent(token) : null
}

export const sharedToken = () => tokenAfter('delad')

/** `#/aterstall/<token>` - a password reset link, opened by someone who cannot log in. */
export const resetToken = () => tokenAfter('aterstall')

function useHashValue<T>(read: () => T): T {
  const [value, setValue] = useState<T>(read)

  useEffect(() => {
    const onChange = () => setValue(read())
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
    // `read` is a module-level function, stable across renders.
  }, [read])

  return value
}

export function useSharedToken(): string | null {
  return useHashValue(sharedToken)
}

export function useResetToken(): string | null {
  return useHashValue(resetToken)
}

export function navigate(next: Route): void {
  if (parse() === next) return
  window.location.hash = `#/${next}`
  // Focus the main region so keyboard and screen-reader users land in the new content.
  requestAnimationFrame(() => document.getElementById('main')?.focus())
}
