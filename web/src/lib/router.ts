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

/** The token in `#/delad/<token>`, or null. Not a `Route`: it sits outside the auth gate. */
export function sharedToken(): string | null {
  const raw = window.location.hash.replace(/^#\/?/, '').split('?')[0]
  const token = raw.startsWith('delad/') ? raw.slice('delad/'.length) : ''
  return token ? decodeURIComponent(token) : null
}

export function useSharedToken(): string | null {
  const [token, setToken] = useState<string | null>(sharedToken)

  useEffect(() => {
    const onChange = () => setToken(sharedToken())
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])

  return token
}

export function navigate(next: Route): void {
  if (parse() === next) return
  window.location.hash = `#/${next}`
  // Focus the main region so keyboard and screen-reader users land in the new content.
  requestAnimationFrame(() => document.getElementById('main')?.focus())
}
