/**
 * The period windows the dashboard offers.
 *
 * This list mirrors `PERIODS` in `api/routes/dashboard.py`, and the keys must match: the
 * backend resolves them against the semantic layer's relative ranges, and an unknown key
 * silently falls back to the default rather than erroring. Keeping the labels here rather
 * than shipping them in the response keeps the contract in `docs/API_CONTRACT.md` frozen —
 * the API gained one querystring parameter, not a new payload shape.
 *
 * The default is deliberately still 12 months. "BI utan BI-avdelning" means the first screen
 * asks nothing; the control exists for the second question, not the first.
 */

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
