/**
 * Formatting, driven by `Intl` rather than by hand.
 *
 * This file used to hardcode sv-SE: a narrow no-break space between value and unit, a
 * kr/tkr/Mkr ladder, two twelve-entry month arrays. All of that is `Intl.NumberFormat` and
 * `Intl.DateTimeFormat` with a locale argument, and the platform knows the conventions of
 * every market this app might be pointed at - including the ones nobody here would guess,
 * like where the currency symbol goes and which languages abbreviate months with a period.
 *
 * The locale comes from the deployment (`lib/config.ts`) and the language from the user
 * (`lib/i18n.ts`); `formatLocale` reconciles them.
 */

import { currency as appCurrency, formatLocale } from './config'
import { currentLanguage, plural, t } from './i18n'
import type { Column, ColumnUnit, DateRange } from '../types'

/** Whether a column's unit is money - i.e. an ISO-4217 code rather than one of the fixed units. */
export function isCurrency(unit: ColumnUnit | null | undefined): boolean {
  return typeof unit === 'string' && /^[A-Z]{3}$/.test(unit)
}

function locale(): string {
  return formatLocale(currentLanguage())
}

// Intl formatters are expensive to construct and are built per cell, so they are cached. The
// key carries the locale *and* the currency, because both are inputs to the formatter: keying
// on the locale alone means a formatter built before `loadConfig` resolved would keep serving
// the fallback currency for the life of the page.
const cache = new Map<string, Intl.NumberFormat>()

function formatter(key: string, options: Intl.NumberFormatOptions): Intl.NumberFormat {
  const cacheKey = `${locale()}:${appCurrency()}:${key}`
  let found = cache.get(cacheKey)
  if (!found) {
    found = new Intl.NumberFormat(locale(), options)
    cache.set(cacheKey, found)
  }
  return found
}

function nf(min: number, max: number): Intl.NumberFormat {
  return formatter(`n${min}:${max}`, {
    minimumFractionDigits: min,
    maximumFractionDigits: max,
    useGrouping: true,
  })
}

export const MISSING = '–'

/** Plain number. `1 243` in sv-SE, `1,243` in en-US. */
export function formatNumber(value: number, decimals = 0): string {
  if (!Number.isFinite(value)) return MISSING
  return nf(decimals, decimals).format(value)
}

// --- money ------------------------------------------------------------------

export type MoneyScale = {
  /** divide the raw amount by this before display */
  divisor: number
  /** what to write after the scaled value, e.g. `Mkr`, `M €`, `M` */
  unit: string
  decimals: number
}

/** The symbol this locale writes for the deployment's currency: `kr`, `$`, `€`, `￥`. */
function currencySymbol(): string {
  const code = appCurrency()
  return (
    formatter(`sym:${code}`, { style: 'currency', currency: code })
      .formatToParts(0)
      .find((part) => part.type === 'currency')?.value ?? code
  )
}

/**
 * The locale's own abbreviation for a magnitude - `mn`, `M`, `Mio.` - or null when this locale
 * has no abbreviation for that exact power of ten.
 *
 * The null case is not hypothetical. Japanese groups in myriads, so `Intl` renders 1 000 000 as
 * "100万" rather than as "1 <suffix>": lifting the suffix out and pairing it with a 1 000 000
 * divisor would label an axis 万 while having divided by a hundred times that. So the integer
 * part is checked, and a locale that cannot write the divisor as a bare 1 gets no abbreviation
 * rather than a wrong one.
 */
function magnitudeMarker(divisor: number): string | null {
  const parts = formatter('compact', {
    notation: 'compact',
    maximumFractionDigits: 0,
  }).formatToParts(divisor)

  if (parts.find((part) => part.type === 'integer')?.value !== '1') return null
  const marker = parts.find((part) => part.type === 'compact')?.value?.trim()
  return marker || null
}

function unitFor(divisor: number): string {
  const symbol = currencySymbol()
  if (divisor === 1) return symbol
  const marker = magnitudeMarker(divisor)
  // Joined with a plain space rather than with whatever `Intl` put between the digits and the
  // marker: several locales use a no-break space there, and two units that render identically
  // but compare unequal are a bug nobody can see.
  return marker ? `${marker} ${symbol}` : symbol
}

