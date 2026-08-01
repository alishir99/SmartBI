/** The period windows the dashboard offers. */

export const DEFAULT_PERIOD = 'last_12_months'

export type PeriodOption = { key: string; label: string; short: string }

export const PERIOD_OPTIONS: PeriodOption[] = [
  { key: 'last_7_days', label: 'Senaste veckan', short: 'Vecka' },
  { key: 'last_30_days', label: 'Senaste 30 dagarna', short: '30 dgr' },
  { key: 'last_90_days', label: 'Senaste kvartalet', short: 'Kvartal' },
  { key: 'last_month', label: 'Förra månaden', short: 'Månad' },
  { key: 'ytd', label: 'Hittills i år', short: 'I år' },
  { key: 'last_12_months', label: 'Senaste 12 mån', short: '12 mån' },
  { key: 'all_time', label: 'Hela perioden', short: 'Allt' },
]

export function periodLabel(key: string): string {
  return PERIOD_OPTIONS.find((option) => option.key === key)?.label ?? key
}

/**
 * What every delta on the screen is measured against. "Versus last period" and "versus last
 * year" answer different questions, and the product used to assume the second silently.
 */
export const DEFAULT_BASIS = 'same_period_last_year'

export const BASIS_OPTIONS: PeriodOption[] = [
  { key: 'same_period_last_year', label: 'vs förra året', short: 'Förra året' },
  { key: 'previous_period', label: 'vs föregående period', short: 'Föregående' },
  { key: 'none', label: 'Ingen jämförelse', short: 'Ingen' },
]
