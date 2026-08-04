/**
 * Every number on screen is the start of a question. The chat and the dashboard already share
 * one card type and one tool layer; this is what makes them feel like one product rather than
 * two tabs, and there is no plumbing to build - `ask()` already exists.
 */

import type { Column, Kpi } from '../types'
import { formatCell, formatKpiValue, formatNumber, MISSING } from './format'
import { t } from './i18n'

/** "vs samma period förra året" is a chip label; a question needs it as a clause. */
function comparisonClause(deltaLabel: string | null): string {
  if (!deltaLabel) return ''
  // The label is server-written and opens with "vs". Strip that and the rest reads as a clause
  // rather than as a chip glued onto one.
  return t('ask.compared_with', { period: deltaLabel.replace(/^vs\s+/i, '') })
}

/**
 * The question a KPI tile asks when you click its number.
 *
 * The subject is looked up per measure rather than taken from the tile's label, because a
 * question needs the definite form: "varför ökade försäljningen", not "varför ökade
 * försäljning". Four keys written out beats guessing any language's morphology.
 */
export function kpiQuestion(kpi: Kpi): string {
  const key = `ask.measure.${kpi.key}`
  const translated = t(key)
  const subject = translated === key ? kpi.label.toLowerCase() : translated
  const value = formatKpiValue(kpi.value, kpi.unit)

  if (kpi.delta_pct === null || Math.abs(kpi.delta_pct) < 0.05) {
    return t('ask.what_drove', { subject, value })
  }

  // A change in a percentage measure is stated in percentage points, the same distinction the
  // tile itself makes - asking "varför ökade andelen 4 %" about a 4 p.e. move is a wrong
  // question.
  const unit = kpi.unit === '%' ? t('unit.percentage_points_long') : t('unit.percent')
  return t('ask.why_changed', {
    measure: subject,
    direction: kpi.delta_pct > 0 ? t('ask.rose') : t('ask.fell'),
    magnitude: `${formatNumber(Math.abs(kpi.delta_pct), 1)} ${unit}`,
    comparison: comparisonClause(kpi.delta_label),
  })
}

/** The question a chart mark or a table row asks: what is behind this one value. */
export function pointQuestion(column: Column | null, value: string): string {
  const label = column ? formatCell(value, column) : value
  if (!label || label === MISSING) return t('ask.tell_me_more')
  if (column?.type === 'date') return t('ask.what_happened', { period: label })
  return t('ask.tell_me_about', { subject: label })
}
