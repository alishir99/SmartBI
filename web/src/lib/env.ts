/** Runtime configuration. */


/** Empty means "same origin" - dev goes through the Vite proxy defined in vite.config.ts. */
export const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

export function apiUrl(path: string): string {
  return `${API_BASE}${path}`
}
