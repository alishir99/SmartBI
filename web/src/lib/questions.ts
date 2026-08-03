/**
 * Every number on screen is the start of a question. The chat and the dashboard already share
 * one card type and one tool layer; this is what makes them feel like one product rather than
 * two tabs, and there is no plumbing to build - `ask()` already exists.
 */

import type { Column, Kpi } from '../types'
import { formatCell, formatKpiValue, formatNumber } from './format'

/** "vs samma period förra året" is a chip label; a question needs it as a clause. */
function comparisonClause(deltaLabel: string | null): string {
  if (!deltaLabel) return ''
  return ` ${deltaLabel.replace(/^vs\s+/, 'jämfört med ')}`
}

/**
 * A question needs the definite form - "varför ökade försäljningen", not "varför ökade
 * försäljning". Four keys, written out, rather than guessing Swedish morphology from the label.
 */
const SUBJECT: Record<string, string> = {
  net_sales_sek: 'försäljningen',
  category_share_pct: 'andelen av kategorin',
  units: 'antalet sålda enheter',
  avg_price_sek: 'snittpriset',
}

/** The question a KPI tile asks when you click its number. */
export function kpiQuestion(kpi: Kpi): string {
  const subject = SUBJECT[kpi.key] ?? kpi.label.toLowerCase()
  const value = formatKpiValue(kpi.value, kpi.unit)

  if (kpi.delta_pct === null || Math.abs(kpi.delta_pct) < 0.05) {
    return `Vad ligger bakom ${subject} på ${value} den här perioden?`
  }

  const rose = kpi.delta_pct > 0
  const verb = rose ? 'ökade' : 'minskade'
  // A change in a percentage measure is stated in percentage points, the same distinction the
  // tile itself makes - asking "varför ökade andelen 4 %" about a 4 p.e. move is a wrong question.
  const unit = kpi.unit === '%' ? 'procentenheter' : '%'
  const magnitude = `${formatNumber(Math.abs(kpi.delta_pct), 1)} ${unit}`

  return `Varför ${verb} ${subject} ${magnitude}${comparisonClause(kpi.delta_label)}?`
}

/** The question a chart mark or a table row asks: what is behind this one value. */
export function pointQuestion(column: Column | null, value: string): string {
  const label = column ? formatCell(value, column) : value
  if (!label || label === '–') return 'Berätta mer om den här perioden.'
  if (column?.type === 'date') return `Vad hände i ${label}?`
  return `Berätta mer om ${label}.`
}