/**
 * Pick one scale for a whole chart or tile from the largest absolute value in it, so every
 * tick and label on the same axis shares a unit.
 *
 * Not `notation: 'compact'` per value, which is the obvious `Intl` answer and the wrong one: it
 * would scale each tick independently and put "900 k" directly below "1,2 mn" on one axis.
 */
export function moneyScale(maxAbs: number): MoneyScale {
  const magnitude = Math.abs(maxAbs)
  const tier =
    magnitude < 100_000
      ? { divisor: 1, decimals: 0 }
      : magnitude < 10_000_000
        ? { divisor: 1_000, decimals: 0 }
        : { divisor: 1_000_000, decimals: 1 }

  // A locale with no abbreviation for this magnitude is left unscaled: an axis reading
  // "23 480 500 ￥" is merely long, and an axis reading "23 ￥" is wrong.
  if (tier.divisor > 1 && magnitudeMarker(tier.divisor) === null) {
    return { divisor: 1, unit: currencySymbol(), decimals: 0 }
  }
  return { ...tier, unit: unitFor(tier.divisor) }
}

/** `12,4 Mkr` - magnitude chosen from this value alone. */
export function formatMoney(amount: number): string {
  if (!Number.isFinite(amount)) return MISSING
  const scale = moneyScale(amount)
  return formatMoneyWithUnit(amount, scale)
}

/** Value only, on a scale decided elsewhere (axis ticks, bar labels). */
export function formatMoneyOnScale(amount: number, scale: MoneyScale): string {
  if (!Number.isFinite(amount)) return MISSING
  return nf(scale.decimals, scale.decimals).format(amount / scale.divisor)
}

/** `12,4 Mkr` on a shared scale. */
export function formatMoneyWithUnit(amount: number, scale: MoneyScale): string {
  if (!Number.isFinite(amount)) return MISSING
  return `${formatMoneyOnScale(amount, scale)} ${scale.unit}`
}

/**
 * Full precision, for tooltips and the source chip. `23 480 500 kr` / `$23,480,500`.
 *
 * The only place `style: 'currency'` is used directly: it is the one context with no shared
 * axis to agree with, so the locale gets to place the symbol wherever it belongs - which is
 * before the digits in most of the world and after them in Sweden.
 */
export function formatMoneyExact(amount: number): string {
  if (!Number.isFinite(amount)) return MISSING
  return formatter('exact', {
    style: 'currency',
    currency: appCurrency(),
    maximumFractionDigits: 0,
  }).format(Math.round(amount))
}

// --- percent, units ---------------------------------------------------------

/** `18,3 %` - always one decimal. */
export function formatPercent(value: number, decimals = 1): string {
  if (!Number.isFinite(value)) return MISSING
  return `${nf(decimals, decimals).format(value)} ${t('unit.percent')}`
}

/** Percentage points, for share deltas. `+0,7 p.e.` / `+0.7 pp` */
export function formatPercentPoints(value: number): string {
  if (!Number.isFinite(value)) return MISSING
  return `${signPrefix(value)}${nf(1, 1).format(Math.abs(value))} ${t(
    'unit.percentage_points',
  )}`
}

export function formatUnits(value: number): string {
  if (!Number.isFinite(value)) return MISSING
  return `${nf(0, 0).format(value)} ${t('unit.count')}`
}

function signPrefix(value: number): string {
  return value > 0 ? '+' : value < 0 ? '−' : ''
}

// --- deltas -----------------------------------------------------------------

export type Delta = {
  direction: 'up' | 'down' | 'flat'
  /** magnitude only, e.g. `8,2 %` - the arrow carries the sign */
  magnitude: string
  /** the comparison period; a delta is never rendered without it */
  label: string
}

/**
 * A delta is only meaningful next to what it is compared against, so this always returns the
 * label too.
 */
export function formatDelta(
  deltaPct: number | null,
  deltaLabel: string | null,
  unit?: ColumnUnit,
): Delta | null {
  if (deltaPct === null || deltaPct === undefined || !Number.isFinite(deltaPct)) return null
  const direction = deltaPct > 0.05 ? 'up' : deltaPct < -0.05 ? 'down' : 'flat'
  // A change in a percentage measure is stated in percentage points, not percent of a percent.
  const suffix = unit === '%' ? t('unit.percentage_points') : t('unit.percent')
  const magnitude = `${nf(1, 1).format(Math.abs(deltaPct))} ${suffix}`
  return { direction, magnitude, label: deltaLabel ?? t('period.previous') }
}

