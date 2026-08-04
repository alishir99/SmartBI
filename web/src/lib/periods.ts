/** The period windows the dashboard offers. Keys only - the labels live in lib/i18n.ts. */

import { t } from './i18n'

export const DEFAULT_PERIOD = 'last_12_months'

export const PERIOD_KEYS = [
  'last_7_days',
  'last_30_days',
  'last_90_days',
  'last_month',
  'ytd',
  'last_12_months',
  'all_time',
] as const

export type PeriodKey = (typeof PERIOD_KEYS)[number]

export type PeriodOption = { key: string; label: string; short: string }

/** Built per call rather than at module load, so switching language relabels the chips. */
export function periodOptions(): PeriodOption[] {
  return PERIOD_KEYS.map((key) => ({
    key,
    label: t(`period.${key}`),
    short: t(`period.${key}.short`),
  }))
}

export function periodLabel(key: string): string {
  const label = t(`period.${key}`)
  return label === `period.${key}` ? key : label
}
