/** Proportional-symbol map from the data's own coordinates - no basemap: the old hand-traced
 * Sweden outline was 600 points that couldn't generalize, so markers float free instead. */

import { useId, useMemo, useState } from 'react'
import { findRegion, project, radiusFor, type RegionPoint } from '../lib/geo'
import { formatMoneyWithUnit, moneyScale, formatPercent } from '../lib/format'
import { useT } from '../lib/i18n'

const VIEW_W = 460
const VIEW_H = 620
const PADDING = 40
const MIN_R = 5
const MAX_R = 36
/** Labels are placed for the biggest regions only, and never within this of another. */
const LABEL_MIN_GAP = 30

export type RegionDatum = { region: string; value: number }

type Props = {
  data: RegionDatum[]
  /** Every region the warehouse knows, with its centroid. Positions come from here. */
  places: RegionPoint[]
  /** Accessible caption; also used as the visible unit hint. */
  label: string
}

export function RegionMap({ data, places, label }: Props) {
  const t = useT()
  const titleId = useId()
  const [active, setActive] = useState<string | null>(null)

  const points = useMemo(() => {
    const max = Math.max(...data.map((d) => d.value), 0)
    const total = data.reduce((sum, d) => sum + d.value, 0)
    return data
      .map((datum) => {
        const point = findRegion(datum.region, places)
        if (!point) return null
        return {
          ...datum,
          point,
          radius: radiusFor(datum.value, max, MIN_R, MAX_R),
          share: total > 0 ? (datum.value / total) * 100 : 0,
        }
      })
      .filter((entry): entry is NonNullable<typeof entry> => entry !== null)
      // Largest first so the small regions draw on top and stay clickable.
      .sort((a, b) => b.radius - a.radius)
  }, [data, places])

  // Fitted to every region the warehouse has, not just this result's: otherwise a period with
  // one empty region would re-scale/re-centre the map, so the country looks different card to card.
  const projection = useMemo(
    () => project(places.length ? places : points.map((p) => p.point), VIEW_W, VIEW_H, PADDING),
    [places, points],
  )

  // Greedy label placement: walk the regions largest-value first and keep a label only if it
  // clears every label already placed.
  const labelled = useMemo(() => {
    const placed: { labelX: number; labelY: number }[] = []
    return [...points]
      .sort((a, b) => b.value - a.value)
      .flatMap((entry) => {
        const labelX = projection.x(entry.point)
        const labelY = projection.y(entry.point) + entry.radius + 13
        const clashes = placed.some(
          (other) => Math.hypot(other.labelX - labelX, other.labelY - labelY) < LABEL_MIN_GAP,
        )
        if (clashes) return []
        placed.push({ labelX, labelY })
        return [{ ...entry, labelX, labelY }]
      })
      .slice(0, 8)
  }, [points, projection])

  const scale = useMemo(() => moneyScale(Math.max(...data.map((d) => d.value), 0)), [data])
  const activeEntry = points.find((entry) => entry.region === active) ?? null

  // Regions with no rows at all still get a faint marker: "we sell nothing here" is a finding,
  // and an absent dot reads as missing data rather than as a zero.
  const covered = new Set(points.map((entry) => entry.point.region))
  const empties = places.filter((point) => !covered.has(point.region))

  if (points.length === 0) {
    return <p className="py-16 text-center text-sm text-ink-muted">{t('card.no_regional_data')}</p>
  }

  return (
    <figure className="relative m-0">
      <figcaption className="mb-2 text-xs text-ink-muted">
        {t('card.map_caption', { label, unit: scale.unit })}
      </figcaption>

      <svg
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        className="mx-auto block h-auto w-full max-w-[440px] overflow-visible"
        role="img"
        aria-labelledby={titleId}
        onMouseLeave={() => setActive(null)}
      >
        <title id={titleId}>{t('card.map_title', { label })}</title>

        {empties.map((point) => (
          <circle
            key={point.region}
            cx={projection.x(point)}
            cy={projection.y(point)}
            r={2.5}
            className="fill-[var(--surface-3)]"
          />
        ))}

        {points.map((entry) => {
          const cx = projection.x(entry.point)
          const cy = projection.y(entry.point)
          const isActive = entry.region === active
          return (
            <g
              key={entry.region}
              onMouseEnter={() => setActive(entry.region)}
              onFocus={() => setActive(entry.region)}
              onBlur={() => setActive(null)}
              tabIndex={0}
              // Not a button: there is no activation here and never was.
              role="img"
              aria-label={`${entry.region}: ${formatMoneyWithUnit(entry.value, scale)}`}
              className="cursor-default outline-none"
            >
              <circle
                cx={cx}
                cy={cy}
                r={entry.radius}
                fill="var(--series-1)"
                fillOpacity={isActive ? 0.42 : 0.24}
                stroke="var(--series-1)"
                strokeWidth={isActive ? 2 : 1.25}
                className="transition-all duration-200"
              />
              <circle cx={cx} cy={cy} r={2} fill="var(--series-1)" />
            </g>
          )
        })}

        {/* Largest regions only, skipped where it'd overlap an already-placed label - dense
            areas would produce overlapping text, so the hover readout carries the rest. */}
        {labelled.map((entry) => (
          <text
            key={`label-${entry.region}`}
            x={entry.labelX}
            y={entry.labelY}
            textAnchor="middle"
            className="pointer-events-none fill-[var(--text-secondary)] text-[10px] font-medium"
          >
            {entry.region}
          </text>
        ))}
      </svg>

      {activeEntry && (
        <div
          className="pointer-events-none absolute left-1/2 top-2 -translate-x-1/2 rounded-lg bg-surface px-3 py-2 text-center shadow-card ring-hairline"
          role="status"
        >
          <p className="text-xs font-medium text-ink">{activeEntry.region}</p>
          <p className="text-sm tabular-nums text-ink">
            {formatMoneyWithUnit(activeEntry.value, scale)}
          </p>
          <p className="text-[11px] text-ink-muted">
            {t('card.map_share', { percent: formatPercent(activeEntry.share) })}
          </p>
        </div>
      )}
    </figure>
  )
}
