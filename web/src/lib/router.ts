/**
 * Minimal hash router — 30 lines instead of a dependency. Hash routing keeps every
 * view deep-linkable and shareable without any server rewrite rules.
 */

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

export function navigate(next: Route): void {
  if (parse() === next) return
  window.location.hash = `#/${next}`
  // Focus the main region so keyboard and screen-reader users land in the new content.
  requestAnimationFrame(() => document.getElementById('main')?.focus())
}
