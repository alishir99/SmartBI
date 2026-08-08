/** Currency and locale come from the server, not a build-time env var: they're properties of
 * the warehouse, stamped onto every result's provenance - a client built with a different
 * answer would render EUR figures with a kronor symbol and be confidently wrong. */

import { apiUrl } from './env'

export type AppConfig = {
  /** ISO-4217, e.g. `SEK`, `EUR`, `JPY`. */
  currency: string
  /** BCP-47, e.g. `sv-SE`, `en-GB`. Drives grouping, decimals and month names. */
  locale: string
  /** The server's own minimum, so the form states the rule it will actually be judged by. */
  passwordMinLength: number
}

// What to use until the server answers, and to fall back to if it never does - the app still
// works offline from the API, it just formats as the build's default market.
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

/** Not the same as the UI language: figures group per the deployment's own market. Only where
 * the deployment's locale and the reading language actually disagree on the digits does the
 * language win. */
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
    // An unreachable API is about to be visible everywhere else; formatting isn't where the
    // user should first hear about it.
  }
  return current
}