// --- dates ------------------------------------------------------------------

const dateCache = new Map<string, Intl.DateTimeFormat>()

function dtf(key: string, options: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  const cacheKey = `${locale()}:${key}`
  let found = dateCache.get(cacheKey)
  if (!found) {
    // UTC throughout: every bucket the warehouse returns is a calendar date, and rendering
    // `2026-01-01` in a timezone behind UTC turns it into December.
    found = new Intl.DateTimeFormat(locale(), { timeZone: 'UTC', ...options })
    dateCache.set(cacheKey, found)
  }
  return found
}

/** Accepts `2026-01`, `2026-01-01` or an ISO timestamp. */
function parseYm(value: string): { year: number; month: number; day: number } | null {
  const m = /^(\d{4})-(\d{2})(?:-(\d{2}))?/.exec(value)
  if (!m) return null
  return { year: Number(m[1]), month: Number(m[2]), day: m[3] ? Number(m[3]) : 1 }
}

function utc(parts: { year: number; month: number; day: number }): Date {
  return new Date(Date.UTC(parts.year, parts.month - 1, parts.day))
}

/** Short month name in the active locale: `jan`, `Jan`, `1月`. */
export function monthName(month: number, style: 'short' | 'long' = 'short'): string {
  return dtf(`month-${style}`, { month: style }).format(Date.UTC(2000, month - 1, 1))
}

/** `jan 2026`. Used for month axis ticks. */
export function formatMonth(value: string, withYear = true): string {
  const parts = parseYm(value)
  if (!parts) return value
  if (!withYear) return monthName(parts.month)
  return dtf('ym', { month: 'short', year: 'numeric' }).format(utc(parts))
}

/** `24 jun` - a day bucket on an axis, where the year is already in the card's period line. */
export function formatDayShort(value: string): string {
  const parts = parseYm(value)
  if (!parts) return value
  return dtf('md', { day: 'numeric', month: 'short' }).format(utc(parts))
}

/** `4 januari 2026`. */
export function formatDateLong(value: string): string {
  const parts = parseYm(value)
  if (!parts) return value
  return dtf('long', { day: 'numeric', month: 'long', year: 'numeric' }).format(utc(parts))
}

/** `2026-01-04`. ISO stays ISO in every locale - it is an identifier here, not a date. */
export function formatDateIso(value: string): string {
  const parts = parseYm(value)
  if (!parts) return value
  return `${parts.year}-${String(parts.month).padStart(2, '0')}-${String(parts.day).padStart(2, '0')}`
}

/** ISO-8601 week number (Monday-based, week 1 contains the first Thursday). */
export function isoWeek(date: Date): { year: number; week: number } {
  const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()))
  const day = d.getUTCDay() || 7
  d.setUTCDate(d.getUTCDate() + 4 - day)
  const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1))
  const week = Math.ceil(((d.getTime() - yearStart.getTime()) / 86_400_000 + 1) / 7)
  return { year: d.getUTCFullYear(), week }
}

/** `v. 14 2026` / `w. 14 2026` - from a date, or from a `2026-W14` key. */
export function formatIsoWeek(value: string): string {
  const prefix = currentLanguage() === 'sv' ? 'v.' : 'w.'
  const parsed = /^(\d{4})-W(\d{1,2})$/.exec(value)
  if (parsed) return `${prefix} ${Number(parsed[2])} ${parsed[1]}`
  const parts = parseYm(value)
  if (!parts) return value
  const { year, week } = isoWeek(utc(parts))
  return `${prefix} ${week} ${year}`
}

/** `jan–jun 2026`, `dec 2025–jun 2026`. */
export function formatPeriod(range: DateRange): string {
  const from = parseYm(range.from)
  const to = parseYm(range.to)
  if (!from || !to) return `${range.from}–${range.to}`
  if (from.year === to.year) {
    if (from.month === to.month) return `${monthName(from.month)} ${from.year}`
    return `${monthName(from.month)}–${monthName(to.month)} ${from.year}`
  }
  return `${monthName(from.month)} ${from.year}–${monthName(to.month)} ${to.year}`
}

