/** Every number on screen is the start of a question - the chat and dashboard share one card
 * type and one tool layer, so `ask()` already exists; this is what makes it feel like one product. */

import type { Column, Kpi } from '../types'
import { formatCell, formatKpiValue, formatNumber, MISSING } from './format'
import { t } from './i18n'

/** "vs samma period förra året" is a chip label; a question needs it as a clause. */
function comparisonClause(deltaLabel: string | null): string {
  if (!deltaLabel) return ''
  return t('ask.compared_with', { period: deltaLabel.replace(/^vs\s+/i, '') })
}

/** The subject is looked up per measure rather than taken from the tile's label, because a
 * question needs the definite form: "varför ökade försäljningen", not "...försäljning". */
export function kpiQuestion(kpi: Kpi): string {
  const key = `ask.measure.${kpi.key}`
  const translated = t(key)
  const subject = translated === key ? kpi.label.toLowerCase() : translated
  const value = formatKpiValue(kpi.value, kpi.unit)

  if (kpi.delta_pct === null || Math.abs(kpi.delta_pct) < 0.05) {
    return t('ask.what_drove', { subject, value })
  }

  // A change in a percentage measure is stated in percentage points, the same distinction
  // the tile itself makes - "why did the share rise 4%" is a different, wrong question.
  const unit = kpi.unit === '%' ? t('unit.percentage_points_long') : t('unit.percent')
  return t('ask.why_changed', {
    measure: subject,
    direction: kpi.delta_pct > 0 ? t('ask.rose') : t('ask.fell'),
    magnitude: `${formatNumber(Math.abs(kpi.delta_pct), 1)} ${unit}`,
    comparison: comparisonClause(kpi.delta_label),
  })
}

/** The question a chart mark or table row asks: what is behind this one value. */
export function pointQuestion(column: Column | null, value: string): string {
  const label = column ? formatCell(value, column) : value
  if (!label || label === MISSING) return t('ask.tell_me_more')
  if (column?.type === 'date') return t('ask.what_happened', { period: label })
  return t('ask.tell_me_about', { subject: label })
}
