/**
 * Sales per county as a proportional-symbol map.
 *
 * The bar chart next to this one is still the better instrument for reading a ranking, and
 * the Geografi page says so. What the map adds is the thing a ranked list cannot show:
 * *where* the demand sits. Three counties carrying most of the revenue in a narrow southern
 * band is a distribution fact, and it is invisible in a sorted list of names.
 *
 * Positions come from `lib/geo.ts` — mean store coordinates out of the seeded data, not a
 * traced outline. There are no county borders here because the repo has no boundary
 * geometry, and inventing one would put a drawn approximation of a real country beside
 * measured figures.
 *
 * Values are read straight from the result rows the card already carries, so this renders
 * from the same numbers as the bar chart and cannot drift from them.
 */

import { useId, useMemo, useState } from 'react'
import { findRegion, project, radiusFor, REGION_POINTS } from '../lib/geo'
import { SWEDEN_PATH } from '../lib/swedenOutline'
import { formatMoneyWithUnit, moneyScale, formatPercent } from '../lib/format'

const VIEW_W = 460
const VIEW_H = 620
const MIN_R = 5
// Capped lower than it could be. Stockholm carries roughly a third of the revenue, and at a
// larger maximum its circle simply covers Uppsala, Västmanland and Södermanland — the
// neighbours whose position is the interesting part. Overlap is inherent to a bubble map;
// this keeps it to translucent overlap rather than occlusion.
const MAX_R = 36
/** Labels are placed for the biggest counties only, and never within this of another. */
const LABEL_MIN_GAP = 30

export type RegionDatum = { region: string; value: number }

type Props = {
  data: RegionDatum[]
  /** Accessible caption; also used as the visible unit hint. */
  label?: string
}

export function RegionMap({ data, label = 'Nettoförsäljning' }: Props) {
  const titleId = useId()
  const [active, setActive] = useState<string | null>(null)

  const points = useMemo(() => {
    const max = Math.max(...data.map((d) => d.value), 0)
    const total = data.reduce((sum, d) => sum + d.value, 0)
    return data
      .map((datum) => {
        const point = findRegion(datum.region)
        if (!point) return null
        return {
          ...datum,
          point,
          radius: radiusFor(datum.value, max, MIN_R, MAX_R),
          share: total > 0 ? (datum.value / total) * 100 : 0,
        }
      })
      .filter((entry): entry is NonNullable<typeof entry> => entry !== null)
      // Largest first so the small counties draw on top and stay clickable.
      .sort((a, b) => b.radius - a.radius)
  }, [data])

  const projection = useMemo(() => project(), [])

  // Greedy label placement: walk the counties largest-value first and keep a label only if
  // it clears every label already placed. Deterministic, and it favours the counties a
  // reader is most likely to be looking for.
  const labelled = useMemo(() => {
    const placed: { labelX: number; labelY: number }[] = []
    return [...points]
      .sort((a, b) => b.value - a.value)
      .flatMap((entry) => {
        const labelX = projection.x(entry.point)
        const labelY = projection.y(entry.point) + entry.radius + 13
        const clashes = placed.some(
          (other) =>
            Math.hypot(other.labelX - labelX, other.labelY - labelY) < LABEL_MIN_GAP,
        )
        if (clashes) return []
        placed.push({ labelX, labelY })
        return [{ ...entry, labelX, labelY }]
      })
      .slice(0, 8)
  }, [points, projection])
  const scale = useMemo(() => moneyScale(Math.max(...data.map((d) => d.value), 0)), [data])
  const activeEntry = points.find((entry) => entry.region === active) ?? null

  // Counties with no rows at all still get a faint marker: "we sell nothing here" is a
  // finding, and an absent dot reads as missing data rather than as a zero.
  const covered = new Set(points.map((entry) => entry.point.region))
  const empties = REGION_POINTS.filter((point) => !covered.has(point.region))

  if (points.length === 0) {
    return (
      <p className="py-16 text-center text-sm text-ink-muted">
        Ingen regional data i det här resultatet.
      </p>
    )
  }

  return (
    <figure className="relative m-0">
      <figcaption className="mb-2 text-xs text-ink-muted">
        {label} per län · {scale.unit} · cirkelns yta står i proportion till värdet
      </figcaption>

      <svg
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        className="mx-auto block h-auto w-full max-w-[440px] overflow-visible"
        role="img"
        aria-labelledby={titleId}
        onMouseLeave={() => setActive(null)}
      >
        <title id={titleId}>{label} per län, karta över Sverige</title>

        {/* The coastline, beneath the data. Filled with a flat surface tone and outlined
            rather than shaded: it is context, and a map whose background competes with its
            marks for attention has stopped being a background. `fillRule` matters — the
            path carries three separate polygons (mainland, Gotland, Öland). */}
        <path
          d={SWEDEN_PATH}
          fillRule="evenodd"
          className="fill-[var(--surface-2)] stroke-[var(--axis)]"
          strokeWidth={0.75}
          strokeOpacity={0.55}
          strokeLinejoin="round"
        />

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
              role="button"
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

        {/* Labels for the largest counties only, and only where one will not land on top of
            another already placed. The south is dense enough that labelling everything
            produces overlapping text — the hover readout carries the rest. */}
        {labelled.map((entry) => (
          <text
            key={`label-${entry.region}`}
            x={entry.labelX}
            y={entry.labelY}
            textAnchor="middle"
            className="pointer-events-none fill-[var(--text-secondary)] text-[10px] font-medium"
          >
            {entry.region.replace(/\s*län$/, '')}
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
            {formatPercent(activeEntry.share)} av perioden
          </p>
        </div>
      )}
    </figure>
  )
}