/** `14:32` - clock only, for the source chip. Rendered in the reader's own timezone. */
export function formatClock(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return new Intl.DateTimeFormat(locale(), { hour: '2-digit', minute: '2-digit' }).format(date)
}

/** `27 juli 2026, 14:32`. A timestamp, so local time is right - unlike the date buckets. */
export function formatTimestamp(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return new Intl.DateTimeFormat(locale(), {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

// --- generic dispatch -------------------------------------------------------

/** `K3 2025` / `Q3 2025`. */
export function formatQuarter(value: string): string {
  const parts = parseYm(value)
  if (!parts) return value
  const prefix = currentLanguage() === 'sv' ? 'K' : 'Q'
  return `${prefix}${Math.floor((parts.month - 1) / 3) + 1} ${parts.year}`
}

/**
 * Every date bucket comes back as its first day, so `2025-07-01` is a month under a `month`
 * grouping and a genuine day under a `day` one: the value alone cannot say which. The column
 * key can, because it is the dimension key the compiler grouped by, which the API contract
 * fixes. Without this the trend axis reads "2025-07-01" where it means "jul 2025".
 */
const DATE_GRAIN: Record<string, (value: string) => string> = {
  day: formatDayShort,
  month: formatMonth,
  quarter: formatQuarter,
  week: formatIsoWeek,
}

/** Format a raw cell according to its column definition. */
export function formatCell(value: string | number | null, column: Column): string {
  if (value === null || value === undefined || value === '') return MISSING
  if (column.type === 'date') {
    const text = String(value)
    if (/^\d{4}-W\d{1,2}$/.test(text)) return formatIsoWeek(text)
    if (/^\d{4}-\d{2}$/.test(text)) return formatMonth(text)
    // `month_compare` is the same grain as `month`.
    const grain = DATE_GRAIN[column.key.replace(/_compare$/, '')]
    return grain ? grain(text) : formatDateIso(text)
  }
  if (column.type === 'number' && typeof value === 'number') {
    if (isCurrency(column.unit)) return formatMoneyExact(value)
    switch (column.unit) {
      case '%':
        return formatPercent(value)
      case 'p.e.':
        return formatPercentPoints(value)
      case 'st':
        return formatUnits(value)
      default:
        return formatNumber(value, Number.isInteger(value) ? 0 : 1)
    }
  }
  return String(value)
}

/** Value for a KPI tile, by unit. */
export function formatKpiValue(value: number, unit: ColumnUnit): string {
  if (isCurrency(unit)) return formatMoney(value)
  switch (unit) {
    case '%':
      return formatPercent(value)
    case 'p.e.':
      return formatPercentPoints(value)
    case 'st':
      return formatUnits(value)
    default:
      return formatNumber(value)
  }
}

/** Shorten a long category label for an axis without clipping mid-word. */
export function truncateLabel(value: string, max = 26): string {
  if (value.length <= max) return value
  return `${value.slice(0, max - 1).trimEnd()}…`
}

/** `Stockholms län · 1 produkt` from provenance.filters_applied. */
export function describeFilters(filters: Record<string, unknown>): string {
  const parts: string[] = []
  for (const [key, raw] of Object.entries(filters)) {
    if (raw === null || raw === undefined) continue
    const values = Array.isArray(raw) ? raw : [raw]
    if (values.length === 0) continue

    // An id filter is real - the numbers are narrowed by it and the user has to know - but
    // the id itself is a database key. "Produkt: 8" says nothing to a supplier and reads as
    // an internal leak, so the filter is counted rather than printed.
    if (COUNTED_FILTERS.has(key)) {
      parts.push(plural(values.length, `filter.${key}`))
      continue
    }

    const value = values.join(', ')
    if (!value) continue
    parts.push(`${filterLabel(key)}: ${value}`)
  }
  return parts.join(' · ')
}

/** The filters that carry ids rather than names, and are therefore counted. */
const COUNTED_FILTERS = new Set(['category_ids', 'product_ids', 'brand_ids', 'store_ids'])

function filterLabel(key: string): string {
  const label = t(`filter.${key}`)
  return label === `filter.${key}` ? key : label
}
