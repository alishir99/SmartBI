/**
 * How this deployment's numbers are denominated and formatted.
 *
 * It comes from the server, not from a build-time `VITE_` variable, because the currency is a
 * property of the *warehouse*: the API stamps it onto every result's provenance, and a client
 * built with a different answer would render EUR figures with a kronor symbol and be
 * confidently wrong. One source, fetched once.
 *
 * Loaded before React mounts (see main.tsx) so the very first render already formats
 * correctly - a currency that arrives one tick late means every amount on screen flips, which
 * reads as a glitch and, for the seconds before it, as a wrong number.
 */

import { apiUrl } from './env'

export type AppConfig = {
  /** ISO-4217, e.g. `SEK`, `EUR`, `JPY`. */
  currency: string
  /** BCP-47, e.g. `sv-SE`, `en-GB`. Drives grouping, decimals and month names. */
  locale: string
  /** The server's own minimum, so the form states the rule it will actually be judged by. */
  passwordMinLength: number
}

// What to use until the server answers, and what to fall back to if it never does. The app
// still works offline from the API this way; it just formats as the build's default market.
const FALLBACK: AppConfig = { currency: 'SEK', locale: 'sv-SE', passwordMinLength: 8 }

let current: AppConfig = FALLBACK

export function appConfig(): AppConfig {
  return current
}

export function currency(): string {
  return current.currency
}

export function passwordMinLength(): number {
  return current.passwordMinLength
}

/**
 * The locale to format in.
 *
 * Not the same as the UI language: a Swedish deployment read in English still groups its
 * thousands the way its own market does, because the *figures* belong to that market. Only
 * where the deployment's locale and the reading language disagree on the actual digits - a
 * Swedish locale read in English - does the language win, so "1 234,5" does not appear in an
 * English sentence that says "1,234.5".
 */
export function formatLocale(lang: string): string {
  return current.locale.split('-')[0] === lang ? current.locale : lang
}

export async function loadConfig(): Promise<AppConfig> {
  try {
    const response = await fetch(apiUrl('/api/config'))
    if (!response.ok) return current
    const body = (await response.json()) as {
      currency?: string
      locale?: string
      password_min_length?: number
    }
    if (body.currency && body.locale) {
      current = {
        currency: body.currency,
        locale: body.locale,
        passwordMinLength: body.password_min_length ?? FALLBACK.passwordMinLength,
      }
    }
  } catch {
    // An unreachable API is about to be visible everywhere else; formatting is not where the
    // user should first hear about it.
  }
  return current
}
